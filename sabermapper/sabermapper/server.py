"""Loopback-only studio server. No assistant processes or provider API calls."""
from __future__ import annotations

import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse, urlencode

from .projects import ConflictError, ProjectStore
from .revisions import arrangement_revision
from .storage import read_json, write_json
from .studio_supervisor import TOKEN_ENV, WorkerControl

STATIC = Path(__file__).parent / "static"
MAX_BODY = 96 * 1024 * 1024
GAME_STATUS = {"game_busy": 409, "game_preempted": 409, "lease_not_held": 409, "game_not_running": 409,
               "stale_revision": 409, "bridge_missing": 503, "bridge_unreachable": 503}


class GameError(Exception):
    """A structured game-console error with the same `.code` / `.to_dict()` shape as the game API's errors."""
    def __init__(self, code: str, message: str, details=None, fix: str | None = None):
        super().__init__(message)
        self.code, self.message, self.details, self.fix = code, message, details, fix

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details, "fix": self.fix}}


def _coded(exc) -> bool:
    return isinstance(getattr(exc, "code", None), str) and callable(getattr(exc, "to_dict", None))


def live_agent_lease(lease_info) -> dict | None:
    """The lease an agent holds right now, from lease_status() or status()["lease"], else None."""
    lease = lease_info.get("lease", lease_info) if isinstance(lease_info, dict) else None
    if not isinstance(lease, dict) or not lease.get("holder") or lease.get("holder_kind") != "agent":
        return None
    return None if lease.get("stale") or lease.get("live") is False else lease


def game_action(game, store: ProjectStore, action: str, data: dict):
    """Run one studio game-console action against the injected game API."""
    def seconds(key, required=False):
        value = data.get(key)
        if value is None and not required:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a nonnegative number of seconds")
        return float(value)
    if action == "play":
        project_id = data.get("project")
        with store.lock:
            path = store.directory(project_id)
            current = read_json(store.arrangement_file(path, data.get("difficulty") or None))
            duration = float(read_json(path / "project.json").get("duration_seconds") or 0)
        name, current_revision = current["difficulty"]["name"], arrangement_revision(current)
        mode = data.get("mode", "play")
        if mode not in {"play", "watch"}:
            raise ValueError("mode must be play or watch")
        start = seconds("seconds") or 0.0
        if start > duration:
            raise ValueError("Start time is after the end of the song")
        revision = data.get("revision") or current_revision
        if revision != current_revision and store.revision_arrangement(path, revision, name) is None:
            raise GameError("stale_revision", f"Revision {str(revision)[:12]} is not a saved {name} revision of "
                            "this project", {"current_revision": current_revision},
                            "Reload the project and pick a revision from the list")
        if not data.get("confirm_preempt"):
            lease = live_agent_lease(game.lease_status() if hasattr(game, "lease_status") else game.status())
            if lease:
                raise GameError("game_busy", f"An agent ({lease.get('holder')}, "
                                f"{lease.get('purpose') or 'no purpose given'}) is using the game. Continue? "
                                "The agent's capture will stop and retry later.",
                                {"lease": lease, "preemptable": True},
                                "Send the same request with confirm_preempt: true to take over the game")
        return game.play(store, project_id, seconds=start, difficulty=name, revision=revision,
                         mode=mode, human=True)
    if action in {"pause", "resume", "stop"}:
        return getattr(game, action)()
    if action == "restart":
        return game.restart(seconds("seconds"))
    if action == "seek":
        return game.seek(seconds("seconds", required=True))
    raise ValueError("Unknown game operation; use play, pause, resume, restart, seek or stop")


