# One-song evaluation and revision protocol

Before generating, freeze the exact audio SHA-256, source/decoded duration, BPM, positive phase offset, arrangement schema, assistant/model version, prompt and skill versions, compiler/export commit, target game/editor build, review time budget, and the question: **would the intended player replay this map?** A human reference of the same song stays hidden from the assistant until its arrangement and revision are saved.

For each arm, retain source arrangement, compiled beatmap, ZIP hash, validation diagnostics, audio provenance, settings/seed, authoring minutes, editing minutes and all exceptions. Start with a simple rules/manual arm and the independently assistant-authored arm. Include BeatForge only after the read-only audit's controlled baseline prerequisites are met. Optional corpus/ranker arms need a song-family holdout; never retrieve or train on the evaluation song or its human note arrays.

Run the mechanical pass first: JSON and asset integrity, decoded audio length, exact alignment at start/middle/end, note counts, collisions, rapid same-hand concerns, NJS, visibility, and basic light events. Then inspect in ArcViewer/editor and play in the exact game build. Record the actual human observation; a structurally valid ZIP is not a successful playtest.

The player rates enjoyment, technical interest, musical fit, readability, repetition, fatigue, and replay desire on 1–5 scales and gives beat-ranged notes. Balance or conceal arm order when practical; record prior song/map familiarity and when labels were revealed. Ask for one concrete scoped revision, preserve before/after artifacts, and replay the changed section and whole map. Capture whether the edit helped and the minutes it cost. The result is go, revise hypothesis, or stop, with reasons and unresolved faults.

A single player and one or a few tracks support a personal qualitative decision. Do not report a population improvement or call a higher note count better mapping. Report technical faults and enjoyment separately, and include failures. The actual user playtest, target build, and song-specific success decision remain to be collected.
