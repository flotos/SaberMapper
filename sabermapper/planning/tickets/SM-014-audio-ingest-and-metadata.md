# SM-014: Import audio and establish reliable metadata provenance

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Audio.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-005, SM-001

## Outcome

Create a stable audio timeline and identity record before musical analysis.

## Minimal v0 slice

Import the single spike track and preserve its exact decoded timeline and tags; omit online identity lookup.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Probe supported audio formats, preserve the original, compute content hashes, and create analysis/playback derivatives with recorded conversion parameters.
- Read tags, duration, channels, sample rate, and artwork; distinguish observed tags, inferred values, and user corrections.
- Specify optional online fingerprint/identity lookup as a separate opt-in adapter decision; retain an unknown/manual fallback without requiring an external service.

## Decisions and pitfalls

- Re-encoding, resampling, trimming, leading silence, and encoder delay can shift every later event.
- Identity metadata and beat analysis have different evidence. Never invent artist/title from a filename.
- Benchmark dependencies on Windows and record licenses, version pins, installation requirements, and disk/cache budgets.
- Use OGG Vorbis for the selected export path, not arbitrary content inside an .ogg extension. Measure round-trip decoded alignment, preserve trim/padding transforms, and avoid relying on negative audio offsets to fix alignment.

## Acceptance criteria

- [ ] A fixture set including silence, malformed input, tagged/untagged tracks, and multiple sample rates produces explainable outcomes.
- [ ] Original, analysis, preview, and export time coordinates have a documented and checked relationship.
- [ ] Manual metadata corrections survive reanalysis, and ordinary local import needs no online identity lookup.

## References to check

- [FFprobe documentation](https://ffmpeg.org/ffprobe.html)
- [BSMG audio preparation](https://bsmg.wiki/mapping/basic-audio.html)
- [Essentia audio analysis](https://essentia.upf.edu/documentation.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/audio.py](../../sabermapper/audio.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
