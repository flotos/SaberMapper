---
name: sabermapper-review
description: Review or revise a SaberMapper arrangement and exported Beat Saber map using exact artifacts, diagnostics, preview, and player feedback; use when the user asks for a map critique or change.
---

# Review a map

Read the exact arrangement, compiled map or ZIP, audio hash, diagnostics, review notes, and requested scope. If the user reports a problem, reproduce it in the file and identify a beat range and section. Read [review rubric](references/rubric.md) for the defect versus taste distinction.

Run `python -m sabermapper validate ARRANGEMENT.json` and inspect structural errors before evaluating flow. Compare notes with the checked audio grid and phrase intent. Assess both hands through entry, motion and exit; inspect sight lines, density, rests, repeated sections, obstacles, lights, and NJS in context. A fast same-hand warning is a prompt for review, not automatic permission to alter the pattern. A `fast_direction_break` error is different: a fast same-hand cut that does not reverse (turns less than 135 degrees within 0.2 s) cannot be hit, so fix it. When a player reports an unhittable pair, run `project repair-swings ID --workspace workspace --revision REV --dry-run` to find every instance in the project, not only the reported one.

For musical connection, inspect section `musical_focus` annotations and exact
`musical/RUN_ID/report.json` evidence. `python -m sabermapper music inspect ID
--workspace workspace --run RUN_ID --start BEAT --end BEAT` converts source events
to the current grid, including tempo changes. Check the declared lead's rhythm,
rests, intentional handoffs and ensemble accents against actual notes. Missing
layers, separator bleed and detector peaks are uncertainty, not proof of an
instrument event. Weights express agent intent, not automatic note generation.
Focus metadata is revision-aware and locked with its containing section.

For a scoped edit, preserve locked sections and unrelated data. Save a new arrangement, compile to a new path, and compare object counts and the exact changed beat range. Export only if resolved and provided with a decodable local OGG Vorbis and valid cover. The local timeline/editor can support inspection, but only an actual user game playtest establishes feel and replay desire. State which stages were completed and what remains unverified.
