# SM-011: Create mapping-quality labels and personal preference examples

Status: Implemented · Human labels not fabricated. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Learning.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-002, SM-003, SM-009, SM-028

## Outcome

Supply evidence for what good mapping means in context and for this player.

## Minimal v0 slice

Time-box the first 20-40 pairwise judgments to 1-2 user hours, reuse previously inspected phrases, and measure minutes per judgment.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Define separate annotation dimensions for structural defects, timing/representation, readability, movement/flow, difficulty fit, repetition/variation, and personal enjoyment.
- Annotate phrase pairs and full-section examples with context, confidence, disagreement, and source attribution; distinguish intentionally demanding tech from accidental awkwardness.
- Use curated status, votes, tags, and rule diagnostics only as weak evidence. Prioritize uncertain examples for further human review.

## Decisions and pitfalls

- A bad score may reflect player skill, hardware, or song difficulty rather than bad mapping. A popular map can contain weak sections.
- Synthetic corruptions help test obvious errors but must not become the only negative examples.
- Allow unknown/ambiguous labels and rubric revisions. The assistant can propose labels, but automated judgments are not independent human ground truth.
- Ranked/curated exact-version examples provide weak priors for mechanical quality, not automatic zero-error labels. Spot-check them and record review era, characteristic, intended resets, and ambiguous cases.
- Assistant-proposed labels are allowed only through the independently invoked user assistant. Keep their origin separate from verified human labels and from benchmark answers.

## Acceptance criteria

- [ ] An annotation guide has examples and counterexamples for each dimension and a policy for disputed cases.
- [ ] Begin with 20-40 contextual pairwise judgments within a 1-2 hour cap; log duration and ambiguity. Any expansion toward 200 requires an explicit capacity decision and is not assumed sufficient for a learned model.
- [ ] Each personal-preference label identifies the user feedback that supports it; a review pass reports consistency and remaining gaps.

## References to check

- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)
- [ScoreSaber ranking criteria](https://wiki.scoresaber.com/ranking/criteria)
- [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/learning.py](../../sabermapper/learning.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
