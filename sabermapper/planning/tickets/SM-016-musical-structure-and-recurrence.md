# SM-016: Analyze onsets, musical sections, energy, and recurring phrases

Status: Implemented · Section labels need musical review. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Audio.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-015

## Outcome

Expose the musical structure needed to place and vary technical patterns deliberately.

## Minimal v0 slice

Provide manually reviewed section boundaries and a compact report for the spike. Automated recurrence comes next; stems are deferred.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Extract onset/accent candidates, energy curves, rests, transitions, recurring sections, and beat-aligned similarity features.
- Offer optional local stem or instrument-role analysis only after evaluating cost, quality, and dependency implications; do not make it necessary for the baseline.
- Generate a compact song report with section IDs, beat ranges, candidate musical layers, repeated-section links, uncertainties, and editable labels.

## Decisions and pitfalls

- Similarity does not prove verse/chorus identity; label anonymous sections until supported or corrected.
- Dense percussion, vocals, and syncopation can produce competing mappings. Preserve options for the assistant rather than selecting every onset.
- Join corpus phrases to audio context through known timing and hashes; badly aligned references must not train representation scoring.
- Known map tempo/offset plus exact audio hash often supplies the initial corpus alignment cheaply. Verify trimming, tempo changes, custom-data semantics, and sample alignment before treating it as reliable.
- Variable tempo and stem separation are deferred beyond the initial steady-tempo slice. The user's intended genres remain an open calibration question; candidate metadata does not establish all future music.

## Acceptance criteria

- [ ] A reviewed sample demonstrates useful section boundaries, repeated-section links, accents, and rests with errors documented.
- [ ] Corrections to timing invalidate affected features while retaining user section intent where possible.
- [ ] The report lets an assistant distinguish rhythmic recurrence from arbitrary repetition without receiving huge raw feature arrays.

## References to check

- [librosa recurrence matrices](https://librosa.org/doc/0.11.0/generated/librosa.segment.recurrence_matrix.html)
- [Essentia audio analysis](https://essentia.upf.edu/documentation.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [FFprobe documentation](https://ffmpeg.org/ffprobe.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/structure.py](../../sabermapper/structure.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
