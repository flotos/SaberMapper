# SaberMapper Studio

A local Beat Saber mapping studio with audio analysis, arrangement authoring, visual review, corpus research and deterministic export. The application makes no LLM calls and never launches an assistant.

## Open the app

Double-click **Start-SaberMapper.cmd**, or run:

```powershell
.\Start-SaberMapper.ps1
```

The studio opens at **http://127.0.0.1:8765**. An original 48-second demo and the measured reference corpus are available in the current workspace. Choose **Import a track** for your own WAV, OGG, MP3 or FLAC file. Play the audio, correct timing, edit sections, record feedback and export a map ZIP. Select **3D preview** to open the saved map in the locally hosted ArcViewer at the current playhead. On a fresh checkout, run `scripts/install_arcviewer.ps1` once; see [local preview setup](docs/arcviewer-local.md).

For a fresh checkout, install Python 3.11 or later and run `setup.ps1` first. Runtime work is local; only explicitly invoked corpus downloads contact BeatSaver. The first setup installs Python packages.

## Optional Tidal downloader

Install the pinned local downloader with `.venv/Scripts/python -m pip install -e ".[tidal]"`.
From this directory, run:

```powershell
.\Tidal.ps1 auth login
.\Tidal.ps1 download url "https://tidal.com/browse/track/TRACK_ID"
```

Complete the login yourself using the instructions shown. The launcher keeps settings,
authentication and downloads under ignored `workspace/tidal/` and supplies the project's
bundled FFmpeg. Downloads go to `workspace/tidal/downloads/`; the default quality is
`high` (CD-quality FLAC when available). Import the resulting file into the studio.
SaberMapper exports OGG Vorbis for Beat Saber. Tiddl is an unofficial external service
client; installation does not verify account authentication or track availability.

## What is implemented


- Persistent projects, waveform playback, zoomable beat/lane timeline, direction preview, range selection and SVG snapshots.
- Audio conversion with exact hashes, tempo and phase hypotheses, editable timing, energy/onset/rest and recurrence reports.
- Stable JSON arrangements, literal notes and motifs, five Standard difficulty labels, bombs, walls, arcs, chains and native tempo events.
- Shared movement estimates, structural diagnostics, section locks, conflict-safe revisions, feedback files and a playtest journal.
- v2/v3 map parsing, bounded exact-version ingestion, resumable corpus processing, pattern extraction/grouping/retrieval, family splits and explicit preference labels.
- An optional local pairwise ranker with held-out evaluation and a no-go result when evidence is inadequate.
- Portable mapping, research and review skills; deterministic ZIPs with decoded OGG Vorbis audio, cover art and basic lighting.

All 31 tickets have implementation/evidence entries in [the coverage record](docs/ticket-coverage.json). Research judgments and physical acceptance tests are not inferred from working software: actual in-game timing, player comfort and replay interest require a playtest. v4 parsing, automatic variable-tempo tracking, stems, modcharts and a custom 3D renderer remain outside the supported scope described in the tickets.

## Commands and verification

```powershell
.venv/Scripts/python -m sabermapper --help
.venv/Scripts/python -m sabermapper demo --workspace workspace
.venv/Scripts/python -m sabermapper serve --workspace workspace --port 8765
.venv/Scripts/python -m unittest discover -s tests -v
```

For browser tests, run `setup.ps1 -Development`, then `.venv/Scripts/python -m playwright install chromium` and `.venv/Scripts/python tests/browser_workflow.py`.

Projects live in `workspace/projects/<id>/`; archives, manifests and pattern data live in `workspace/corpus/`. Each project preserves its original arrangement, saved versions, feedback, review records, analysis and exports. Back up the workspace directory before moving or deleting projects.

- [User guide](docs/user-guide.md)
- [Supported features and limitations](docs/supported-features.md)
- [Architecture and artifact boundaries](docs/architecture.md)
- [Corpus method and measured run](docs/corpus-research.md)
- [Mapping knowledge](docs/mapping-knowledge.md)
- [Evaluation protocol](docs/evaluation-protocol.md)
- [External reference audit](docs/external-audit.md)
- [Planning tickets](planning/README.md)

The external reference in `../external-ideas-dont-trust/` was audited read-only. It is not imported, executed or distributed as part of this app. No corpus audio is published by these tools.
