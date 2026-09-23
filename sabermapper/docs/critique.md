# Arrangement critique

`sabermapper.critique` is a descriptive, non-blocking report on an arrangement.
It answers "what shape is this map, in numbers" so the authoring agent can spot
a problem that structural validation cannot see: a map made of one looping
figure, a map that never uses the top row, a section that empties out right
before the loudest part, or a section seam that lands on a strong musical
accent with no note on it.

What it is not:

- **Not a gate.** Every finding carries `severity: "warning"`. The critique
  never emits an `error` and never prevents `compile`, `export` or `project save`.
  `project check` (SM-036) reports the critique beside placement, validation and
  audio grounding in one list, marks which findings block a save, and attaches
  suggested edits.
- **Not a playability model.** It does not judge flow, parity, swing angles or
  difficulty; `validation.py` and the movement model own those questions.
- **Not a musical verdict.** A warning marks a measurable property, not a
  mistake. A deliberately hypnotic section will trip `repetitive_cycle`, and
  that is the correct reading of the numbers.

Because the metrics are fixed and reproducible, the report's main use is a
before/after baseline: save the critique of the current revision, rewrite, and
compare the same fields.

## CLI

```
# The one report: placement, validation, movement, audio grounding and critique findings with suggestions
.venv/Scripts/python -m sabermapper project check PROJECT_ID --workspace workspace \
    [--run RUN_ID] [--arrangement DRAFT.json] [--metrics] [--output PATH]

# Aliases kept for existing workflows (SM-036 decision): the same report plus the critique's metrics and warnings
.venv/Scripts/python -m sabermapper project critique PROJECT_ID --workspace workspace [--run RUN_ID] [--output PATH]
.venv/Scripts/python -m sabermapper critique ARRANGEMENT.json [--report REPORT.json] [--output PATH]
```

The critique forms print the `project check` report with the critique's
`metrics`, `warnings` and `definitions` added; `--output` writes it to a new
file instead. Each check finding is `{"code", "severity", "blocking", "source",
"section_id", "object_ids", "beats", "message", "suggestions"}`. `project save`
refuses exactly the findings marked `blocking`. The
project form also reports the project's current `revision` and the `run_id`
used, so a stored baseline can be tied to an exact arrangement.

`--run` takes a musical evidence run ID (`music list PROJECT_ID`). The run's
`source.sha256` must match the project's `song.ogg`, otherwise the command
fails rather than reporting seam findings against the wrong audio. Without a
report, the seam check is skipped and `metrics.boundary_accents.checked` is
`false`; every other metric is unaffected.

Programmatically: `critique_arrangement(arrangement, report=None) -> dict` with

```json
{"model_version": "1.0", "metrics": {...}, "warnings": [...], "definitions": {...}}
```

Each warning is `{"severity": "warning", "code", "message", "section_id",
"object_ids", "value", "threshold"}`. `definitions` maps every metric and
warning code to a one-sentence plain-language definition, so a reported number
can be audited without reading the source.

## Metric definitions

Beats convert to source-audio seconds through `song.bpm`,
`song.audio_offset_seconds` and `tempo_events`; beat 0 is the audio offset.

### Density (`metrics.density`)

- `rolling_nps` — notes per second in **4-second windows hopped every 1 second**
  from the first note to the last, as `{start_seconds, end_seconds, nps}`.
- `section_nps` — per section, `{section_id, nps, note_count, seconds}`, where
  `nps` is the section's notes divided by its `length_beats` in seconds.
- `overall_nps` — all notes divided by the seconds between the first and last note.

**`density_collapse`** — for each boundary between consecutive sections S and T:
`pre` is the nps of the sparsest 2-second window (hopped 0.5 s) inside the last 8 seconds of S, `s_med` is the median of the
rolling windows lying fully inside S, and `t_head` is the nps of the first 8
seconds of T. The boundary is flagged when `pre < 0.6 · s_med` **and**
`t_head > s_med` **and** S holds at least 8 notes. `value` is `pre / s_med`,
`threshold` is `0.6`, `section_id` is S, and `object_ids` lists the notes inside
that final 4-second window.

### Repetition (`metrics.repetition`)

A *placement* is the tuple `(x, y, color, direction)`.

- `distinct_placements` — how many distinct placements the map uses at all.
- `placement_histogram` — the twelve most frequent placements with counts.
- `cycle_coverage` — for each period k in 2..16, the fraction of notes i ≥ k
  whose placement equals the placement k notes earlier; reported as the best
  `{k, coverage}`.
- `placement_entropy` — Shannon entropy in bits of the placement distribution
  inside rolling windows of **64 consecutive notes hopped by 16 notes**;
  reported as `min` and `median` across windows. A map with fewer than 64 notes
  is measured as a single window so the metric stays defined.
