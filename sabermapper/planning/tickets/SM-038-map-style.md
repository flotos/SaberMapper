# SM-038: Each song's map has a style of its own, decided before drafting

Status: Implemented (2026-09-23) · applied to Living a Lie; the other projects report `style_missing`.
Phase: Productize.
Size: M.
Dependencies: SM-036 (placer and rhythm draft), SM-037 (recurring themes), SM-032-034 (listen and concept).
Raised: 2026-09-23, from the user's request that the agent, when starting the map skill, "brainstorm and decide on the style of the map according to its style, spectrogram, song name, etc".

## Problem

The map skill went from calibration straight to timing, drafting and placement. The placer chose every hand, cut and cell by fixed costs, so every song came out in the same mechanical style. The only concept step (`concept`) served Vivify visuals.

## Behaviour

- **Style brainstorm** (`style template|validate|save|get`, `style.py`): the template gathers the song's title and artist, tempo, the stems that carry it, the overview image, mood, moments, lyrics, themes, the current map's measured style and the other songs' styles. The agent writes three candidates (idea, grounding, six settings, signature moves tied to themes), scores them on a rubric and selects one. Saving is revision-aware with history, and returns the `style` block for the arrangements.
- **Settings the tools read**: placement reads `flow` (turn target and weight, repeated-angle cost, travel), `diagonals` (diagonal cut cost) and `top_row` (target share and costs); the rhythm draft reads `arcs` (held-length scale), `accents` (doubles per loud bar) and `theme_variation` (echo mirroring). Middle values reproduce the previous behaviour exactly. Every setting is a comfort cost or a draft parameter, never a rule.
- **`project check`**: `style_missing` and `style_drift` (flow, diagonals and top row measured against bands calibrated on four workspace songs), both warnings; `metrics.style` shows the declared and measured style.
- **Validation**: a malformed `style` block is `invalid_style`.
- **Skills**: `sabermapper-map` adds "Decide the map's style before drafting"; `sabermapper-review` explains both findings.

## Out of scope

Style knobs for density (the target tier and loudness keep it), NJS, lighting, and any setting that would relax a movement rule.

## Evidence

Tests: `tests/test_style.py`. On four workspace songs placed from scratch, round flow turns 1-10 degrees against 21-24 by default and 42-45 angular; few diagonals 23-27% against 45-50% and many 58-84%; a low top row 8-11% against 18-21% and a high one 25-26%; no setting broke a rule.
