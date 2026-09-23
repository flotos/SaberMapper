"""Handover gate: every agent check a revision must pass before the human is asked to verify it.

`project verify` runs, for one difficulty of the current revision:

1. structure: arrangement validation (errors block);
2. audio: critique against the newest evidence run; unresolved audio findings block (AGENTS.md
   "Audio is the source of every note"), the rest are reported as warnings;
3. show: Vivify show validation when the project has a show (errors block);
4. capture: the newest in-game capture of exactly this revision and difficulty (required for a
   vivified project, optional otherwise), its frame metrics (errors block; a vivified project must
   also have a dense probe so the photosensitivity check ran) and its game-log errors (block).

The result says which checks ran, which were skipped and why, and what to do next.
"""
from __future__ import annotations

from pathlib import Path

from .revisions import arrangement_revision
from .storage import now, read_json, write_json

# Unresolved audio findings are never handed over (AGENTS.md); the rest of the critique is descriptive.
AUDIO_BLOCKING = {"audio_unmapped", "note_without_audio", "low_audio_support", "audio_evidence_missing"}


def _check(check_id, status, blocking=(), warnings=(), **detail):
    return {"id": check_id, "status": status, "blocking": list(blocking), "warnings": list(warnings), **detail}


def latest_capture(project_dir: Path, revision: str, difficulty: str) -> Path | None:
    """Newest `captures/*/capture.json` taken of exactly this revision and difficulty."""
    found = []
    for manifest in (Path(project_dir) / "captures").glob("*/capture.json"):
        try:
            data = read_json(manifest)
        except ValueError:
            continue
        if data.get("revision") == revision and data.get("difficulty") == difficulty:
            found.append((str(data.get("created_at", "")), manifest.parent))
    return max(found)[1] if found else None


def _structure(arrangement):
    from .validation import validate_arrangement
    diagnostics = validate_arrangement(arrangement)
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    return _check("structure", "fail" if errors else "pass", errors,
                  [d for d in diagnostics if d.get("severity") == "warning"])


def _audio(store, directory, arrangement):
    from .critique import critique_arrangement
    from .musical import latest_run
    run_id, report = latest_run(directory)
    reference_path = store.root / "corpus" / "tier-reference.json"
    result = critique_arrangement(arrangement, report, read_json(reference_path) if reference_path.exists() else None)
    findings = list(result["warnings"])
    if report is None:
        findings.insert(0, {"severity": "error", "code": "audio_evidence_missing", "section_id": None,
                            "object_ids": [], "value": None, "threshold": None,
                            "message": "No musical evidence run matches this project's audio; run "
                                       "`music analyze PROJECT` so the map is checked against the song."})
    blocking = [f for f in findings if f.get("code") in AUDIO_BLOCKING]
    return _check("audio", "fail" if blocking else "pass", blocking,
                  [f for f in findings if f.get("code") not in AUDIO_BLOCKING], run_id=run_id)


def _show(directory, show, arrangements, difficulty):
    from .musical import latest_run
    from .show import bundle_directory
    from .show_validation import validate_project_show
    from .vivify import read_bundle
    run_id, report = latest_run(directory)
    result = validate_project_show(show, {difficulty: arrangements[difficulty]},
                                   bundle=read_bundle(bundle_directory(directory)),
                                   evidence={"project_dir": directory, "run_id": run_id, "report": report})
    errors = [d for d in result["diagnostics"] if d.get("severity") == "error"]
    return _check("show", "fail" if errors else "pass", errors,
                  [d for d in result["diagnostics"] if d.get("severity") == "warning"])


