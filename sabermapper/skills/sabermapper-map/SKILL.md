---
name: sabermapper-map
description: Author or revise a SaberMapper JSON Beat Saber arrangement using local audio analysis, player calibration and reference phrases when the user requests map composition or a scoped edit.
---

# Author or revise a map

In this repository, read workspace-root `PLAYER.md` and the app workspace's `player-profile.json` before choosing difficulty or patterns. Use the documented player's calibration by default, unless the user specifies another player. Expert/ExpertPlus are output labels, not skill estimates. New explicit preferences and actual playtest feedback take priority over historical scores. State the reference-based target briefly; do not claim a generated map has an official star rating. When this skill is used outside this repository, use the supplied player profile instead.

Read the available song report, exact audio hash, phrase examples with provenance, player preferences, and any existing arrangement. The app does not call an LLM; the assistant authors JSON using its own tools. A user-checked report is useful evidence, not a prerequisite for starting or completing a provisional map.

## Establish timing from available audio

Work from the application directory (`sabermapper/` in this repository); on Windows use `.venv/Scripts/python` in place of `python`. Locate the requested track in existing projects (`python -m sabermapper project list --workspace workspace`, then `project get ID --workspace workspace`), the local tracklist and workspace audio before asking the user for files or timing. Preserve original audio and source provenance. Use `import-audio --help` for a new project and `python -m sabermapper analyze TRACK --output REPORT.json` for an analysis report; BPM and offset are optional estimates, not information the user must supply. The implementation is in `sabermapper/audio.py` and `sabermapper/timing.py`.

Use onset, energy, tempo alternatives and recurrence candidates to investigate BPM, beat-zero phase and phrase boundaries. Compare plausible half/double tempos and inspect grid-to-onset alignment in separated passages near the start, middle and end; check phase consistency and cumulative drift, not just the global estimator score. Rerun analysis with `--bpm BPM --offset SECONDS` when testing a hypothesis. Supplied BPM produces the report status `reviewed_bpm`; that label alone does not establish human review. If the report is inconclusive, inspect the decoded signal or local analysis helpers before asking the user. Derive provisional section labels from evidence and distinguish inference from listening.

Record the selected timing, exact audio hash, passages checked, method and remaining uncertainty in the project notes or a companion evidence artifact. The analyzer does not establish meter or a bar/downbeat anchor; document any inference separately from its beat-phase estimate. Automated agreement can justify drafting and a provisional export without human timing confirmation. Report fields such as `manual_review_required` describe outstanding human review; do not treat them as blanket permission gates. Preserve human-review flags such as `timing_reviewed` and `playtested` as false until that review actually occurs. Keep a section `resolved: false` while a material timing or authoring ambiguity remains; set it true when the available evidence supports the chosen arrangement, without implying that it was human-reviewed. Never clear it merely to bypass compilation. Ask one specific question only when a blocking ambiguity remains after available analysis, explaining the competing choices and affected passage.

## Author, save and export

For real-song composition or revisions to musical connection, read
[musical focus and evidence](references/musical-focus.md). Use the
local `music` tools to gather complementary evidence, then author phrase focus,
rhythm and movement yourself. The application never delegates composition to an
internal model or converts detector peaks to patterns. Prefer musical events and
rests over stock-pattern density when deciding the rhythm of a phrase.

Read [held notes](references/held-notes.md) before authoring. Held or intense
vocals are the focus of their window and get arcs per that page, with the color
notes that connect them at the head and tail. In low-intensity passages follow
the quiet-passage policy in [musical focus and evidence](references/musical-focus.md).

Read [arrangement contract](references/arrangement.md) before writing. Give each section a musical intent and stable IDs. Use motifs for recognizable recurring phrases and literal notes for a deliberate local change. Consider entry posture, intended motion, exit and recovery. Do not flatten unusual rotations or repetition merely because a heuristic warned; inspect context and ask how the player experienced it. Keep target source-map note arrays hidden until the authored map is frozen for comparison.

For a requested revision, inspect the current file and exact feedback artifact first. Change only the requested unlocked section or shared motif when the requested scope warrants it. Preserve other IDs and `locked: true` sections. For projects, save with `python -m sabermapper project save ID --workspace workspace --revision CURRENT_SHA --arrangement EDITED.json`, rather than overwriting stored project files. If the revision conflicts, reread and reconcile with the current content rather than replacing it with an old draft. For standalone arrangements, save a new artifact or show a clear diff.

Run `python -m sabermapper validate ARRANGEMENT.json`, then `python -m sabermapper compile ARRANGEMENT.json --output NEW_FILE.dat`. Fix hard diagnostics. Every same-hand cut that follows the previous one by less than 0.2 s must turn at least 135 degrees (a reversal). The validator blocks save and export with `fast_direction_break` otherwise. The usual cause is a 16th pickup running into a sideways cut that opens the next phrase; check these seams when you compose. `python -m sabermapper project repair-swings ID --workspace workspace --revision REV [--dry-run]` removes the weaker pickup or re-angles the later cut, and leaves arc/chain anchors, locked sections and motif notes alone. After saving a resolved project, export with `python -m sabermapper project export ID --workspace workspace`. For standalone arrangements, use `python -m sabermapper export ARRANGEMENT.json --audio TRACK.ogg --cover COVER.png --output NEW_MAP.zip`. Check audio identity, duration and cover validity; human review is not required to produce a provisional local ZIP. Standalone output files are created exclusively; choose a new name for each iteration. A clean validator is a structural check, not a playability judgment. Record authored, validated, compiled, previewed and playtested status separately.

Inspect the ZIP in an available editor or ArcViewer and report exactly what was checked. Deliver the provisional artifact with remaining human timing and VR review clearly identified; do not stop the authorized local work merely because the user has not played it. When player feedback becomes available, save the exact verdict and use it for a scoped revision. Never claim listening, human approval or a game playtest from signal analysis, a synthetic result or local preview playback.
