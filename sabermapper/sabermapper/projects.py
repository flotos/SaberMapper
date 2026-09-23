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


DIFFICULTY_RANKS = {"Easy": 1, "Normal": 3, "Hard": 5, "Expert": 7, "ExpertPlus": 9}
_history_names: dict[Path, tuple[float, str | None]] = {}


class ConflictError(ValueError):
    pass


def _history_difficulty(file: Path) -> str | None:
    """Difficulty name of one content-addressed history file, cached by modification time."""
    mtime = file.stat().st_mtime
    cached = _history_names.get(file)
    if cached is None or cached[0] != mtime:
        try:
            name = read_json(file)["difficulty"]["name"]
        except (OSError, ValueError, KeyError, TypeError):
            name = None
        cached = _history_names[file] = (mtime, name)
    return cached[1]


def timing_mismatches(arrangements: dict[str, dict]) -> list[dict]:
    """Difficulties whose song timing differs from the first one; they all share one audio file."""
    items = list(arrangements.items())
    if len(items) < 2:
        return []
    reference_name, reference = items[0]

    def timing(arrangement):
        song = arrangement.get("song", {})
        return song.get("bpm"), song.get("audio_offset_seconds"), arrangement.get("tempo_events", [])
    return [{"severity": "warning", "code": "difficulty_timing_mismatch", "section_id": None, "object_ids": [],
             "message": f"{name} uses song timing (bpm {timing(item)[0]}, offset {timing(item)[1]} s) different from "
                        f"{reference_name} (bpm {timing(reference)[0]}, offset {timing(reference)[1]} s). Every "
                        "difficulty shares the audio: save matching song.bpm, audio_offset_seconds and tempo_events "
                        "before export."}
            for name, item in items[1:] if timing(item) != timing(reference)]


