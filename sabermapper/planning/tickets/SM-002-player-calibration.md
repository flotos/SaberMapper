# SM-002: Calibrate player difficulty and technical preferences

Status: Implemented · Current player calibration pending. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Research.
Size: S; v0 slice: S (see backlog size legend).
Dependencies: None.

## Outcome

Turn historical scores and explicit taste into a testable target profile.

## Minimal v0 slice

Review existing snapshots, ask for loved/disliked sections, and choose three calibration references. Do not build a generalized importer.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Use the saved ScoreSaber and BeatLeader snapshots and a small one-off refresh if needed; reconcile exact map hash, characteristic, difficulty, score context, and modifiers. Do not require a reusable importer for one user.
- Separate older top scores, recent saved results, unranked maps, and modifier cohorts. Report dates, counts, accuracy denominator, median, and spread.
- Build comfort/challenge references and a short playtest calibration set. Gather section-level likes/dislikes for technical movement, repetition, rhythm, fatigue, and readability.
- Express the target as ranges for swing rate, burst/sustained NPS, NJS, jump distance/reaction time, recovery, and accepted pattern classes. Keep each provider's stars and rating components separately named and versioned.

## Decisions and pitfalls

- The latest saved result is March 2025. Saved best results are not all attempts; score recency can understate later activity.
- No Fail scores do not establish a clean pass. Excluding all modifiers is the conservative baseline, with other cohorts reported separately.
- Stars cannot quantify technical taste, and generated maps have no official ScoreSaber star rating. Ranked maps can be technical.
- Eight of the nine later ScoreSaber ranked results fall in late January 2025, plus one in December 2024. This may be a ranked session rather than representative taste. Ask for five loved and three disliked maps/mappers or sections, accepting fewer initially.

## Acceptance criteria

- [ ] A versioned player profile records evidence, dates, uncertainty, preferences, and user overrides.
- [ ] The nine unmodified ranked Standard results from 2024 onward reproduce approximately 7.43-star mean and 80.50% base-score accuracy from the snapshot.
- [ ] A calibration session confirms or revises the provisional 6.5-8-star reference band and records named positive/negative examples without inferring taste from score alone.

## References to check

- [ScoreSaber API](https://scoresaber.com/api/docs)
- [Player profile](https://scoresaber.com/u/76561198016617991)
- [BeatSaver API](https://api.beatsaver.com/docs/)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BeatLeader API](https://api.beatleader.xyz/swagger/index.html)
- [BeatLeader RatingAPI](https://github.com/BeatLeader/RatingAPI)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/profile.py](../../sabermapper/profile.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
