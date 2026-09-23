"""`music listen` (sections, moments, mood) and `music lyrics` for the authoring agent."""
from pathlib import Path


def register_listen(actions):
    listen = actions.add_parser("listen", help="Sections, moments (drops, builds, breaks, key changes, final chorus...) "
                                               "and per-section mood for an evidence run; stored as listen.json in the run")
    lyrics = actions.add_parser("lyrics", help="Lyrics with word timestamps (Whisper on the vocal stem, or --from-file "
                                               "LRC/text); stored as lyrics.json in the run")
    for parser in (listen, lyrics):
        parser.add_argument("project")
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        parser.add_argument("--run", help="Evidence run ID; default: newest run for the current audio")
    listen.add_argument("--force", action="store_true", help="Recompute even when listen.json exists")
    listen.add_argument("--full", action="store_true", help="Print the whole listen.json instead of the summary")
    listen.add_argument("--mood-backend", choices=("heuristic", "external"), default="heuristic",
                        help="external runs a local model module (see --mood-python/--mood-module)")
    listen.add_argument("--mood-python", type=Path, help="Interpreter for the external mood model")
    listen.add_argument("--mood-module", help="Module run as `PYTHON -m MODULE`; JSON in on stdin, JSON out")
    lyrics.add_argument("--python", type=Path, help="Interpreter with faster-whisper or openai-whisper; "
                                                     "default: .venv-separation")
    lyrics.add_argument("--model", default="large-v3", help="Whisper model name (large-v3, medium, small...)")
    lyrics.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    lyrics.add_argument("--language", help="Language code (en, fr...); default: detected")
    lyrics.add_argument("--input", dest="source", choices=("vocals", "mix"), default="vocals",
                        help="Audio Whisper hears; default: the Demucs vocal stem")
    lyrics.add_argument("--from-file", dest="from_file", type=Path,
                        help="Import an LRC or plain-text lyric sheet instead of running a model")


def dispatch_listen(args, emit):
    if args.command != "music" or args.music_action not in ("listen", "lyrics"):
        return False
    from .lyrics import ListenError
    from .mood import MoodBackendError
    from .projects import ProjectStore
    store = ProjectStore(args.workspace)
    try:
        if args.music_action == "listen":
            from .listen import listen_project, listen_path
            options = {"python": str(args.mood_python) if args.mood_python else None, "module": args.mood_module}
            result = listen_project(store, args.project, args.run, force=args.force, mood_backend=args.mood_backend,
                                    mood_options=options)
            if args.full:
                from .storage import read_json
                result = read_json(result["path"])
            emit(result)
        else:
            from .lyrics import lyrics_project
            emit(lyrics_project(store, args.project, args.run, python=args.python, model=args.model,
                                device=args.device, language=args.language, source=args.source,
                                from_file=args.from_file))
    except (ListenError, MoodBackendError) as exc:
        emit({"error": {"code": exc.code, "message": str(exc), "fix": exc.fix, **getattr(exc, "details", {})}})
        raise SystemExit(2)
    return True
