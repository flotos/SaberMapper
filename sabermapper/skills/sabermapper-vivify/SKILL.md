---
name: sabermapper-vivify
description: Build, verify and refine a vivified (Vivify/Heck/Chroma) SaberMapper map end to end - listen, concept, custom assets, show choreography, compile, in-game capture under the game lease, frame review and handover - when the user asks for a vivified, Vivify, EXSII-style or "extra sensory" map, or feedback on one.
---

# Build a vivified map

A vivified map is one artistic piece: a note chart plus a scene choreographed to the same song. You own the whole loop; the user only verifies from the studio (Play in game, Watch, slider, Note) and gives feedback in text. Read `PLAYER.md`, `workspace/player-profile.json`, and the `sabermapper-map` skill first: the note chart follows every rule there (audio first, flow, player calibration). This skill adds the scene layer and the in-game verification loop. Background: `docs/vivify-approach.md`, `docs/references/extrasensory/README.md`, and the ticket `tickets/vivify/base-ticket.md`.

Run commands from `sabermapper/` with `.venv/Scripts/python -m sabermapper ... --workspace workspace`.

## The loop

```
listen -> concept -> forge assets -> choreograph (show) -> compile/export -> game capture
   ^                                                                            |
   +---- refine <---- critique <---- project verify (static + frames + game log) +
                                           | ready_for_human only
                                           v
                         handover: user verifies in the studio, leaves Notes
                         -> project feedback list -> next iteration
```

Iterate until `project verify` is `ready_for_human`, then hand over. Never hand over a revision that failed a check, and never open the studio, ArcViewer or a browser preview yourself.

### 1. Listen

1. `music analyze ID --backend ensemble` (stems; required for lyrics and mood). Read `musical/RUN/overview.png`.
2. `music listen ID` writes `moments.json` (drops, builds, breaks, key changes, final chorus, vocal entries, big hits) and per-section mood (valence/arousal, timbre tags; a heuristic, not a trained model).
3. `music lyrics ID` runs faster-whisper (large-v3, local GPU) on the vocal stem and writes `lyrics.json` with word timestamps. Words can be misheard; use them for meaning and for timing cues on clear words, and check a surprising word against the spectrogram before building an effect on it. `--from-file` imports an LRC or text sheet when the user supplies one.

### 2. Concept

1. `concept corpus` lists the ten EXSII reference treatments and how each idea follows from its song. Study the shape; never copy EXSII assets or event arrays.
2. `concept template ID` gives a skeleton pre-filled with moments, section mood and lyric lines. Write **three** candidate treatments: a central idea grounded in this song (lyrics, mood, structure), a palette, 2-4 motifs and how each develops per section, at most three key moments with **one held for the end**, and the possession decision (`none` by default; `player`/`head`/`hands` only when the idea needs it).
3. Score each candidate 1-5 on the rubric (grounded in this song, one strong idea, develops, readable while playing, buildable) with a one-line justification, select one, and `concept save ID --file F --revision none|CURRENT`.
4. Tell the user the selected treatment in a few sentences before building assets, so they can steer it in text. Record steering in the concept's `steering` field and save a new revision.

### 3. Design the look, then forge assets

The shaders carry the spectacle. EXSII maps ship 8 to 76 custom shaders each on mostly primitive meshes, and their screen effects are tiny: the effect comes from timing and a few semantic properties the events animate. Read [shader craft](references/shader-craft.md) before writing or restyling a shader or designing a section's look. It covers why things look good in the headset, the platform rules, the technique catalogue with its music handles, and VR cost. [What the EXSII shaders do](references/exsii-shaders.md) calibrates ambition with measured numbers. The [cookbook](references/shader-cookbook.md) holds the functions, and `templates/` holds five complete shaders that compile in the forge and render in the game: a raymarched set-piece, a procedural sky, a world-anchored full-screen effect, a custom note, and a stage surface for scene meshes.

Rules that hold for every shader:
- Stereo macros in every pass. Anchor patterns to world or view directions, never to screen UV.
- Alpha is bloom: 0 on skies, floors, walls and other large surfaces; glow only on small parts; blits pass `src.a` through.
- One to three semantic 0..1 handles per effect (`_Progress`, `_Pulse`, `_Warp`, `_Phase`, a seed). The show animates them from audio evidence, never from `_Time`.
- Keep the lane calm (dark, low contrast, low motion behind the notes). Large surfaces move on hits rather than brighten.
- A skybox needs `setup.camera_properties` `{"clearFlags": "Skybox"}` or it stays black (`skybox_not_cleared`).

1. `assets library` lists tier-1 shaders (post-process, skyboxes, emissive surfaces, particles) with typed properties, safe ranges and a description of how each looks. Compose the library for supporting layers.
2. `assets init ID`, edit `<project>/assets/assets.json`, then `assets lint ID`. Tier 2: write per-map shaders for the concept's central image, starting from the nearest template, plus mesh or particle generators as needed. Every shader must pass the single-pass-instanced stereo lint. Tier 3 (generated textures/meshes) returns `generator_unavailable` until a local model is set up.
3. `assets build ID` runs Unity batchmode and writes `<project>/assets/bundleinfo.json` and `bundleWindows2021.vivify`. If it returns `unity_missing`, tell the user the one-time install in its `fix`; you can still write and validate the show, but export and capture need the bundle.
4. When a per-map asset is worth keeping, `assets promote ID ASSET` and fill its library entry.

### 4. Choreograph the show

