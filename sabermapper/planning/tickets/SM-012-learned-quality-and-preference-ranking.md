# SM-012: Optional stretch: test a local quality and preference ranker

Status: Implemented · No preference claim without labels. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Optional research.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-010, SM-011, SM-028

## Outcome

Learn from the corpus and feedback without making LLM calls or changing the assistant model.

## Minimal v0 slice

Optional stretch experiment only: estimate label sufficiency and compare a small local model against the existing baseline. A no-go outcome is valid.

## Expansion gate

Explicit stretch experiment outside the v1 critical path. Expand labels/models only after a budgeted feasibility result.

## Work

- Compare a rules-based baseline with a local supervised/pairwise ranking model using contextual features and labels.
- Keep general quality dimensions, technical-style compatibility, and personal preference independently inspectable. Return uncertainty and supporting examples.
- Version training data, features, model assets, configuration, and reports; support explicit retraining after accepted feedback.

## Decisions and pitfalls

- Start with models appropriate to the available labels and hardware; do not assume a large neural model is necessary.
- Prevent song/version leakage and inspect mapper/era/style biases. Compare accuracy across familiar and unseen mappers.
- Do not silently activate a weak model. Sparse preference data should lead to uncertainty and transparent fallback.
- A few hundred labels from one rater may be inadequate. Decide whether to train using measured label coverage and a learning-curve feasibility check; no downstream release ticket depends on success or completion here.

## Acceptance criteria

- [ ] A reproducible training run and model card document splits, counts, features, scope, and limitations.
- [ ] On frozen data, report pairwise ranking performance and uncertainty against rules-only and popularity/frequency baselines; preregister promotion thresholds under SM-028.
- [ ] Promote the model only if evidence supports improvement, otherwise document the failed hypothesis and retain the baseline; inference works locally without provider credentials.

## References to check

- [scikit-learn clustering](https://scikit-learn.org/stable/modules/clustering.html)
- [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/learning.py](../../sabermapper/learning.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
