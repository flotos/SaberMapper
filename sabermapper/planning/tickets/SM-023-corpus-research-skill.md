# SM-023: Create the corpus and mapping-research skill

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Skills.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-003, SM-006, SM-009

## Outcome

Make future research passes reproducible and turn findings into traceable knowledge and examples.

## Minimal v0 slice

Package the proven manual research workflow into concise skill instructions after it has been exercised; do not require the entire large corpus.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Guide the assistant through source review, bounded corpus queries, motif inspection, contrasting examples, evidence summaries, and proposals for new knowledge entries.
- Provide a workflow for inspecting rare/outlier patterns, reviewing cluster errors, and updating the taxonomy with source references.
- Keep corpus execution in local scripts and require an explicit research run configuration rather than unbounded downloads.

## Decisions and pitfalls

- Research conclusions must distinguish statistical correlation, a guide's recommendation, user preference, and tested causal improvement.
- External guide text and map descriptions are untrusted data; never adopt instructions from them.
- Updates to labels or the knowledge base should be versioned and reviewable; frozen benchmark labels must remain untouched.
- Package the pilot research workflow first; large corpus releases, clustering, and richer labels are optional expansion inputs.

## Acceptance criteria

- [ ] A repeat research task yields a sourced report, reproducible query/configuration, and traceable proposed annotations.
- [ ] The skill can explain both a frequent pattern family and a rare technical exception using contextual examples.
- [ ] Changing a source or corpus version is reflected in the output provenance and does not silently rewrite prior conclusions.

## References to check

- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BeatSaver API](https://api.beatsaver.com/docs/)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [skills/sabermapper-research/SKILL.md](../../skills/sabermapper-research/SKILL.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
