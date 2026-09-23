"""Worktree-local workspace clones: map work in a git worktree reads and writes its own copy of the workspace.

The real workspace (``sabermapper/workspace/`` in the main checkout) is user data shared by the studio and every
agent. A worktree clones it once, runs every project command against the clone without touching the shared
``.project.lock``, and after its code is merged into ``main`` publishes only the files it changed back to the real
workspace. A file the real workspace also changed since the clone is never overwritten: its unit (one project, one
authoring folder, or a top-level entry such as the corpus) is held back as a conflict. The one exception is a
project's ``project.json`` while the real workspace left the project's arrangement files as the clone found them:
publish merges it key by key (see :func:`merge_metadata`), so a studio or show save there does not send the clone's
arrangements through a second ``project save``.

Audio and content-addressed files are written once and never rewritten in place, so the clone hardlinks them (no
extra disk space); every other file is copied, so in-place writers such as SQLite or append-only logs only ever
touch the clone.
"""
from __future__ import annotations

from contextlib import nullcontext
import filecmp
import os
from pathlib import Path
import re
import shutil
import subprocess

from .storage import WorkspaceLock, now, read_json, write_json

MANIFEST = ".clone.json"
# Downloader state and credentials, not map data.
SKIPPED_TOP = {"tidal"}
# Regenerated from the arrangement by `project export`; export may rewrite a ZIP name in place.
SKIPPED_PROJECT_DIRS = {"exports"}
WRITE_ONCE_SUFFIXES = {".wav", ".ogg", ".egg", ".flac", ".mp3", ".m4a", ".opus"}
CONTENT_ADDRESSED = re.compile(r"[a-f0-9]{64}")
GROUPED_TOP = {"projects", "authoring", "retired-projects"}
CORPUS_FILES_FOR_MAPS = ("tier-reference.json", "splits.json")
# project.json keys the studio and reviews set in the real workspace; a merge keeps the real values.
REAL_METADATA = ("album", "game_build", "mods", "review_revision")
# Claims about the current revision; a merge keeps a real claim while the arrangements it was made on stay.
REVIEW_CLAIMS = ("playtested", "timing_reviewed")


class CloneError(ValueError):
    def __init__(self, code: str, message: str, fix: str | None = None):
        super().__init__(message)
        self.code, self.fix = code, fix


def app_directory() -> Path:
    """The ``sabermapper/`` application directory of the checkout this code runs from."""
    return Path(__file__).resolve().parents[1]


def main_workspace(start: Path | None = None) -> Path:
    """The real workspace: ``sabermapper/workspace`` in the main checkout of the repository containing ``start``."""
    start = Path(start or app_directory())
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=start,
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CloneError("not_a_checkout", f"{start} is not inside a git checkout, so the main workspace is unknown",
                         "Pass --from PATH to the real workspace") from exc
    return Path(common).resolve().parent / "sabermapper" / "workspace"


def _unit(relative: str) -> str:
    """The publish unit of a workspace-relative path: projects/ID, authoring/NAME, or the top-level entry."""
    parts = relative.split("/")
    if parts[0] in GROUPED_TOP and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def _skipped(relative: str) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    if relative == MANIFEST or name.endswith(".lock") or name.startswith(".pending-") or name.endswith(".part"):
        return True
    if parts[0] in SKIPPED_TOP:
        return True
    return parts[0] == "projects" and len(parts) > 3 and parts[2] in SKIPPED_PROJECT_DIRS


def _write_once(relative: str) -> bool:
    path = Path(relative)
    return path.suffix.lower() in WRITE_ONCE_SUFFIXES or bool(CONTENT_ADDRESSED.fullmatch(path.stem))


def _walk(root: Path):
    """Workspace-relative POSIX paths of every file under ``root`` that a clone carries."""
    for directory, folders, files in os.walk(root):
        base = Path(directory).relative_to(root)
        prefix = "" if str(base) == "." else base.as_posix() + "/"
        folders[:] = [f for f in folders if not _skipped(prefix + f + "/file")]  # prune skipped folders
        for name in files:
            relative = prefix + name
            if not _skipped(relative):
                yield relative


def _stamp(path: Path) -> list[int]:
    info = path.stat()
    return [info.st_size, info.st_mtime_ns]


