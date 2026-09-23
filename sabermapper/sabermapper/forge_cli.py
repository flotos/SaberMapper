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
             "credits": "Sources, authors and licences of every fetched or generated (tier-3) asset, with the "
                        "attribution text to paste into the map description; --write saves <project>/assets/credits.json",
             "doctor": "Where Unity is looked for, what is installed, targets and config",
             "config": "Persist the Unity path, version or build project directory for this machine"}
    for action, text in helps.items():
        parser = actions.add_parser(action, help=text)
        if action in ("init", "lint", "build", "promote", "generate", "credits"):
            parser.add_argument("project", nargs="?" if action in ("lint", "build", "credits") else None,
                                help="Project ID; its spec is <project>/assets/assets.json")
            parser.add_argument("--workspace", type=Path, default=Path("workspace"))
        if action in ("lint", "build", "credits"):
            parser.add_argument("--spec", type=Path, help="Use this assets.json instead of a project's")
        if action == "credits":
            parser.add_argument("--write", action="store_true", help="Also write credits.json next to assets.json")
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
    _register_fetch(actions)


def _register_fetch(actions):
    fetch = actions.add_parser(
        "fetch", help="Free CC0 models, textures and sky panoramas from Poly Haven, ambientCG and Kenney: "
                      "search, inspect with previews, then convert into a project as tier-3 assets")
    steps = fetch.add_subparsers(dest="fetch_action", required=True)
    search = steps.add_parser("search", help="Candidates with licence, triangle count, size and preview URL")
    search.add_argument("query", nargs="?", default="", help="Words to match (name, tags, categories)")
    search.add_argument("--kind", choices=["model", "texture", "sky"], default="model")
    search.add_argument("--source", action="append", choices=["polyhaven", "ambientcg", "kenney"],
                        help="Repeat to combine; default: every source that offers the kind")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--max-triangles", dest="max_triangles", type=int, default=20000,
                        help="Budget used to mark fits_budget (models above it are decimated by get)")
    info = steps.add_parser("info", help="Download a candidate into the machine cache and list its mesh nodes, pack "
                                         "models or maps, with local preview images to read before choosing")
    info.add_argument("ref", help="SOURCE:ID from search, e.g. polyhaven:rock_moss_set_01 or kenney:nature-kit")
    info.add_argument("--max-download-mb", dest="max_download_mb", type=float, default=200)
    get = steps.add_parser("get", help="Convert a candidate into <project>/assets/ (models/*.obj or textures/*.jpg) with "
                                       "provenance; prints the assets.json entries, or appends them with --add")
    get.add_argument("ref")
    get.add_argument("project", help="Project ID")
    get.add_argument("--workspace", type=Path, default=Path("workspace"))
    get.add_argument("--kind", choices=["model", "texture", "sky"], help="Default: the candidate's own kind")
    get.add_argument("--model", help="Kenney: the model name inside the pack (from info)")
    get.add_argument("--node", action="append", dest="nodes", help="Poly Haven: keep only these mesh nodes (repeatable)")
    get.add_argument("--id", dest="asset_id", help="Asset id in assets.json (default: from the model or asset name)")
    get.add_argument("--height", type=float, help="Scale the model to this height in metres (default: native size)")
    get.add_argument("--origin", choices=["base", "center", "keep"], default="base",
                     help="base: footprint centre at the lowest point (default); center: bounding-box centre")
    get.add_argument("--max-triangles", dest="max_triangles", type=int,
                     help="Decimate above this (default: budgets.max_triangles_per_mesh)")
    get.add_argument("--resolution", help="Texture or sky resolution (Poly Haven 1k/2k/4k; ambientCG 1K-JPG, 2K, ...)")
    get.add_argument("--maps", help="Texture maps, comma-separated: color,normal,roughness,ao,height (default color)")
    get.add_argument("--max-size", dest="max_size", type=int, help="Downscale images to this many pixels on the long side")
    get.add_argument("--add", action="store_true", help="Append the entries to <project>/assets/assets.json")
    get.add_argument("--force", action="store_true", help="Replace existing files or entries with the same id")
    get.add_argument("--max-download-mb", dest="max_download_mb", type=float, default=200)


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
    from .mesh_files import MeshFileError
    try:
        return _dispatch(args, emit)
    except ForgeError as exc:
        emit(exc.as_dict())
        return 1
    except MeshFileError as exc:
        emit(ForgeError(exc.code, exc.message, exc.fix).as_dict())
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
    if action == "credits":
        from .asset_credits import CREDITS_FILE, credits_for_file
        spec, _, _ = _spec_and_dest(args)
        if not spec.is_file():
            raise ForgeError("spec_missing", f"{spec} does not exist", "Run `assets init PROJECT` or pass --spec FILE")
        credits = credits_for_file(spec)
        if args.write:
            from .storage import write_json
            write_json(spec.parent / CREDITS_FILE, credits)
            credits["written"] = str(spec.parent / CREDITS_FILE)
        emit(credits)
        return 0
    if action == "fetch":
        from . import asset_fetch
        if args.fetch_action == "search":
            sources = args.source or [s for s in asset_fetch.SOURCES
                                      if not (args.kind == "model" and s == "ambientcg") and not (args.kind != "model" and s == "kenney")]
            emit(asset_fetch.search(args.query, kind=args.kind, sources=sources, limit=args.limit,
                                    max_triangles=args.max_triangles))
        elif args.fetch_action == "info":
            emit(asset_fetch.info(args.ref, max_download_mb=args.max_download_mb))
        else:
            directory, _ = _project(args)
            emit(asset_fetch.get(args.ref, directory, args.project, kind=args.kind, model=args.model, nodes=args.nodes,
                                 asset_id=args.asset_id, height=args.height, origin=args.origin,
                                 max_triangles=args.max_triangles, resolution=args.resolution,
                                 maps=args.maps.split(",") if args.maps else None, max_size=args.max_size,
                                 add=args.add, force=args.force, max_download_mb=args.max_download_mb))
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
