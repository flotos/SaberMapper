# SM-008: Run and audit the large corpus research pipeline

Status: Implemented · Measured pilot report available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Corpus.
Size: XL; v0 slice: S–M (see backlog size legend).
Dependencies: SM-006, SM-007, SM-028, SM-029

## Outcome

Deliver the substantial corpus pass with measurable coverage, resource use, and reproducibility.

## Minimal v0 slice

Run the first 100-map audit only after Milestone 0 and a resource budget; expansion is coverage-driven and not a 10,000-map release gate.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Run staged ingestion and normalization using the agreed sampling manifest and record per-stage CPU/GPU time, disk use, and failures.
- Deduplicate exact archives, alternate versions, repeated audio, and overlapping difficulty material; preserve grouping relationships for evaluation.
- Produce a coverage report by style, difficulty, mapper, era, format, and mods, then fill important gaps. Feed normalized artifacts into later pattern extraction without requiring re-downloads.

## Decisions and pitfalls

- Freeze family assignment rules before learned tuning; discovery adds new assignments without changing the rule. Resolve family merges and audio aliases before releasing a training/evaluation snapshot.
- Near-duplicate audio and remixes need review; mapper-disjoint evaluation is an additional generalization test.
- The completion criterion is agreed coverage and usable evidence, not a raw download count.
- Broader collection follows the positive or revised Milestone 0 decision and a user-capacity/resource budget. Discovery-only pilot examples are explicitly development data and cannot later masquerade as unseen tests.

## Acceptance criteria

- [ ] The agreed large manifest is processed with explicit success, unsupported, duplicate, and failure totals that reconcile.
- [ ] A reproducible corpus release includes manifests, hashes, split assignments, resource measurements, and bias/coverage notes.
- [ ] A rerun is incremental; measured bytes and resource limits determine expansion. Use frozen family assignment rules as data arrives, then version manifests for actual training/evaluation releases.

## References to check

- [BeatSaver API](https://api.beatsaver.com/docs/)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/corpus.py](../../sabermapper/corpus.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
