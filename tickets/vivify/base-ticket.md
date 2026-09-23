# Vivify pipeline: agent-built, game-verified vivified maps

Status: open, 2026-09-23. Extends [sabermapper/docs/vivify-approach.md](../../sabermapper/docs/vivify-approach.md)
(proposal of 2026-09-22) and the EXSII study in
[sabermapper/docs/references/extrasensory/README.md](../../sabermapper/docs/references/extrasensory/README.md).
Where this ticket and the approach doc disagree, this ticket wins.

## Request

Build a pipeline in which a Claude Code or Codex agent creates a Vivify map for a song on its own,
with the creative ambition of the EXSII maps: it understands the song's mood and lyrics, proposes an
idea, builds custom assets for it, and choreographs them to the audio.

Always frame the work as **a pipeline for an agent to build, iterate, verify, refine, and loop**. The
human is only there to verify, and verifying a song must be easy. The existing web studio gets a
button that plays the map in the game, starting it at the map start or the playhead, and a way to
start a replay. The studio also hosts the slider that changes the song time.

## Principles

1. **The agent owns the loop.** Import, analysis, concept, asset build, choreography, compile,
   export, game verification and revision are all agent operations with CLI commands, structured JSON
   output and actionable errors. No step requires a human in Unity, the game menus or a text editor.
2. **The human only verifies, in one click.** From the studio: pick a revision, press *Play in game*
   or *Watch*, scrub with the slider, press *Note* to leave a timestamped comment. Nothing else.
3. **Every studio control has a CLI twin.** The studio calls the same API the agent calls.
4. **The agent verifies before the human sees anything.** A revision reaches the human only after
   the agent's static checks, game-log checks and frame review pass, and the handover states which
   checks ran.
5. **The real game is the renderer.** Agent frame captures come from Beat Saber running the actual
   Vivify stack, not from an approximate interpreter. This replaces the approach doc's "show sheet"
   and WebGL preview as the verification surface.
6. **Audio is the source of every visual event**, as it is of every note (see `AGENTS.md`). Each
   generated visual keyframe records the audio evidence, lyric word or moment it came from.
7. Systematic fixes apply: a visual defect found in one map becomes a check, a pipeline correction
   or a skill rule, with a regression test, rerun across all vivified projects.

## Current state (observed 2026-09-22/23)

- Pipeline compiles arrangement 0.1 to vanilla v3.3.0; no `customData`; validation rejects unknown
  fields.
- ArcViewer 0.8.1 does not render Vivify.
- Game 1.45.1 (Steam, `C:/Program Files (x86)/Steam/steamapps/common/Beat Saber`), BSIPA present,
  only `SaberSiege.dll` enabled. SongCore, BSML, CustomJSONData, SiraUtil disabled; Heck, Noodle,
  Chroma, Vivify not installed. `docs/installed-game-target.json` is stale.
- Bundle target: Unity 2021.3.16f1, `bundleWindows2021.vivify`.
- Not installed: Unity Editor, Deno, .NET SDK. GPU: RTX 5070 Ti, 16 GB.
- Audio analysis already has a Demucs stem backend (`musical.py`); no lyrics, mood or "moment"
  detection.
- Studio: stdlib HTTP server (`sabermapper/server.py`) plus static UI; no game integration.

## Target loop

```
 listen → concept → forge assets → choreograph → compile/export → install + game refresh
    ▲                                                                    │
    │                                                  game load (FPFC) + capture + logs
    │                                                                    │
    └── refine ◄── critique ◄── static checks + frame metrics + agent reads frames
                                                                         │
                                                (only when agent checks pass)
                                                                         ▼
                                   human: studio ▶ Play in game / Watch, slider, Note
                                   → timestamped feedback → agent's next iteration
```

## Milestones

Each milestone is merged separately, with tests, and leaves every command usable by the agent.

### M0 — Game bridge spike (go/no-go)

A BSIPA plugin, **SaberMapper Bridge**, for game 1.45.1, source in `sabermapper/game-bridge/`,
built with `dotnet build` against the installed game assemblies. It serves a localhost-only
HTTP/WebSocket API.

- `load(level_path, characteristic, difficulty, start_time, speed)`: start a level at a song time
  using the game's practice start-time support.
- `state`: stream `{scene, level, song_time, paused, fps}`.
- CLI: `sabermapper game launch [--fpfc]`, `game play PROJECT --at SECONDS`, `game status`.

Acceptance:
- `game play` starts an exported **vanilla** SaberMapper map at the requested time in FPFC
  (SiraUtil `fpfc` launch argument), and `game status` reports song time within 0.1 s.
- A one-shader test Vivify map renders correctly in FPFC desktop mode (single-pass-instanced shader
  on a non-VR camera). Record the result; if it fails, document the workaround or fall back to
  headset-only verification for the human and a Unity-side capture for the agent.
- Document how Heck, Noodle and Vivify behave when a level starts late (are events before
  `start_time` applied?). This decides whether `seek` can be exact.

### M1 — Studio verification console

- Export installs the map into `Beat Saber_Data/CustomWIPLevels/` and calls the bridge `refresh`
  (SongCore reload).
- Studio transport: *Play in game* (at map start or playhead), *Watch* (ghost autoplay, see M6),
  pause, resume, restart, revision picker.