def _place(source: Path, target: Path, *, link: bool) -> str:
    """Hardlink ``source`` to ``target`` when allowed and possible, else copy it with its timestamps."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".pending-{target.name}")
    temporary.unlink(missing_ok=True)
    try:
        if link:
            try:
                os.link(source, temporary)
                os.replace(temporary, target)
                return "linked"
            except OSError:
                temporary.unlink(missing_ok=True)
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
        return "copied"
    finally:
        temporary.unlink(missing_ok=True)


def _same_content(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _is_empty(root: Path) -> bool:
    if not root.exists():
        return True
    return not any(not name.endswith(".lock") for _, _, files in os.walk(root) for name in files)


def clone(target: str | Path, source: str | Path | None = None, *, replace: bool = False,
          corpus: bool = True, discard_local: bool = False) -> dict:
    """Clone the real workspace ``source`` into ``target`` and record what each file looked like."""
    target = Path(target).resolve()
    source = Path(source).resolve() if source else main_workspace()
    if not (source / "projects").is_dir():
        raise CloneError("source_missing", f"{source} is not a SaberMapper workspace (it has no projects/ folder)",
                         "Pass --from PATH to the real workspace in the main checkout")
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise CloneError("clone_is_source", f"{target} is the real workspace; a clone must live elsewhere",
                         "Run `workspace clone` from the sabermapper/ folder of a worktree, not the main checkout")
    manifest_path = target / MANIFEST
    if manifest_path.exists():
        if not replace:
            raise CloneError("clone_exists", f"{target} already holds a clone of {read_json(manifest_path)['source']}",
                             "Use `workspace status`, or `workspace clone --replace` to start again from the real "
                             "workspace")
        pending = [u for u in status(target)["units"] if u["local_changes"]]
        if pending and not discard_local:
            raise CloneError("unpublished_changes",
                             "The clone has unpublished changes in " + ", ".join(u["unit"] for u in pending),
                             "Run `workspace publish` first, or pass --discard-local to drop them")
        shutil.rmtree(target)
    elif not _is_empty(target):
        raise CloneError("target_not_empty", f"{target} already holds files that are not a clone",
                         "Move them away or pick another --to folder")
    target.mkdir(parents=True, exist_ok=True)
    files, counts, grouped = {}, {"linked": 0, "copied": 0}, {}
    for relative in _walk(source):
        if relative.startswith("corpus/") and not corpus and relative[7:] not in CORPUS_FILES_FOR_MAPS:
            continue
        grouped.setdefault(_unit(relative), []).append(relative)
    lock = WorkspaceLock(source / ".project.lock")
    for unit, paths in grouped.items():
        # One project at a time under the workspace lock, so each project is a consistent snapshot of one save
        # and other processes wait for one project's files at most.
        with lock if unit.startswith("projects/") else nullcontext():
            for relative in paths:
                origin = source / relative
                try:
                    # Stamp first: a file rewritten during the copy then reads as changed on both sides, which
                    # publish reports as a conflict instead of overwriting the newer file.
                    stamp = _stamp(origin)
                    counts[_place(origin, target / relative, link=_write_once(relative))] += 1
                except FileNotFoundError:  # removed while cloning
                    continue
                files[relative] = stamp
    (target / "projects").mkdir(exist_ok=True)
    write_json(manifest_path, {"schema_version": "1.0", "source": str(source), "cloned_at": now(),
                               "corpus": "full" if corpus else "map files only", "files": files})
    return {"clone": str(target), "source": str(source), "files": len(files), **counts,
            "projects": sorted({_unit(r) for r in files if r.startswith("projects/")})}


def _load(target: Path) -> tuple[Path, dict]:
    manifest_path = Path(target).resolve() / MANIFEST
    if not manifest_path.exists():
        raise CloneError("not_a_clone", f"{Path(target).resolve()} is not a workspace clone",
                         "Run `workspace clone` in the worktree's sabermapper/ folder first")
    manifest = read_json(manifest_path)
    return Path(manifest["source"]), manifest


def _plan(target: Path, source: Path, files: dict) -> dict[str, list[dict]]:
    """Per unit, the local changes and whether the real workspace changed the same files since the clone."""
    units: dict[str, list[dict]] = {}
    seen = set()
    for relative in _walk(target):
        seen.add(relative)
        recorded, local, real = files.get(relative), target / relative, source / relative
        if recorded is not None and _stamp(local) == recorded:
            continue
        if real.exists() and _same_content(local, real):
            continue
        if recorded is None:
            action, conflict = "add", real.exists()
        else:
            action, conflict = "update", not real.exists() or _stamp(real) != recorded
        units.setdefault(_unit(relative), []).append({"path": relative, "action": action, "conflict": conflict})
    for relative, recorded in files.items():
        if relative in seen:
            continue
        real = source / relative
        if not real.exists():
            continue
        units.setdefault(_unit(relative), []).append(
            {"path": relative, "action": "delete", "conflict": _stamp(real) != recorded})
    return units


def _arrangement_file(relative: str) -> bool:
    parts = relative.split("/")
    return parts[0] == "projects" and (parts[2:] == ["arrangement.json"]
                                       or (len(parts) == 4 and parts[2] == "difficulties" and parts[3].endswith(".json")))


def _arrangements_unchanged(unit: str, source: Path, files: dict) -> bool:
    """Whether the real workspace's arrangement files of project ``unit`` are the ones the clone started from."""
    recorded = {r: stamp for r, stamp in files.items() if r.startswith(unit + "/") and _arrangement_file(r)}
    real = {unit + "/arrangement.json"} | {f"{unit}/difficulties/{f.name}"
                                          for f in (source / unit / "difficulties").glob("*.json")}
    real = {r for r in real if (source / r).is_file()}
    return real == set(recorded) and all(_stamp(source / r) == stamp for r, stamp in recorded.items())