def _capture(directory, revision, difficulty, arrangement, vivified, capture):
    from .frame_metrics import analyze_frames
    capture = Path(capture) if capture else latest_capture(directory, revision, difficulty)
    if capture is None:
        missing = {"severity": "error", "code": "capture_missing", "section_id": None, "object_ids": [],
                   "value": None, "threshold": None,
                   "message": f"No in-game capture of revision {revision[:10]} ({difficulty}); run "
                              "`game capture PROJECT --difficulty D` (it takes the game lease, plays the map "
                              "in FPFC and closes the game afterwards)."}
        if vivified:
            return [_check("capture", "fail", [missing]), _check("frames", "skipped", reason="no capture"),
                    _check("game_log", "skipped", reason="no capture")]
        return [_check("capture", "skipped", reason="optional for a map without a Vivify show; run "
                                                     "`game capture` to also check it in the game"),
                _check("frames", "skipped", reason="no capture"), _check("game_log", "skipped", reason="no capture")]
    manifest = read_json(capture / "capture.json")
    stale = manifest.get("revision") != revision
    checks = [_check("capture", "fail" if stale else "pass", [{
        "severity": "error", "code": "capture_revision_stale", "section_id": None, "object_ids": [],
        "value": manifest.get("revision"), "threshold": revision,
        "message": "The capture was taken of another revision; capture the current one."}] if stale else [],
        directory=str(capture), frames=len(manifest.get("frames", [])), created_at=manifest.get("created_at"))]
    concept = None
    for name in ("concept.json", "show.json"):
        if (directory / name).is_file():
            concept = read_json(directory / name)
            break
    result = analyze_frames(capture, arrangement, concept)
    findings = result["findings"]
    blocking = [f for f in findings if f.get("severity") == "error"]
    if vivified:
        blocking += [dict(f, severity="error", code="flash_unchecked",
                          message="The photosensitivity check did not run: " + f["message"] +
                                  " Capture a dense probe over the brightest or fastest-pulsing passage "
                                  "(`game capture ... --probe START-END@30`).")
                     for f in findings if f.get("code") == "flash_check_insufficient_sampling"]
    checks.append(_check("frames", "fail" if blocking else "pass", blocking,
                         [f for f in findings if f.get("severity") == "warning"]))
    logs = manifest.get("log_diagnostics") or []
    errors = [d for d in logs if d.get("severity") == "error"]
    checks.append(_check("game_log", "fail" if errors else "pass", errors,
                         [d for d in logs if d.get("severity") == "warning"]))
    return checks


def verify_project(store, project_id: str, difficulty: str | None = None, *, capture=None, record=False) -> dict:
    """Run every handover check on the current revision of one difficulty."""
    from .show import load_show
    with store.lock:
        directory = store.directory(project_id)
        arrangements = {name: read_json(file) for name, file in store.difficulty_files(directory).items()}
        arrangement = read_json(store.arrangement_file(directory, difficulty))
    name = arrangement["difficulty"]["name"]
    revision = arrangement_revision(arrangement)
    show = load_show(directory)
    vivified = show is not None
    checks = [_structure(arrangement), _audio(store, directory, arrangement)]
    checks.append(_show(directory, show, arrangements, name) if vivified
                  else _check("show", "skipped", reason="the project has no Vivify show"))
    checks += _capture(directory, revision, name, arrangement, vivified, capture)
    blocking = [dict(item, check=check["id"]) for check in checks for item in check["blocking"]]
    ready = not blocking
    result = {"project": project_id, "difficulty": name, "revision": revision, "vivified": vivified,
              "ready_for_human": ready, "checked_at": now(),
              "ran": [c["id"] for c in checks if c["status"] != "skipped"],
              "skipped": {c["id"]: c.get("reason") for c in checks if c["status"] == "skipped"},
              "blocking": blocking, "checks": checks,
              "scope": "Agent checks only: 2D captures and static checks do not show VR scale, comfort or feel; "
                       "the user's playtest remains ground truth."}
    result["next"] = (["Hand over: tell the user the revision, the checks that ran (`ran`) and what was skipped; "
                       "they verify it from the studio (Play in game / Watch / Note)."] if ready else
                      [f"Fix {item['check']}/{item['code']}: {item['message']}" for item in blocking[:10]])
    if record:
        path = directory / "verifications" / f"{revision[:16]}-{name}.json"
        write_json(path, result)
        result["recorded"] = str(path)
    return result


def register_verify(project_commands):
    leaf = project_commands.add_parser("verify", help="Handover gate: structure, audio, show, in-game capture, "
                                                      "frame metrics and game-log checks on the current revision")
    leaf.add_argument("project")
    leaf.add_argument("--workspace", type=Path, default=Path("workspace"))
    leaf.add_argument("--difficulty", choices=("Easy", "Normal", "Hard", "Expert", "ExpertPlus"),
                      help="Default: the primary difficulty")
    leaf.add_argument("--capture", type=Path, help="Capture directory; default: the newest capture of this revision")
    leaf.add_argument("--record", action="store_true",
                      help="Store the result in the project's verifications/ folder (do this before a handover)")


def dispatch_verify(args, emit):
    if args.command != "project" or getattr(args, "project_action", None) != "verify":
        return None
    from .projects import ProjectStore
    result = verify_project(ProjectStore(args.workspace), args.project, args.difficulty, capture=args.capture,
                            record=args.record)
    emit(result)
    return 0 if result["ready_for_human"] else 3