- Song-time slider, two-way: dragging seeks the game (debounced restart-at-time if exact seek is not
  possible); game time moves the slider. Section and key-moment markers on the slider.
- *Note* button: stores `{project, revision, song_time, beat, section, text, created_at}` as project
  feedback. CLI `project feedback list ID` returns it for the agent.
- CLI twins: `game seek`, `game pause`, `game resume`, `game restart`.

Acceptance: from a cold studio, one click plays the current revision in the game at the playhead,
and a note left at 1:23 is returned by `project feedback list` with the right beat and section.

### M2 — Agent verification in the game

- `game capture PROJECT --times ... [--camera player|wide] --out DIR`: PNG frames from the running
  game at given song times; default set = every key moment, every section boundary, every N beats.
- Contact-sheet builder (one PNG per section) for the agent to read.
- `game logs`: Heck/Vivify/Noodle/Chroma errors and exceptions from `Logs/_latest.log`, filtered
  for the current level and returned as structured diagnostics (e.g. bundle checksum mismatch,
  missing material, shader error).
- Frame metrics as critique findings: full-frame luminance flash rate (photosensitivity ceiling,
  blocking above a hard limit), note contrast against the background along the note corridor,
  palette drift from the concept palette, visual change aligned with section boundaries.

Open decision: may the agent launch the game on its own for capture runs? `CLAUDE.md` forbids the
agent from opening previews because it cannot see them; game captures are evidence it *can* read, so
the rule needs an explicit exception, including when launches are allowed (e.g. not while the user
is playing).

### M3 — Vivify compile and export

Phase A of the approach doc: arrangement 0.2 `presentation` block, revision-aware `show.json` with
primitives (`setup`, `look`, `scene`, `skin`, `pulse`, `possess`, `env`, `path`, `raw`), compiler
merge into `customData`, `_requirements` and `_assetBundle` in `Info.dat`, bundles in the ZIP, the
validation set listed there, and a vanilla twin export for ArcViewer. EXSII files become parser
fixtures.

### M4 — Asset forge (Unity batchmode)

- VivifyTemplate-based Unity project in `sabermapper/assets/vivify-src/`.
- Agent writes an `assets.json` spec plus shader and editor-script sources; a C# builder creates
  materials, prefabs and particle systems; `sabermapper assets build` runs Unity `-batchmode` and
  returns the bundle, `bundleinfo.json` and the build CRC, or structured compile errors with file and
  line.
- Three tiers: (1) parametric library, (2) agent-written code assets (shaders, procedural meshes,
  particles), (3) optional generative media (textures and skyboxes from an image model, meshes from a
  text-to-3D model, decimated in Blender) with provenance recorded.
- Guardrails: single-pass-instanced stereo macros required, poly / draw-call / shader-cost budgets,
  lowercase asset paths.
- Every per-map asset worth keeping is generalized into the library with a `library.md` entry
  (intent, properties, safe ranges, a description in words).

### M5 — Listen and concept

- Analysis additions: lyrics with word timestamps (Whisper on the Demucs vocal stem), per-section
  mood descriptors (valence/arousal, timbre tags), and a **moments** list (drops, risers, silences,
  key changes, final chorus).
- Concept artifact per project: three candidate treatments (central idea, palette, 2–4 motifs and
  their development, at most three key moments, one held for the end, possession decision), scored
  on a rubric (grounded in this song, one strong idea, develops, readable while playing, buildable),
  one selected. The human can steer it in text before assets are built.
- Concept corpus: extend the EXSII write-ups with how each map's idea follows from its song.

### M6 — Ghost autoplay

The agent synthesizes a saber path from the arrangement (reusing `movement.py`); the bridge plays it
as autoplay. Used by *Watch* in the studio and by `game capture` so frames show sabers in motion.
Optional later: export as BeatLeader BSOR.

### M7 — Skill and first map

`sabermapper-map` (or a new `sabermapper-vivify` skill) gains the full loop: when to iterate, which
checks gate handover, how to read contact sheets and feedback notes. One vivified map built end to
end by the agent, verified by the user from the studio, revised from their notes.

## One-time setup the user must do

- Install and enable the mod stack for 1.45.1: SongCore, SiraUtil, BSML, CustomJSONData, Heck,
  Noodle Extensions, Chroma, Vivify (alongside SaberSiege).
- Install Unity 2021.3.16f1 and activate a Personal license (M4).
- Approve installing the .NET SDK (M0) and the Python packages for Whisper and mood models (M5).

## Decisions needed

- Agent-launched game runs for capture (M2): allowed, and under which conditions?
- Generative models (M4 tier 3, M5): run locally on the 5070 Ti or on RunPod?
- PCVR only (Windows 2021 bundle), or Quest too?

## Out of scope

Publishing to BeatSaver or LunarRepo; copying EXSII note arrays or bundle assets; any claim about VR
comfort or feel not backed by the user's own playtest.

## Risks

- Single-pass-instanced shaders may not render correctly in FPFC (checked in M0).
- Late-start event state in Heck/Vivify may make scrubbing inexact (checked in M0).
- Bridge must be rebuilt on game updates; pin the game version in `installed-game-target.json`.
- 2D captures do not show VR scale, comfort or performance; the human playtest remains ground truth.
