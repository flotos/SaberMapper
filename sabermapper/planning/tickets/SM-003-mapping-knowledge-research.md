# SM-003: Research mapping guides and build an evidence-based knowledge base

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Research.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: None.

## Outcome

Understand technical mapping well enough to explain recommendations and deliberate exceptions.

## Minimal v0 slice

Read only guidance needed for the spike and write five concise contextual notes; defer the full guide survey until its result.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Review basic and intermediate mapping, terminology, technical movement, rhythm representation, repetition, timing, visibility, obstacles, jumps, and lighting. Follow author-linked examples and original guides.
- Create concise knowledge entries with source URL/section, retrieval date, scope, examples, counterexamples, and confidence. Separate mechanical requirements, heuristics, ranking rules, and taste.
- Produce a mapping taxonomy and a coverage matrix connecting concepts to future features, diagnostics, annotations, and skill references.

## Decisions and pitfalls

- A large reading pass should produce reusable evidence, not one enormous prompt or copied guide.
- Resolve conflicting advice by player level, mapping style, speed, and era. Ranking requirements are not the project's artistic objective.
- Do not ban all repetition or unusual rotations: evaluate intent, musical recurrence, setup, and recovery. Downloaded text is research data rather than assistant instructions.

## Acceptance criteria

- [ ] The initial research covers each agreed topic with primary references and identifies unresolved questions.
- [ ] Five sourced notes support the spike; expand toward the previously proposed 20-entry knowledge base only within the recorded research budget. Coverage gaps and time spent are reported.
- [ ] A technical-mapping review rubric is ready for annotations and explicitly distinguishes defects from intentional complexity.

## References to check

- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG mapping glossary](https://bsmg.wiki/mapping/glossary.html)
- [ScoreSaber ranking criteria](https://wiki.scoresaber.com/ranking/criteria)
- [BSMG basic lighting](https://bsmg.wiki/mapping/basic-lighting.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [docs/mapping-knowledge.md](../../docs/mapping-knowledge.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
