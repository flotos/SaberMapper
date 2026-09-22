"""Agent-facing entry points for musical evidence; never compose notes."""
from pathlib import Path
import re

from .musical import BACKENDS, PRESETS
from .storage import read_json


def register_musical(commands):
    root = commands.add_parser("music", help="Instrument and mix evidence for the authoring agent")
    actions = root.add_subparsers(dest="music_action", required=True)
    actions.add_parser("backends", help="List techniques, dependencies, and authoring boundaries")
    for action in ("analyze", "list", "inspect"):
        parser = actions.add_parser(action)
        parser.add_argument("project")
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action == "analyze":
            parser.add_argument("--backend", choices=BACKENDS, default="bands")
            parser.add_argument("--preset", choices=PRESETS, default="balanced")
            parser.add_argument("--manifest", type=Path, help="Aligned stems and producer/model provenance")
            parser.add_argument("--python", type=Path, help="Python environment with Demucs installed")
            parser.add_argument("--model", default="htdemucs")
            parser.add_argument("--device", default="cpu")
        if action == "inspect":
            parser.add_argument("--run", required=True)
            parser.add_argument("--start", type=float, required=True, help="Absolute start beat")
            parser.add_argument("--end", type=float, required=True, help="Exclusive end beat")
            parser.add_argument("--layer", help="Restrict evidence to one analyzed layer")
            parser.add_argument("--output", type=Path)


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
            {"id": "import", "available": True,
             "setup": "Run any separator (e.g. BS-RoFormer) externally, then provide --manifest with source_sha256, producer and stems"}],
            "presets": PRESETS, "authoring": "An independently invoked Codex or Claude Code agent authors all notes and focus changes."})
        return True
    from .musical import analyze_project, evidence_slice, project_runs
    from .projects import ProjectStore
    store = ProjectStore(args.workspace)
    directory = store.directory(args.project)
    if args.music_action == "analyze":
        emit(analyze_project(store, args.project, **{key: getattr(args, key) for key in
             ("backend", "preset", "manifest", "python", "model", "device")}))
    elif args.music_action == "list":
        emit(project_runs(directory))
    else:
        if not re.fullmatch(r"[a-f0-9]{32}", args.run):
            raise ValueError("Invalid musical evidence run ID")
        with store.lock:
            arrangement = read_json(directory / "arrangement.json")
        report = read_json(directory / "musical" / args.run / "report.json")
        from .audio import _hash
        if report["source"]["sha256"] != _hash(directory / "song.ogg"):
            raise ValueError("Evidence belongs to different audio; analyze the current project audio again")
        emit({"run_id": args.run,
              **evidence_slice(report, arrangement, args.start, args.end, args.layer)}, args.output)
    return True
