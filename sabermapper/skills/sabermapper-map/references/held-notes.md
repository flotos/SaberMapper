# Arcs, chains and held vocal notes

## Object fields

Section arrays `arcs` and `chains` use section-relative beats. `tail_beat` must be
greater than `beat` and land inside the same section. Unsupported fields fail closed.

`arcs` require `id`, `beat`, `x` (0-3), `y` (0-2), `color` (0-1), `direction` (0-8),
`tail_beat`, `tail_x` (0-3), `tail_y` (0-2), `tail_direction` (0-8). Optional:
`head_multiplier` (>= 0, default 1), `tail_multiplier` (>= 0, default 1),
`mid_anchor` (0-2, default 0).

`chains` require `id`, `beat`, `x`, `y`, `color`, `direction`, `tail_beat`,
`tail_x`, `tail_y`, `slice_count` (2-100). Optional: `squish` (0..1, default 0.5).

## The head and tail note rule

An arc connects and alters scoring only when an authored color note sits at its
head and at its tail: same absolute beat, same `x`, `y`, `color` and cut
`direction`. A chain needs one at its head. In the local corpus of 6.5-8 star
reference maps, 98.7% of arc heads and 97.2% of arc tails coincide with a color
note. The validator errors otherwise: `arc_head_without_note`,
`arc_tail_without_note`, `chain_head_without_note`, and the matching
`*_direction_mismatch` codes when the note exists but its direction differs.
A dangling arc is a cosmetic curve, not a held note.

## A held saber cuts nothing else

An arc or chain occupies its saber from head to tail. A note of the same color
strictly between them is impossible: following the hold misses the note, and
cutting the note breaks the hold. This is a standing player rule, set on
2026-09-23 after a report at End of You 0:42: a blue up-cut sat inside a held
blue arc. The validator blocks it with `arc_note_conflict` or
`chain_note_conflict`; the finding is a warning when the section is locked.
Notes on the other hand inside the hold, and same-color chord notes on the
head or tail beat, are fine. While the hold lasts, give every other sound to the
other hand. When recoloring or moving a note, check whether a hold of its new color
spans that beat. `project repair-swings` resolves remaining conflicts. It moves
the note to the other hand when that hand is free. Otherwise it ends the arc on
that cut when at least a beat of hold remains, or drops the arc and keeps its notes.
For a chain it removes the inner note.

## Held vocals take focus

Standing user rule (2026-09-22): held singing notes, or intense singing, should
always be the focus of the track; use held notes for these, bottom-to-top or
top-to-bottom to match the pitch change if there is one.

When the evidence report (`music inspect`) shows a vocal `sustains` entry of at
least 0.7 s, or one full beat, whichever is longer, that sustain takes focus
priority over backing percussion for its duration. Place a head note at the
sustain start, an arc across the sustain, and a tail note at the sustain end or
at the next vocal attack. Do not fill the sustain with stock onset notes.

Direction follows `pitch_shape`: `rise` puts the tail row above the head row,
`fall` below, and `flat` or `unstable` keep the same row with lateral movement
across lanes. Default vertical travel is one row; use two rows (`y` 0 -> 2 or
2 -> 0) only for sustains of at least 1.5 s or the climactic sustain of a
section. The corpus median arc lasts one beat, and one-row travel is as common
as two.

Record the sustain evidence IDs (for example `RUN_ID/vocals:sustain:26415`) in
the section `intent` or in the focus phrase `evidence`.

## Chains are not used by default

Zero of the 128 v3 reference-band difficulties in the local corpus contain a
chain, and a burst slider reads as a staccato roll, not a held note. Intense or
belted vocals get an arc plus a strong accent note, not a chain. If a chain is
ever used, the head-note rule still applies.

## Worked example

A rising one-beat vocal sustain, authored so validation passes:

```json
{
  "id": "chorus", "start_beat": 64, "length_beats": 16,
  "intent": "Held chorus vowel, RUN_ID/vocals:sustain:26415, rise.",
  "locked": false, "resolved": true, "patterns": [],
  "notes": [
    {"id": "hold-head", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1},
    {"id": "hold-tail", "beat": 1, "x": 1, "y": 1, "color": 0, "direction": 0}
  ],
  "arcs": [
    {"id": "hold", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1,
     "tail_beat": 1, "tail_x": 1, "tail_y": 1, "tail_direction": 0}
  ]
}
```
