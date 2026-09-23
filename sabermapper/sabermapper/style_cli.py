"""`style` commands: template, validate, save and get the per-song map style (three candidates, one selected)."""
from pathlib import Path


def register_style(commands):
    root = commands.add_parser("style", help="Brainstorm the song's map style: three candidates scored, one selected")
    actions = root.add_subparsers(dest="style_action", required=True)
    helps = {"template": "Skeleton brainstorm with the song evidence (title, stems, overview image, mood, lyrics, "
                         "themes, measured style, other songs' styles)",
             "validate": "Check a style file's candidates, settings and rubric",
             "save": "Validate and store the brainstorm (revision-aware; first save uses --revision none); prints "
                     "the selected style block for the arrangements",
             "get": "The stored brainstorm, its selected style block and history"}
    for action in ("template", "validate", "save", "get"):
        parser = actions.add_parser(action, help=helps[action])
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action == "validate":
            parser.add_argument("--project", required=True)
        else:
            parser.add_argument("project")
        if action in ("validate", "save"):
            parser.add_argument("--file", type=Path, required=True, help="Style JSON (bare, or template output)")
        if action == "save":
            parser.add_argument("--revision", required=True, help="Current style revision, or none")
        if action == "template":
            parser.add_argument("--output", type=Path)


def dispatch_style(args, emit):
    if args.command != "style":
        return False
    from .projects import ConflictError, ProjectStore
    from .storage import read_json
    from .style import StyleError, get_style, save_style, style_template, validate_file
    store = ProjectStore(args.workspace)
    try:
        if args.style_action == "template":
            emit(style_template(store, args.project), args.output)
        elif args.style_action == "get":
            emit(get_style(store, args.project))
        elif args.style_action == "validate":
            result = validate_file(store, args.project, read_json(args.file))
            emit(result)
            if not result["valid"]:
                raise SystemExit(1)
        else:
            emit(save_style(store, args.project, read_json(args.file), args.revision))
    except StyleError as exc:
        emit({"error": {"code": exc.code, "message": str(exc), "fix": exc.fix, **exc.details}})
        raise SystemExit(2)
    except ConflictError as exc:
        emit({"error": {"code": "revision_conflict", "message": str(exc),
                        "fix": f"Run `style get {args.project}`, merge your changes onto it and save with its revision"}})
        raise SystemExit(2)
    return True
