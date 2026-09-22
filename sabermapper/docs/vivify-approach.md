# Vivified maps: approach draft

Status: proposal, 2026-09-22. Goal: the user says "Create a vivified map of YYY.flac" and the agent
delivers a map whose scene, lighting and note chart were composed together as one artistic piece,
playable in the installed game. Builds on the EXSII study in
[references/extrasensory/README.md](references/extrasensory/README.md); nothing there is repeated
here except where it drives a decision.

## Where we stand

- The pipeline compiles arrangement 0.1 to a clean vanilla v3.3.0 map. It emits no `customData`
  anywhere, and validation rejects unknown fields. Vivify, Noodle and Chroma are all `customData`.
- ArcViewer 0.8.1 (vendored) does not render Vivify at all. It cannot be the review surface for the
  scene layer.
- The installed game is **1.45.1** with BSIPA. Only `SaberSiege.dll` is enabled; SongCore, BSML,
  CustomJSONData and SiraUtil are in `Plugins_disabled`. Heck, Noodle Extensions, Chroma and Vivify are
  not installed. `docs/installed-game-target.json` still says no Plugins directory; it is stale.
- Game 1.45.1 means the **Unity 2021.3.16f1 bundle target** (`bundleWindows2021.vivify`).
- No Unity Editor and no Deno on this machine. Every EXSII map was scripted (ReMapper) and its assets
  were built in Unity from VivifyTemplate.

The last point is the real constraint. Vivify only loads content from a compiled Unity AssetBundle.
Nothing in the map folder can add a shader, mesh or texture at runtime. Per-map novelty therefore has
to come from *parameters and composition* over a fixed asset vocabulary, unless a Unity build step is
in the loop.

## Design in one paragraph

Author a **storyboard** first, then author the **notes** and the **show** against it, from the same
musical evidence. The storyboard is a short per-section plan (concept, visual family, attention
budget, reveal points). The notes stay in arrangement 0.1. The show is a new document, difficulty
independent, written in agent-level primitives ("look", "scene", "pulse", "reveal", "possess") that a
compiler expands into Vivify, Heck and Chroma events against a **curated SaberMapper asset library**
shipped as one prebuilt `.vivify` bundle with a `bundleinfo.json`. Validation checks the show against
the bundle's property schema and against the notes' density, so that the two layers never compete for
the same attention. Export writes `_requirements`, `_assetBundle`, the bundle files and per-note
`customData`, then installs the map into the game's `CustomWIPLevels`. The user reviews the note layer
in ArcViewer as today and the full piece in the game.

## Why both layers must be authored together

EXSII measures this rather than asserts it: note density and visual load trade against each other per
section, the show is written once for all difficulties, and the busiest chart in the pack keeps note
`customData` minimal so that all its ambition sits in the scene. For Flotos' 6.5–8 star band the
matching model is Yoi Okashi's, not `you`'s: a conventionally dense chart, plain notes, the scene
carrying the spectacle, with deliberate density troughs where the set-pieces land. The storyboard is
the artifact where that trade is decided **before** either layer is written, and it is what the user
can react to in text before anything expensive is built.

## Artifacts

### 1. Storyboard (in the arrangement, per section)

Add an optional `presentation` block to each section in arrangement 0.2:

```json
"presentation": {
  "concept": "glass corridor; the pad swells open the walls",
  "family": "post_process",
  "attention": {"notes": 0.7, "scene": 0.3},
  "reveal": false,
  "note_style": "plain"
}
```

- `family` is one of `post_process`, `scene`, `none`. One family per section, as in the pack.
- `attention` is the agent's declared budget. Validation warns when a section with high measured NPS
  also declares scene-heavy attention plus choreographed notes.
- `note_style` is `plain` (no per-note animation; NJS/track only) or `choreographed` (paths,
  world rotation, custom spawn). Choreographed sections require the lower NJS and the negative offset
  that `you` uses, and validation warns if density is above a threshold.
- A map-level `presentation` records the concept sentence, the palette, and the single
  `possession` decision (`none`, `player`, `head`, `hands`, `right_hand`), because EXSII treats
  possession as a once-per-map structural choice.

This lives in the arrangement so it participates in locks and revisions with the notes it governs.

### 2. Show document (project-level `show.json`, revision-aware)

A separate file beside `arrangement.json`, saved through `project save --show`, with its own revision
SHA and the arrangement revision it was written against. Difficulty independent by construction: a
later second difficulty reuses it unchanged, which is what six of ten EXSII maps do.

