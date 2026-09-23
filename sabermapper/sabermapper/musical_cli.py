"""Agent-facing entry points for musical evidence; never compose notes."""
from pathlib import Path
import re

from .musical import BACKENDS, PRESETS
from .storage import read_json


def register_musical(commands):
    root = commands.add_parser("music", help="Instrument and mix evidence for the authoring agent")
    actions = root.add_subparsers(dest="music_action", required=True)
    actions.add_parser("backends", help="List techniques, dependencies, and authoring boundaries")
    helps = {"analyze": "Create an immutable evidence run (stems, onsets, pitch and chord changes)",
             "list": "List evidence runs", "inspect": "Evidence and mapped notes for a beat range",
             "rhythm": "Per-bar onset grids per layer beside the mapped notes, with the bar's lead; --propose "
                       "drafts note times from the critique's own rules, placed and checked",
             "spectrogram": "PNG of the mix and stems over a beat range with grid, notes, attacks and entries"}
    for action in ("analyze", "list", "inspect", "rhythm", "spectrogram"):
        parser = actions.add_parser(action, help=helps[action])
        parser.add_argument("project")
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action in ("inspect", "rhythm", "spectrogram"):
            parser.add_argument("--difficulty", choices=("Easy", "Normal", "Hard", "Expert", "ExpertPlus"),
                                help="Difficulty whose notes are shown; default: the primary one")
        if action == "analyze":
            parser.add_argument("--backend", choices=BACKENDS, default="bands")
            parser.add_argument("--preset", choices=PRESETS, help="Default: balanced, or the source run's preset")
            parser.add_argument("--from-run", dest="from_run",
                                help="Re-analyze the stems this run already separated (backend rerun)")
            parser.add_argument("--manifest", type=Path, help="Aligned stems and producer/model provenance")
            parser.add_argument("--python", type=Path,
                                help="Python with Demucs; default: this one if it has Demucs, else .venv-separation")
            parser.add_argument("--model", default="htdemucs")
            parser.add_argument("--device", default="auto", help="cuda, cpu or auto (cuda when available)")
        if action == "rhythm":
            parser.add_argument("--run", help="Evidence run ID; default: newest run for the current audio")
            parser.add_argument("--start", type=float, help="Absolute start beat (required without --propose)")
            parser.add_argument("--end", type=float, help="Exclusive end beat (required without --propose)")
            parser.add_argument("--propose", action="store_true",
                                help="Draft note times for the range (default: the whole song) with the evidence "
                                     "behind each: the lead's attacks, fills, drum or melody onsets and accents, "
                                     "scaled to the difficulty's target tier, then placed and checked so the draft "
                                     "carries no rhythm finding the critique would raise")
            parser.add_argument("--tier", help="Target tier for --propose; default: difficulty.target_tier, else band")
            parser.add_argument("--held", type=float, action="append", default=[],
                                help="With --propose: source seconds of a held vocal the user named (repeatable); "
                                     "it becomes an arc. The player profile's held_vocals for this project are added")
            parser.add_argument("--draft", type=Path,
                                help="With --propose: write the arrangement with the range's notes replaced by the "
                                     "drafted rhythm-only notes (id and beat), ready to edit and `project save`")
            parser.add_argument("--layers", help="Comma-separated layers; default: every stem")
            parser.add_argument("--division", type=int, default=4, help="Grid cells per beat: 2, 3, 4, 6, 8 or 12")
            parser.add_argument("--output", type=Path)
        if action == "spectrogram":
            parser.add_argument("--run", help="Evidence run ID; default: newest run for the current audio")
            parser.add_argument("--start", type=float, help="Absolute start beat; omit with --end for the whole song")
            parser.add_argument("--end", type=float, help="Exclusive end beat")
            parser.add_argument("--layers", help="Comma-separated layers; default: mix and every separated stem")
            parser.add_argument("--output", type=Path, help="PNG path; default: views/ in the project")
        if action == "inspect":
            parser.add_argument("--run", required=True)
            parser.add_argument("--start", type=float, required=True, help="Absolute start beat")
            parser.add_argument("--end", type=float, required=True, help="Exclusive end beat")
            parser.add_argument("--layer", help="Restrict evidence to one analyzed layer")
            parser.add_argument("--output", type=Path)
    from .listen_cli import register_listen
    register_listen(actions)


