---
name: sabermapper-review
description: Review or revise a SaberMapper arrangement and exported Beat Saber map using exact artifacts, diagnostics and player feedback; use when the user asks for a map critique or change.
---

# Review a map

Read the exact arrangement, compiled map or ZIP, audio hash, diagnostics, review notes, and requested scope. If the user reports a problem, reproduce it in the file and identify a beat range and section. Read [review rubric](references/rubric.md) for the defect versus taste distinction.

Run `python -m sabermapper validate ARRANGEMENT.json` and inspect structural errors before evaluating flow. Compare notes with the checked audio grid and phrase intent. Assess both hands through entry, motion and exit; inspect sight lines, density, rests, repeated sections, obstacles, lights, and NJS in context. A movement warning is a prompt for review, not automatic permission to alter the pattern. Flow errors are different; they are a standing player rule. `fast_direction_break` fires when a same-hand cut 0.3 s or less after the previous one turns less than 135 degrees. `flow_parity_break` fires when consecutive same-hand swings without a full-beat reset turn less than 90 degrees or stay on the same forehand/backhand. Fix both kinds. When a player reports any awkward swing pair, generalize it rather than patching one spot. Reproduce the pair and check whether the model flags it. If it does not, extend `movement.flow_break` and its tests. Then run `project repair-swings ID --workspace workspace --revision REV` on every project, not only the reported one.

Audio is the focus of every review. Run `python -m sabermapper project critique ID --workspace workspace`; it uses the project's newest evidence run for the current audio. Treat `audio_unmapped` (the song plays but the map is empty, blocking from 8 s), `note_without_audio` and `low_audio_support` (notes with no sound under them) as defects to fix before judging patterns or flow. `audio_evidence_missing` means the map was never checked against the song; run `music analyze` first. `vocal_line_unmapped` and `drum_rhythm_unmapped` mean the notes miss the bar's salient layer (articulated singing, else the drum pattern while the voice holds). `focus_on_quiet_stem` means a focus phrase weights a stem that is absent there, as bleed or a mislabeled instrument. `difficulty_exceeds_intensity` (a soft bar as hard as the heavy passages) and `intensity_underplayed` (a heavy run easier than the soft passages) mean difficulty does not follow loudness; when a player says a map gets easier as the music gets heavier, read `metrics.intensity.bars` for the exact bars. These appear in `project get`/`project save` diagnostics as warnings; resolve or justify each. `project repair-audio ID --workspace workspace --revision REV` reweights focus phrases away from absent stems, moves or removes unsupported notes, thins quiet passages flagged `density_exceeds_audio` (thin, soft audio mapped as densely as the full band) rebuilds bars flagged `lead_rhythm_diluted` on the lead instrument's attacks, and maps the unmapped vocal, drum, lead, accent and density-collapse onsets it can place without a flow break. It then raises underplayed heavy runs (notes on their attacks, else wider swings) and eases soft bars over their allowance. Run it on every project when these findings appear, and review its `unresolved` list by hand.

For musical connection, inspect section `musical_focus` annotations and exact
`musical/RUN_ID/report.json` evidence. `python -m sabermapper music rhythm ID --workspace workspace --start A --end B`
prints per-bar attack grids per layer beside the mapped notes; use it when feedback says the pacing is regular or
misses an instrument. `python -m sabermapper music inspect ID
--workspace workspace --run RUN_ID --start BEAT --end BEAT` converts source events
to the current grid, including tempo changes. Check the declared lead's rhythm,
rests, intentional handoffs and ensemble accents against actual notes. Missing
layers, separator bleed and detector peaks are uncertainty, not proof of an
instrument event. Weights express agent intent, not automatic note generation.
Focus metadata is revision-aware and locked with its containing section.

For a scoped edit, preserve locked sections and unrelated data. Save a new arrangement, compile to a new path, and compare object counts and the exact changed beat range. Export only if resolved and provided with a decodable local OGG Vorbis and valid cover. Do not open ArcViewer, the studio or a browser preview unless the user asks; the user reviews saved revisions themselves, and a rendered view the agent cannot see is not a check. Only an actual user game playtest establishes feel and replay desire. State which stages were completed and what remains unverified.