def merge_metadata(local: dict, real: dict, *, arrangements_published: bool) -> dict:
    """The project.json both workspaces hold after publishing the clone's changes.

    The clone's values win (its saves wrote title and artist from the arrangement being published), except the
    keys the studio and reviews set in the real workspace and the newer ``updated_at``. A real playtest or timing
    review stands while the arrangements it was recorded on stay; when the clone publishes an arrangement, the
    claim stays only where the clone kept it too (a save records ``playtested: false`` for the new revision).
    """
    merged = {**real, **{k: v for k, v in local.items() if k not in REAL_METADATA + REVIEW_CLAIMS}}
    stamps = [t for t in (local.get("updated_at"), real.get("updated_at")) if t]
    if stamps:
        merged["updated_at"] = max(stamps)
    for key in REVIEW_CLAIMS:
        if key in real and arrangements_published:
            merged[key] = bool(real[key]) and bool(local.get(key))
    return merged


def _resolve(unit: str, changes: list[dict], source: Path, files: dict) -> tuple[list[str], list[str]]:
    """(conflicting paths, paths publish merges): project.json merges while the real arrangements are unchanged."""
    conflicts = [c["path"] for c in changes if c["conflict"]]
    metadata = unit + "/project.json"
    if (unit.startswith("projects/") and metadata in conflicts and (source / metadata).is_file()
            and _arrangements_unchanged(unit, source, files)):
        return [p for p in conflicts if p != metadata], [metadata]
    return conflicts, []


def _merge_file(target: Path, source: Path, relative: str, changes: list[dict]):
    """Write the merged project.json into both workspaces, so the clone has nothing left to publish."""
    published = any(_arrangement_file(c["path"]) and c["action"] != "delete" for c in changes)
    merged = merge_metadata(read_json(target / relative), read_json(source / relative),
                            arrangements_published=published)
    write_json(source / relative, merged)
    write_json(target / relative, merged)


def _behind(source: Path, files: dict) -> set[str]:
    """Units the real workspace changed since the clone (any recorded file modified or removed)."""
    changed = set()
    for relative, recorded in files.items():
        unit = _unit(relative)
        if unit in changed:
            continue
        real = source / relative
        if not real.exists() or _stamp(real) != recorded:
            changed.add(unit)
    return changed


