# SM-004: Design a diverse corpus and exact-version reference manifest

Status: Implemented · Human phrase curation pending. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Research.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-002, SM-003

## Outcome

Collect enough varied evidence to discover patterns without teaching the system only one mapper's habits.

## Minimal v0 slice

Select 15-20 phrases from a small curated subset and record exact hashes and provenance; broader sampling follows a positive spike decision.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Favor deliberate curated positive pools: reviewed tech examples, ScoreSaber/BeatLeader ranked maps, BeastSaber curation, and named technical mappers. Set explicit diversity quotas and retain a small random/contrast cohort; neither rank nor popularity alone establishes quality.
- Start from the candidate metadata snapshot; preserve ScoreSaber stars separately from any BeatSaver or BeatLeader ratings.
- Plan a 100-map pilot and then measured expansion toward 1,000 or more only if gaps justify it. A 10,000+ collection remains a possible research scale, not a release requirement or fixed initial commitment.

## Decisions and pitfalls

- The large research pass is required; the pilot validates tooling rather than replacing it.
- Community tags and ratings are noisy hints. Include selected contrast examples, not just popular maps, and avoid labeling whole maps bad from votes.
- Record source hashes, exact difficulty, authors, source URLs, permitted uses, and audio retention. Do not assume downloading implies redistributing music.
- Choose per-map audio retention here: retain exact audio for timing/representation exemplars and evaluation, otherwise keep derived features plus map files and discard audio/ZIP only after successful extraction under the configured policy. Record archive/audio hashes, retained bytes, deletion state, and re-download source. Estimate storage from pilot byte counts, not an unverified 50-200 GB claim.
- BeatLeader pass/accuracy/tech ratings are useful stratification proxies, with nulls and algorithm versions handled explicitly; they do not replace human preference labels. Exclude the two Noodle Hard candidates from core gameplay learning unless a separate modchart cohort is requested.

## Acceptance criteria

- [ ] A manifest schema and sampling policy specify quotas, exclusions, provenance, and missing/deleted-version behavior.
- [ ] Each seed references an exact version/difficulty and a proposed purpose: calibration, style, contrast, or unsupported/modded research.
- [ ] A staged resource estimate and collection plan identify coverage gaps and split rules for benchmark isolation.

## References to check

- [BeatSaver API](https://api.beatsaver.com/docs/)
- [BeastSaber discovery and curation](https://bsaber.com/getting-started/custom-songs)
- [ScoreSaber API](https://scoresaber.com/api/docs)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BeatLeader API](https://api.beatleader.xyz/swagger/index.html)
- [BeatLeader RatingAPI](https://github.com/BeatLeader/RatingAPI)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/corpus.py](../../sabermapper/corpus.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
