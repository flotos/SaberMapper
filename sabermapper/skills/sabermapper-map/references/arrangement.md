# Arrangement 0.1 quick contract

Top level: `schema_version: "0.1"`, `song`, `difficulty`, `motifs`, `sections`; optional `tempo_events` and `mapper` (a nonempty level-author name written to Info.dat; defaults to "SaberMapper"). `song` has nonempty `title`, `artist`, positive `bpm`, and finite nonnegative `audio_offset_seconds`. `difficulty` has a built-in name and matching rank (Easy/1, Normal/3, Hard/5, Expert/7, ExpertPlus/9), positive `njs`, and finite `spawn_offset_beats`. Optional `difficulty.target_tier` names the player star tier the difficulty aims for: `below_band`, `band`, `challenge`, `stretch` or `beyond` (see [difficulties and star tiers](difficulties.md)). It is not exported to the game.

`sections` have stable `id`, absolute `start_beat`, positive `length_beats`, nonempty `intent`, boolean `locked` and `resolved`, local literal `notes`, and `patterns`. Every note has `id`, local `beat`, `x` in 0–3, `y` in 0–2, `color` 0 red or 1 blue, and `direction` 0–8 (8 is dot). A pattern has `id`, `motif`, local `start_beat`, and optional boolean `mirror`. A motif maps an ID to local notes. Beats may be numbers or rational strings such as `"3/4"`. Pattern and literal notes must expand inside their section; no two notes may occupy the same beat and cell.

Optional section arrays `bombs`, `obstacles`, `arcs`, `chains` and top-level `tempo_events` are supported by the compiler. See [held notes](held-notes.md) for the exact `arcs` and `chains` fields and the rule that an arc needs an authored color note at its head and tail, and a chain at its head; unsupported fields and unconnected arcs or chains fail closed. A section with `resolved: false` blocks compilation. An audio offset shifts every exported object in beat space; the song audio itself is not trimmed at export.

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
# Musical focus

Sections optionally accept `musical_focus`, an ordered array of section-relative
phrase ranges with a lead layer, normalized weights and musical intent. See
[the focus contract and examples](musical-focus.md). This metadata records the
agent's decisions and participates in revision/lock checks; it does not generate
or retime notes during compilation. Existing arrangements remain compatible.
