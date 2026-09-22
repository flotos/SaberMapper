---
name: sabermapper-map
description: Author or revise a SaberMapper JSON Beat Saber arrangement from a checked song report and reviewed phrase examples when the user requests map composition or a scoped edit.
---

# Author or revise a map

In this repository, read workspace-root `PLAYER.md` and the app workspace's `player-profile.json` before choosing difficulty or patterns. Use the documented player's calibration by default, unless the user specifies another player. Expert/ExpertPlus are output labels, not skill estimates. New explicit preferences and actual playtest feedback take priority over historical scores. State the reference-based target briefly; do not claim a generated map has an official star rating. When this skill is used outside this repository, use the supplied player profile instead.

Read the user's checked song report, exact audio hash, phrase examples with provenance, player preferences, and any existing arrangement. The app does not call an LLM; the assistant edits JSON files through its own file tools. A detected BPM or section label is a candidate until the user checks the exact audio. Ask for a timing check only if the missing anchor blocks a safe export; keep an uncertain section `resolved: false` during drafting.

Read [arrangement contract](references/arrangement.md) before writing. Give each section a musical intent and stable IDs. Use motifs for recognizable recurring phrases and literal notes for a deliberate local change. Consider entry posture, intended motion, exit and recovery. Do not flatten unusual rotations or repetition merely because a heuristic warned; inspect context and ask how the player experienced it. Keep target source-map note arrays hidden until the authored map is frozen for comparison.

For a requested revision, inspect the current file and exact feedback artifact first. Change only the requested unlocked section or shared motif when the requested scope warrants it. Preserve other IDs and `locked: true` sections. Save a new artifact or show a clear diff. If the file changed concurrently, reconcile with its current content rather than replacing it with an old draft.

From a SaberMapper project directory, run `python -m sabermapper validate ARRANGEMENT.json`, then `python -m sabermapper compile ARRANGEMENT.json --output NEW_FILE.dat`. Fix hard diagnostics. Export with `python -m sabermapper export ARRANGEMENT.json --audio TRACK.ogg --cover COVER.png --output NEW_MAP.zip` only after the arrangement is resolved and the audio and cover are reviewed. Output files are created exclusively; choose a new name for each iteration. A clean validator is a structural check, not a playability judgment. Record authored, validated, compiled, previewed and playtested status separately.

For a real song, inspect the ZIP in the chosen editor and game, check timing near start, middle and end, then request one concrete scoped change. Save both versions and the player's replay verdict. Never claim a game playtest from a synthetic or local command result.
