# Use SaberMapper locally

SaberMapper works on local files. An independently invoked assistant can author the JSON arrangement; the Python program does not contact an LLM. Start in the project directory and use the environment created by the setup script, or activate `.venv` and run `python -m sabermapper --help` to see the commands in your installed version. On Windows PowerShell, `./.venv/Scripts/python` can replace `python` below.

## Try the original demo

The generated 48-second demonstration is original synthesized audio with three progressively fuller sections. It is useful for checking the local workflow without obtaining a song or cover. Run `python -m sabermapper demo --workspace workspace`; it creates a saved local project and prints its ID. `python -m sabermapper project get ID --workspace workspace` inspects it. The demo demonstrates software integration, not whether the player enjoys the generated map.

## Prepare a real song

Choose a locally available WAV, FLAC, OGG or MP3 that you can use for this purpose. Record the source path and SHA-256, manually enter title and artist, and inspect decoded duration and waveform. `sabermapper.audio.inspect_audio(path)` returns a local identity record without guessing tags from the filename. `analyze_audio(path, bpm=..., offset_seconds=...)` provides onset, energy, tempo and section candidates. Review BPM, beat-zero phase and a bar anchor against the exact audio near its start, middle and end. The proposed half/double tempo alternatives are prompts to listen, not verified answers. Encode a new Vorbis file with `prepare_audio(source, destination)` if needed; it records both hashes and checks decoded duration/onset shift. Retain the original audio and conversion record.

The CLI can create a real project with `python -m sabermapper import-audio TRACK --workspace workspace --title TITLE --artist ARTIST --bpm BPM`; title/artist may be entered later. Importing audio whose exact source bytes already belong to a project is refused with the existing project ID (continue that project instead); pass `--allow-duplicate` only for a deliberate second copy. Mis-encoded title/artist text such as `FumÃ©e` is repaired to UTF-8 on import. The studio sidebar groups projects as artist / album / song, alphabetically, with each song's last-update time (month/day hh:mm); the album comes from `--album`, else the file's album tag, else an `Artist/Album/` source folder. Change it later with `python -m sabermapper project set-album ID --workspace workspace --album NAME` (an empty name restores the derived album). For an analysis JSON without creating a project, run `python -m sabermapper analyze TRACK --bpm BPM --offset SECONDS --output report.json`. Use `python -m sabermapper serve --workspace workspace --port 8765` for the local browser review UI, then browse the displayed localhost address. The UI is a 2D review surface and does not replace editor or game playback. Projects keep arrangement revisions, locks and feedback in the selected workspace. Back up that workspace along with exact source audio and art.

## Author, validate and export

For instrument-led phrasing and whole-mix accents, the agent uses `music backends`,
`music analyze` (with `--from-run RUN_ID` to re-analyze existing stems), `music list`, `music inspect`,
and `music rhythm` (per-bar attack grids per layer beside the mapped notes). The studio's **Music layers**
panel is an optional agent-operated inspection surface. See [musical analysis and agent composition](musical-analysis.md)
for separation options, phrase focus weights, and listening controls. Codex or
Claude Code authors the rhythms and movements from this evidence.

The arrangement schema is summarized in the bundled [map skill](../skills/sabermapper-map/SKILL.md). It names song BPM/offset, one difficulty, reusable motifs, and ordered sections with stable IDs. A section can be marked unresolved while timing or its transition is uncertain; compilation will then fail until it is reviewed. Keep locked sections intact during an assistant edit.

```powershell
python -m sabermapper validate arrangement.json
python -m sabermapper compile arrangement.json --output Expert.dat
python -m sabermapper export arrangement.json --audio track.ogg --cover cover.png --output map.zip
```

`validate` prints JSON diagnostics and exits nonzero for hard errors. `compile` writes Beat Saber v3.3 difficulty data. `export` writes a ZIP with Info.dat, the difficulty, song audio, cover and `SaberMapper-report.json`. Each output path must be new. Audio must decode as OGG Vorbis and the final gameplay object must fit inside decoded duration. PNG or JPEG covers are accepted. A positive `audio_offset_seconds` shifts exported object beats while Info.dat stays at zero offset. It does not edit the source audio. Keep the compatibility report and exact ZIP hash with your project record.

Arcs and chains must be connected. `validate` reports a hard error when an arc has no color note at its head or tail, or a chain none at its head, matching the same beat, lane, row, colour and cut direction (`arc_head_without_note`, `arc_tail_without_note`, `chain_head_without_note`, plus `*_direction_mismatch` when a note is there with a different direction). An unconnected arc would export as a cosmetic curve rather than a held note.

For a scoped change, give the assistant the report, relevant reviewed phrases, the current arrangement, and the player's beat-ranged feedback. Save a new arrangement/ZIP and compare the changed section while preserving unrelated sections and locks. The [review skill](../skills/sabermapper-review/SKILL.md) has a defect-versus-taste rubric. Use the [research skill](../skills/sabermapper-research/SKILL.md) only when collecting external mapping references or phrases.

