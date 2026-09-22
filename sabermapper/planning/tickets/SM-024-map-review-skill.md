# SM-024: Create a critique and revision skill for finished drafts

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Skills.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-019, SM-020, SM-021

## Outcome

Review whole-map musical coherence and technical sections without mistaking passing checks for good mapping.

## Minimal v0 slice

Create a short review workflow for a single draft and targeted revision, then add further evidence sources as they become available.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Guide an independent review pass over timing, motif development, fatigue, readability, transitions, difficulty fit, and repeated sections.
- Combine script diagnostics, source-backed heuristics, visual artifacts, and user playtest feedback into prioritized, range-linked findings.
- Propose local fixes with tradeoffs and regression checks; preserve intent and accepted exceptions.

## Decisions and pitfalls

- A second assistant pass is not a human playtest or guaranteed independent opinion.
- Avoid optimizing only measurable quantities such as density, novelty, or zero heuristic warnings.
- State when the assistant cannot directly judge audio or physical movement and which evidence supports each criticism.

## Acceptance criteria

- [ ] Seeded mechanical issues are identified, known intentional tech is not categorically rejected, and vague criticism is tied to specific ranges.
- [ ] Each proposed revision includes intended benefit, affected scope, and checks to repeat.
- [ ] The report distinguishes verified findings, hypotheses, user taste, and in-game questions.

## References to check

- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [skills/sabermapper-review/SKILL.md](../../skills/sabermapper-review/SKILL.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
