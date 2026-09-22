# Arrangement 0.1 quick contract

Top level: `schema_version: "0.1"`, `song`, `difficulty`, `motifs`, `sections`; optional `tempo_events`. `song` has nonempty `title`, `artist`, positive `bpm`, and finite nonnegative `audio_offset_seconds`. `difficulty` has a built-in name and matching rank (Easy/1, Normal/3, Hard/5, Expert/7, ExpertPlus/9), positive `njs`, and finite `spawn_offset_beats`.

`sections` have stable `id`, absolute `start_beat`, positive `length_beats`, nonempty `intent`, boolean `locked` and `resolved`, local literal `notes`, and `patterns`. Every note has `id`, local `beat`, `x` in 0–3, `y` in 0–2, `color` 0 red or 1 blue, and `direction` 0–8 (8 is dot). A pattern has `id`, `motif`, local `start_beat`, and optional boolean `mirror`. A motif maps an ID to local notes. Beats may be numbers or rational strings such as `"3/4"`. Pattern and literal notes must expand inside their section; no two notes may occupy the same beat and cell.

Optional section arrays `bombs`, `obstacles`, `arcs`, `chains` and top-level `tempo_events` are supported by the compiler. Consult `python -m sabermapper validate` and repository code for exact object fields when using these advanced objects, because unsupported fields fail closed. A section with `resolved: false` blocks compilation. An audio offset shifts every exported object in beat space; the song audio itself is not trimmed at export.

Minimal example:

```json
{
  "schema_version": "0.1",
  "song": {"title": "Example", "artist": "Artist", "bpm": 120, "audio_offset_seconds": 0},
  "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
  "motifs": {"pair": [
    {"id": "red", "beat": 0, "x": 0, "y": 1, "color": 0, "direction": 1},
    {"id": "blue", "beat": "1/2", "x": 3, "y": 1, "color": 1, "direction": 0}
  ]},
  "sections": [{"id": "opening", "start_beat": 0, "length_beats": 8,
    "intent": "open with a readable alternating phrase", "locked": false, "resolved": true,
    "notes": [], "patterns": [{"id": "opening-pair", "motif": "pair", "start_beat": 1}]
  }]
}
```