- `top_row_share`, `lane_histogram` (x = 0..3), `row_histogram` (y = 0..2).

**`repetitive_cycle`** — the best `cycle_coverage` reaches **0.6** or more.
**`low_placement_variety`** — the median window entropy falls below **2.5 bits**.
**`top_row_starved`** — `top_row_share` is below **0.05** in a map of at least
**100** notes.

### Recurrence (`metrics.recurrence`)

The other side of repetition: a part of the song that returns should return in
the map too (`sabermapper/recurrence.py`). An *audio repeat* is a listen section
paired with the earliest section it repeats (repetition group similarity 0.5 or
more, aligned at their starts over the shorter length, on whole bars), or two
16-beat phrases at least 32 beats apart whose sixteenth attack grids (the drums
and the busiest other instrument) reach cosine **0.85**. `project check` passes
the newest listen run for the evidence run; without one only the rhythm is used.

- `themes`: per declared echo, `rhythm` (share of note times that match the
  statement at the same relative beat, within 0.13 beat) and `placement` (share
  of the matched notes that repeat the statement's placement, mirrored when the
  echo is).
- `repeats`: per audio repeat, the same two scores (placement the better of
  direct and mirrored) and whether a theme covers it.

**`repeat_unechoed`**: an audio repeat no theme covers, with at least 8 matched
notes and rhythm **0.5** or more but placement below **0.35**. Its `add_theme`
suggestion declares the theme and reopens the echo's unlocked notes.
**`theme_unechoed`**: a declared echo with at least 8 matched notes whose
placement is below **0.35**.

### Style (`metrics.style`)

The map's declared style (`style` in the arrangement, `sabermapper/style.py`) beside its measured one:

- `turn_degrees`: the mean angle between each cut and the clean reversal of the same hand's previous cut (same-hand
  swings under 2 s apart, dots skipped). 0 is a pure pendulum.
- `diagonal_share`: the share of directional notes cut diagonally.
- `top_row_share`, `accent_share` (note times with two or more notes) and `arcs_per_minute`.

**`style_missing`**: the arrangement declares no style.
**`style_drift`**: a declared setting whose metric leaves its band. Round flow turns at most **14** degrees and angular
at least **34**; few diagonals are at most **30%** and many at least **55%**; a low top row is at most **13%** and a
high one at least **23%**. The bands come from four workspace songs placed from scratch under each value: the
default placed turns of 21-24 degrees, diagonal shares of 45-50% and top-row shares of 18-21%. Round placed 1-10 degrees,
angular 42-45, few diagonals 23-27%, many 58-84%, a low top row 8-11% and a high one 25-26%.

### Boundary accents (`metrics.boundary_accents`)

Only checked when a musical evidence report is supplied. For every section
start beat except the first, the critique looks for a layer event with
`strength ≥ 0.7` whose `method` is not `energy_rise` and whose beat (converted
with `musical.seconds_to_beat`) is within **±0.25 beat** of the seam.

**`boundary_accent_unmapped`** — such an event exists but no note lies within
±0.25 beat of the seam. The message names the layer, the event ID and its beat;
`object_ids` is the event ID, `value` is the event's beat distance from the
seam and `threshold` is `0.25`.

### Movement objects (`metrics.movement_objects`)

`arc_count` and `chain_count` overall and per section, plus
`arc_vertical_travel`, a histogram of each arc's `tail_y − y`. **No warning is
derived from these**; they exist so a rewrite that adds arcs and chains can be
compared against a baseline that had none.

When the supplied report provides per-layer `sustains` for a `vocals` layer
(schema 1.1 musical runs), two extra fields appear: `long_vocal_sustains`, the
number of sustains lasting at least 0.7 s, and `sustains_covered_by_arcs`, how
many of those start within ±0.5 beat of an arc head. Reports without sustains
simply omit both keys.

## Using it as a rewrite baseline

1. Record the baseline before changing anything, tagged by revision:
   `project check ID --workspace workspace --run RUN_ID --metrics --output baseline.json`.
2. Note the fields the rewrite is meant to move — usually
   `repetition.cycle_coverage.coverage`, `repetition.placement_entropy.median`,
   `repetition.top_row_share`, the `density_collapse` boundaries and
   `movement_objects.arc_count`.
3. Rewrite and save through `project save`.
4. Re-run the critique into a second file and compare the same fields. A
   rewrite that resolves a code removes its warning; a rewrite that only moves
   the problem elsewhere shows up as a new `section_id` on the same code.

Thresholds are deliberately fixed constants in `critique.py`. Do not relax one
to make a warning disappear: the useful output of a near-miss is the measured
`value`, which is reported whether or not the finding trips.