def song_position(arrangement: dict, seconds: float) -> dict:
    """Beat and containing section of a source-audio time (honours audio offset and tempo events)."""
    from .arrangement import beat_fraction
    from .musical import seconds_to_beat
    beat = seconds_to_beat(float(seconds), arrangement)
    section = None
    for item in arrangement.get("sections", []):
        try:
            start = float(beat_fraction(item["start_beat"]))
            end = start + float(beat_fraction(item["length_beats"]))
        except (KeyError, TypeError, ValueError):
            continue
        if start <= beat < end:
            section = item
            break
    return {"song_time": round(float(seconds), 3), "beat": round(beat, 3),
            "section": section["id"] if section else None,
            "section_label": (section.get("label") or section.get("name") or section.get("intent")) if section else None}


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

    def difficulty_files(self, path: Path) -> dict[str, Path]:
        """Every stored difficulty by name, primary first; arrangement.json holds the primary one."""
        primary = path / "arrangement.json"
        files = {read_json(primary)["difficulty"]["name"]: primary}
        for file in sorted((path / "difficulties").glob("*.json"), key=lambda f: DIFFICULTY_RANKS.get(f.stem, 0)):
            if file.stem in DIFFICULTY_RANKS and file.stem not in files:
                files[file.stem] = file
        return files

    def arrangement_file(self, path: Path, difficulty: str | None = None) -> Path:
        """The arrangement file for one difficulty; None selects the primary one."""
        if difficulty is None:
            return path / "arrangement.json"
        if difficulty not in DIFFICULTY_RANKS:
            raise ValueError(f"Unknown difficulty {difficulty!r}; use one of {', '.join(DIFFICULTY_RANKS)}")
        files = self.difficulty_files(path)
        if difficulty not in files:
            raise FileNotFoundError(f"Project has no {difficulty} difficulty (it has {', '.join(files)}); "
                                    "create it with `project add-difficulty`")
        return files[difficulty]

    def difficulties(self, project_id: str) -> list[dict]:
        """One summary row per stored difficulty: name, revision, density and target tier."""
        with self.lock:
            path = self.directory(project_id)
            duration = read_json(path / "project.json").get("duration_seconds") or 0
            rows = []
            for name, file in self.difficulty_files(path).items():
                arrangement = read_json(file)
                try:
                    count = len(expanded_notes(arrangement))
                except (ValueError, KeyError, TypeError):
                    count = None
                setting = arrangement.get("difficulty", {})
                rows.append({"name": name, "rank": DIFFICULTY_RANKS[name], "primary": file.name == "arrangement.json",
                             "revision": arrangement_revision(arrangement), "njs": setting.get("njs"),
                             "target_tier": setting.get("target_tier"), "note_count": count,
                             "nps": round(count / duration, 3) if count is not None and duration else None})
            return rows

    def list(self) -> list[dict]:
        result = []
        for path in self.projects.glob("*/project.json"):
            try:
                item = read_json(path)
                entry = {k: item.get(k) for k in ("id", "title", "artist", "created_at", "updated_at", "origin", "duration_seconds")}
                entry["album"] = item.get("album") or source_album((item.get("audio") or {}).get("source_path"),
                                                                    item.get("artist"))
                entry["difficulties"] = list(self.difficulty_files(path.parent))
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

    def get(self, project_id: str, difficulty: str | None = None) -> dict:
        from .movement import analyze_movement
        from .musical import project_runs
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(self.arrangement_file(path, difficulty))
            name = arrangement["difficulty"]["name"]
            siblings = {name: arrangement, **{other: read_json(file) for other, file in self.difficulty_files(path).items()
                                              if other != name}}
            diagnostics = validate_arrangement(arrangement) + timing_mismatches(siblings)
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
                from .lighting import lighting_findings
                diagnostics += lighting_findings(arrangement, report)[1]
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
            return {"project": read_json(path / "project.json"), "difficulty": name,
                    "difficulties": self.difficulties(project_id), "arrangement": arrangement,
                    "revision": arrangement_revision(arrangement), "analysis": read_json(path / "analysis.json"),
                    "musical_runs": project_runs(path), "audio_check": {"run_id": audio_run, **audio},
                    "notes": notes, "beatmap": beatmap, "diagnostics": diagnostics,
                    "movement": analyze_movement(notes, bpm=arrangement["song"]["bpm"],
                                                 njs=arrangement["difficulty"]["njs"],
                                                 spawn_offset_beats=arrangement["difficulty"]["spawn_offset_beats"]) if notes else {},
                    "feedback": self.feedback(project_id),
                    "reviews": [read_json(p) for p in sorted((path / "reviews").glob("*.json"))],
                    "history": [p.stem for p in sorted((path / "history").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                                if _history_difficulty(p) in (name, None)],
                    "exports": [p.name for p in sorted((path / "exports").glob("*.zip"))],
                    "show": self.show(path, siblings)}

    def show(self, path: Path, arrangements: dict[str, dict]) -> dict:
        """The project's Vivify show record (document, revision, what it was written against, bundle)."""
        from .show import show_record
        return show_record(path, arrangements)

    def check_save(self, project_id: str, arrangement: dict, expected_revision: str,
                   difficulty: str | None = None) -> dict:
        """Raise the conflict or validation error a save would raise; write nothing.

        Returns the current stored arrangement so callers can continue under the lock.
        """
        with self.lock:
            path = self.directory(project_id)
            original = read_json(self.arrangement_file(path, difficulty))
            old_revision = arrangement_revision(original)
            if expected_revision != old_revision:
                raise ConflictError("This arrangement changed since you opened it. Reload before saving.")
            errors = [d for d in validate_arrangement(arrangement) if d["severity"] == "error" and d["code"] != "unresolved_section"]
            if errors:
                raise ValueError("; ".join(d["message"] for d in errors[:10]))
            renamed = arrangement["difficulty"]["name"]
            if renamed != original["difficulty"]["name"] and renamed in self.difficulty_files(path):
                raise ConflictError(f"The project already has a {renamed} difficulty; pick another name "
                                    "or save into that difficulty with --difficulty")
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
                        or any(original["difficulty"].get(k) != arrangement["difficulty"].get(k)
                               for k in ("njs", "spawn_offset_beats"))):
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

    def save(self, project_id: str, arrangement: dict, expected_revision: str, *, request_id=None,
             difficulty: str | None = None) -> dict:
        with self.lock:
            path = self.directory(project_id)
            source = self.arrangement_file(path, difficulty)
            original = self.check_save(project_id, arrangement, expected_revision, difficulty)
            arrangement, lighting = self.refresh_lights(path, arrangement, original)
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
            name, previous_name = arrangement["difficulty"]["name"], original["difficulty"]["name"]
            primary = source.name == "arrangement.json"
            target = source if primary else path / "difficulties" / f"{name}.json"
            write_json(path / "history" / (old_revision + ".json"), original)
            write_json(path / "history" / (revision + ".json"), arrangement)
            write_json(target, arrangement)
            if target != source:
                source.unlink()
            meta = read_json(path / "project.json")
            meta["updated_at"] = now()
            if primary:
                meta.update(title=arrangement["song"]["title"], artist=arrangement["song"]["artist"])
            if original["song"] != arrangement["song"]:
                meta["timing_reviewed"] = False
            meta["playtested"] = False
            write_json(path / "project.json", meta)
            if request_id is not None:
                request.update(status="addressed", resulting_revision=revision)
                write_json(request_path, request)
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "previous": old_revision, "revision": revision,
                        "difficulty": name, **({"previous_difficulty": previous_name} if name != previous_name else {}),
                        "request_id": request_id, "at": now(), "lighting": lighting["action"],
                        "diagnostics": validate_arrangement(arrangement)})
            return {**self.get(project_id, None if primary else name), "lighting": lighting}

    def refresh_lights(self, path: Path, arrangement: dict, original: dict, *, force=False) -> tuple[dict, dict]:
        """Carry over, regenerate when missing or stale, and check the lightshow a save will store."""
        from .lighting import locked_light_changes, refresh_lightshow
        from .musical import latest_run
        run_id, report = latest_run(path)
        arrangement, info = refresh_lightshow(arrangement, original, run_id, report, force=force)
        if info["action"] == "generated":
            errors = [d for d in validate_arrangement(arrangement)
                      if d["severity"] == "error" and d["code"] != "unresolved_section"]
            if errors:
                raise ValueError("Generated lightshow failed validation: " + "; ".join(d["message"] for d in errors[:10]))
        changed = locked_light_changes(original, arrangement)
        if changed:
            raise ConflictError(f"Lights of locked section(s) {', '.join(changed)} would change. Unlock them first.")
        return arrangement, {**info, "run_id": run_id}

    def add_difficulty(self, project_id: str, name: str, *, source: str | None = None, njs: float | None = None,
                       target_tier: str | None = None) -> dict:
        """Create a difficulty as an unlocked copy of another one, ready to be rewritten at its own level."""
        if name not in DIFFICULTY_RANKS:
            raise ValueError(f"Unknown difficulty {name!r}; use one of {', '.join(DIFFICULTY_RANKS)}")
        with self.lock:
            path = self.directory(project_id)
            if name in self.difficulty_files(path):
                raise ConflictError(f"The project already has a {name} difficulty")
            original = read_json(self.arrangement_file(path, source))
            arrangement = deepcopy(original)
            arrangement["difficulty"].update(name=name, rank=DIFFICULTY_RANKS[name])
            if njs is not None:
                arrangement["difficulty"]["njs"] = njs
            if target_tier is not None:
                arrangement["difficulty"]["target_tier"] = target_tier
            unlocked = [s["id"] for s in arrangement["sections"] if s.get("locked")]
            for section in arrangement["sections"]:
                section["locked"] = False
            errors = [d for d in validate_arrangement(arrangement)
                      if d["severity"] == "error" and d["code"] != "unresolved_section"]
            if errors:
                raise ValueError("; ".join(d["message"] for d in errors[:10]))
            revision = arrangement_revision(arrangement)
            write_json(path / "history" / (revision + ".json"), arrangement)
            write_json(path / "difficulties" / f"{name}.json", arrangement)
            meta = read_json(path / "project.json")
            meta.update(updated_at=now(), playtested=False)
            write_json(path / "project.json", meta)
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "operation": "add_difficulty", "difficulty": name,
                        "source_difficulty": original["difficulty"]["name"],
                        "source_revision": arrangement_revision(original),
                        "revision": revision, "unlocked_sections": unlocked, "at": now()})
            return self.get(project_id, name)

    def remove_difficulty(self, project_id: str, name: str, expected_revision: str) -> dict:
        """Delete a non-primary difficulty; its content stays in history."""
        with self.lock:
            path = self.directory(project_id)
            file = self.arrangement_file(path, name)
            if file.name == "arrangement.json":
                raise ValueError("The primary difficulty cannot be removed; rename it by saving another name instead")
            arrangement = read_json(file)
            revision = arrangement_revision(arrangement)
            if revision != expected_revision:
                raise ConflictError("This difficulty changed since you opened it. Reload before removing it.")
            write_json(path / "history" / (revision + ".json"), arrangement)
            file.unlink()
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "operation": "remove_difficulty", "difficulty": name,
                        "previous": revision, "at": now()})
            return self.get(project_id)

    def set_lock(self, project_id: str, section_id: str, locked: bool, expected_revision: str,
                 difficulty: str | None = None) -> dict:
        if type(locked) is not bool:
            raise ValueError("locked must be a boolean")
        with self.lock:
            path = self.directory(project_id)
            file = self.arrangement_file(path, difficulty)
            arrangement = read_json(file)
            if arrangement_revision(arrangement) != expected_revision:
                raise ConflictError("Stale revision; reload the project")
            section = next((s for s in arrangement["sections"] if s["id"] == section_id), None)
            if section is None:
                raise ValueError("Section was not found")
            previous = arrangement_revision(arrangement)
            section["locked"] = locked
            revision = arrangement_revision(arrangement)
            write_json(path / "history" / (revision + ".json"), arrangement)
            write_json(file, arrangement)
            write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                       {"schema_version": "1.0", "previous": previous, "revision": revision,
                        "difficulty": arrangement["difficulty"]["name"],
                        "operation": "lock" if locked else "unlock", "section_id": section_id, "at": now()})
            return self.get(project_id, difficulty)

    def restore(self, project_id: str, revision: str, expected_revision: str, difficulty: str | None = None) -> dict:
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Invalid saved revision")
        return self.save(project_id, read_json(self.directory(project_id) / "history" / (revision + ".json")),
                         expected_revision, difficulty=difficulty)

    def feedback(self, project_id: str) -> list[dict]:
        """Every feedback record: beat ranges (kind "range") and timestamped notes (kind "note")."""
        return [{"kind": "range", **read_json(p)} for p in sorted((self.directory(project_id) / "feedback").glob("*.json"))]

    def revision_arrangement(self, path: Path, revision, difficulty: str | None) -> dict | None:
        """The stored arrangement of one saved revision of this difficulty, or None when it is unknown."""
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            return None
        file = path / "history" / (revision + ".json")
        if not file.is_file() or _history_difficulty(file) not in (difficulty, None):
            return None
        return read_json(file)

    def add_note(self, project_id: str, *, song_time: float, text: str, revision: str | None = None,
                 difficulty: str | None = None, source: str = "cli") -> dict:
        """Record a timestamped verification note; its beat and section come from the reviewed revision.

        A note on an older saved revision is kept (the human may verify an earlier version) and marked
        ``stale`` with both the reviewed ``revision`` and the ``current_revision`` recorded.
        """
        if source not in {"studio", "cli"}:
            raise ValueError("Note source must be studio or cli")
        with self.lock:
            path = self.directory(project_id)
            current = read_json(self.arrangement_file(path, difficulty))
            name = current["difficulty"]["name"]
            current_revision = arrangement_revision(current)
            revision = revision or current_revision
            arrangement = current if revision == current_revision else self.revision_arrangement(path, revision, name)
            if arrangement is None:
                raise ValueError(f"Revision {revision!r} is not a saved {name} revision of this project; use the "
                                 f"current revision {current_revision} or one listed in `project get` history")
            duration = float(read_json(path / "project.json").get("duration_seconds") or 0)
            if isinstance(song_time, bool) or not isinstance(song_time, (int, float)) or not math.isfinite(song_time) \
                    or not 0 <= song_time <= duration:
                raise ValueError(f"Note time must be between 0 and the song duration ({duration:.3f} s)")
            text = str(text or "").strip()
            if not text or len(text) > 2000:
                raise ValueError("Enter a note between 1 and 2,000 characters")
            stale = revision != current_revision
            result = {"schema_version": "1.0", "id": uuid.uuid4().hex[:12], "kind": "note", "project": project_id,
                      "revision": revision, "difficulty": name, "stale": stale,
                      **({"current_revision": current_revision} if stale else {}),
                      **song_position(arrangement, float(song_time)), "text": text, "created_at": now(),
                      "source": source, "status": "recorded", "reviewer": "local user"}
            write_json(path / "feedback" / (result["id"] + ".json"), result)
            return result

    def list_feedback(self, project_id: str, *, difficulty: str | None = None, revision: str | None = None,
                      kind: str | None = None, since: str | None = None) -> dict:
        """Notes and beat-range feedback sorted by song time, each with beat, section and revision status."""
        from datetime import datetime, timezone
        from .critique import beat_to_seconds
        if kind not in (None, "note", "range"):
            raise ValueError("Kind must be note or range")
        if difficulty is not None and difficulty not in DIFFICULTY_RANKS:
            raise ValueError(f"Unknown difficulty {difficulty!r}; use one of {', '.join(DIFFICULTY_RANKS)}")

        def moment(value):
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        try:
            after = moment(since) if since else None
        except ValueError as exc:
            raise ValueError("since must be an ISO date or time, e.g. 2026-09-23 or 2026-09-23T18:00:00+00:00") from exc
        with self.lock:
            path = self.directory(project_id)
            current = {name: read_json(file) for name, file in self.difficulty_files(path).items()}
            primary = next(iter(current))
            revisions = {name: arrangement_revision(a) for name, a in current.items()}
            rows = []
            for item in self.feedback(project_id):
                name = item.get("difficulty") or primary
                if (difficulty and name != difficulty) or (kind and item["kind"] != kind) \
                        or (revision and not str(item.get("revision", "")).startswith(revision)):
                    continue
                if after and moment(item.get("created_at") or "1970-01-01") < after:
                    continue
                row = {**item, "difficulty": name, "on_current_revision": item.get("revision") == revisions.get(name)}
                if item["kind"] == "range":
                    source = (current.get(name) if row["on_current_revision"] else
                              self.revision_arrangement(path, item.get("revision"), name) or current.get(name))
                    if source is not None:
                        seconds = beat_to_seconds(item["start_beat"], source)
                        position = song_position(source, seconds)
                        row.update(song_time=position["song_time"], beat=item["start_beat"],
                                   section=position["section"], section_label=position["section_label"],
                                   end_song_time=round(beat_to_seconds(item["end_beat"], source), 3))
                rows.append(row)
        rows.sort(key=lambda r: (r.get("song_time") is None, r.get("song_time") or 0, r.get("created_at") or ""))
        return {"project": project_id, "count": len(rows), "current_revisions": revisions,
                "filters": {"difficulty": difficulty, "revision": revision, "kind": kind, "since": since},
                "feedback": rows}

    def add_feedback(self, project_id: str, data: dict) -> dict:
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(self.arrangement_file(path, data.get("difficulty")))
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
                      "difficulty": arrangement["difficulty"]["name"],
                      "start_beat": start, "end_beat": end, "object_ids": selected,
                      "text": text, "created_at": now(), "status": "recorded", "reviewer": "local user"}
            write_json(path / "feedback" / (result["id"] + ".json"), result)
            return result

    def review(self, project_id: str, data: dict) -> dict:
        with self.lock:
            path = self.directory(project_id)
            arrangement = read_json(self.arrangement_file(path, data.get("difficulty")))
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
                       {**data, "difficulty": arrangement["difficulty"]["name"], "schema_version": "1.0",
                        "at": now(), "origin": "user-entered",
                        "audio_sha256": hashlib.sha256((path / "song.ogg").read_bytes()).hexdigest(),
                        "mechanical": {"diagnostics": validate_arrangement(arrangement)},
                        "scope": "One-rater qualitative observation; no population-level or automatic quality claim"})
            return self.get(project_id, data.get("difficulty"))

    def export(self, project_id: str) -> dict:
        """Export every difficulty of the project into one map ZIP."""
        from .export import export_arrangements
        with self.lock:
            path = self.directory(project_id)
            arrangements = [read_json(file) for file in self.difficulty_files(path).values()]
            revisions = {a["difficulty"]["name"]: arrangement_revision(a) for a in arrangements}
            revision = next(iter(revisions.values())) if len(revisions) == 1 else digest(revisions)
            filename = f"map-{revision[:10]}-{uuid.uuid4().hex[:6]}.zip"
            from .musical import latest_run
            from .show import bundle_directory, load_show
            run_id, evidence = latest_run(path)
            report = export_arrangements(arrangements, path / "song.ogg", path / "cover.png",
                                         path / "exports" / filename, show=load_show(path),
                                         bundle_dir=bundle_directory(path),
                                         evidence={"project_dir": path, "run_id": run_id, "report": evidence})
            report["review"] = read_json(path / "project.json")
            write_json(path / "exports" / (filename + ".json"), report)
            result = {"filename": filename, "report": report, "url": f"/api/projects/{project_id}/files/exports/{filename}"}
            if "vivify" in report:  # vivified: the ArcViewer twin and the provenance sidecar sit beside the map
                result["vanilla_twin"] = Path(report["vivify"]["vanilla_twin"]).name
                result["vanilla_twin_url"] = f"/api/projects/{project_id}/files/exports/{result['vanilla_twin']}"
                result["provenance_file"] = Path(report["vivify"]["provenance_file"]).name
            return result
