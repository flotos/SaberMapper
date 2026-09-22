# SM-022: Create the mapping skill for Codex and Claude Code

Status: Implemented · Musical quality requires player feedback. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Skills.
Size: M; v0 slice: S (see backlog size legend).
Dependencies: SM-017

## Outcome

Guide the independently invoked assistant through musical planning, authoring, review, and revision using the local toolkit.

## Minimal v0 slice

Create one minimal shared SKILL.md directory during the spike to read the report and edit the arrangement. Productize it against stable commands after the experiment.

## Expansion gate

Production workflow integration follows SM-003/013/016/018/019/021/025 as their interfaces land; second-host support is not a spike gate.

## Work

- Create skill instructions and concise references for inspecting a project, reviewing uncertain timing, defining section intent, retrieving patterns, composing, compiling, validating, previewing, and exporting.
- Start with one shared skill directory and SKILL.md using scripts/references supported by both hosts. Choose one primary host for the spike; add host-specific placement instructions only when required by tested discovery behavior.
- Cover follow-up instructions and resume from saved project state. Require evidence-backed completion claims: compiled, validated, previewed, and playtested are distinct statuses.

## Decisions and pitfalls

- Do not embed a huge corpus or every guide in SKILL.md; fetch relevant knowledge and patterns on demand.
- Do not ask the model to emit thousands of raw JSON objects when structured arrangement edits suffice, but preserve custom authoring capability.
- Skill behavior must not assume audio perception, installed tools, or identical discovery mechanisms in both hosts. Verify current official host docs.
- Co-design the arrangement and skill through the real experiment, not separate specifications. The spike skill need not wait for a feedback UI, a retrieval service, or the production exporter.

## Acceptance criteria

- [ ] The minimal skill is invoked in the selected primary host during SM-029 and authors/edits the plain-text arrangement. Secondary-host smoke testing is a later compatibility increment.
- [ ] Scenario evaluation covers a fresh map, ambiguous timing, difficult technical transition, section revision, and resumed session.
- [ ] No application LLM calls, invented analysis, unrelated rewrites, or silent export of unresolved hard failures occur in the scenarios.

## References to check

- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)

## Implementation evidence (2026-09-22)

The disposable slice is described in [the experiment workflow](../../docs/experiment-workflow.md) and [architecture contract](../../docs/architecture-v0.md). Run `python -m unittest discover -s tests -v` from the project directory. Synthetic fixtures exercise the format and scoped revision, but do not satisfy real-song, preview, import, or playtest criteria above.

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [skills/sabermapper-map/SKILL.md](../../skills/sabermapper-map/SKILL.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
