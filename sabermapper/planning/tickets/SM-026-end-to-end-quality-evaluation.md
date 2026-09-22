# SM-026: Evaluate generated maps and close the playtest feedback loop

Status: Implemented · Human playtest observations pending. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Evaluation.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-021, SM-022, SM-025, SM-028

## Outcome

Demonstrate that corpus learning and assistant iteration improve maps for the intended player.

## Minimal v0 slice

Record qualitative comparisons for one song and one revision with the user. Corpus/ranker improvements are later experimental arms, not prerequisites.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Run the frozen evaluation protocol on held-out songs using recorded assistant versions/prompts, artifact hashes, and pipeline settings.
- Compare a simple rules-only baseline, SaberMapper, and a human reference where available; inspect the human note arrangement only after assistant authoring. Include BeatForge only after SM-031 supports a controlled run. Corpus clustering and learned ranking are optional later experimental arms.
- Collect blind or order-balanced user judgments and playtest notes on enjoyment, technical interest, repetition, fatigue, timing, and revision effort.

## Decisions and pitfalls

- Hold out target audio/song families from retrieval and model fitting; a human map of the same evaluation song can leak the solution.
- A model that fails promotion under SM-012 remains off; evaluation can proceed with the baseline and explicitly record that result.
- Novelty and difficulty are not inherently quality. Record failures, not just successful showcases.
- One rater and a handful of songs support qualitative findings, not population-level claims. Order-balance and conceal variant names where practical, while documenting unavoidable familiarity.

## Acceptance criteria

- [ ] A report separates mechanical/timing measures from qualitative user notes, records elapsed review time, and explicitly states the single-rater/sample-size limitations.
- [ ] At least one full create -> preview -> instruction -> revision -> export -> playtest cycle is demonstrated from saved artifacts.
- [ ] The report identifies whether the assistant authored a replay-worthy result and which changes helped. Optional ranker/corpus experiments are reported only if run; omission does not block release.

## References to check

- [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)
- [Player profile](https://scoresaber.com/u/76561198016617991)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [docs/evaluation-protocol.md](../../docs/evaluation-protocol.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
