"""Agent-facing Vivify show commands: get, save, validate, compile, bundle and the EXSII envelope."""
from pathlib import Path

from .storage import read_json

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def register_show(commands):
    root = commands.add_parser("show", help="Vivify show (show.json): read, save, validate and compile it")
    actions = root.add_subparsers(dest="show_action", required=True)
    helps = {"get": "The project's show, its revision, what it was written against and its bundle",
             "save": "Save show.json revision-aware (--revision none for the first save)",
             "validate": "Structural, bundle, lifetime, possession, flash, attention and choreography checks",
             "compile": "The merged customData, requirements and provenance for one difficulty",
             "bundle": "The project's asset bundle set (assets/bundleinfo.json): materials, prefabs, CRCs",
             "envelope": "The EXSII custom-event envelope the validator warns against"}
    for action in ("get", "save", "validate", "compile", "bundle", "envelope"):
        parser = actions.add_parser(action, help=helps[action])
        if action == "envelope":
            continue
        parser.add_argument("project")
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action in ("save", "validate", "compile"):
            parser.add_argument("--show", type=Path, required=action == "save",
                                help="Show JSON file; default: the stored show.json")
        if action == "save":
            parser.add_argument("--revision", required=True, help="Current show revision from `show get` ('none' "
                                                                  "when the project has no show yet)")
        if action in ("validate", "compile"):
            parser.add_argument("--difficulty", choices=DIFFICULTIES,
                                help="Check or compile one difficulty; default: all (compile: the primary one)")
        if action == "compile":
            parser.add_argument("--output", type=Path, help="Write the JSON here instead of stdout")


def dispatch_show(args, emit):
    if args.command != "show":
        return False
    if args.show_action == "envelope":
        from .show_validation import load_envelope
        envelope = load_envelope() or {}
        emit({k: v for k, v in envelope.items() if k != "difficulties"})
        return True
    from .projects import ProjectStore
    from .show import bundle_directory, load_show, save_show, show_revision, ShowError
    from .vivify import bundle_summary, read_bundle
    store = ProjectStore(args.workspace)
    with store.lock:
        path = store.directory(args.project)
        arrangements = {name: read_json(file) for name, file in store.difficulty_files(path).items()}
    if args.show_action == "get":
        emit({"project": args.project, **store.show(path, arrangements)})
        return True
    if args.show_action == "bundle":
        emit({"project": args.project, "directory": str(bundle_directory(path)),
              "bundle": bundle_summary(read_bundle(bundle_directory(path)))})
        return True
    if args.show_action == "save":
        record = save_show(store, args.project, read_json(args.show), args.revision)
        emit({"project": args.project, "saved": True, **record})
        return True
    show = read_json(args.show) if args.show else load_show(path)
    if show is None:
        raise ShowError("show_missing", f"project {args.project} has no show.json; write one and save it with "
                                        "`show save PROJECT --show FILE --revision none`")
    from .musical import latest_run
    run_id, report = latest_run(path)
    evidence = {"project_dir": path, "run_id": run_id, "report": report}
    bundle = read_bundle(bundle_directory(path))
    if args.show_action == "validate":
        from .show_validation import validate_project_show
        chosen = {args.difficulty: arrangements[args.difficulty]} if args.difficulty else arrangements
        if args.difficulty and args.difficulty not in arrangements:
            raise ValueError(f"Project has no {args.difficulty} difficulty (it has {', '.join(arrangements)})")
        emit({"project": args.project, "show_revision": show_revision(show), "evidence_run": run_id,
              **validate_project_show(show, chosen, bundle=bundle, evidence=evidence)})
        return True
    from .show import validate_show
    from .show_validation import compile_difficulty, load_envelope
    name = args.difficulty or next(iter(arrangements))
    if name not in arrangements:
        raise ValueError(f"Project has no {name} difficulty (it has {', '.join(arrangements)})")
    structural = [d for d in validate_show(show, {name: arrangements[name]}) if d["severity"] == "error"]
    if structural:
        emit({"project": args.project, "difficulty": name, "ok": False, "diagnostics": structural}, args.output)
        return True
    beatmap, result = compile_difficulty(show, arrangements[name], bundle=bundle, evidence=evidence,
                                         envelope=load_envelope())
    emit({"project": args.project, "difficulty": name, "show_revision": show_revision(show),
          "ok": not any(d["severity"] == "error" for d in result["diagnostics"]),
          "requirements": result["requirements"], "event_count": result["event_count"],
          "evidence_run": result["evidence_run"], "diagnostics": result["diagnostics"],
          "customData": beatmap.get("customData", {}),
          "object_customData": {group: {str(i): obj["customData"] for i, obj in enumerate(beatmap.get(group, []))
                                        if "customData" in obj}
                                for group in ("colorNotes", "bombNotes", "burstSliders")},
          "provenance": result["provenance"],
          "note": "beats are arrangement beats; export adds the audio-offset shift"}, args.output)
    return True