def dispatch_musical(args, emit):
    if args.command != "music":
        return False
    if args.music_action == "backends":
        import importlib.util
        emit({"backends": [
            {"id": "bands", "available": True, "layers": ["mix", "low", "mid", "high"],
             "description": "Frequency bands, not instrument isolation"},
            {"id": "hpss", "available": True, "layers": ["mix", "harmonic", "percussive"],
             "description": "Harmonic/percussive median-mask separation with mono previews"},
            {"id": "demucs", "available_in_current_python": importlib.util.find_spec("demucs") is not None,
             "setup": "Install Demucs in a compatible environment; pass its executable with --python",
             "models": ["htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi"]},
            {"id": "ensemble", "models": ["htdemucs_ft", "htdemucs_6s"],
             "description": "Recommended. htdemucs_ft vocals/drums/bass (shifts 2) with its other split into "
                            "guitar/piano/other by htdemucs_6s masks; uses .venv-separation and CUDA automatically"},
            {"id": "import", "available": True,
             "setup": "Run any separator (e.g. BS-RoFormer) externally, then provide --manifest with source_sha256, producer and stems"},
            {"id": "rerun", "available": True,
             "setup": "Pass --from-run RUN_ID to re-analyze that run's separated stems with the current detectors"}],
            "presets": PRESETS, "authoring": "An independently invoked Codex or Claude Code agent authors all notes and focus changes."})
        return True
    from .listen_cli import dispatch_listen
    if dispatch_listen(args, emit):
        return True
    from .musical import analyze_project, evidence_slice, project_runs, rhythm_grid
    from .projects import ProjectStore
    store = ProjectStore(args.workspace)
    directory = store.directory(args.project)
    if args.music_action == "analyze":
        emit(analyze_project(store, args.project, **{key: getattr(args, key) for key in
             ("backend", "preset", "manifest", "python", "model", "device", "from_run")}))
    elif args.music_action == "list":
        emit([{**run, "listen": (directory / "musical" / run["id"] / "listen.json").exists(),
               "lyrics": (directory / "musical" / run["id"] / "lyrics.json").exists()} for run in project_runs(directory)])
    elif args.music_action == "spectrogram":
        from .spectrogram import project_view
        with store.lock:
            arrangement = read_json(store.arrangement_file(directory, args.difficulty))
        run_id, report = _run(directory, args.run)
        layers = [name.strip() for name in args.layers.split(",") if name.strip()] if args.layers else None
        emit(project_view(directory, arrangement, report, run_id, start_beat=args.start, end_beat=args.end,
                          layers=layers, output=args.output, difficulty=args.difficulty))
    elif args.music_action == "rhythm" and args.propose:
        from .rhythm_proposal import propose_rhythm
        from .revisions import arrangement_revision
        with store.lock:
            arrangement = read_json(store.arrangement_file(directory, args.difficulty))
        run_id, report = _run(directory, args.run)
        reference_path = store.root / "corpus" / "tier-reference.json"
        profile_path = store.root / "player-profile.json"
        named = [float(item["seconds"]) for item in (read_json(profile_path).get("held_vocals") or []
                                                     if profile_path.exists() else [])
                 if isinstance(item, dict) and item.get("project") == args.project and "seconds" in item]
        result = propose_rhythm(arrangement, report, start=args.start, end=args.end, tier=args.tier,
                                tier_reference=read_json(reference_path) if reference_path.exists() else None,
                                held=sorted(set(named + args.held)))
        draft = result.pop("draft")
        if args.draft:
            args.draft.parent.mkdir(parents=True, exist_ok=True)
            with args.draft.open("x", encoding="utf-8") as stream:
                import json
                stream.write(json.dumps(draft, ensure_ascii=False, indent=1) + "\n")
        emit({"run_id": run_id, "revision": arrangement_revision(arrangement),
              "draft": str(args.draft) if args.draft else None, **result}, args.output)
    elif args.music_action == "rhythm":
        if args.start is None or args.end is None:
            raise ValueError("music rhythm needs --start and --end (or --propose)")
        with store.lock:
            arrangement = read_json(store.arrangement_file(directory, args.difficulty))
        run_id, report = _run(directory, args.run)
        layers = [name.strip() for name in args.layers.split(",") if name.strip()] if args.layers else None
        emit({"run_id": run_id, **rhythm_grid(report, arrangement, args.start, args.end,
                                              layers=layers, division=args.division)}, args.output)
    else:
        if not re.fullmatch(r"[a-f0-9]{32}", args.run):
            raise ValueError("Invalid musical evidence run ID")
        with store.lock:
            arrangement = read_json(store.arrangement_file(directory, args.difficulty))
        report = read_json(directory / "musical" / args.run / "report.json")
        from .audio import _hash
        if report["source"]["sha256"] != _hash(directory / "song.ogg"):
            raise ValueError("Evidence belongs to different audio; analyze the current project audio again")
        emit({"run_id": args.run,
              **evidence_slice(report, arrangement, args.start, args.end, args.layer)}, args.output)
    return True


def _run(directory, run_id):
    """(run ID, report): the named run, else the newest run for the current audio."""
    from .musical import latest_run
    if run_id is None:
        run_id, report = latest_run(directory)
        if report is None:
            raise ValueError("No evidence run matches the current audio; run `music analyze` first")
        return run_id, report
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid musical evidence run ID")
    return run_id, read_json(directory / "musical" / run_id / "report.json")
