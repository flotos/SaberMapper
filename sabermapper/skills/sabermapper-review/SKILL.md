---
name: sabermapper-review
description: Review or revise a SaberMapper arrangement and exported Beat Saber map using exact artifacts, diagnostics, preview, and player feedback; use when the user asks for a map critique or change.
---

# Review a map

Read the exact arrangement, compiled map or ZIP, audio hash, diagnostics, review notes, and requested scope. If the user reports a problem, reproduce it in the file and identify a beat range and section. Read [review rubric](references/rubric.md) for the defect versus taste distinction.

Run `python -m sabermapper validate ARRANGEMENT.json` and inspect structural errors before evaluating flow. Compare notes with the checked audio grid and phrase intent. Assess both hands through entry, motion and exit; inspect sight lines, density, rests, repeated sections, obstacles, lights, and NJS in context. A fast same-hand warning is a prompt for review, not automatic permission to alter the pattern.

For a scoped edit, preserve locked sections and unrelated data. Save a new arrangement, compile to a new path, and compare object counts and the exact changed beat range. Export only if resolved and provided with a decodable local OGG Vorbis and valid cover. The local timeline/editor can support inspection, but only an actual user game playtest establishes feel and replay desire. State which stages were completed and what remains unverified.
