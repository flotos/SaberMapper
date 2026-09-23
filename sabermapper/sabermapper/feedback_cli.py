"""Agent-facing twins of the studio's verification notes: `project feedback list|add|resolve`."""
from pathlib import Path

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def register_feedback(project_commands):
    root = project_commands.add_parser("feedback", help="List, add or resolve feedback: timestamped verification "
                                                         "notes and beat-range requests")
    actions = root.add_subparsers(dest="feedback_action", required=True)
    listing = actions.add_parser("list", help="Feedback sorted by song time, each with beat, section, revision and "
                                              "whether it is about the current revision")
    add = actions.add_parser("add", help="Record a note at a song time (same store as the studio's Note button)")
    resolve = actions.add_parser("resolve", help="Mark a feedback record addressed by a saved revision, with how "
                                                 "that revision answers it")
    for leaf in (listing, add, resolve):
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
    resolve.add_argument("feedback_id", help="The record's id from `project feedback list`")
    resolve.add_argument("--note", required=True, help="How the revision addresses the feedback")
    resolve.add_argument("--revision", help="Full SHA of the saved revision that addresses it (its difficulty's); "
                                            "default: the current one")


def dispatch_feedback(args, emit):
    if args.command != "project" or getattr(args, "project_action", None) != "feedback":
        return False
    from .projects import ProjectStore
    store = ProjectStore(args.workspace)
    if args.feedback_action == "list":
        emit(store.list_feedback(args.project, difficulty=args.difficulty, revision=args.revision,
                                 kind=args.kind, since=args.since))
    elif args.feedback_action == "resolve":
        emit(store.resolve_feedback(args.project, args.feedback_id, note=args.note, revision=args.revision))
    else:
        emit(store.add_note(args.project, song_time=args.at, text=args.text, revision=args.revision,
                            difficulty=args.difficulty, source="cli"))
    return True
