# SM-021: Connect visual feedback to scoped assistant revisions

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Review.
Size: S; v0 slice: S (see backlog size legend).
Dependencies: SM-017, SM-018, SM-020

## Outcome

Support instructions such as 'vary this chorus' or 'keep the rhythm but soften this crossover' with reviewable results.

## Minimal v0 slice

Write one local JSON file containing revision ID, beat range, selected object IDs, and free-text feedback. The user asks the assistant to read it.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Write a small local feedback JSON file containing map revision, selected range, object IDs, free text, and optional visual artifact paths; the user then tells the assistant to read it.
- Provide commands for the separately operated assistant to read requests, propose changes, run compilation/validation, and produce before/after artifacts.
- Use ordinary file versions/diffs and a saved prior arrangement for comparison/undo; detect stale revision IDs and respect locked regions. Defer a request queue, workflow engine, and status dashboard.

## Decisions and pitfalls

- The previewer writes a request; it must not call an assistant, launch an LLM worker, or imply that typing a comment automatically triggers inference.
- An edit may affect neighboring transitions; show the affected scope and preserve unrelated sections.
- Separate liking a revision from endorsing every pattern inside it. Do not automatically turn all feedback into training truth.

## Acceptance criteria

- [ ] A user selects a range, leaves an instruction, invokes the assistant independently, reviews the resulting diff, and accepts or undoes it.
- [ ] Concurrent/stale revisions are detected; locked objects remain unchanged or produce an explicit conflict.
- [ ] An accepted edit updates lineage and diagnostics and records which user request it addressed.

## References to check

- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [ArcViewer source and capabilities](https://github.com/AllPoland/ArcViewer)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/projects.py](../../sabermapper/projects.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