class PreviewExports:
    """Background exports for studio previews, so ArcViewer boots in its tab while the map ZIP is written.

    `wait` blocks until an export finishes and returns its result, or raises its error. A running
    export counts as an in-flight request, so a code reload drains it before the worker stops. A job
    this worker never started (it began before a reload) resolves from the finished files on disk.
    """

    KEEP = 16

    def __init__(self, store: ProjectStore, control: WorkerControl):
        self.store, self.control = store, control
        self.jobs: dict[tuple[str, str], dict] = {}
        self.guard = threading.Lock()

    def start(self, project_id: str, filename: str, difficulty: str | None, revision: str) -> str:
        job = filename.removesuffix(".zip")
        entry = {"done": threading.Event(), "result": None, "error": None, "started": time.monotonic()}
        with self.guard:
            self.jobs[(project_id, job)] = entry
            for key in sorted(self.jobs, key=lambda k: self.jobs[k]["started"])[:-self.KEEP]:
                if self.jobs[key]["done"].is_set():
                    del self.jobs[key]
        counted = threading.Event()

        def run():
            with self.control.request():
                counted.set()
                try:
                    with self.store.lock:
                        if self.store.get(project_id, difficulty)["revision"] != revision:
                            raise ConflictError("Project changed. Reload it before previewing.")
                        entry["result"] = self.store.export(project_id, filename)
                except Exception as exc:
                    entry["error"] = exc
                finally:
                    entry["done"].set()

        threading.Thread(target=run, name=f"preview-{job}", daemon=True).start()
        counted.wait(5)  # the export is in flight before the request that started it ends
        return job

    def wait(self, project_id: str, job: str, timeout: float = 600.0) -> dict:
        with self.guard:
            entry = self.jobs.get((project_id, job))
        if entry is None:
            exports = self.store.directory(project_id) / "exports"
            if not (exports / f"{job}.zip").is_file():
                raise FileNotFoundError("Preview export was not found; start the preview again")
            result = {"filename": f"{job}.zip", "url": f"/api/projects/{project_id}/files/exports/{job}.zip"}
            if (exports / f"{job}-vanilla.zip").is_file():
                result["vanilla_twin"] = f"{job}-vanilla.zip"
            return result
        if not entry["done"].wait(timeout):
            raise ValueError("The preview export is still running; try again shortly")
        if entry["error"] is not None:
            raise entry["error"]
        return entry["result"]


def warm_up():
    """Import the export pipeline (SciPy included) in the background, so the first preview skips it."""
    def run():
        try:
            from . import export, musical, placement, show  # noqa: F401
        except Exception:
            pass
    threading.Thread(target=run, name="studio-warm-up", daemon=True).start()


