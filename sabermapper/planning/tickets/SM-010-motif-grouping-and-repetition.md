# SM-010: Group motif families and measure repetition versus variation

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Learning.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-009

## Outcome

Discover recurring mapping elements while distinguishing musical motifs from monotonous reuse.

## Minimal v0 slice

Group exact/mirrored repeats in the pilot and inspect a handful of near matches. Compare transparent distances before complex clustering.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Build exact and near-match representations for rhythm, movement, and their combination; compare transparent sequence distances with clustering approaches.
- Group repeated phrases within a song and across maps; record mirrors, rhythmic shifts, spacing changes, and tempo-context differences.
- Produce a pattern atlas with exemplars, outliers, transition context, occurrence counts, and maps back to source ranges; support incremental updates.

## Decisions and pitfalls

- Frequency is not a quality score. A repeated chorus may deserve a recognizable motif with controlled variation.
- A single giant cluster or singleton-heavy result may hide poor features; inspect stability and human pair judgments.
- Keep rare intentional technical motifs and maintain transformation links without treating all transformed patterns as equally playable.
- The similarity-label sample shares the development phrase pool where possible and has its own time cap; evaluation identities remain separate.

## Acceptance criteria

- [ ] On a labeled sample, report exact/near-match precision and recall with errors; agree targets before tuning.
- [ ] Atlas examples demonstrate exact repetition, meaningful variation, false lookalikes, and rare technical patterns.
- [ ] Repetition summaries distinguish within-section monotony from recurrence across matching musical sections once audio alignment is available.

## References to check

- [scikit-learn clustering](https://scikit-learn.org/stable/modules/clustering.html)
- [librosa recurrence matrices](https://librosa.org/doc/0.11.0/generated/librosa.segment.recurrence_matrix.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/patterns.py](../../sabermapper/patterns.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
