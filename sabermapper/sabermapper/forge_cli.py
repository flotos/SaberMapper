"""Agent-facing entry points for the Vivify asset forge (assets.json, shader lint, Unity batchmode builds)."""
from pathlib import Path

from .forge import (DEFAULT_TARGET, TARGETS, UNSUPPORTED_TARGETS, ForgeError, TEMPLATE_DIR, build, forge_config_path,
                    generate, init_spec, installed_editors, lint_spec, load_config, load_library, locate_unity, promote,
                    project_slug, render_library_md, save_config, LIBRARY_DIR, GENERATOR_KINDS)


def register_forge(commands):
    root = commands.add_parser("assets", help="Vivify asset forge: specs, shader lint and Unity batchmode bundle builds")
    actions = root.add_subparsers(dest="assets_action", required=True)
    helps = {"library": "List the tier-1 library (shaders with typed properties and safe ranges, mesh generators)",
             "init": "Write a starter <project>/assets/assets.json from the library",
             "lint": "Validate assets.json, lint shaders (stereo macros, screen-space macros, cost) and check budgets",
             "build": "Lint, then build the bundle with Unity batchmode; outputs go to <project>/assets/",
             "promote": "Copy a project's agent-written shader into the library (needs intent, properties, safe ranges, description)",
             "generate": "Tier-3 generative media (textures, skyboxes, meshes); returns generator_unavailable until a local model is installed",
             "doctor": "Where Unity is looked for, what is installed, targets and config",
             "config": "Persist the Unity path, version or build project directory for this machine"}
    for action, text in helps.items():
        parser = actions.add_parser(action, help=text)
        if action in ("init", "lint", "build", "promote", "generate"):
            parser.add_argument("project", nargs="?" if action in ("lint", "build") else None,
                                help="Project ID; its spec is <project>/assets/assets.json")
            parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action in ("lint", "build"):
            parser.add_argument("--spec", type=Path, help="Build or lint this assets.json instead of a project's")
        if action in ("build", "doctor"):
            parser.add_argument("--target", choices=sorted(TARGETS) + sorted(UNSUPPORTED_TARGETS),
                                help=f"Bundle target; default: the spec's, else {DEFAULT_TARGET}")
            parser.add_argument("--unity", help="Unity.exe; default: SABERMAPPER_UNITY, config, then Unity Hub installs")
            parser.add_argument("--unity-version", dest="unity_version", help="Editor version to look for in Unity Hub")
        if action == "build":
            parser.add_argument("--out", type=Path, help="Output directory with --spec; default: the spec's directory")
            parser.add_argument("--unity-project", dest="unity_project", type=Path,
                                help="Machine-local Unity build project; default: %%LOCALAPPDATA%%/SaberMapper/forge/unity-<version>")
            parser.add_argument("--timeout", type=float, default=3600, help="Seconds before Unity is abandoned (first run imports packages)")
            parser.add_argument("--allow-no-xr", dest="allow_no_xr", action="store_true",
                                help="Build even if the OpenXR loader cannot be enabled (risk: left-eye-only shaders)")
            parser.add_argument("--graphics", action="store_true", help="Run Unity without -nographics")
        if action == "library":
            parser.add_argument("--id", help="Show one shader or mesh generator")
            parser.add_argument("--write-md", dest="write_md", action="store_true", help="Regenerate library.md from library.json")
            parser.add_argument("--library", type=Path, default=None, help="Library directory (default: the bundled one)")
        if action == "init":
            parser.add_argument("--force", action="store_true", help="Replace an existing assets.json")
        if action == "promote":
            parser.add_argument("asset_id")
            parser.add_argument("--library-id", dest="library_id", help="New library id, sm_<name>")
            parser.add_argument("--library", type=Path, default=None, help="Library directory (default: the bundled one)")
        if action == "generate":
            parser.add_argument("--kind", required=True, choices=sorted(GENERATOR_KINDS))
            parser.add_argument("--prompt", required=True)
            parser.add_argument("--seed", type=int)
            parser.add_argument("--backend", default="local")
        if action == "config":
            parser.add_argument("--unity", help="Unity.exe path ('' clears)")
            parser.add_argument("--unity-version", dest="unity_version", help="Editor version ('' clears)")
            parser.add_argument("--unity-project", dest="unity_project", help="Build project directory ('' clears)")


