# SM-013: Retrieve compatible, diverse patterns with evidence

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Learning.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-002, SM-009

## Outcome

Give the assistant useful examples for a musical section without overwhelming its context.

## Minimal v0 slice

Filter the tiny phrase list by rhythm, speed, hand state, and selected style; provide diverse examples without embeddings or learned ranking.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Implement structured retrieval by rhythm, tempo, musical role, length, difficulty envelope, technical features, and entry/exit requirements.
- Return a small diverse set with source links, compatibility explanations, available quality evidence, confidence, and contrast examples. Begin with metadata/feature filtering.
- Support a deterministic baseline first; integrate SM-012 as an optional ranking provider after its evaluation gate. Exclude evaluation songs when building benchmark maps.

## Decisions and pitfalls

- A popular family must not crowd out all rare patterns. Maintain variety without encouraging random novelty.
- Requested movement may have no compatible example: report that and support constrained new authoring.
- Retrieved examples guide composition; avoid copying long passages unchanged and retain provenance when adapting.
- SM-010 clustering and SM-011 labels enrich retrieval when available; SM-012 ranking and text embeddings are optional adapters and cannot block the baseline.

## Acceptance criteria

- [ ] Representative queries produce reproducible, compact results with exact source versions and reasons for inclusion/exclusion.
- [ ] A reviewed query set measures relevance, diversity, and entry/exit compatibility; record failures.
- [ ] The same interface works without a trained ranker, and every suggested transformation is rechecked in its destination context.

## References to check

- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [scikit-learn clustering](https://scikit-learn.org/stable/modules/clustering.html)
- [BeatSaver API](https://api.beatsaver.com/docs/)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/patterns.py](../../sabermapper/patterns.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