Primitives, all in absolute beats, all referencing the section IDs of the arrangement:

| Primitive | Expands to | Notes |
|---|---|---|
| `setup` | `CreateCamera`, `CreateScreenTexture`, `SetRenderingSettings`, initial `AssignPlayerToTrack` | Beat 0 only; one per map |
| `look` | `Blit` with a library post-process material plus `SetMaterialProperty` keyframes | The luminescent technique; a timeline of typed property keyframes |
| `scene` | `InstantiatePrefab` on a generated track, `AnimateTrack` keyframes, paired `DestroyObject` | Lifetime is explicit; the compiler emits the destroy |
| `skin` | `AssignObjectPrefab` for notes, bombs, arcs, chains, sabers | Per section, as `you` swaps note bodies |
| `pulse` | keyframe bursts on a property, driven by musical evidence | See drivers below |
| `possess` | `AssignPlayerToTrack` plus `AnimateTrack` on that track | Only if the map-level decision allows it |
| `env` | Chroma `environment` and `AnimateComponent` (fog, bloom) | Vanilla environment in step with the shaders |
| `path` | Noodle `AssignPathAnimation` for a note track plus per-note NJS/offset | Only in `choreographed` sections |

**Drivers** are the mechanism that makes the show musical rather than decorative, and they reuse the
evidence the note author already reads:

```json
{"kind": "pulse", "section": "drop-1", "material": "sm/post/chroma_split.mat",
 "property": "_Amount", "driver": {"run": "RUN_ID", "layer": "drums", "detector": "spectral_flux",
 "min_strength": 0.6}, "envelope": {"peak": 0.8, "decay_beats": "1/2"}}
```

The compiler turns the matching events into keyframes. A driver can also bind to `sustains`
(SM-032 pitch segments) so that a held vocal opens a skybox gradient or lifts a scene object with the
pitch, which is the visual twin of the held-note rule in `notes.txt`. Every generated keyframe carries
the evidence ID it came from, so a critique can trace a flash back to an onset.

Raw event escape hatch: a `raw` primitive accepting a literal Vivify or Heck event, validated against
the event vocabulary and the bundle schema, for things the primitives do not cover yet.

### 3. Asset library (`assets/vivify/`)

One prebuilt bundle per platform, built once from a VivifyTemplate project kept in the repo, plus a
generated `bundleinfo.json` listing every material with typed, defaulted properties. The agent never
needs Unity per map. The library is the palette, and it needs to be broad enough that composition
alone gives each map its own character:

- **Post-process materials**: colour grade and split-tone, chromatic split, vignette, bloom-like glow,
  pixelate, kaleidoscope, dissolve or threshold, VHS or scan, radial blur, screen-space fog. Each with
  a small set of float and colour properties.
- **Skybox and backdrop materials**: two-colour gradient, procedural nebula, sun disc, horizon line;
  a numbered series is how luminescent cross-fades sections.
- **Scene prefabs**: ring, tunnel segment, floating shard, plane, lantern, pillar, particle field,
  mirror plane. Parametric through material properties and track animation.
- **Object skins**: glass note, wire note, emissive note, debris, saber guide, minimal saber.
- **Render helpers**: a mirror camera, a depth camera, a screen texture for a diegetic HUD.

Ship a `library.md` written for the agent: each asset with its intent, its properties, safe ranges,
and what it looks like in words, since the agent composes without seeing the bundle.

Building this bundle is the one step that needs Unity. Unity Personal can build in `-batchmode`
from a script, so once the editor is installed the build becomes an agent-runnable command
(`scripts/build_vivify_bundle.ps1`). Until then the library build is a human step, and that is the
critical-path item in the plan below. Note that the `_assetBundle` value is Unity's build CRC, taken
from the build output; the exporter reads it from the library manifest and never computes it.

### 4. Compiler and validation changes

- `compile` merges the show into the beatmap: `customData.customEvents`, `customData.environment`,
  `customData.materials`, per-note `customData` (`track`, `noteJumpMovementSpeed`,
  `noteJumpStartBeatOffset`, `animation`, `worldRotation` only where declared), and
  `_requirements: ["Vivify", "Noodle Extensions", "Chroma"]` in Info.dat with the `_assetBundle` block.
- Export copies the platform bundles into the ZIP so the map is self-contained locally. LunarRepo
  hosting is a publishing concern, not a local one.
