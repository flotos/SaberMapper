"""Command line entry point for the local studio and inspectable artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from .star_tiers import TIER_IDS
from .storage import read_json

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def emit(value, output=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sabermapper", description="Local Beat Saber authoring, review and research studio")
    parser.add_argument("--version", action="version", version="SaberMapper 0.2.0")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "compile", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("arrangement", type=Path)
        if name != "validate":
            sub.add_argument("--output", type=Path, required=True)
        if name == "export":
            sub.add_argument("--audio", type=Path, required=True)
            sub.add_argument("--cover", type=Path, required=True)
    sub = commands.add_parser("critique", help="Descriptive, non-blocking density, repetition and seam metrics")
    sub.add_argument("arrangement", type=Path)
    sub.add_argument("--report", type=Path, help="Musical evidence report.json enabling seam accent checks")
    sub.add_argument("--tier-reference", type=Path,
                     help="corpus tier-reference.json enabling the difficulty.target_tier comparison")
    sub.add_argument("--output", type=Path)
    sub = commands.add_parser("serve", help="Start the browser studio on localhost; it follows code updates")
    sub.add_argument("--workspace", type=Path, default=Path("workspace"))
    sub.add_argument("--port", type=int, default=8765)
    sub.add_argument("--no-reload", action="store_true",
                     help="Serve in one process and keep the code loaded at start (no automatic update)")
    sub.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    sub = commands.add_parser("demo", help="Create the original musical demo with an editable arrangement")
    sub.add_argument("--workspace", type=Path, default=Path("workspace"))
    sub = commands.add_parser("import-audio", help="Create a saved project from a local track")
    sub.add_argument("audio", type=Path)
    sub.add_argument("--workspace", type=Path, default=Path("workspace"))
    sub.add_argument("--title", default="Untitled track")
    sub.add_argument("--artist", default="Unknown artist")
    sub.add_argument("--album", help="Defaults to the file's album tag, else its Artist/Album/ folder")
    sub.add_argument("--bpm", type=float)
    sub.add_argument("--allow-duplicate", action="store_true",
                     help="Import even if a project already uses this exact source audio")
    sub = commands.add_parser("analyze", help="Inspect waveform, tempo hypotheses, onsets and recurrence")
    sub.add_argument("audio", type=Path)
    sub.add_argument("--bpm", type=float)
    sub.add_argument("--offset", type=float)
    sub.add_argument("--output", type=Path)
    sub = commands.add_parser("parse-map", help="Normalize supported v2/v3 map objects without losing source evidence")
    sub.add_argument("map", type=Path)
    sub.add_argument("--bpm", type=float, default=120)
    sub.add_argument("--offset", type=float, default=0)
    sub.add_argument("--output", type=Path)
    sub = commands.add_parser("feedback", help="Record an instruction for a separately invoked assistant")
    sub.add_argument("project")
    sub.add_argument("--workspace", type=Path, default=Path("workspace"))
    sub.add_argument("--start", type=float, required=True)
    sub.add_argument("--end", type=float, required=True)
    sub.add_argument("--text", required=True)
    sub.add_argument("--revision", required=True)
    sub.add_argument("--difficulty", choices=DIFFICULTIES, help="Difficulty the feedback is about; default: primary")
    sub = commands.add_parser("project", help="Read, revise, restore and export persistent projects")
    project_commands = sub.add_subparsers(dest="project_action", required=True)
    for name in ("list", "get", "save", "export", "restore", "review", "critique", "repair-swings",
                 "repair-visibility", "repair-audio", "set-album", "add-difficulty", "remove-difficulty",
                 "lights", "lights-inspect"):
        leaf = project_commands.add_parser(name, help={
            "lights": "Regenerate the lightshow from the newest musical evidence run (keeps environment, style, "
                      "section overrides, cues and locked sections' lights) and save it",
            "lights-inspect": "Show the lighting timeline of a beat range: events per moment with the sounds under "
                              "them, section moods and cues",
            "set-album": "Set the album that groups this project in the studio's artist/album tree",
            "repair-swings": "Fix same-color notes inside a held arc or chain (move to the other hand, or split "
                             "the arc at the cut), then blocking fast_direction_break/flow_parity_break findings: "
                             "drop 16th pickups, re-angle one cut, or reverse the hand's cuts from the "
                             "repeated one up to its next rest (arc directions follow)",
            "repair-visibility": "Fix blocking hidden_note findings: move a note hidden behind the note in front "
                                 "of it in the same cell to a free neighbouring cell (arcs follow)",
            "repair-audio": "Fix audio findings (and split one_hand_burst runs): move notes with no sound under "
                            "them onto the nearest onset "
                            "(or remove them), thin quiet passages mapped as densely as the full band, then "
                            "add flow-safe notes on unmapped vocal, drum, accent and density-collapse onsets; "
                            "raise heavy bars that play easier than soft ones and ease soft bars that play as "
                            "hard as the heavy passages; a note added or removed inside a phrase reverses the "
                            "hand's following cuts up to its next rest so the flow holds",
            "add-difficulty": "Add a difficulty as an unlocked copy of another one (then rewrite it at its level)",
            "remove-difficulty": "Delete a non-primary difficulty; its content stays in history",
            "export": "Export every difficulty of the project into one map ZIP"}.get(name))
        leaf.add_argument("--workspace", type=Path, default=Path("workspace"))
        if name != "list":
            leaf.add_argument("project")
        if name in ("get", "save", "restore", "review", "critique", "repair-swings", "repair-visibility",
                    "repair-audio", "lights", "lights-inspect"):
            leaf.add_argument("--difficulty", choices=DIFFICULTIES,
                              help="Which difficulty to act on; default: the primary one (arrangement.json)")
        if name == "add-difficulty":
            leaf.add_argument("--name", choices=DIFFICULTIES, required=True, help="The new difficulty")
            leaf.add_argument("--from", dest="source", choices=DIFFICULTIES, help="Difficulty to copy; default: primary")
            leaf.add_argument("--njs", type=float, help="Note jump speed for the new difficulty")
            leaf.add_argument("--target-tier", choices=TIER_IDS,
                              help="Player star tier the difficulty aims for (see `corpus tiers`)")
        if name == "remove-difficulty":
            leaf.add_argument("--difficulty", choices=DIFFICULTIES, required=True)
        if name == "critique":
            leaf.add_argument("--run", help="Musical evidence run ID for the audio checks; "
                                             "defaults to the newest run of the current audio")
            leaf.add_argument("--output", type=Path)
        if name == "lights-inspect":
            leaf.add_argument("--start", type=float, required=True, help="First beat")
            leaf.add_argument("--end", type=float, required=True, help="End beat (exclusive)")
        if name in ("lights", "lights-inspect"):
            leaf.add_argument("--output", type=Path, help="Write the report here instead of stdout")
        if name in ("repair-swings", "repair-visibility", "repair-audio", "lights"):
            leaf.add_argument("--dry-run", action="store_true", help="Report planned changes without saving")
        if name == "repair-audio":
            leaf.add_argument("--output", type=Path, help="Write the full report here instead of stdout")
        if name in ("save", "restore", "review", "repair-swings", "repair-visibility", "repair-audio",
                    "remove-difficulty", "lights"):
            leaf.add_argument("--revision", required=True)
        if name == "save":
            leaf.add_argument("--arrangement", type=Path, required=True)
            leaf.add_argument("--request-id")
        if name == "restore":
            leaf.add_argument("--restore-revision", required=True)
        if name == "set-album":
            leaf.add_argument("--album", required=True,
                              help="Album name; an empty string restores the source-derived album")
        if name == "review":
            leaf.add_argument("--timing-reviewed", action=argparse.BooleanOptionalAction)
            leaf.add_argument("--playtested", action=argparse.BooleanOptionalAction)
            leaf.add_argument("--game-build")
            leaf.add_argument("--notes")
            leaf.add_argument("--minutes", type=float)
            leaf.add_argument("--decision", choices=("pending", "go", "revise", "stop"))
            leaf.add_argument("--variant", choices=("initial", "revised", "baseline"))
    from .feedback_cli import register_feedback, dispatch_feedback
    register_feedback(project_commands)
    from .musical_cli import register_musical, dispatch_musical
    register_musical(commands)
    from .frames_cli import register_frames, dispatch_frames
    register_frames(commands)
    from .research_cli import register_subcommands, dispatch
    register_subcommands(commands)
    from .game.cli import register_game, dispatch_game
    register_game(commands)
    from .show_cli import register_show, dispatch_show
    register_show(commands)
    from .forge_cli import register_forge, dispatch_forge
    register_forge(commands)
    from .concept_cli import register_concept, dispatch_concept
    register_concept(commands)
    args = parser.parse_args(argv)
    try:
        if (code := dispatch_game(args, emit)) is not None:
            return code
        if dispatch_musical(args, emit) or dispatch_frames(args, emit) or dispatch_feedback(args, emit):
            return 0
        if dispatch_show(args, emit) or dispatch_concept(args, emit):
            return 0
        if (code := dispatch_forge(args, emit)) is not None:
            return code
        if dispatch(args):
            return 0
        if args.command == "serve":
            if args.no_reload or args.worker:
                from .server import serve
                serve(args.workspace, args.port, worker=args.worker)
            else:
                from .studio_supervisor import Supervisor
                return Supervisor(args.workspace, args.port).run()
        elif args.command in ("validate", "compile", "export"):
            from .arrangement import compile_arrangement
            from .validation import validate_arrangement
            arrangement = read_json(args.arrangement)
            diagnostics = validate_arrangement(arrangement)
            if args.command == "validate":
                for item in diagnostics:
                    print(json.dumps(item, ensure_ascii=False))
                return int(any(x["severity"] == "error" for x in diagnostics))
            if args.command == "compile":
                emit(compile_arrangement(arrangement), args.output)
            else:
                from .export import export_arrangement
                emit(export_arrangement(arrangement, args.audio, args.cover, args.output))
        elif args.command == "critique":
            from .critique import critique_arrangement
            from .tier_fit import missing_reference_warning
            arrangement = read_json(args.arrangement)
            result = critique_arrangement(arrangement, read_json(args.report) if args.report else None,
                                          read_json(args.tier_reference) if args.tier_reference else None)
            missing = None if args.tier_reference else missing_reference_warning(arrangement)
            result["warnings"] += [missing] if missing else []
            emit(result, args.output)
        elif args.command == "analyze":
            from .audio import analyze_audio
            emit(analyze_audio(args.audio, bpm=args.bpm, offset_seconds=args.offset), args.output)
        elif args.command == "parse-map":
            from .mapio import parse_map
            emit(parse_map(read_json(args.map), bpm=args.bpm, audio_offset_seconds=args.offset,
                           provenance={"local_file": str(args.map.resolve())}), args.output)
        elif args.command in ("demo", "import-audio", "feedback", "project"):
            from .projects import ProjectStore
            store = ProjectStore(args.workspace)
            if args.command == "demo":
                result = store.create(demo=True)
                emit({"project": result["project"], "revision": result["revision"]})
            elif args.command == "import-audio":
                result = store.create(args.audio, title=args.title, artist=args.artist, album=args.album,
                                      bpm=args.bpm, allow_duplicate=args.allow_duplicate)
                emit({"project": result["project"], "revision": result["revision"]})
            elif args.command == "feedback":
                emit(store.add_feedback(args.project, {"revision": args.revision, "start_beat": args.start,
                     "end_beat": args.end, "text": args.text, "difficulty": args.difficulty}))
            elif args.project_action == "list":
                emit(store.list())
            elif args.project_action == "get":
                emit(store.get(args.project, args.difficulty))
            elif args.project_action == "set-album":
                emit(store.set_album(args.project, args.album))
            elif args.project_action == "save":
                emit(store.save(args.project, read_json(args.arrangement), args.revision, request_id=args.request_id,
                                difficulty=args.difficulty))
            elif args.project_action == "export":
                emit(store.export(args.project))
            elif args.project_action == "restore":
                emit(store.restore(args.project, args.restore_revision, args.revision, args.difficulty))
            elif args.project_action == "add-difficulty":
                emit(store.add_difficulty(args.project, args.name, source=args.source, njs=args.njs,
                                          target_tier=args.target_tier))
            elif args.project_action == "remove-difficulty":
                emit(store.remove_difficulty(args.project, args.difficulty, args.revision))
            elif args.project_action == "critique":
                from .critique import critique_arrangement
                record = store.get(args.project, args.difficulty)
                report, run_id = None, args.run
                if not args.run:
                    from .musical import latest_run
                    run_id, report = latest_run(store.directory(args.project))
                else:
                    if not re.fullmatch(r"[a-f0-9]{32}", args.run):
                        raise ValueError("Invalid musical evidence run ID")
                    directory = store.directory(args.project)
                    report = read_json(directory / "musical" / args.run / "report.json")
                    from .audio import _hash
                    if report["source"]["sha256"] != _hash(directory / "song.ogg"):
                        raise ValueError("Evidence belongs to different audio; analyze the current project audio again")
                reference_path = store.root / "corpus" / "tier-reference.json"
                result = critique_arrangement(record["arrangement"], report,
                                              read_json(reference_path) if reference_path.exists() else None)
                from .tier_fit import missing_reference_warning
                missing = None if reference_path.exists() else missing_reference_warning(record["arrangement"])
                result["warnings"] += [missing] if missing else []
                if report is None:
                    result["warnings"].insert(0, {
                        "severity": "warning", "code": "audio_evidence_missing", "section_id": None,
                        "object_ids": [], "value": None, "threshold": None,
                        "message": "No musical evidence run matches this project's audio, so nothing was checked "
                                   f"against the song; run `music analyze {args.project}` before judging the map."})
                emit({"difficulty": record["difficulty"], "revision": record["revision"], "run_id": run_id, **result},
                     args.output)
            elif args.project_action in ("repair-swings", "repair-visibility"):
                from .swing_repair import repair_fast_breaks
                from .visibility_repair import repair_hidden_notes
                record = store.get(args.project, args.difficulty)
                if record["revision"] != args.revision:
                    raise ValueError(f"Project is at revision {record['revision']}; reread it before repairing")
                repair = (repair_fast_breaks if args.project_action == "repair-swings"
                          else repair_hidden_notes)(record["arrangement"])
                revision = record["revision"]
                if repair["changes"] and not args.dry_run:
                    revision = store.save(args.project, repair["arrangement"], args.revision,
                                          difficulty=args.difficulty)["revision"]
                emit({"project": args.project, "difficulty": record["difficulty"],
                      "previous_revision": record["revision"], "revision": revision,
                      "saved": revision != record["revision"], "changes": repair["changes"],
                      "unresolved": repair["unresolved"]})
            elif args.project_action == "repair-audio":
                from .audio_repair import repair_audio
                from .musical import latest_run
                record = store.get(args.project, args.difficulty)
                if record["revision"] != args.revision:
                    raise ValueError(f"Project is at revision {record['revision']}; reread it before repairing")
                run_id, report = latest_run(store.directory(args.project))
                repair = repair_audio(record["arrangement"], report)
                revision = record["revision"]
                if repair["changes"] and not args.dry_run:
                    revision = store.save(args.project, repair["arrangement"], args.revision,
                                          difficulty=args.difficulty)["revision"]
                emit({"project": args.project, "difficulty": record["difficulty"], "run_id": run_id,
                      "previous_revision": record["revision"],
                      "revision": revision, "saved": revision != record["revision"],
                      "summary": {action: sum(1 for c in repair["changes"] if c["action"] == action)
                                  for action in ("moved", "removed", "added")},
                      "changes": repair["changes"], "unresolved": repair["unresolved"],
                      "remaining_warnings": repair["remaining"]}, args.output)
            elif args.project_action in ("lights", "lights-inspect"):
                from .lighting import inspect_lights, lighting_findings, refresh_lightshow
                from .musical import latest_run
                record = store.get(args.project, args.difficulty)
                run_id, report = latest_run(store.directory(args.project))
                if args.project_action == "lights-inspect":
                    if args.end <= args.start:
                        raise ValueError("--end must follow --start")
                    emit({"project": args.project, "difficulty": record["difficulty"], "revision": record["revision"],
                          "run_id": run_id, **inspect_lights(record["arrangement"], report, args.start, args.end)}, args.output)
                    return 0
                if record["revision"] != args.revision:
                    raise ValueError(f"Project is at revision {record['revision']}; reread it before regenerating lights")
                if report is None:
                    raise ValueError("No musical evidence run matches this project's audio; run "
                                     f"`music analyze {args.project} --workspace WORKSPACE` first")
                arrangement, info = refresh_lightshow(record["arrangement"], record["arrangement"], run_id, report,
                                                      force=True)
                revision = record["revision"]
                if arrangement != record["arrangement"] and not args.dry_run:
                    revision = store.save(args.project, arrangement, args.revision,
                                          difficulty=args.difficulty)["revision"]
                metrics, findings = lighting_findings(arrangement, report)
                show = arrangement["lightshow"]
                emit({"project": args.project, "difficulty": record["difficulty"], "run_id": run_id,
                      "previous_revision": record["revision"], "revision": revision,
                      "saved": revision != record["revision"], "environment": show["environment"], "auto": show.get("auto", True),
                      "sections": show["generated"]["sections"], "metrics": metrics, "warnings": findings},
                     args.output)
            elif args.project_action == "review":
                record = {"revision": args.revision, "difficulty": args.difficulty}
                for name, key in (("timing_reviewed", "timing_reviewed"), ("playtested", "playtested"),
                                  ("game_build", "game_build"), ("notes", "notes"), ("minutes", "minutes_spent"),
                                  ("decision", "decision"), ("variant", "variant")):
                    value = getattr(args, name)
                    if value is not None:
                        record[key] = value
                emit(store.review(args.project, {k: v for k, v in record.items() if v is not None}))
        return 0
    except KeyboardInterrupt:
        print("Interrupted; saved artifacts are preserved.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        if isinstance(getattr(exc, "code", None), str):  # typed errors carry a stable code for agents
            print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