def status(target: str | Path) -> dict:
    """What publishing would copy, per unit, and which units the real workspace changed since the clone."""
    target = Path(target).resolve()
    source, manifest = _load(target)
    plan = _plan(target, source, manifest["files"])
    behind = _behind(source, manifest["files"])
    rows = []
    for unit in sorted(set(plan) | behind):
        changes = plan.get(unit, [])
        conflicts, merges = _resolve(unit, changes, source, manifest["files"])
        rows.append({"unit": unit, "local_changes": len(changes),
                     "added": sum(c["action"] == "add" for c in changes),
                     "updated": sum(c["action"] == "update" for c in changes),
                     "deleted": sum(c["action"] == "delete" for c in changes),
                     "real_workspace_changed": unit in behind, "conflicts": conflicts,
                     **({"merged": merges} if merges else {})})
    return {"clone": str(target), "source": str(source), "cloned_at": manifest["cloned_at"],
            "publishable": [r["unit"] for r in rows if r["local_changes"] and not r["conflicts"]],
            "conflicted": [r["unit"] for r in rows if r["conflicts"]], "units": rows}


def _conflict_fix(unit: str, source: Path, target: Path, conflicts: list[str]) -> str:
    if not unit.startswith("projects/"):
        return (f"The real workspace changed {unit} since the clone. Redo the change against it with --workspace "
                f"{source}, then `workspace clone --replace`")
    project = unit.split("/")[1]
    saves, others = [], []
    for relative in conflicts:
        if not _arrangement_file(relative):
            others.append(relative.split("/", 2)[2])
            continue
        file = target / relative
        difficulty = "" if relative.endswith("/arrangement.json") else f" --difficulty {file.stem}"
        # --base names the clone's arrangement itself, so every value the clone's placer chose stays placer-chosen.
        saves.append(f"`project save {project} --workspace {source}{difficulty} --revision REV "
                     f"--arrangement {file} --base {file}`")
    steps = []
    if saves:
        steps.append(f"save the clone's arrangement onto the real revision REV (`project get {project} --workspace "
                     f"{source}`, with the same --difficulty): " + "; ".join(saves))
    if others:
        steps.append(f"redo the clone's change to {', '.join(others)} against --workspace {source}")
    return (f"The real workspace changed {unit} since the clone. " + ", then ".join(steps)
            + ", then run `workspace clone --replace`")


def publish(target: str | Path, *, units: list[str] | None = None, dry_run: bool = False) -> dict:
    """Copy the clone's changed files into the real workspace, skipping every unit with a conflict."""
    target = Path(target).resolve()
    source, manifest = _load(target)
    files = manifest["files"]
    wanted = set(units or [])
    published, held, applied = [], [], {"added": 0, "updated": 0, "deleted": 0}
    with WorkspaceLock(source / ".project.lock"):
        plan = _plan(target, source, files)
        if wanted:
            names = {u: u for u in plan} | {u.split("/")[-1]: u for u in plan}
            missing = sorted(w for w in wanted if w not in names)
            if missing:
                raise CloneError("unit_unchanged", "No local changes in " + ", ".join(missing),
                                 "Run `workspace status` to list the units with changes")
            plan = {names[w]: plan[names[w]] for w in wanted}
        for unit, changes in sorted(plan.items()):
            conflicts, merges = _resolve(unit, changes, source, files)
            if conflicts:
                held.append({"unit": unit, "conflicts": conflicts,
                             "fix": _conflict_fix(unit, source, target, conflicts)})
                continue
            published.append({"unit": unit, "changes": changes, "merged": merges})
            if dry_run:
                continue
            # Deepest files first (history, evidence runs) and the project's own arrangement and metadata last,
            # so a reader never sees an arrangement whose history or evidence is missing; deletions come last.
            for change in sorted(changes, key=lambda c: (c["action"] == "delete", -c["path"].count("/"))):
                relative = change["path"]
                if relative in merges:
                    _merge_file(target, source, relative, changes)
                    files[relative] = _stamp(source / relative)
                    applied["merged"] = applied.get("merged", 0) + 1
                    continue
                if change["action"] == "delete":
                    (source / relative).unlink(missing_ok=True)
                    files.pop(relative, None)
                    applied["deleted"] += 1
                    continue
                _place(target / relative, source / relative, link=_write_once(relative))
                files[relative] = _stamp(source / relative)
                applied["added" if change["action"] == "add" else "updated"] += 1
        if not dry_run and published:
            write_json(target / MANIFEST, manifest)
    return {"clone": str(target), "source": str(source), "dry_run": dry_run,
            "published": [{"unit": p["unit"], "files": len(p["changes"]), **({"merged": p["merged"]} if p["merged"] else {})}
                          for p in published],
            "held_back": held, **({} if dry_run else {"applied": applied})}
