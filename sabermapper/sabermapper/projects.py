"""Local project lifecycle, auditable edits, feedback and export artifacts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
import shutil
import threading
import uuid

from .arrangement import compile_arrangement, expanded_notes
from .audio_grounding import project_audio_findings
from .composition import make_cover, starting_arrangement
from .revisions import arrangement_revision
from .storage import WorkspaceLock, contained, digest, now, read_json, write_json
from .validation import validate_arrangement


class ConflictError(ValueError):
    pass


class DuplicateProjectError(ValueError):
    def __init__(self, project_id: str, title: str):
        super().__init__(f"This audio was already imported as project {project_id} ({title}); "
                         "continue that project, or pass allow_duplicate / --allow-duplicate for a deliberate second copy")
        self.project_id = project_id


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that was decoded as cp1252/latin-1 (e.g. 'FumÃ©e' -> 'Fumée')."""
    if not re.search("[Â-ô][\u0080-¿‘-›Œ-Ÿ€™]", text):
        return text
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def source_album(source: str | Path | None, artist: str | None) -> str | None:
    """Album of the imported source file: its embedded tag, else an Artist/Album/Song folder layout."""
    if not source:
        return None
    source = Path(source)
    try:
        import soundfile as sf
        with sf.SoundFile(source) as handle:
            tagged = (handle.album or "").strip()
        if tagged:
            return repair_mojibake(tagged)
    except Exception:  # missing file or a format without tags
        pass
    folder = source.parent
    if artist and folder.name and folder.parent.name.casefold() == artist.strip().casefold():
        return folder.name
    return None


class ProjectStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects = self.root / "projects"
        self.projects.mkdir(exist_ok=True)
        self.lock = WorkspaceLock(self.root / ".project.lock")

    def directory(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", project_id):
            raise ValueError("Invalid project ID")
        path = contained(self.projects, project_id)
        if not (path / "project.json").is_file():
            raise FileNotFoundError("Project was not found")
        return path

    def list(self) -> list[dict]:
        result = []
        for path in self.projects.glob("*/project.json"):
            try:
                item = read_json(path)
                entry = {k: item.get(k) for k in ("id", "title", "artist", "created_at", "updated_at", "origin", "duration_seconds")}
                entry["album"] = item.get("album") or source_album((item.get("audio") or {}).get("source_path"),
                                                                    item.get("artist"))
                result.append(entry)
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda x: x["updated_at"] or "", reverse=True)

    def set_album(self, project_id: str, album: str | None) -> dict:
        """Record the album shown in the studio's artist/album tree; empty restores the source-derived album."""
        with self.lock:
            path = self.directory(project_id)
            meta = read_json(path / "project.json")
            meta["album"] = repair_mojibake(album.strip()) if album and album.strip() else None
            write_json(path / "project.json", meta)
        return next(item for item in self.list() if item["id"] == project_id)

    def find_by_source(self, source_sha256: str) -> dict | None:
        """Return the most recently updated project imported from the exact same source audio."""
        matches = []
        for path in self.projects.glob("*/project.json"):
            try:
                item = read_json(path)
            except (OSError, ValueError):
                continue
            if (item.get("audio") or {}).get("source_sha256") == source_sha256:
                matches.append(item)
        return max(matches, key=lambda x: x.get("updated_at") or "", default=None)

    def create(self, source: str | Path | None = None, *, title="Untitled track", artist="Unknown artist",
               album: str | None = None, bpm: float | None = None, demo=False, allow_duplicate=False) -> dict:
        from .audio import _hash, analyze_audio, generate_demo_audio, prepare_audio
        title, artist = repair_mojibake(title), repair_mojibake(artist)
        album = repair_mojibake(album.strip()) if album and album.strip() else None
        if album is None and not demo:
            album = source_album(source, artist)
        if not demo and source is not None and not allow_duplicate:
            existing = self.find_by_source(_hash(Path(source)))
            if existing:
                raise DuplicateProjectError(existing["id"], existing.get("title") or "")
        project_id = uuid.uuid4().hex[:12]
        path = self.projects / project_id
        path.mkdir()
        try:
            if demo:
                title, artist, bpm = "Neon Circuit", "SaberMapper Originals", 120.0
                audio_meta = generate_demo_audio(path / "song.ogg")
            else:
                if source is None:
                    raise ValueError("Select a local audio file")
                audio_meta = prepare_audio(source, path / "song.ogg")
            report = analyze_audio(path / "song.ogg", bpm=bpm)
            import soundfile as sf
            duration = sf.info(path / "song.ogg").duration
            report_bpm = report.get("timing", {}).get("bpm") or report.get("bpm") or bpm or 120.0
            if isinstance(report_bpm, dict):
                report_bpm = report_bpm.get("value", 120.0)
            chosen_bpm = float(bpm or report_bpm)
            arrangement = starting_arrangement(title.strip() or "Untitled track", artist.strip() or "Unknown artist",
                                                chosen_bpm, duration, demo=demo)
            metadata = {"schema_version": "1.0", "id": project_id, "title": title, "artist": artist, "album": album,
                        "created_at": now(), "updated_at": now(), "origin": "original-demo" if demo else "local-audio",
                        "composition_origin": "deterministic demonstration" if demo else "rules-only starting arrangement",
                        "duration_seconds": duration, "audio": audio_meta, "timing_reviewed": False,
                        "game_build": None, "mods": [], "playtested": False}
            make_cover(path / "cover.png", title)
            write_json(path / "arrangement.json", arrangement)
            write_json(path / "analysis.json", report)
            write_json(path / "project.json", metadata)
            write_json(path / "history" / (arrangement_revision(arrangement) + ".json"), arrangement)
        except Exception:
            # Only a newly allocated, checked child directory is removed.
            if path.resolve().is_relative_to(self.projects.resolve()):
                shutil.rmtree(path)
            raise
        return self.get(project_id)

    def get(self, project_id: str) -> dict:
        from .movement import analyze_movement
        from .musical import project_runs
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(path / "arrangement.json")
            diagnostics = validate_arrangement(arrangement)
            audio_run, audio = None, {"checked": False}
            try:
                from .audio_grounding import audio_findings
                from .critique import focus_findings
                from .musical import latest_run
                audio_run, report = latest_run(path)
                if report is not None:
                    audio, findings = audio_findings(arrangement, report)
                    # Focus and salience warnings travel with every read and save: never blocking, never silent.
                    diagnostics += findings + focus_findings(arrangement, report)
            except (ValueError, KeyError, TypeError, ZeroDivisionError):
                pass  # structurally invalid arrangements already carry their own errors
            notes = []
            try:
                notes = [{**n, "beat": float(n["beat"])} for n in expanded_notes(arrangement)]
            except (ValueError, KeyError, TypeError):
                pass
            try:
                beatmap = compile_arrangement(arrangement)
                from .mapio import parse_map
                normalized = parse_map(beatmap, bpm=arrangement["song"]["bpm"],
                                       audio_offset_seconds=arrangement["song"]["audio_offset_seconds"])
                times = {(n["beat"], n["x"], n["y"], n["color"]): n["seconds"] for n in normalized["notes"]}
                for note in notes:
                    note["seconds"] = times[(note["beat"], note["x"], note["y"], note["color"])]
            except ValueError:
                beatmap = None
            return {"project": read_json(path / "project.json"), "arrangement": arrangement,
                    "revision": arrangement_revision(arrangement), "analysis": read_json(path / "analysis.json"),
                    "musical_runs": project_runs(path), "audio_check": {"run_id": audio_run, **audio},
                    "notes": notes, "beatmap": beatmap, "diagnostics": diagnostics,
                    "movement": analyze_movement(notes, bpm=arrangement["song"]["bpm"],
                                                 njs=arrangement["difficulty"]["njs"],
                                                 spawn_offset_beats=arrangement["difficulty"]["spawn_offset_beats"]) if notes else {},
                    "feedback": self.feedback(project_id),
                    "reviews": [read_json(p) for p in sorted((path / "reviews").glob("*.json"))],
                    "history": [p.stem for p in sorted((path / "history").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)],
                    "exports": [p.name for p in sorted((path / "exports").glob("*.zip"))]}

    def check_save(self, project_id: str, arrangement: dict, expected_revision: str) -> dict:
        """Raise the conflict or validation error a save would raise; write nothing.

        Returns the current stored arrangement so callers can continue under the lock.
        """
        with self.lock:
            path = self.directory(project_id)
            original = read_json(path / "arrangement.json")
            old_revision = arrangement_revision(original)
            if expected_revision != old_revision:
                raise ConflictError("This arrangement changed since you opened it. Reload before saving.")
            errors = [d for d in validate_arrangement(arrangement) if d["severity"] == "error" and d["code"] != "unresolved_section"]
            if errors:
                raise ValueError("; ".join(d["message"] for d in errors[:10]))
            # The map exists to follow the song: refuse long stretches of playing audio left unmapped.
            run_id, _, findings = project_audio_findings(path, arrangement)
            blocking = [d for d in findings if d["severity"] == "error"]
            if blocking:
                raise ValueError(f"Audio left unmapped (evidence run {run_id}): "
                                 + "; ".join(d["message"] for d in blocking[:10]))
            new_sections = {s["id"]: s for s in arrangement["sections"]}
            if any(s["locked"] for s in original["sections"]):
                if (any(original["song"].get(k) != arrangement["song"].get(k) for k in ("bpm", "audio_offset_seconds"))
                        or original.get("tempo_events", []) != arrangement.get("tempo_events", [])
                        or original["difficulty"] != arrangement["difficulty"]):
                    raise ConflictError("Global timing or jump settings would alter a locked section. Unlock it before editing.")
            for section in original["sections"]:
                if not section["locked"]:
                    continue
                if new_sections.get(section["id"]) != section:
                    raise ConflictError(f"Section {section['id']} is locked. Unlock it before editing.")
                for pattern in section["patterns"]:
                    if original["motifs"][pattern["motif"]] != arrangement["motifs"].get(pattern["motif"]):
                        raise ConflictError("A changed motif would alter a locked section")
            return original

    def save(self, project_id: str, arrangement: dict, expected_revision: str, *, request_id=None) -> dict:
        with self.lock:
            path = self.directory(project_id)
            original = self.check_save(project_id, arrangement, expected_revision)
            old_revision = arrangement_revision(original)
            revision = arrangement_revision(arrangement)
            if request_id is not None:
                if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{12}", request_id):
                    raise ValueError("Invalid feedback request ID")
                request_path = path / "feedback" / (request_id + ".json")
                if not request_path.exists():
                    raise ValueError("Feedback request was not found in this project")
                request = read_json(request_path)
                if request["revision"] != old_revision:
                    raise ConflictError("Feedback request refers to an older arrangement")
            write_json(path / "history" / (old_revision + ".json"), original)
            write_json(path / "history" / (revision + ".json"), arrangement)
            write_json(path / "arrangement.json", arrangement)
            meta = read_json(path / "project.json")
            meta.update(updated_at=now(), title=arrangement["song"]["title"], artist=arrangement["song"]["artist"])
            if original["song"] != arrangement["song"]:
                meta["timing_reviewed"] = False
            meta["playtested"] = False
            write_json(path / "project.json", meta)
            if request_id is not None:
                request.update(status="addressed", resulting_revision=revision)
                write_json(request_path, request)
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "previous": old_revision, "revision": revision,
                        "request_id": request_id, "at": now(), "diagnostics": validate_arrangement(arrangement)})
            return self.get(project_id)

    def set_lock(self, project_id: str, section_id: str, locked: bool, expected_revision: str) -> dict:
        if type(locked) is not bool:
            raise ValueError("locked must be a boolean")
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(path / "arrangement.json")
            if arrangement_revision(arrangement) != expected_revision:
                raise ConflictError("Stale revision; reload the project")
            section = next((s for s in arrangement["sections"] if s["id"] == section_id), None)
            if section is None:
                raise ValueError("Section was not found")
            previous = arrangement_revision(arrangement)
            section["locked"] = locked
            revision = arrangement_revision(arrangement)
            write_json(path / "history" / (revision + ".json"), arrangement)
            write_json(path / "arrangement.json", arrangement)
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "previous": previous, "revision": revision,
                        "operation": "lock" if locked else "unlock", "section_id": section_id, "at": now()})
            return self.get(project_id)

    def restore(self, project_id: str, revision: str, expected_revision: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Invalid saved revision")
        return self.save(project_id, read_json(self.directory(project_id) / "history" / (revision + ".json")), expected_revision)

    def feedback(self, project_id: str) -> list[dict]:
        return [read_json(p) for p in sorted((self.directory(project_id) / "feedback").glob("*.json"))]

    def add_feedback(self, project_id: str, data: dict) -> dict:
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(path / "arrangement.json")
            revision = arrangement_revision(arrangement)
            if data.get("revision") != revision:
                raise ConflictError("Feedback refers to a stale arrangement; reload first")
            text = str(data.get("text", "")).strip()
            if not text or len(text) > 10000:
                raise ValueError("Enter feedback between 1 and 10,000 characters")
            start, end = float(data.get("start_beat", 0)), float(data.get("end_beat", 0))
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("Select a valid increasing beat range")
            notes = expanded_notes(arrangement)
            selected = [n["id"] for n in notes if start <= n["beat"] < end]
            result = {"schema_version": "1.0", "id": uuid.uuid4().hex[:12], "revision": revision,
                      "start_beat": start, "end_beat": end, "object_ids": selected,
                      "text": text, "created_at": now(), "status": "recorded", "reviewer": "local user"}
            write_json(path / "feedback" / (result["id"] + ".json"), result)
            return result

    def review(self, project_id: str, data: dict) -> dict:
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(path / "arrangement.json")
            if data.get("revision") != arrangement_revision(arrangement):
                raise ConflictError("Review is stale; reload the project")
            meta = read_json(path / "project.json")
            if data.get("decision") == "go" and not (data.get("playtested") is True or
                    (meta.get("playtested") and meta.get("review_revision") == arrangement_revision(arrangement))):
                raise ValueError("A go decision requires an in-game playtest on this revision")
            if "minutes_spent" in data:
                minutes = data["minutes_spent"]
                if isinstance(minutes, bool) or not isinstance(minutes, (float, int)) or not math.isfinite(minutes) or not 0 <= minutes <= 1440:
                    raise ValueError("Review time must be between zero and 1,440 minutes")
            if data.get("playtested"):
                if not str(data.get("game_build", meta.get("game_build") or "")).strip():
                    raise ValueError("Record the game build for an in-game playtest")
                if not str(data.get("notes", "")).strip():
                    raise ValueError("Record observations from the playtest")
            if "decision" in data and data["decision"] not in {"pending", "go", "revise", "stop"}:
                raise ValueError("Decision must be pending, go, revise or stop")
            if "ratings" in data:
                if not isinstance(data["ratings"], dict):
                    raise ValueError("Ratings must be an object")
                for rating in data["ratings"].values():
                    if type(rating) is not int or not 1 <= rating <= 5:
                        raise ValueError("Qualitative ratings must be integers from 1 to 5")
            for key in ("timing_reviewed", "playtested"):
                if key in data:
                    if type(data[key]) is not bool:
                        raise ValueError(f"{key} must be boolean")
                    meta[key] = data[key]
            if "game_build" in data:
                meta["game_build"] = str(data["game_build"])[:200]
            meta["updated_at"] = now()
            meta["review_revision"] = arrangement_revision(arrangement)
            write_json(path / "project.json", meta)
            write_json(path / "reviews" / (uuid.uuid4().hex + ".json"),
                       {**data, "schema_version": "1.0", "at": now(), "origin": "user-entered",
                        "audio_sha256": hashlib.sha256((path / "song.ogg").read_bytes()).hexdigest(),
                        "mechanical": {"diagnostics": validate_arrangement(arrangement)},
                        "scope": "One-rater qualitative observation; no population-level or automatic quality claim"})
            return self.get(project_id)

    def export(self, project_id: str) -> dict:
        from .export import export_arrangement
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(path / "arrangement.json")
            revision = arrangement_revision(arrangement)
            filename = f"map-{revision[:10]}-{uuid.uuid4().hex[:6]}.zip"
            report = export_arrangement(arrangement, path / "song.ogg", path / "cover.png", path / "exports" / filename)
            report["review"] = read_json(path / "project.json")
            write_json(path / "exports" / (filename + ".json"), report)
            return {"filename": filename, "report": report, "url": f"/api/projects/{project_id}/files/exports/{filename}"}
