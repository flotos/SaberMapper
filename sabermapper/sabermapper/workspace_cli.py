"""`workspace` commands: clone the real workspace into a worktree, inspect the clone, publish its changed files."""
from pathlib import Path


def register_workspace(commands):
    root = commands.add_parser("workspace", help="Worktree-local copy of the real workspace: clone it, check what "
                                                 "changed, publish the changed files back after the code merge")
    actions = root.add_subparsers(dest="workspace_action", required=True)
    helps = {"clone": "Copy the real workspace (main checkout) into this worktree: audio and content-addressed files "
                      "are hardlinked, everything else copied; exports and downloader state are left out",
             "status": "Per project (and corpus, profile, authoring folder): files changed in the clone, whether the "
                       "real workspace changed since the clone, and conflicts",
             "publish": "Copy only the clone's changed files into the real workspace; a unit the real workspace also "
                        "changed since the clone is held back with the fix (a project.json changed on both sides "
                        "merges while the real arrangements are as the clone found them)"}
    for action in ("clone", "status", "publish"):
        parser = actions.add_parser(action, help=helps[action])
        parser.add_argument("--workspace", type=Path, default=Path("workspace"), help="The clone (default: workspace)")
        if action == "clone":
            parser.add_argument("--from", dest="source", type=Path,
                                help="The real workspace; default: sabermapper/workspace in the main checkout")
            parser.add_argument("--replace", action="store_true",
                                help="Start again from the real workspace (refused while changes are unpublished)")
            parser.add_argument("--discard-local", action="store_true", help="With --replace: drop unpublished changes")
            parser.add_argument("--skip-corpus", action="store_true",
                                help="Leave out the reference corpus except the files project commands read "
                                     "(tier-reference.json, splits.json); research commands then need --from's corpus")
        if action == "publish":
            parser.add_argument("units", nargs="*", help="Only these units (project ID, projects/ID, corpus, ...)")
            parser.add_argument("--dry-run", action="store_true", help="Report what would be copied, copy nothing")


def dispatch_workspace(args, emit):
    if args.command != "workspace":
        return None
    from .workspace_clone import CloneError, clone, publish, status
    try:
        if args.workspace_action == "clone":
            emit(clone(args.workspace, args.source, replace=args.replace, corpus=not args.skip_corpus,
                       discard_local=args.discard_local))
            return 0
        if args.workspace_action == "status":
            emit(status(args.workspace))
            return 0
        result = publish(args.workspace, units=args.units, dry_run=args.dry_run)
        emit(result)
        return 2 if result["held_back"] else 0
    except CloneError as exc:
        emit({"error": {"code": exc.code, "message": str(exc), "fix": exc.fix}})
        return 2