def make_server(workspace: str | Path, port: int = 8765, game=None, token: str | None = None,
                control: WorkerControl | None = None) -> ThreadingHTTPServer:
    """Build the studio server. `game` is the game API (sabermapper.game.api); None imports it on first use.

    `token` and `control` come from the studio supervisor, which keeps one token across code reloads.
    """
    store = ProjectStore(workspace)
    control = control or WorkerControl()
    games = [game]

    def game_api():
        if games[0] is None:
            try:
                import importlib
                games[0] = importlib.import_module("sabermapper.game.api")
            except ImportError as exc:
                raise GameError("bridge_missing", f"The game integration is not installed ({exc})", None,
                                "Install the SaberMapper game bridge (sabermapper.game) and restart the studio") from exc
        return games[0]
    token = token or secrets.token_urlsafe(32)
    arc_root = Path(os.environ.get("SABERMAPPER_ARCVIEWER", str(Path(__file__).resolve().parents[1] / "vendor" / "arcviewer"))).resolve()
    previews = PreviewExports(store, control)

    class Handler(BaseHTTPRequestHandler):
        server_version = "SaberMapper/0.2"

        def log_message(self, fmt, *args):
            pass

        def _json(self, value, status=200):
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _file(self, path: Path, viewer=False):
            if not path.is_file():
                raise FileNotFoundError("File was not found")
            stat = path.stat()
            size = stat.st_size
            # ArcViewer's 53 MB engine revalidates to a 304, so the browser reuses its download and compiled code.
            tag = f'"{stat.st_mtime_ns:x}-{size:x}"' if viewer else None
            if tag and tag in {t.strip() for t in self.headers.get("If-None-Match", "").split(",")}:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            start, end = 0, size - 1
            range_header = self.headers.get("Range")
            partial = False
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                if not match:
                    self._json({"error": "Unsupported byte range"}, 416)
                    return
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if start > end or start >= size:
                    self._json({"error": "Range outside file"}, 416)
                    return
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", "application/wasm" if path.suffix == ".wasm" else mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache")
            if tag:
                self.send_header("ETag", tag)
            if viewer:
                self.send_header("Content-Security-Policy", "default-src 'self' blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
            else:
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if path.suffix.lower() == ".zip":
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _host(self):
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            with control.request():
                self._get()

        def do_POST(self):
            with control.request():
                self._post()

        def _get(self):
            try:
                if not self._host():
                    self._json({"error": "Use the local studio URL"}, 403)
                    return
                path = unquote(urlparse(self.path).path)
                if path.startswith("/arcviewer/"):
                    relative = path.removeprefix("/arcviewer/") or "index.html"
                    target = (arc_root / relative).resolve()
                    if not target.is_relative_to(arc_root) or any(part.startswith(".") for part in Path(relative).parts):
                        raise ValueError("Invalid viewer asset")
                    self._file(target, viewer=True)
                elif path == "/api/status":
                    self._json({"version": "0.2.0", "token": token, "workspace": str(store.root),
                                "offline": True, "assistant_calls": False, "code": control.status()})
                elif path == "/api/projects":
                    self._json(store.list())
                elif path == "/api/game/status":
                    try:
                        self._json({"available": True, **game_api().status()})
                    except Exception as exc:
                        if not _coded(exc):
                            raise
                        # Polling never fails: it reports why the game cannot be reached.
                        self._json({"available": exc.code != "bridge_missing", "running": False, "lease": None,
                                    "bridge": None, **exc.to_dict()})
                elif re.fullmatch(r"/api/projects/[\w-]+/feedback", path):
                    query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                    self._json(store.list_feedback(path.split("/")[3], difficulty=query.get("difficulty") or None,
                                                   revision=query.get("revision") or None,
                                                   kind=query.get("kind") or None, since=query.get("since") or None))
                elif path == "/api/corpus":
                    from .corpus import CorpusStore, corpus_report
                    corpus = CorpusStore(store.root / "corpus")
                    try:
                        rows = [{k: v for k, v in row.items() if k not in {"processing_json", "provenance_json"}} for row in corpus.rows()]
                        summary = corpus.library_summary(limit=100)
                    finally:
                        corpus.close()
                    self._json({"rows": rows, "report": corpus_report(rows),
                                "pattern_count": summary.get("pattern_count", 0),
                                "group_count": summary.get("motif_group_count", 0),
                                "groups": summary.get("groups", []), "patterns": summary.get("patterns", [])})
                elif path == "/api/research":
                    resources = Path(__file__).parent / "resources"
                    payload = {}
                    for name in ("profile", "knowledge", "ticket-status", "protocol"):
                        file = resources / (name + ".json")
                        payload[name] = read_json(file) if file.exists() else {}
                    self._json(payload)
                elif re.fullmatch(r"/api/projects/[\w-]+", path):
                    difficulty = parse_qs(urlparse(self.path).query).get("difficulty", [None])[0]
                    self._json(store.get(path.split("/")[3], difficulty or None))
                elif match := re.fullmatch(r"/api/projects/([\w-]+)/previews/(map-[0-9a-f]{10}-[0-9a-f]{6})\.(zip|json)", path):
                    project_id, job, kind = match.groups()
                    result = previews.wait(project_id, job)
                    if kind == "json":
                        self._json(result)
                    else:  # ArcViewer cannot render Vivify: a vivified export previews its vanilla twin.
                        self._file(store.directory(project_id) / "exports" / (result.get("vanilla_twin") or result["filename"]))
                elif path.startswith("/api/projects/") and "/files/" in path:
                    pieces = path.split("/", 5)
                    folder = store.directory(pieces[3])
                    relative = pieces[5]
                    if not re.fullmatch(r"(?:song\.ogg|cover\.png|arrangement\.json|difficulties/(?:Easy|Normal|Hard|Expert|ExpertPlus)\.json|analysis\.json|musical/[a-f0-9]{32}/(?:report\.json|[a-z][a-z0-9_-]{0,39}\.wav)|feedback/[a-f0-9]+\.json|exports/[a-zA-Z0-9.-]+\.(?:zip|json))", relative):
                        raise ValueError("File is not a project download")
                    self._file(folder / relative)
                elif path in {"/", "/index.html", "/app.js", "/music.js", "/style.css"}:
                    self._file(STATIC / ("index.html" if path == "/" else path[1:]))
                else:
                    self._json({"error": "Not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self._error(exc)

        def _error(self, exc):
            if _coded(exc):
                self._json(exc.to_dict(), GAME_STATUS.get(exc.code, 400))
                return
            status = 409 if isinstance(exc, ConflictError) else 404 if isinstance(exc, FileNotFoundError) else 400 if isinstance(exc, (ValueError, KeyError, TypeError)) else 500
            self._json({"error": str(exc) if status != 500 else "Operation failed. Check local files and dependencies.",
                        "type": type(exc).__name__}, status)

        def _post(self):
            try:
                if not self._host() or self.headers.get("X-SaberMapper-Token") != token:
                    self._json({"error": "Reload the local studio before making changes"}, 403)
                    return
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                    self._json({"error": "Cross-origin changes are not allowed"}, 403)
                    return
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("Request is empty or exceeds the 96 MB upload limit")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Request must be a JSON object")
                path = unquote(urlparse(self.path).path)
                if path == "/api/demo":
                    self._json(store.create(demo=True))
                elif re.fullmatch(r"/api/game/[a-z]+", path):
                    self._json(game_action(game_api(), store, path.rsplit("/", 1)[-1], data))
                elif re.fullmatch(r"/api/projects/[\w-]+/music", path):
                    from .musical import analyze_project
                    # Browser runs only bundled DSP. Optional model processes are agent CLI work.
                    if data.get("backend") not in {"bands", "hpss"}:
                        raise ValueError("Choose frequency bands or harmonic/percussive analysis")
                    self._json(analyze_project(store, path.split("/")[3],
                                              backend=data["backend"], preset=data.get("preset", "balanced")))
                elif path == "/api/projects/import":
                    suffix = Path(str(data.get("filename", ""))).suffix.lower()
                    if suffix not in {".wav", ".ogg", ".mp3", ".flac"}:
                        raise ValueError("Choose WAV, OGG, MP3 or FLAC audio")
                    payload = base64.b64decode(data.get("audio", ""), validate=True)
                    if not payload:
                        raise ValueError("Audio is empty")
                    uploads = store.root / ".uploads"
                    uploads.mkdir(exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=uploads, suffix=suffix, delete=False) as output:
                        temporary = Path(output.name)
                        output.write(payload)
                    try:
                        self._json(store.create(temporary, title=str(data.get("title") or Path(data["filename"]).stem),
                                                artist=str(data.get("artist") or "Unknown artist"),
                                                album=str(data.get("album") or "") or None,
                                                bpm=float(data["bpm"]) if data.get("bpm") else None))
                    finally:
                        temporary.unlink(missing_ok=True)
                elif path.startswith("/api/projects/"):
                    pieces = path.split("/")
                    if len(pieces) != 5:
                        raise ValueError("Unknown project operation")
                    project_id, action = pieces[3:]
                    difficulty = data.get("difficulty") or None
                    if action == "save":
                        result = store.save(project_id, data["arrangement"], data["revision"], request_id=data.get("request_id"),
                                            difficulty=difficulty)
                    elif action == "lock":
                        result = store.set_lock(project_id, data["section_id"], data["locked"], data["revision"], difficulty)
                    elif action == "restore":
                        result = store.restore(project_id, data["restore_revision"], data["revision"], difficulty)
                    elif action == "feedback":
                        result = store.add_feedback(project_id, data)
                    elif action == "note":
                        result = store.add_note(project_id, song_time=data.get("song_time"), text=data.get("text"),
                                                revision=data.get("revision") or None, difficulty=difficulty,
                                                source="studio")
                    elif action == "review":
                        result = store.review(project_id, data)
                    elif action == "export":
                        result = store.export(project_id)
                    elif action == "preview":
                        if not (arc_root / "Build" / "ArcViewer.wasm").is_file():
                            raise ValueError("Local ArcViewer is missing. Run scripts/install_arcviewer.ps1 first.")
                        start = float(data.get("seconds", 0))
                        if not math.isfinite(start) or start < 0:
                            raise ValueError("Preview time must be a nonnegative finite number")
                        with store.lock:
                            current = store.get(project_id, difficulty)
                            if data.get("revision") != current["revision"]:
                                raise ConflictError("Project changed. Reload it before previewing.")
                            filename = store.export_filename(project_id)
                        # The export runs while the viewer tab boots ArcViewer; the viewer's map request waits for it.
                        job = previews.start(project_id, filename, difficulty, current["revision"])
                        result = {"filename": filename, "url": f"/api/projects/{project_id}/files/exports/{filename}",
                                  "status_url": f"/api/projects/{project_id}/previews/{job}.json"}
                        local_url = f"http://{self.headers['Host']}/api/projects/{project_id}/previews/{job}.zip"
                        result["viewer_url"] = "/arcviewer/?" + urlencode({
                            "url": local_url, "noProxy": "true", "t": min(start, current["project"]["duration_seconds"]),
                            "mode": "Standard", "difficulty": current["difficulty"]})
                    elif action == "analyze":
                        from .audio import analyze_audio
                        directory = store.directory(project_id)
                        bpm = float(data["bpm"])
                        offset_seconds = float(data.get("offset_seconds", 0))
                        # Timing belongs to the audio: every difficulty is retimed together.
                        with store.lock:
                            current = store.get(project_id, difficulty)
                            if data["revision"] != current["revision"]:
                                raise ConflictError("This arrangement changed since you opened it. Reload before saving.")
                            changes = []
                            for row in current["difficulties"]:
                                changed = store.get(project_id, row["name"])["arrangement"]
                                changed["song"]["bpm"] = bpm
                                changed["song"]["audio_offset_seconds"] = offset_seconds
                                # Reject stale revisions and locked-section conflicts
                                # before the slow audio analysis, not after it.
                                store.check_save(project_id, changed, row["revision"], row["name"])
                                changes.append((row["name"], changed, row["revision"]))
                        report = analyze_audio(directory / "song.ogg", bpm=bpm, offset_seconds=offset_seconds)
                        with store.lock:
                            for name, changed, revision in changes:
                                store.save(project_id, changed, revision, difficulty=name)
                            write_json(directory / "analysis.json", report)
                            result = store.get(project_id, difficulty)
                    else:
                        raise ValueError("Unknown project operation")
                    self._json(result)
                elif path.startswith("/api/corpus/"):
                    self._json(corpus_action(store.root, path.rsplit("/", 1)[-1], data))
                else:
                    self._json({"error": "Not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except (Exception,) as exc:
                self._error(exc)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.store = store
    return server


def corpus_action(root: Path, action: str, data: dict):
    from .corpus import CorpusStore
    from .patterns import retrieve_patterns
    corpus = CorpusStore(root / "corpus")
    try:
        if action == "fetch":
            return corpus.fetch_exact(str(data["hash"]), retain_audio=True)
        if action == "import":
            from .corpus import beat_saber_map_hash
            payload = base64.b64decode(data["archive"], validate=True)
            return corpus.import_archive(payload, version_hash=beat_saber_map_hash(payload), retain_audio=True,
                                         provenance={"origin": "local archive", "filename": str(data.get("filename", "local.zip"))})
        if action == "process":
            return corpus.process_all(max_maps=100, max_seconds=120)
        if action == "retrieve":
            forbidden = set(data.get("forbidden_song_families", []))
            if data.get("project_id"):
                project_path = ProjectStore(root).directory(str(data["project_id"]))
                project = read_json(project_path / "project.json")
                from .evaluation import SplitRegistry
                aliases = SplitRegistry(root / "corpus" / "splits.json").data["aliases"]
                for key in ("source_sha256", "export_sha256"):
                    audio_hash = project.get("audio", {}).get(key)
                    if audio_hash and f"audio:{audio_hash}" in aliases:
                        forbidden.add(aliases[f"audio:{audio_hash}"])
            options = {"bpm": float(data["bpm"]) if data.get("bpm") else None,
                       "forbidden_song_families": forbidden,
                       "target_nps": float(data["nps"]) if data.get("nps") else None,
                       "limit": max(1, min(50, int(data.get("limit", 12))))}
            return retrieve_patterns(corpus.catalog_patterns(), **options)
        if action == "pattern":
            pattern_id = str(data["id"])
            found = next((p for p in corpus.catalog_patterns() if p.get("id") == pattern_id), None)
            if found:
                return found
            processed = corpus.valid_processed(pattern_id.split(":", 1)[0])
            if processed:
                found = next((p for p in processed.get("patterns", []) if p["id"] == pattern_id), None)
                if found:
                    return found
            raise ValueError("Pattern is unavailable; reprocess its source")
        raise ValueError("Unknown corpus operation")
    finally:
        corpus.close()


def serve(workspace: str | Path, port=8765, game=None, worker=False):
    """Serve in this process. `worker` means a studio supervisor started it and controls it through stdin."""
    control = WorkerControl()
    server = make_server(workspace, port, game, token=os.environ.get(TOKEN_ENV) if worker else None, control=control)
    if worker:
        control.listen(server)
    warm_up()
    print(f"SaberMapper Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Workspace: {Path(workspace).resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