1. Add arrangement `0.2` `presentation`: map-level concept, palette, possession; per section a `family` (`post_process`, `scene`, `none`), an `attention` budget and `note_style`. For this player the default is a dense plain chart with the scene carrying the spectacle, and one or two density troughs where set-pieces land.
2. Write `show.json` with the primitives in `docs/vivify-show.md` (`setup`, `look`, `scene`, `skin`, `pulse`, `possess`, `env`, `path`, `raw`). Bind every pulse to evidence with a driver (`onsets` by layer/detector, `sustains`, `moments`, `lyrics` words); put an `anchor` on hand-placed keyframes. A visual event with no evidence under it is a `visual_without_evidence` warning; treat it like a note without audio.
3. Structure follows a reveal: setup at beat 0, discrete changes at section boundaries, the densest scene work in the final section, the held key moment last. Quiet passages get colour drift, not flashes. Pair every spawn with a destroy. Sight-readable first: cut any visual that only works once the player knows it is coming.
4. Lessons from the first vivified map (Ko Phangan, 2026-09-23), each seen in game captures:
   - **Large surfaces move on the beat; they do not brighten.** A kick pulse that brightens a grass wall or canopy filling the frame trips the photosensitivity limit (`flash_rate_exceeded`). Bend, sway or scale big geometry on the beat, and keep brightness pulses to small objects (the sun core, a trail rim).
   - **Keep what must be seen in a clear lane.** The note corridor covers roughly x = ±1.2 m in front of the player, and foliage near the track hides small objects. Put creatures and set-pieces between the trail edge and the plants (about x = ±1.9 to ±3 m, z = 4 to 5 m), or give them a glowing background to stand out against. Check a full-resolution crop of the frame, not only the contact sheet, before deciding something is missing.
   - **Distant geometry dissolves instead of fading to black.** Opaque plants faded to black still hide what is behind them, such as a sun at the end of the path. Use a dithered `clip` on distance.
   - **Colour the notes with the concept.** Use `presentation.note_colors` (Info.dat colour scheme plus Chroma colours). If the arrow needs its own colour, add a note skin (`skin` primitive with `colorNotes.asset`/`anyDirectionAsset` prefabs). Vivify passes the note colour per instance in `_Color` (and `_Cutout`), so one shader can tell the two hands apart.
   - **Scale and position given at instantiation work**, but a sun quad only fills the part its shader draws. Judge size from captures, not from arithmetic on the quad.
   Lessons from the shader-template captures (2026-09-23):
   - **Large surfaces write alpha 0.** A floor with a rim alpha of about 0.2 turned near-white for four frames every time an additive object pulsed. With alpha 0 it held steady.
   - **Fresnel rim stays off floors and walls.** At grazing angles a flat plane is all rim and lights up across its whole surface.
   - **Set-pieces face the player.** A horizontal ring above the track reads as a flat ellipse.
   - **Give stars a brightness spread.** Equal-brightness stars read as snow.
5. `show validate ID`, fix every error, then `show save ID --show F --revision none|CURRENT`. Save the arrangement with `project save` as usual.

### 5. Compile, export, capture

1. `project export ID` writes the full ZIP plus a `-vanilla.zip` twin for ArcViewer. Export fails on show errors and a missing bundle.
2. `game capture ID [--difficulty D]` is the only way you open the game. It takes the machine-wide game lease, launches Beat Saber in FPFC, installs the current revision into `CustomWIPLevels/SaberMapper-ID`, plays it (from 0 for Vivify maps so all earlier events apply), captures frames at every section boundary, key moment and every 16 beats plus a 3 s dense probe for the flash check (notes are hidden for the whole probe window and come back once afterwards, since uncut notes fly through the capture camera and read as flashes a player never sees), then closes the game and releases the lease. Add `--probe START-END@30` over the brightest or fastest-pulsing passage; `--no-hud` for clean frames.
   - `game_busy`: another agent or the user holds the game. Retry later or pass `--wait SECONDS`; never close a game you did not launch.
   - `game_preempted`: the user took the game. Retry later; it is never a map defect.
3. `frames sheet CAPTURE_DIR` writes one labelled contact sheet per section. **Read every sheet** with your file-reading tool and compare it with the concept: is the idea visible, does each section look different where the concept says it should, are notes readable against the scene, is the held moment actually held back? Open full-resolution frames for detail. When a large area might pulse, measure its mean brightness across the probe frames. A jump between neighbouring frames is a flash even when no event targets that surface.
4. `game logs --level PATH` (also stored in `capture.json`) lists Vivify/Heck/Chroma errors such as bundle checksum mismatches, missing materials or custom-data parse errors.

### 6. Verify, then hand over

`project verify ID [--difficulty D] --record` runs structure, audio, show, capture, frame metrics (photosensitivity flash rate, note-corridor contrast, palette drift, boundary changes) and game-log checks on the current revision. Exit code 0 and `ready_for_human: true` are required before a handover. Fix everything in `blocking` (its `next` list says what), re-capture, and verify again. A flash-rate error is a hard stop: slow the effect below 3 flashes per second or shrink its area.

When ready, tell the user the project, the revision, the checks that ran (`ran`) and what was skipped (`skipped`), the selected concept in two sentences, and that they can verify it from the studio: pick the revision, press Play in game (or Play at playhead), scrub with the slider, and press Note at any moment to leave feedback.

### 7. Feedback

`project feedback list ID` returns the user's timestamped notes with song time, beat, section and revision (`stale: true` when about an older revision). Map each note to the concept, show primitive or notes at that time, revise, and run the loop again from the step it touches. A reusable preference goes into the player profile. A visual defect that could recur in another map becomes a check, a pipeline correction or a skill rule with a regression test, rerun on every vivified project (Systematic fixes in `AGENTS.md`).

## Honesty

Captures are 2D desktop frames. They do not show VR scale, comfort, performance or how a visual feels at speed; say so, and never claim a playtest. Do not assign a star rating. State which references and assumptions guided the concept and the chart.
