# Arrangement 0.1 quick contract

Top level: `schema_version: "0.1"`, `song`, `difficulty`, `motifs`, `sections`; optional `tempo_events`, `themes` and `style` (below), `lightshow` (see [lightshow](lightshow.md); generated automatically on save) and `mapper` (a nonempty level-author name written to Info.dat; defaults to "SaberMapper"). `song` has nonempty `title`, `artist`, positive `bpm`, and finite nonnegative `audio_offset_seconds`. `difficulty` has a built-in name and matching rank (Easy/1, Normal/3, Hard/5, Expert/7, ExpertPlus/9), positive `njs`, and finite `spawn_offset_beats`. Optional `difficulty.target_tier` names the player star tier the difficulty aims for: `below_band`, `band`, `challenge`, `stretch` or `beyond` (see [difficulties and star tiers](difficulties.md)). It is not exported to the game.

`sections` have stable `id`, absolute `start_beat`, positive `length_beats`, nonempty `intent`, boolean `locked` and `resolved`, local literal `notes`, and `patterns`. Every note has `id`, local `beat`, `x` in 0–3, `y` in 0–2, `color` 0 red or 1 blue, and `direction` 0–8 (8 is dot). Only `id` and `beat` are required: `x`, `y`, `color` and `direction` are optional pins, and the placer fills any that are missing when the arrangement compiles or saves, so the movement rules hold (see the movement model's Placement section). A saved note lists the placer-chosen fields in `placed` (for example `"placed": ["x", "y", "color", "direction"]`); those values are kept while valid and re-chosen only when a rhythm edit breaks a rule. Editing one pins it; deleting a field asks for a new choice. A pattern has `id`, `motif`, local `start_beat`, and optional boolean `mirror`; a motif with open fields is placed once, and every use is checked. A motif maps an ID to local notes. Beats may be numbers or rational strings such as `"3/4"`. Pattern and literal notes must expand inside their section; no two notes may occupy the same beat and cell.

`themes` declares the song's recurring parts: an array of `{"id", "intent", "spans"[, "evidence"]}`. `id` is a unique lowercase identifier and `intent` names the recurring sound. `spans` lists the statement first, then one or more echoes, each `{"start_beat", "end_beat"}` in absolute beats; an echo may add `"mirror": true`, and repeats the statement from its start or from `from_beat`, a beat inside the statement (the echo's length must fit inside the statement from there). One riff that returns in pieces is one theme: echoes of different parts of it name their `from_beat`. No beat belongs to two theme spans. `evidence` is free-form provenance, such as the listen sections or rhythm similarity. Placement gives each open echo note whose time matches a statement note (within 0.13 beat; a single on a single, a double on a double) the statement note's hand, cut and cell, mirrored when asked, unless a movement rule or a stored value says otherwise. Motifs repeat an identical figure; themes repeat a part whose rhythm follows each occurrence's own audio.

```json
"themes": [{"id": "chorus-hook", "intent": "the sung hook over the half-time drums",
  "spans": [{"start_beat": 148, "end_beat": 180}, {"start_beat": 252, "end_beat": 284},
            {"start_beat": 496, "end_beat": 528, "mirror": true}]}]
```

`style` records the map's style, the selected candidate from `style save` (see the map skill): `{"idea", "grounding", "settings"[, "signatures", "source"]}`. `idea` is one sentence, `grounding` a nonempty list of the song evidence it follows from, and `settings` any of `flow` (round, balanced, angular), `diagonals` (few, some, many), `top_row` (low, normal, high), `arcs` (sparse, normal, lavish), `accents` (sparse, normal, heavy) and `theme_variation` (repeat, alternate, mirror); a missing setting takes its middle value. `signatures` are `{"theme", "move"}` pairs naming a declared theme, and `source` records the style revision and candidate. Placement reads `flow`, `diagonals` and `top_row` as comfort costs (never a rule); the rhythm draft reads `arcs`, `accents` and `theme_variation`.

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
