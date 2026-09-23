"""Agent-facing twins of the studio's verification notes: `project feedback list|add`."""
from pathlib import Path

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def register_feedback(project_commands):
    root = project_commands.add_parser("feedback", help="List or add feedback: timestamped verification notes "
                                                         "and beat-range requests")
    actions = root.add_subparsers(dest="feedback_action", required=True)
    listing = actions.add_parser("list", help="Feedback sorted by song time, each with beat, section, revision and "
                                              "whether it is about the current revision")
    add = actions.add_parser("add", help="Record a note at a song time (same store as the studio's Note button)")
    for leaf in (listing, add):
        leaf.add_argument("project")
        leaf.add_argument("--workspace", type=Path, default=Path("workspace"))
    listing.add_argument("--difficulty", choices=DIFFICULTIES, help="Only this difficulty; default: every difficulty")
    listing.add_argument("--revision", help="Only feedback about this revision (full SHA or a prefix)")
    listing.add_argument("--kind", choices=("note", "range"), help="note = timestamped, range = beat range")
    listing.add_argument("--since", help="Only feedback created at or after this ISO date/time")
    add.add_argument("--at", dest="at", type=float, required=True, help="Song time in seconds (source audio)")
    add.add_argument("--text", required=True)
    add.add_argument("--revision", help="Revision the note is about; default: current. An older saved revision "
                                        "is accepted and recorded as stale")
    add.add_argument("--difficulty", choices=DIFFICULTIES, help="Default: the primary difficulty")


def dispatch_feedback(args, emit):
    if args.command != "project" or getattr(args, "project_action", None) != "feedback":
        return False
    from .projects import ProjectStore
    store = ProjectStore(args.workspace)
    if args.feedback_action == "list":
        emit(store.list_feedback(args.project, difficulty=args.difficulty, revision=args.revision,
                                 kind=args.kind, since=args.since))
    else:
        emit(store.add_note(args.project, song_time=args.at, text=args.text, revision=args.revision,
                            difficulty=args.difficulty, source="cli"))
    return True
