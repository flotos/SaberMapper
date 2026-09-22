# SM-015: Build a correctable beat, downbeat, and tempo pipeline

Status: Implemented · Listening review required. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Audio.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-014

## Outcome

Produce an explicit musical timing grid reliable enough for technical rhythms.

## Minimal v0 slice

Confirm a constant BPM, beat phase, and bar/downbeat anchor against the exact audio at the start, middle, and end. No pretrained model is needed for the spike.

## Expansion gate

Model comparison and variable-tempo support follow measured failures or user music needs; use SM-028 before benchmarking/tuning, not as a prerequisite to pilot exploration.

## Work

- Start with a constant-tempo/offset finder and a manually checked bar anchor. Later compare a conventional beat tracker with Beat This! on the budgeted fixture set; check code and weights licenses separately and measure local runtime.
- Store beat phase, downbeat/meter anchor, competing half/double-tempo interpretations, and reviewed corrections. Reserve a tempo-map contract; implement variable-tempo detection/rejection first and full support in a later increment unless the user's music requires it now.
- Support manual anchors, corrections, and local reanalysis; preserve those constraints and flag unreliable sections instead of silently quantizing everything.

## Decisions and pitfalls

- Beat tracking does not identify every note onset. Tempo, beat phase, meter, and musical accent are separate estimates.
- Variable-tempo music and irregular meters must have explicit behavior; do not hide drift behind one global BPM.
- Model confidence may not be calibrated. Use disagreement and annotation error measurements rather than presenting arbitrary probabilities as certainty.
- A conventional librosa beat-tracking call does not supply downbeat/meter labels; those need a separate estimate or human anchor. Existing map grids are provisional labels until exact audio alignment is spot-checked.

## Acceptance criteria

- [ ] Three exact-audio timing references, with sampled manual anchors, report timing error/drift and method cost. Enlarge or add variable-tempo ground truth only within the human-time budget.
- [ ] The v0 tests cover offset, half/double tempo, silence, and correction persistence. Variable-tempo input is explicitly identified as unsupported until its later acceptance tests exist.
- [ ] Beat-to-time and time-to-beat conversions stay consistent across segment boundaries and later export.

## References to check

- [Beat This! implementation and models](https://github.com/CPJKU/beat_this)
- [librosa beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html)
- [BSMG variable-tempo audio](https://bsmg.wiki/mapping/advanced-audio.html#variable-bpm)
- [BSMG audio preparation](https://bsmg.wiki/mapping/basic-audio.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/timing.py](../../sabermapper/timing.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
