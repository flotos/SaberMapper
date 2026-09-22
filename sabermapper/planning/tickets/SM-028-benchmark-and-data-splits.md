# SM-028: Freeze family-split rules and a budgeted evaluation protocol

Status: Implemented · Manual timing anchors pending. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Research.
Size: M; v0 slice: S (see backlog size legend).
Dependencies: SM-001, SM-002

## Outcome

Make progress measurable before tuning features, clusters, or quality models.

## Minimal v0 slice

Freeze deterministic family-split rules and a small evaluation protocol before learning; begin with three spot-checked timing references rather than annotating 20 entire songs.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Define distinct datasets for parser/validator correctness, audio timing, motif similarity, quality/preference ranking, and full-map playtests.
- Freeze deterministic split assignment rules before learned tuning, then assign maps as they arrive. Canonical song/audio families keep versions and difficulties together; freeze concrete manifests at each evaluated dataset/model release.
- Set metrics and provisional acceptance thresholds before model tuning, including false-positive limits on intentional tech, timing error, retrieval relevance/diversity, and user preference.

## Decisions and pitfalls

- Avoid phrase-level random splits that put almost identical sections on both sides.
- Choose initial sample sizes and tolerances from a small pilot, record rationale, and do not retrospectively change targets to claim success.
- For held-out generation, target audio is necessarily supplied, but existing human note arrangements and corpus phrases from that song family stay out of authoring context. If timing is borrowed from a human map, mark timing as given and evaluate composition separately. Public assistant pretraining cannot be fully audited.
- Do not hash raw normalized title/artist alone: collisions, edits, aliases, covers, and remixes require explicit family resolution using IDs/audio hashes and an alias registry. On cross-split family merges, quarantine or move the family and retire any contaminated evaluation, never conceal it.
- Pilot/spike songs and all manually inspected examples are development material. Reuse inspected exact-audio map timing and tech fixtures as weak reference labels with spot-checks; hold out a small independent set for later claims.

## Acceptance criteria

- [ ] A versioned evaluation protocol names owners/reviewers, cohorts, splits, measures, thresholds, and test-data access rules.
- [ ] Start with three timing references checked at selected anchors and 3-5 evaluation songs as the user budget permits; do not require full manual beat/downbeat annotations for 20 songs.
- [ ] A versioned ruleset assigns incremental family splits reproducibly, and each evaluated release freezes its actual membership and leakage checks. Pilot exploration may precede this protocol; model tuning may not.

## References to check

- [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG variable-tempo audio](https://bsmg.wiki/mapping/advanced-audio.html#variable-bpm)
- [librosa beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/evaluation.py](../../sabermapper/evaluation.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
