# Asset forge (ticket M4)

The forge turns an agent-written `assets.json` (plus shader and C# generator sources) into a Vivify asset
bundle, `bundleinfo.json` and the Unity build CRC, using Unity in `-batchmode`. Everything except the final
Unity step runs without Unity: spec validation, shader lint, budgets, library lookup, starter specs and
library promotion. When Unity is absent, `assets build` returns a structured `unity_missing` error.

Status (2026-09-23): the Python side is tested (tests/test_forge.py, with a stub standing in for Unity).
Unity is not installed on this machine, so the C# builder in `assets/vivify-src/` has not been compiled by
Unity yet. It was compiled with Roslyn (C# 9) against the game's Unity 2022.3 runtime DLLs, plus
hand-written stubs of the UnityEditor and XR Management APIs it calls, which catches syntax and type
errors. The first real build is the first check of the actual editor API signatures.

## Which Unity to install

**Unity 2021.3.45f1** (changeset `0da89fac8e79`, Windows editor with its built-in Windows Mono build
support; no extra modules). Target `windows2021` → `bundleWindows2021.vivify`, Info.dat key
`_assetBundle._windows2021`. Both the version and the target can be configured (`--unity-version`,
`--target`, `assets config`); these values are the defaults.

**Why 2021.3.45f1 and not 2021.3.16f1 (verified 2026-09-23 on this machine, Hub 3.21.3, licensing client
1.18.3).** The Vivify docs name 2021.3.16f1, and it is installed here, but it cannot build headless with a
Hub Personal license: Hub passes the editor its sign-in token only when Hub itself opens it, and in
batchmode 2021.3.16f1 stops with `Access token is unavailable` / `Unity has not been activated with a valid
License`, even with the Personal seat active and after opening the editor once from Hub. 2021.3.45f1
takes the seat headless (`Serial number assigned`), and the first real build with it produced a
single-pass-instanced (OpenXR) bundle in 30 s. `assets build` reports that failure as
`unity_headless_license_unsupported` with this fix. Any 2021.3 patch writes the same bundle format and
keys; the game runs Unity 2022.3.33 and already loads 2019.4 and 2021.3.16 bundles.

Evidence:

- Vivify picks its bundle file and checksum key at compile time. `BUNDLE_SUFFIX = "Windows2021"` and
  `BUNDLE_CHECKSUM = "_windows2021"` are used for every build except the one for game 1.29.1
  (`#if !V1_29_1`). The bundle is loaded with `AssetBundle.LoadFromFile(path, checksum)`, where the checksum
  is `_assetBundle._windows2021` from the Info.dat custom data; the `-aerolunaisthebestmodder` launch
  argument (Heck debug mode) skips the check. There is no 2022 key. Sources:
  [VivifyController.cs](https://github.com/Aeroluna/Vivify/blob/master/Vivify/VivifyController.cs),
  [AssetBundleManager.cs](https://github.com/Aeroluna/Vivify/blob/master/Vivify/Managers/AssetBundleManager.cs).
- Vivify v1.1.0 (2026-05-09) ships a build for game 1.40.8, with the same keys
  ([releases](https://github.com/Aeroluna/Vivify/releases)). The installed plugin is Vivify 1.0.5 on
  game 1.40.8_7379 with UnityPlayer 2022.3.33 (read from the local files).
- The Heck/Vivify docs state: "Beat Saber 1.29.1 uses version 2019.4.28f and Beat Saber 1.30.0+ uses
  2021.3.16f1". They list the bundle names `bundleWindows2019.vivify`, `bundleWindows2021.vivify` and
  `bundleAndroid2021.vivify`, and say the checksum comes from the build manifest
  ([Getting started with Vivify](https://heck.aeroluna.dev/vivify/getting-started-with-vivify/)).
- VivifyTemplate itself pins **2019.4.28f1** (`ProjectSettings/ProjectVersion.txt`). It builds the Windows2021
  bundle from that old editor with `stereoRenderingPath = Instancing`. For any editor up to 2019 it then
  rewrites the shader keywords into the 2021 format with a bundled AssetsTools.NET DLL and computes the CRC
  itself. On a newer editor it uses `BuildPipeline.GetCRCForAssetBundle`
  ([BuildAssetBundles.cs](https://github.com/Swifter1243/VivifyTemplate/blob/master/Packages/com.swifter.vivify-template.exporter/Scripts/Editor/Build/BuildAssetBundles.cs)).
  So a bundle built by a 2021.3 editor needs no rewrite step.
- Local evidence: the headers of the ten EXSII `windows2021` bundles in
  `workspace/corpus/extrasensory/bundles/` show nine built with 2019.4.28f1 (the VivifyTemplate rewrite path)
  and one (`42-flux`) with **2021.3.16f1**. Both kinds of bundle are in published maps.

Why not 2019.4.28f1: it would need VivifyTemplate's binary keyword rewriter and its asynchronous, UI-driven
build, which cannot run in unattended batchmode. Why not 2022.3.33 (the game's own runtime): Vivify's docs
do not name it, so it is untested for this purpose. It stays reachable with `--unity-version`.
If Unity Hub no longer offers 2021.3.45f1, install the newest 2021.3 LTS patch. The locator falls back to
the newest installed `2021.3.x` and reports a `unity_version_mismatch` warning. Unity's CVE-2025-59489
concerns built players, not asset bundles.

## One-time user setup

1. Install Unity Hub from unity.com and sign in with a (free) Unity ID.
2. Install editor **2021.3.45f1**: run `start unityhub://2021.3.45f1/0da89fac8e79`, or open the
   [release page](https://unity.com/releases/editor/whats-new/2021.3.45) and press Install (Hub's own
   Install Editor list only shows current versions). Defaults are enough: Windows Mono build support is
   part of the Windows editor, and Android/iOS/IL2CPP are not needed. The default location is
   `C:\Program Files\Unity\Hub\Editor\2021.3.45f1\Editor\Unity.exe`.
3. Activate a license once: Hub > Preferences > Licenses > Add > *Get a free personal license*.
   Batchmode uses the license Hub activated while Hub stays signed in. There is no per-build login.
4. Nothing else. The agent runs `sabermapper assets doctor`, then `assets build`. The first build downloads
   `com.unity.xr.management` and `com.unity.xr.openxr` (network needed once) and imports the project,
   which takes several minutes. Later builds reuse the cached `Library/`.

If Unity is installed elsewhere, the agent records it with `sabermapper assets config --unity PATH`.

## Layout

```
sabermapper/assets/
  library/                  tier-1 library: library.json (machine-readable), library.md (generated), shaders/*.shader
  vivify-src/               Unity project template, text only (no Library, no .meta, no binaries)
    Packages/manifest.json  XR Plug-in Management + OpenXR (single-pass-instanced variants), built-in modules
    ProjectSettings/ProjectVersion.txt   2021.3.45f1 (rewritten to the chosen editor at build time)
    Assets/SaberMapper/Editor/Forge.cs            batchmode entry SaberMapper.Forge.Build
                              ForgeJson.cs        JSON reader/writer + ForgeParams (generator/particle params)
                              ForgeMeshes.cs      built-in mesh generators
                              ForgeParticles.cs   particle system modules
                              XR/ForgeXR.cs + .asmdef  enables the OpenXR loader for Standalone
<project>/assets/
  assets.json               the agent's spec (plus shaders/, generators/, textures next to it)
  bundleWindows2021.vivify  built bundle            ← read by the show compiler (M3)
  bundleinfo.json           VivifyTemplate format   ← read by the show compiler (M3)
  bundleWindows2021.vivify.manifest, build-report.json, build.log
  builds/<build_id>/        report, log and bundleinfo of every attempt (failed ones too)
```

`assets build` never builds inside the git checkout. It copies the template into a machine-local project,
`%LOCALAPPDATA%/SaberMapper/forge/unity-<version>/` (configurable), which keeps `Library/` between builds.
A lock file serialises builds (`forge_busy`). The generated assets and the agent's generator code go
under `Assets/SaberMapper/<project>/` and `Assets/SaberMapper/Staging/Editor/`, and are wiped at the
start of every build.

## Commands

All output is JSON. Failures print `{"error": {"code", "message", "fix", ...}}` and exit with status 1.

| Command | Purpose |
|---|---|
| `assets library [--id ID] [--write-md]` | Library shaders (typed properties, safe ranges, words) and mesh generators |
| `assets init PROJECT [--force]` | Starter `<project>/assets/assets.json` from the library (lint-clean) |
| `assets lint PROJECT \| --spec FILE` | Schema, paths, references, shader lint, budgets; exit 1 on errors |
| `assets build PROJECT \| --spec FILE [--out DIR] [--target windows2021] [--unity PATH] [--unity-version V] [--unity-project DIR] [--timeout S] [--allow-no-xr] [--graphics]` | Lint, stage, run Unity, verify, copy outputs |
| `assets promote PROJECT ASSET_ID [--library-id sm_x] [--library DIR]` | Move a tier-2 shader into the library |
| `assets generate PROJECT --kind image\|skybox\|mesh --prompt TEXT [--seed N]` | Tier-3 interface; `generator_unavailable` for now |
| `assets doctor [--target] [--unity] [--unity-version]` | Config, installed editors, targets, the resolved Unity or `unity_missing` |
| `assets config [--unity PATH] [--unity-version V] [--unity-project DIR]` | Persist machine settings (`''` clears) |

Unity is located from `--unity`, then `SABERMAPPER_UNITY`, then the config file
(`%LOCALAPPDATA%/SaberMapper/forge.json` or `SABERMAPPER_FORGE_CONFIG`), then the Unity Hub installs:
`C:\Program Files\Unity\Hub\Editor\<version>`, Hub's `secondaryInstallPath.json`, and Hub's
`editors-v2.json`/`editors.json`.

Without Unity:

```json
{"error": {"code": "unity_missing",
  "message": "Unity 2021.3.45f1 was not found (installed editors: none)",
  "fix": "Install Unity 2021.3.45f1 with Unity Hub (unityhub://2021.3.45f1/0da89fac8e79) and activate a Personal license once, then rerun",
  "required_version": "2021.3.45f1", "target": "windows2021", "tried": ["hub: C:\\Program Files\\Unity\\Hub\\Editor"], "installed": []}}
```

A successful build returns `{ok, build_id, unity, target, log, duration_s, bundle_paths, bundleinfo, crc,
crc_key, build_report, warnings}`. A failed one returns `unity_build_failed` (or `unity_timeout`,
`crc_mismatch`, `bundle_invalid`, `bundle_budget_exceeded`, `lint_failed`, `forge_busy`) with `errors`. Each
error carries `source` (`csharp`, `shader`, `forge`, `unity`), `code`, `file` and `line` mapped back to
**your** source (the library shader, the project's shader, or the generator `.cs`), plus a `message` and a
`fix`. The full log is saved under `builds/<build_id>/build.log`.

Log formats parsed: C# `Assets/…/File.cs(12,9): error CS1002: ; expected`. Shader
`Shader error in 'Name': msg at line 58 (on d3d11)` and `… at Assets/…/inc.cginc(7) (on d3d11)`. Forge
`[SaberMapperForge] {json}` lines. Editor failures: licence missing, project already open, package
resolution, and `executeMethod … could not be found` (the scripts did not compile).

## assets.json

```json
{
  "format": "sabermapper-assets/1",
  "project": "demo-song",
  "target": "windows2021",
  "compression": "lz4",
  "budgets": {"max_triangles_per_mesh": 20000, "max_total_triangles": 150000, "max_renderers": 64,
              "max_particles": 4000, "max_texture_samples": 24, "max_loop_iterations": 64,
              "max_texture_size": 4096, "max_bundle_mb": 64},
  "assets": [
    {"id": "grade", "kind": "post_process", "tier": 1, "path": "assets/sabermapper/demo-song/post/grade.mat",
     "shader": {"library": "sm_color_grade"}, "properties": {"_Saturation": 0.6, "_ShadowTint": [0.4, 0.45, 0.6, 1]},
     "provenance": {"library": "sm_color_grade"}},
    {"id": "neon", "kind": "material", "tier": 1, "path": "assets/sabermapper/demo-song/materials/neon.mat",
     "shader": {"library": "sm_unlit_emissive"}, "properties": {"_Color": [1, 0.2, 0.6, 1]}},
    {"id": "ring", "kind": "prefab", "tier": 1, "path": "assets/sabermapper/demo-song/prefabs/ring.prefab",
     "children": [{"name": "ring", "mesh": {"generator": "torus", "params": {"radius": 3, "thickness": 0.04}},
                   "material": "neon", "position": [0, 2, 20], "rotation": [0, 0, 0], "scale": 1}]}
  ]
}
```

- `project`: the project id in lowercase. Every `path` is lowercase, lives under
  `assets/sabermapper/<project>/`, and uses only `a-z 0-9 _ - . /`. It is the exact string Vivify events
  use (`InstantiatePrefab.asset`, `Blit.asset`, `SetMaterialProperty.asset`). Extensions: `.mat` for
  material, post_process and skybox; `.prefab` for prefab and particles; `.asset` for mesh; `.png` (or
  jpg/tga/exr) for texture. The folders `editor/` and `staging/` are reserved.
- `kind`:
  - `material`: a surface for renderers.
  - `post_process`: a Blit material. Its shader must sample `_MainTex` through the screen-space macros.
  - `skybox`: for `SetRenderingSettings` `renderSettings.skybox`.
  - `prefab`: `children`, each with exactly one of `mesh` or `particles`, plus a `material` id of kind
    `material`, and `position`/`rotation`/`scale`.
  - `particles`: a prefab whose root is a particle system (`particles` and `material`).
  - `mesh`: a standalone mesh asset.
  - `texture`: an image file (`source`) with import settings `texture: {srgb, mipmaps, wrap: repeat|clamp,
    max_size, shape: 2d|cube}`. `cube` imports an equirectangular panorama as a cubemap.
- `shader`: either `{"library": "sm_…"}` or `{"source": "shaders/x.shader"}` (relative to assets.json).
  `properties` are checked against the shader's own `Properties` block: the name must exist, the type must
  match (Float number, Color `[r,g,b(,a)]`, Vector 2–4 numbers, Texture `{"texture": "<texture id>"}`) and
  the value must lie inside `Range()`. Library safe ranges give warnings.
- `mesh`: one of `{"generator": NAME, "params": {…}}` (built-in, triangles computed from library.json),
  `{"asset": "<mesh id>"}`, or tier 2 `{"source": "generators/X.cs", "class": "Ns.X", "params": {…},
  "max_triangles": N}`. Inline prefab-child meshes become mesh assets named
  `meshes/<prefab>__<child>.asset`.
- `particles`: `max_particles, duration, looping, prewarm, start_lifetime|start_speed|start_size|start_rotation`
  (number or `[min, max]`), `start_color, gravity, simulation_space: local|world, play_on_awake`,
  `emission {rate_over_time, rate_over_distance, bursts: [{time, count, cycles, interval}]}`,
  `shape {type: sphere|hemisphere|cone|box|circle|edge|donut, radius, angle, arc, donut_radius, thickness,
  scale, position, rotation}`, `color_over_lifetime {gradient: [[t, r, g, b, a], …]}`,
  `size_over_lifetime {curve: [[t, v], …]}`, `velocity_over_lifetime {linear, orbital, radial, space}`,
  `noise {strength, frequency, scroll_speed, octaves}`, and `renderer {render_mode:
  billboard|stretched|horizontal|vertical|mesh, mesh, velocity_scale, length_scale, max_particle_size}`.
- `tier`: 1, 2 or 3, with `provenance` (below). `render_queue` (optional) overrides a material's queue.

## Guardrails (`assets lint`, also run first by `assets build`)

| Rule | Severity | Meaning |
|---|---|---|
| `stereo_input_instance_id`, `stereo_output`, `stereo_setup_instance`, `stereo_init_output`, `stereo_eye_index` | error | Single-pass-instanced macros: `UNITY_VERTEX_INPUT_INSTANCE_ID` in the vertex input struct, `UNITY_VERTEX_OUTPUT_STEREO` in the output struct, `UNITY_SETUP_INSTANCE_ID(v)` and `UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o)` in the vertex function, `UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i)` in the fragment function. Without them a shader renders in the left eye only. |
| `screenspace_declare`, `screenspace_sample` | error (post_process) | `UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex)` and `UNITY_SAMPLE_SCREENSPACE_TEXTURE`; `sampler2D _MainTex` / `tex2D(_MainTex…)` are rejected |
| `screenspace_transform` | warning | UVs not wrapped in `UnityStereoTransformScreenSpaceTex` |
| `cost_texture_samples`, `cost_loop_iterations` | error | Fragment cost heuristic over budget: samples are counted through loops (literal bounds) and helper calls |
| `unbounded_loop`, `grabpass`, `surface_shader` | warning | Non-literal loop bound (assumed 16), GrabPass, or a lit surface shader |
| `path_not_lowercase`, `path_outside_project`, `path_extension`, `path_duplicate`, `asset_id_duplicate` | error | Paths and ids |
| `property_unknown`, `property_type`, `property_out_of_range` / `property_outside_safe_range` | error / warning | Material values |
| `material_reference`, `mesh_reference`, `texture_reference` | error | References to the wrong kind |
| `mesh_budget_exceeded`, `mesh_budget_undeclared`, `budget_exceeded`, `texture_budget_exceeded` | error | Triangles per mesh and in total (prefab usage), renderers (≈ draw calls), particles, texture size; custom generators are checked again after generation in Unity, and bundle size after the build |
| `provenance_missing`, `provenance_incomplete`, `provenance_hash_mismatch`, `tier_mismatch` | error | Tier records |
| `project_mismatch` | error | assets.json `project` differs from the project's slug |

Diagnostics carry `file`, `line` (the shader line, or the asset's `"id"` line in assets.json), `rule`,
`message` and `fix`.

## Tier 1: the parametric library

`library/library.json` lists 13 shaders: nine post-processes (colour grade/split-tone, chromatic split,
vignette, glow, pixelate, kaleidoscope, threshold/dissolve, scanline/VHS, radial blur), two skyboxes
(gradient, procedural nebula), an unlit emissive surface for prefabs and an additive particle sprite. It
also lists 9 mesh generators (quad, plane, cube, uv_sphere, ring, torus, tube, cone, shard). Each shader
entry gives the intent, typed properties with defaults, safe ranges and meanings, and a description in
words. `library.md` is generated from the JSON (`assets library --write-md`), and a test keeps them in
sync. Tests also check that every library shader is lint-clean and that its JSON properties match the
shader's `Properties` block. All shaders write alpha deliberately (`_Glow`), because Beat Saber's bloom
reads the alpha channel.

## Tier 2: agent-written code assets

**Shaders.** Copy the nearest library shader as a template (the vertex/fragment skeleton already carries
every stereo macro) and put the new file next to assets.json. Reference it with
`"shader": {"source": "shaders/x.shader"}`, `"tier": 2` and
`"provenance": {"author": "agent", "description": "…"}`. Blits keep `_MainTex` as the screen and sample it
only through `UNITY_SAMPLE_SCREENSPACE_TEXTURE`. Checks, in order:

1. `assets lint`: macros, cost, property values.
2. `assets build`: Unity compiles the shader. Errors come back with the line in your file. A shader error
   during the bundle build fails the build, because StrictMode is on.
3. The game: M0/M2 frame captures confirm the look.

**Procedural meshes.** Write an editor C# file with a static generator:

```csharp
using UnityEngine;
namespace SaberMapper.Generated
{
    public static class RibbonMesh
    {
        public static Mesh Generate(SaberMapper.ForgeParams p)
        {
            int segments = p.Int("segments", 64);   // also p.Float, p.Bool, p.Vec3, p.Color, p.Floats, p.Child
            // build vertices/uvs/triangles, then: return ForgeMeshes.Build("ribbon", verts, uvs, tris);
        }
    }
}
```

Reference it with `{"source": "generators/Ribbon.cs", "class": "SaberMapper.Generated.RibbonMesh",
"params": {…}, "max_triangles": N}`. The file is compiled into the editor assembly with the forge, so a C#
error blocks the whole build and is reported with your file and line. After generation, the triangle
count is checked against `max_triangles` and the budget. Unity winding is clockwise for front faces.

**Particles.** These are pure data (the `particles` block). Use the `sm_particle_additive` material or
your own tier-2 particle shader.

## Tier 3: generative media (interface only)

Decided 2026-09-23: models run **locally** on the RTX 5070 Ti. `assets generate PROJECT --kind
image|skybox|mesh --prompt … [--seed]` is the interface. No model is integrated, so it returns
`generator_unavailable` with a `provenance_template`. The intended pipeline:

- image or skybox: a local text-to-image model writes a PNG (skybox: a 2:1 equirectangular image imported
  with `texture.shape: "cube"`).
- mesh: a local text-to-3D model writes a mesh, Blender decimates it to the budget, and the result is
  imported as a texture/mesh source.

Each output becomes an asset with `"tier": 3` and a provenance record that lint enforces:

```json
"provenance": {
  "generator": {"kind": "skybox", "model": "…", "model_version": "…", "backend": "local", "device": "cuda:0",
                "prompt": "…", "negative_prompt": "", "seed": 7, "params": {}},
  "created_at": "2026-09-23T12:00:00Z", "license": "model licence / terms", "output_sha256": "<sha256 of source file>",
  "postprocess": [{"tool": "blender", "version": "4.x", "op": "decimate", "ratio": 0.2}]
}
```

`output_sha256` must match the file actually used (`provenance_hash_mismatch`). Installing any model
needs the user's approval.

## Promoting into the library

`assets promote PROJECT ASSET_ID` accepts only lint-clean tier-2 shader assets. The asset must carry a
`library` block: `id` (`sm_…`), `intent`, `description`, and for every property a `meaning`, plus a
`safe` `[min, max]` inside the shader Range for each Float. When anything is missing, the command returns
`library_entry_incomplete` with `missing` and a pre-filled `stub` to copy into the asset. When the block
is complete, it copies the shader to `library/shaders/<id>.shader`, adds the JSON entry (with
`promoted_from` provenance) and regenerates library.md. That is a code change: commit it from a worktree.

## Builder details

`SaberMapper.Forge.Build` runs these steps:

1. Check the editor version against the target (`editor_target_mismatch`).
2. Switch to StandaloneWindows64 and set linear colour space and `stereoRenderingPath = Instancing`.
3. Enable the OpenXR loader for Standalone through XR Plug-in Management. OpenXR defaults to
   single-pass instanced, so Unity keeps the `STEREO_INSTANCING_ON` variants in the bundle. It fails with
   `xr_not_configured` unless `--allow-no-xr` is passed.
4. Create textures, meshes, materials (typed property setters) and prefabs, then enforce budgets.
5. Build one bundle `sabermapper_<project>` with LZ4, ForceRebuild and StrictMode.
6. Read the CRC with `BuildPipeline.GetCRCForAssetBundle`. Python checks it against the Unity `.manifest`
   `CRC:` line.
7. Write `bundleinfo.json` in VivifyTemplate's shape:
   `{"materials": {name: {"path", "properties": {prop: {"value", "type": {"Float"|"Color"|"Vector"|"Texture": null}}}}},
   "prefabs": {name: path}, "bundleFiles": [...], "bundleCRCs": {"_windows2021": crc}, "isCompressed": true}`.
   Python rewrites `bundleFiles` to the copy in `<project>/assets/`.
8. Write `build-report.json`: assets with triangles, renderers and particles, totals, XR status, CRC, bundle
   assets, errors and warnings.

VivifyTemplate is MIT-licensed (Swifter, 2026). No code was copied from it. The bundleinfo format and the
build approach were reimplemented from reading its source.

## Integration notes

- Show compiler (M3): read `<project>/assets/bundleinfo.json`. `bundleCRCs._windows2021` becomes
  `Info.dat _customData._assetBundle._windows2021`. Copy `<project>/assets/bundleWindows2021.vivify` into
  the map folder. Material and prefab paths in bundleinfo are the lowercase asset paths Vivify events use.
  Property names and types come from `materials.*.properties`.
- Verification (M0/M2): the first built bundle should be checked in FPFC with a one-material Blit, to
  confirm that single-pass-instanced variants survive the batchmode build (XR loader path) and that
  Vivify 1.0.5 on 1.40.8 accepts a 2021.3.16f1 bundle and its CRC.

## Known risks

- The editor-side C# has not been compiled by a real Unity editor. The `UnityEditor` and XR Management
  calls (`ShaderUtil.GetShaderMessages`, `XRPackageMetadataStore.AssignLoader`, …) follow the Unity 2021.3
  API docs and were checked only against stubs. The runtime-side code (meshes, particles, JSON) compiles
  against the game's real UnityEngine DLLs.
- Package versions `com.unity.xr.management 4.2.1` and `com.unity.xr.openxr 1.5.3` were chosen for
  2021.3. If Unity resolves different ones, the build still works when the XR loader can be assigned.
- The cost heuristic counts texture samples and literal loop bounds. It is a guardrail, not a profiler.
