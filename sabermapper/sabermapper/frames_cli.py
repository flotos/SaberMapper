"""Agent-facing commands for in-game frame captures: contact sheets, metrics and per-section summaries."""
from pathlib import Path

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def register_frames(commands):
    root = commands.add_parser("frames", help="Read `game capture` frames: contact sheets, metrics, summaries")
    actions = root.add_subparsers(dest="frames_action", required=True)
    sheet = actions.add_parser("sheet", help="Labelled contact sheets (one or more PNGs per section) to read")
    sheet.add_argument("directory", type=Path, help="Capture directory (capture.json + PNGs, or tSSSS.mmm.png)")
    sheet.add_argument("--out", type=Path, help="Output directory; default DIR/sheets")
    sheet.add_argument("--per-section", action="store_true", default=True,
                       help="Group by section (default); --no-per-section uses fixed-size chunks")
    sheet.add_argument("--no-per-section", dest="per_section", action="store_false")
    sheet.add_argument("--columns", type=int, default=4)
    sheet.add_argument("--thumb-width", type=int, default=420, help="Thumbnail width in px (sheets stay <= 2000 px)")
    sheet.add_argument("--include-probe", action="store_true", help="Also lay out dense flash-probe frames")
    for name, text in (("metrics", "Flash rate, note-corridor contrast, palette drift and boundary changes "
                                    "as critique findings"),
                       ("summary", "Per-section luminance, corridor contrast, palette, change and flash stats")):
        leaf = actions.add_parser(name, help=text)
        leaf.add_argument("directory", type=Path)
        leaf.add_argument("--project", help="Project whose arrangement gives sections, timing and colours")
        leaf.add_argument("--workspace", type=Path, default=Path("workspace"))
        leaf.add_argument("--difficulty", choices=DIFFICULTIES,
                          help="Default: the capture's difficulty, else the primary one")
        leaf.add_argument("--concept", type=Path, help="Concept JSON with palette (and optional note_colors, "
                                                       "moments); default: the project's concept.json if present")
        leaf.add_argument("--corridor", help="Note corridor x0,y0,x1,y1 (normalized, y down); "
                                             "default 0.25,0.35,0.75,0.90")
        leaf.add_argument("--output", type=Path)


def _context(args, capture_difficulty):
    arrangement, concept = None, None
    if args.project:
        from .projects import ProjectStore
        from .storage import read_json
        store = ProjectStore(args.workspace)
        directory = store.directory(args.project)
        difficulty = args.difficulty or capture_difficulty
        try:
            arrangement = read_json(store.arrangement_file(directory, difficulty))
        except (FileNotFoundError, ValueError):
            if args.difficulty:
                raise
            arrangement = read_json(store.arrangement_file(directory))
        if not args.concept:
            for name in ("concept.json", "show.json"):
                if (directory / name).is_file():
                    concept = read_json(directory / name)
                    break
    if args.concept:
        from .frame_metrics import load_concept
        concept = load_concept(args.concept)
    return arrangement, concept


def dispatch_frames(args, emit):
    if args.command != "frames":
        return False
    if args.frames_action == "sheet":
        from .frames import contact_sheets
        emit(contact_sheets(args.directory, args.out, per_section=args.per_section, columns=args.columns,
                            thumb_width=args.thumb_width, include_probe=args.include_probe))
        return True
    from .frame_metrics import analyze_frames, parse_corridor, section_summary
    from .frames import load_capture
    capture = load_capture(args.directory)
    if args.project and capture["project"] and capture["project"] != args.project:
        raise ValueError(f"Capture belongs to project {capture['project']}, not {args.project}; "
                         "pass the matching --project or recapture")
    arrangement, concept = _context(args, capture["difficulty"])
    corridor = parse_corridor(args.corridor) if args.corridor else None
    run = analyze_frames if args.frames_action == "metrics" else section_summary
    emit(run(args.directory, arrangement, concept, corridor=corridor), args.output)
    return True