def _project(args):
    from .projects import ProjectStore
    directory = ProjectStore(args.workspace).directory(args.project)
    return directory, project_slug(args.project)


def _spec_and_dest(args):
    if getattr(args, "spec", None):
        spec = args.spec.resolve()
        return spec, (getattr(args, "out", None) or spec.parent).resolve(), None
    if not args.project:
        raise ForgeError("spec_required", "Name a PROJECT or pass --spec FILE", "e.g. `sabermapper assets build my-song`")
    directory, slug = _project(args)
    return directory / "assets" / "assets.json", directory / "assets", slug


def dispatch_forge(args, emit):
    """Returns the exit code when this was an `assets` command, else None."""
    if args.command != "assets":
        return None
    try:
        return _dispatch(args, emit)
    except ForgeError as exc:
        emit(exc.as_dict())
        return 1


def _dispatch(args, emit):
    action = args.assets_action
    if action == "library":
        library_dir = args.library or LIBRARY_DIR
        library = load_library(library_dir)
        if args.write_md:
            raw = {k: v for k, v in library.items() if k != "_dir"}
            (Path(library_dir) / "library.md").write_text(render_library_md(raw), encoding="utf-8", newline="\n")
        if args.id:
            entry = library["shaders"].get(args.id) or library["meshes"].get(args.id)
            if entry is None:
                raise ForgeError("library_id_unknown", f"No library entry {args.id!r}",
                                 "Run `sabermapper assets library` for the list")
            emit({"id": args.id, **entry})
        else:
            emit({"library": library["_dir"], "shaders": library["shaders"], "meshes": library["meshes"],
                  "library_md": str(Path(library["_dir"]) / "library.md")})
        return 0
    if action == "init":
        directory, slug = _project(args)
        emit(init_spec(directory, slug, args.force))
        return 0
    if action == "lint":
        spec, _, slug = _spec_and_dest(args)
        result = lint_spec(spec, expected_project=slug)
        emit(result)
        return 0 if result["ok"] else 1
    if action == "build":
        spec, dest, slug = _spec_and_dest(args)
        emit(build(spec, dest, target=args.target, unity=args.unity, unity_version=args.unity_version,
                   unity_project=args.unity_project, timeout=args.timeout, allow_no_xr=args.allow_no_xr,
                   nographics=not args.graphics, expected_project=slug))
        return 0
    if action == "promote":
        directory, _ = _project(args)
        emit(promote(directory / "assets" / "assets.json", args.asset_id, args.library, args.library_id))
        return 0
    if action == "generate":
        _project(args)
        emit(generate(args.kind, args.prompt, backend=args.backend, seed=args.seed))
        return 0
    if action == "config":
        emit(save_config({"unity_path": args.unity, "unity_version": args.unity_version,
                          "unity_project_dir": args.unity_project}))
        return 0
    target = args.target or DEFAULT_TARGET
    report = {"config": str(forge_config_path()), "config_values": load_config(), "template": str(TEMPLATE_DIR),
              "library": str(LIBRARY_DIR), "default_target": DEFAULT_TARGET, "targets": TARGETS,
              "unsupported_targets": UNSUPPORTED_TARGETS,
              "installed_editors": {k: str(v) for k, v in installed_editors().items()}}
    try:
        report["unity"] = locate_unity(args.unity, args.unity_version, target if target in TARGETS else DEFAULT_TARGET)
    except ForgeError as exc:
        report.update(exc.as_dict())
    emit(report)
    return 0 if "error" not in report else 1