For a saved project, get its current revision with `project get ID --workspace workspace`, then save an edited JSON file with `project save ID --workspace workspace --revision CURRENT_SHA --arrangement EDITED.json`. `project export ID --workspace workspace` creates a ZIP with a new filename. `feedback ID --workspace workspace --start BEAT --end BEAT --text "..." --revision CURRENT_SHA` records a beat-ranged instruction for the assistant. After a real playtest, `project review ID --workspace workspace --revision CURRENT_SHA --playtested --game-build BUILD --notes "..." --minutes NUMBER --decision revise` records the observation. A `go` decision requires an actual recorded game playtest; do not mark an automated QA observation as user feedback.

`project critique ID --workspace workspace` checks the saved arrangement against the project's newest musical evidence run. Its density, salience and accent warnings include the absolute `beats` range they refer to. `project repair-audio ID --workspace workspace --revision CURRENT_SHA [--dry-run] [--output REPORT.json]` fixes the mechanical audio findings. Notes with no onset under them move to the nearest onset within half a beat, or are removed when no onset is in reach. Quiet passages flagged `density_exceeds_audio` (low mix energy and few drum hits, yet mapped as densely as the full band) lose their weakest-supported, most crowded note times until they fit. Unmapped vocal, drum, section-accent and density-collapse onsets then get notes that add no flow break. The report lists every change, the onsets it could not place (`unresolved`) and the critique warnings that remain.

`project repair-visibility ID --workspace workspace --revision CURRENT_SHA [--dry-run]` fixes blocking `hidden_note` findings. These are notes that arrive in the same cell as the note just in front of them, under 0.35 s later in the centre middle/top cells or under 0.2 s later elsewhere, so the front note hides them. It moves one note of each pair to a free cell nearby, without changing timing or direction; arc anchors follow. It removes the weaker note only when no cell is free. `project repair-swings` fixes the blocking flow findings the same way. Run both before `repair-audio`, which refuses to run while blocking findings remain.

To make the bundled skills discoverable in Codex from this repository, run `python scripts/install_skills.py`. It copies all three complete directories into workspace-root `.agents/skills/` for Codex and `.claude/skills/` for Claude. Root `AGENTS.md` and `CLAUDE.md` provide the shared project overview. Use `--update` to refresh existing copies after edits. You can then invoke `$sabermapper-map`, `$sabermapper-research`, or `$sabermapper-review` explicitly. Codex's [official skill documentation](https://developers.openai.com/es-419/docs/build-skills) describes repository and user discovery locations; restart Codex if a newly copied skill is not shown.

## Inspect and playtest

Preview the ZIP in a compatible editor or ArcViewer, then import it into the exact Beat Saber build you intend to use. Check the opening, middle and ending against audio, note visibility, movement, lighting, and the player's comfort. Record game/editor version, mods, artifacts, editing time, problems and whether the player wants to replay the map. Make one scoped revision and repeat the playtest. A successful validator or ZIP export is not evidence of in-game compatibility or enjoyment. [The evaluation protocol](evaluation-protocol.md) gives a compact comparison record.

## Corpus and learning tools

The local corpus path can import a map ZIP, fetch an exact BeatSaver version when requested, parse maps, group/retrieve phrases, freeze song-family splits and store human preference labels. Use `python -m sabermapper corpus status --workspace workspace` to see the local store. `corpus import ARCHIVE --hash VERSION_HASH --workspace workspace` imports a local archive; `corpus fetch VERSION_HASH --workspace workspace` explicitly fetches an exact BeatSaver version; `corpus process --workspace workspace` extracts patterns; and `corpus retrieve --workspace workspace --bpm 120 --nps 4.5 --limit 20` lists nearby phrases. `corpus batch SEEDS.json` applies the stated budget in the seed file; `corpus cleanup VERSION_HASH` removes a retained archive after processing. Use `--help` on each leaf before a broader run.

For local evaluation records, `profile calibrate SNAPSHOT.json`, `profile feedback RECORD.json`, `splits freeze RECORDS.json --output FROZEN.json`, and `labels add RECORD.json` record provenance and grouping. `labels report` summarizes the stored labels; `labels train --dimension DIMENSION` trains only if its held-out checks and minimum sample gates pass. `parse-map MAP --bpm BPM --output IR.json` normalizes a supported v2/v3 map. These research steps do not automatically author a full map. Use exact source provenance and keep third-party audio and map rights visible. A small local ranker is optional and should only be used after held-out evaluation. Its scores are not a substitute for the intended player's review.

The current [feature list](supported-features.md) distinguishes implemented local behavior from unresolved game and user checks. The project performs no automatic publishing or audio redistribution.

The original demo ZIP and a separate [assistant-authored study](authored-study.md) were loaded in ArcViewer's browser preview. Their screenshots and exact ZIP hashes document preview import only; the intended player's VR playtest remains open.
