# SM-029: Milestone 0: test assistant-authored mapping on one track

Status: Implemented · Replay decision belongs to user. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Milestone 0.
Size: M; v0 slice: M (see backlog size legend).
Dependencies: None.

## Outcome

Test the core hypothesis before building the large corpus or production pipeline: can the independently invoked assistant produce a technical arrangement the user wants to replay from a checked song report and a small pattern list?

## Minimal v0 slice

Complete one steady-tempo song, one assistant-authored difficulty, one targeted revision, and a user playtest. Prototype the minimum skill and arrangement together.

## Expansion gate

Proposed timebox: the first 1-2 working weeks, subject to actual development and user review availability. Freeze the experiment scope first; a failed result redirects the plan rather than triggering automatic corpus expansion.

## Work

- Select a familiar steady-tempo track and retain its exact audio hash. Obtain a provisional BPM/offset from a known map or local estimate; the user checks timing and the bar anchor. Keep the existing target note arrangement out of assistant inputs.
- Hand-extract 15-20 contextual phrases from suitable core reference candidates, including entry/exit state and technical variety. Use a concise song report with manually reviewed sections and accents; no corpus pipeline or trained model is required.
- Co-design a plain-text arrangement v0 and a minimal shared mapping skill, exercising the first slices of SM-017 and SM-022. Write only a disposable compiler, narrow overlap/parity checks, and v3 ZIP export needed for the experiment. Use the current SteamVR build as the first compatibility target.
- Preview the local ZIP in ArcViewer, then playtest. Have the assistant author from the same report/pattern inputs used for the baseline, request one concrete revision, and compare with a simple rules/manual arrangement. Use minimally visible lighting and reviewed jump settings.

## Decisions and pitfalls

- This ticket owns the disposable integration experiment; it does not wait for completion of production SM-001 through SM-028. Successful pieces may later be promoted into those tickets.
- Human-derived timing tests composition, not autonomous timing accuracy. Source-song note arrays must stay out of the authoring context; reveal a human reference only afterward.
- Measure user time, editing effort, and failures. A visually correct map can still be unenjoyable; one person's result is qualitative and specific to that person.
- Pretrained audio models, a custom viewer, broad source collection, labels, and a generalized command framework must not expand this spike. A missing local dependency can be handled manually in the documented fixture.

## Acceptance criteria

- [ ] Before starting, record the song, inputs, narrow scope, time budget, primary assistant, target game build, and qualitative success question: would the user replay it?
- [ ] The assistant authors and revises a complete arrangement through its file tools and local commands; no application LLM call occurs.
- [ ] A map imports into the chosen game, has reviewed timing and no known hard structural faults, and is playtested before and after one scoped revision.
- [ ] The result is an explicit go, revise-hypothesis, or stop decision with saved artifacts and reasons. Large-scale collection and production expansion wait for this decision.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [ArcViewer](https://github.com/AllPoland/ArcViewer)
- [OpenAI skills](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills](https://code.claude.com/docs/en/skills)


## Implementation evidence (2026-09-22)

The disposable slice is described in [the experiment workflow](../../docs/experiment-workflow.md) and [architecture contract](../../docs/architecture-v0.md). Run `python -m unittest discover -s tests -v` from the project directory. Synthetic fixtures exercise the format and scoped revision, but do not satisfy real-song, preview, import, or playtest criteria above.

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [docs/experiment-workflow.md](../../docs/experiment-workflow.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
