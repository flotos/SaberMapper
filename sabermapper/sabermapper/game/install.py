"""Install exported maps into Beat Saber's CustomWIPLevels as `SaberMapper-<name>` folders.

Every install replaces the previous folder atomically (extract to a staging folder, then swap) and records
`sabermapper-install.json` = {project, revision, difficulty, export, installed_at, source}. SaberMapper never
writes into CustomLevels.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid
import zipfile

from .errors import GameError
from .logs import default_game_dir

PREFIX = "SaberMapper-"
INSTALL_RECORD = "sabermapper-install.json"
_NAME = re.compile(r"^SaberMapper-[A-Za-z0-9_.-]{1,80}$")


def wip_root(game_dir: str | Path | None = None) -> Path:
    root = default_game_dir(game_dir) / "Beat Saber_Data" / "CustomWIPLevels"
    if not root.parent.is_dir():
        raise GameError("game_not_found", f"No Beat Saber_Data folder under {root.parent.parent}",
                        {"game_dir": str(root.parent.parent)}, fix="Pass --game-dir or set SABERMAPPER_GAME_DIR")
    return root


def folder_name(project_id: str) -> str:
    return PREFIX + project_id


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise GameError("install_invalid", f"Install folder {name!r} must match {_NAME.pattern}",
                        fix="Use a SaberMapper- prefixed folder name made of letters, digits, '_', '.', '-'")
    return name


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir():
            continue
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise GameError("install_invalid", f"Map ZIP entry {info.filename!r} is not a top-level file",
                            fix="Re-export the map; SaberMapper exports only top-level files")
        members.append(info)
    if not any(m.filename.lower() == "info.dat" for m in members):
        raise GameError("install_invalid", "Map ZIP has no Info.dat", fix="Re-export the map")
    return members


def install_folder(source: str | Path, name: str, *, record: dict, game_dir: str | Path | None = None) -> dict:
    """Install a map ZIP or a map folder as CustomWIPLevels/<name>, replacing any previous install."""
    source = Path(source)
    root = wip_root(game_dir)
    root.mkdir(exist_ok=True)
    target = root / _check_name(name)
    staging = root / f".{name}.staging-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        if source.is_dir():
            if not (source / "Info.dat").is_file():
                raise GameError("install_invalid", f"{source} has no Info.dat", fix="Point at an extracted map folder")
            for file in source.iterdir():
                if file.is_file():
                    shutil.copy2(file, staging / file.name)
        else:
            with zipfile.ZipFile(source) as archive:
                for info in _members(archive):
                    (staging / Path(info.filename).name).write_bytes(archive.read(info))
        payload = {**record, "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "source": str(source)}
        (staging / INSTALL_RECORD).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"level_path": str(target), "folder": name, "files": sorted(p.name for p in target.iterdir()),
            "record": payload}


CUSTOM_REQUIREMENTS = ("Vivify", "Noodle Extensions", "Chroma")


def uses_custom_events(level_path: str | Path) -> bool:
    """True when an installed map needs Heck-family mods (requirements) or carries customEvents.

    Late starts do not rebuild Heck/Vivify animation state (docs/game-bridge.md), so such maps are captured
    from song time 0.
    """
    level = Path(level_path)
    try:
        info = json.loads((level / "Info.dat").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    text = json.dumps(info)
    if any(f'"{name}"' in text for name in CUSTOM_REQUIREMENTS):
        return True
    for file in level.glob("*.dat"):
        if file.name.lower() == "info.dat":
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        custom = data.get("customData") or data.get("_customData") or {}
        if custom.get("customEvents") or custom.get("_customEvents"):
            return True
    return False


def installed(name: str, game_dir: str | Path | None = None) -> dict | None:
    path = wip_root(game_dir) / _check_name(name) / INSTALL_RECORD
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def uninstall(name: str, game_dir: str | Path | None = None) -> dict:
    target = wip_root(game_dir) / _check_name(name)
    existed = target.exists()
    if existed:
        shutil.rmtree(target)
    return {"removed": existed, "level_path": str(target)}


def export_revision(store, project_id: str, *, revision: str | None = None, difficulty: str | None = None) -> dict:
    """Export the project to a map ZIP: the current revision, or an older saved revision of one difficulty.

    Returns {filename, path, revision, difficulty, current}. Unknown revisions raise `stale_revision`.
    """
    from ..export import export_arrangements
    from ..revisions import arrangement_revision
    from ..storage import read_json, write_json
    with store.lock:
        path = store.directory(project_id)
        files = store.difficulty_files(path)
        primary = store.arrangement_file(path, difficulty)
        current = read_json(primary)
        name, current_revision = current["difficulty"]["name"], arrangement_revision(current)
    if revision in (None, current_revision):
        result = store.export(project_id)
        return {"filename": result["filename"], "path": str(path / "exports" / result["filename"]),
                "revision": current_revision, "difficulty": name, "current": True}
    old = store.revision_arrangement(path, revision, name)
    if old is None:
        raise GameError("stale_revision", f"Revision {str(revision)[:12]} is not a saved {name} revision of {project_id}",
                        {"current_revision": current_revision, "difficulty": name},
                        fix="Use the current revision (omit --revision) or one listed in `project get` history")
    with store.lock:
        arrangements = [old if other == name else read_json(file) for other, file in files.items()]
        filename = f"map-{revision[:10]}-{uuid.uuid4().hex[:6]}.zip"
        report = export_arrangements(arrangements, path / "song.ogg", path / "cover.png", path / "exports" / filename)
        report["review"] = read_json(path / "project.json")
        write_json(path / "exports" / (filename + ".json"), report)
    return {"filename": filename, "path": str(path / "exports" / filename), "revision": revision, "difficulty": name,
            "current": False}


def install_project(store, project_id: str, *, revision: str | None = None, difficulty: str | None = None,
                    game_dir: str | Path | None = None) -> dict:
    exported = export_revision(store, project_id, revision=revision, difficulty=difficulty)
    record = {"project": project_id, "revision": exported["revision"], "difficulty": exported["difficulty"],
              "export": exported["filename"], "current_revision": exported["current"]}
    result = install_folder(exported["path"], folder_name(project_id), record=record, game_dir=game_dir)
    return {**result, "export": exported}
