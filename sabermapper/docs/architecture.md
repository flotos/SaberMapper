# SaberMapper implementation map

SaberMapper is a local Python application. The user invokes an assistant independently to write or revise a JSON arrangement; the app does not call an LLM. The browser UI served from localhost edits saved projects, draws a 2D review timeline, and can play local project audio. JSON arrangements remain the inspectable source of truth for game export.

```text
local audio -> audio/timing/structure report -> project + checked timing
                                          -> assistant-authored arrangement
                                          -> validation -> v3 compiler -> OGG ZIP
                                          -> local preview -> editor/game review
BeatSaver/local map ZIP -> safe corpus store -> map parser -> pattern retrieval
feedback/labels -> split registry -> optional local ranker evaluation
```

`audio.py` decodes WAV/OGG/MP3/FLAC locally, hashes exact bytes, analyzes waveform/onsets, prepares Vorbis, and creates an original demo. `timing.py` provides a constant BPM grid and hypotheses; `structure.py` offers unlabeled section, energy and recurrence candidates. Automated timing does not infer meter or verify a song's identity. The user must review BPM, phase, downbeat and section names. `projects.py` stores revisioned arrangements, locks and feedback in a workspace. `server.py` serves the local UI and project operations.

`arrangement.py` expands motifs and compiles supported notes, bombs, obstacles, arcs, chains and tempo events to Beat Saber v3.3 JSON. `validation.py` blocks structural faults and reports contextual warnings. `movement.py` computes review features rather than deciding whether a map is fun. `export.py` writes a deterministic ZIP with v2 Info.dat, one Standard difficulty, decodable Vorbis, cover and compatibility report. Positive audio offsets are baked into exported beats; no source audio is silently trimmed.

`corpus.py` imports a local Beat Saber ZIP or fetches an exact BeatSaver version when explicitly requested, bounds archive expansion and stores provenance. `mapio.py` parses supported Beat Saber schemas into a normalized form. `patterns.py` groups and retrieves phrases; `evaluation.py` freezes song-family splits; `learning.py` trains an optional small local preference ranker only from labelled, permitted families. Those research tools do not generate a complete map by themselves. `profile.py` records dated profile evidence.

The current playback surface is a 2D local preview, not a game simulation. An exported ZIP must still be checked in a compatible editor and the user's exact Beat Saber build. The original demo and synthetic fixtures demonstrate software flow only; they are not a personal playtest or a quality result.