- New validation, all fail-closed or warning as marked:
  - every material and prefab path exists in `bundleinfo.json`, is lowercase, and each property name
    and type matches (error);
  - every `InstantiatePrefab` id has a `DestroyObject` or an explicit `persist: true` (error);
  - at most one `setup`, possession only as the map-level decision allows (error);
  - blit and flash rate per second against a photosensitivity ceiling, with the offending beats
    listed (error above a hard ceiling, warning below);
  - attention budget versus measured NPS and `note_style` per section (warning);
  - choreographed sections have per-note NJS and offset set (error);
  - event count and spawn burst size against the EXSII envelope, as a warning only, so the agent
    notices when it is far outside anything the reference pack does.
- `mapio.parse_map` already preserves `customData` as unsupported evidence; extend it to parse
  `customEvents` so the EXSII files become test fixtures and a phrase corpus for the show layer.

### 5. Preview and review

Honest answer: the scene layer cannot be reviewed in ArcViewer. The workflow becomes:

1. ArcViewer, as today, for the note layer alone. The exporter can produce a vanilla twin ZIP with
   the customData stripped for exactly this purpose.
2. A **show sheet** the agent renders from the compiled events: per section, the family, the
   assets in use, keyframe density, drivers, and a simple timeline of property curves. It is a
   structural preview for the agent and a readable summary for the user, not a render.
3. The **game**. Export installs the ZIP into `Beat Saber_Data/CustomWIPLevels/` and the user plays
   it. This requires the user to install Heck, Noodle Extensions, Chroma, Vivify, SongCore and their
   dependencies for 1.45.1 once. That is a one-time user action outside the agent-first contract and
   should be stated as such.
4. Optional later: because the library is ours and finite, each post-process shader can have a GLSL
   twin, and a small local WebGL page can play the `look` timeline over a static frame. It would
   preview the colour work, which is the cheapest high-impact family, without touching Unity.

## Composition policy for the agent

Written into the skill, derived from the pack:

1. Read the musical evidence and the sections. Write the concept in one paragraph and choose the
   possession decision and the palette before any event.
2. Give every section a family and an attention budget. Default for this player: dense plain chart,
   `scene` or `post_process` carrying the spectacle, one or two density troughs placed where the
   set-pieces are. `choreographed` sections only where the music is sparse enough to afford NJS 8–12.
3. Structure follows a reveal: a setup burst at beat 0, discrete changes at section boundaries, the
   densest scene work in the final section. Keep something back for the end.
4. Bind pulses to evidence, not to the beat grid. A held vocal drives a slow property; a drum
   onset drives a fast one; a quiet passage gets colour drift and no flashes.
5. Pair every spawn with a destroy. Prefer few tracks with many keyframes over many tracks.
6. Sight-readable first. If a visual only works once the player knows it is coming, cut it.
7. No copying of EXSII assets or event arrays. Study the shape of their timelines, then write our own.

## Phased plan

| Phase | Deliverable | Depends on |
|---|---|---|
| A. Schema and compiler | arrangement 0.2 `presentation`; `show.json` 0.1 with primitives and `raw`; compiler merge; Info.dat requirements and bundle block; ZIP packaging; validation set above; `project save --show`; tests using EXSII files as parser fixtures | nothing |
| B. Asset library v1 | VivifyTemplate project in `assets/vivify-src/`, ~20 materials and ~10 prefabs, batchmode build script, `bundleinfo.json`, `library.md` | Unity 2021.3.16f1 installed once |
| C. Drivers and show sheet | evidence-bound `pulse` and sustain bindings, show sheet renderer, vanilla twin export for ArcViewer | A, musical evidence runs |
| D. Skill and workflow | `sabermapper-map` gains the vivified flow; new `references/show.md` and `references/library.md`; export installs to `CustomWIPLevels`; `installed-game-target.json` refreshed with version and mod list | A, B, C |
| E. First map | one full vivified map for a chosen track, played by the user, feedback captured as revisions to both documents | D, mods installed in the game |
| F. Optional | WebGL look preview; Unity batchmode as an agent command for adding library assets on request | B |

Phase A can start now and is entirely testable offline. Phase B is the critical path and needs a
decision from the user: install Unity 2021.3.16f1 locally, or accept a longer loop where the library
is built elsewhere. Everything in A and C is designed so that B's output is a data file the compiler
reads, never something the agent has to touch by hand.

## Open questions for the user

- Install Unity 2021.3.16f1 on this machine so the library build is a local command?
- Install the Vivify mod stack for 1.45.1 in the game for playtests, alongside SaberSiege?
- Windows PCVR only for now (one bundle target), or also Quest (`android2021`)?
- Any first track in mind for Phase E, so the library's first materials can be chosen for it?
