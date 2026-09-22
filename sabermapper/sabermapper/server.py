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
from urllib.parse import unquote, urlparse, urlencode

from .projects import ConflictError, ProjectStore
from .storage import read_json, write_json

STATIC = Path(__file__).parent / "static"
MAX_BODY = 96 * 1024 * 1024


def make_server(workspace: str | Path, port: int = 8765) -> ThreadingHTTPServer:
    store = ProjectStore(workspace)
    token = secrets.token_urlsafe(32)
    arc_root = Path(os.environ.get("SABERMAPPER_ARCVIEWER", str(Path(__file__).resolve().parents[1] / "vendor" / "arcviewer"))).resolve()

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
            size = path.stat().st_size
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
                                "offline": True, "assistant_calls": False})
                elif path == "/api/projects":
                    self._json(store.list())
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
                    self._json(store.get(path.split("/")[3]))
                elif path.startswith("/api/projects/") and "/files/" in path:
                    pieces = path.split("/", 5)
                    folder = store.directory(pieces[3])
                    relative = pieces[5]
                    if not re.fullmatch(r"(?:song\.ogg|cover\.png|arrangement\.json|analysis\.json|feedback/[a-f0-9]+\.json|exports/[a-zA-Z0-9.-]+\.(?:zip|json))", relative):
                        raise ValueError("File is not a project download")
                    self._file(folder / relative)
                elif path in {"/", "/index.html", "/app.js", "/style.css"}:
                    self._file(STATIC / ("index.html" if path == "/" else path[1:]))
                else:
                    self._json({"error": "Not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self._error(exc)

        def _error(self, exc):
            status = 409 if isinstance(exc, ConflictError) else 404 if isinstance(exc, FileNotFoundError) else 400 if isinstance(exc, (ValueError, KeyError, TypeError)) else 500
            self._json({"error": str(exc) if status != 500 else "Operation failed. Check local files and dependencies.",
                        "type": type(exc).__name__}, status)

        def do_POST(self):
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
                                                bpm=float(data["bpm"]) if data.get("bpm") else None))
                    finally:
                        temporary.unlink(missing_ok=True)
                elif path.startswith("/api/projects/"):
                    pieces = path.split("/")
                    if len(pieces) != 5:
                        raise ValueError("Unknown project operation")
                    project_id, action = pieces[3:]
                    if action == "save":
                        result = store.save(project_id, data["arrangement"], data["revision"], request_id=data.get("request_id"))
                    elif action == "lock":
                        result = store.set_lock(project_id, data["section_id"], data["locked"], data["revision"])
                    elif action == "restore":
                        result = store.restore(project_id, data["restore_revision"], data["revision"])
                    elif action == "feedback":
                        result = store.add_feedback(project_id, data)
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
                            current = store.get(project_id)
                            if data.get("revision") != current["revision"]:
                                raise ConflictError("Project changed. Reload it before previewing.")
                            result = store.export(project_id)
                        local_url = f"http://{self.headers['Host']}{result['url']}"
                        result["viewer_url"] = "/arcviewer/?" + urlencode({
                            "url": local_url, "noProxy": "true", "t": min(start, current["project"]["duration_seconds"]),
                            "mode": "Standard", "difficulty": current["arrangement"]["difficulty"]["name"]})
                    elif action == "analyze":
                        from .audio import analyze_audio
                        directory = store.directory(project_id)
                        bpm = float(data["bpm"])
                        offset_seconds = float(data.get("offset_seconds", 0))
                        with store.lock:
                            current = store.get(project_id)
                            changed = current["arrangement"]
                            changed["song"]["bpm"] = bpm
                            changed["song"]["audio_offset_seconds"] = offset_seconds
                            # Reject stale revisions and locked-section conflicts
                            # before the slow audio analysis, not after it.
                            store.check_save(project_id, changed, data["revision"])
                        report = analyze_audio(directory / "song.ogg", bpm=bpm, offset_seconds=offset_seconds)
                        with store.lock:
                            store.save(project_id, changed, data["revision"])
                            write_json(directory / "analysis.json", report)
                            result = store.get(project_id)
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


def serve(workspace: str | Path, port=8765):
    server = make_server(workspace, port)
    print(f"SaberMapper Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Workspace: {Path(workspace).resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
