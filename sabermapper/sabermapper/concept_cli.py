"""`concept` commands: template, validate, save and get the per-project visual concept."""
from pathlib import Path


def register_concept(commands):
    root = commands.add_parser("concept", help="Three candidate visual treatments per project, scored, one selected")
    actions = root.add_subparsers(dest="concept_action", required=True)
    helps = {"template": "Skeleton concept pre-filled with the listen evidence (moments, section mood, lyric lines)",
             "validate": "Check a concept file's structure and references against the latest listen evidence",
             "save": "Validate and store a concept (revision-aware; first save uses --revision none)",
             "get": "The stored concept, its computed totals, current validation and history",
             "corpus": "Reference treatments reverse-engineered from the EXSII Vivify maps"}
    for action in ("template", "validate", "save", "get", "corpus"):
        parser = actions.add_parser(action, help=helps[action])
        if action == "corpus":
            parser.add_argument("--id", dest="entry_id", help="One treatment in full")
            continue
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action == "validate":
            parser.add_argument("--project", required=True)
        else:
            parser.add_argument("project")
        if action in ("validate", "save"):
            parser.add_argument("--file", type=Path, required=True, help="Concept JSON (bare, or template output)")
        if action == "save":
            parser.add_argument("--revision", required=True, help="Current concept revision, or none")
        if action == "template":
            parser.add_argument("--output", type=Path)


def dispatch_concept(args, emit):
    if args.command != "concept":
        return False
    from .concept import ConceptError, concept_corpus, concept_template, get_concept, save_concept, validate_file
    from .projects import ConflictError, ProjectStore
    from .storage import read_json
    try:
        if args.concept_action == "corpus":
            emit(concept_corpus(args.entry_id))
            return True
        store = ProjectStore(args.workspace)
        if args.concept_action == "template":
            emit(concept_template(store, args.project), args.output)
        elif args.concept_action == "get":
            emit(get_concept(store, args.project))
        elif args.concept_action == "validate":
            result = validate_file(store, args.project, read_json(args.file))
            emit(result)
            if not result["valid"]:
                raise SystemExit(1)
        else:
            emit(save_concept(store, args.project, read_json(args.file), args.revision))
    except ConceptError as exc:
        emit({"error": {"code": exc.code, "message": str(exc), "fix": exc.fix, **exc.details}})
        raise SystemExit(2)
    except ConflictError as exc:
        emit({"error": {"code": "revision_conflict", "message": str(exc),
                        "fix": f"Run `concept get {args.project}`, merge your changes onto it and save with its revision"}})
        raise SystemExit(2)
    return True
