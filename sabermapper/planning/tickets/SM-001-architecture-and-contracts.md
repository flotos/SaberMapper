# SM-001: Define architecture, boundaries, and versioned contracts

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Foundation.
Size: S; v0 slice: S (see backlog size legend).
Dependencies: None.

## Outcome

Give every component a shared contract while keeping map authoring in the user-operated assistant.

## Minimal v0 slice

Write one page of contracts and working defaults for the spike: Python tools, plain-text arrangement, existing 3D playback, and static HTML review UI. Record SteamVR; verify installed game version and mods later.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Use Python for local analysis/tools and a no-build static HTML/JavaScript page for 2D review as the working default. Use ArcViewer separately for playback. Keep the ADR focused on contracts and change these defaults only for a measured blocker.
- Specify contracts for map IR (internal representation), track analysis, pattern records, arrangement, diagnostics, feedback, and player preferences. Include units, stable IDs, schema versions, provenance, and migration rules.
- Define the no-LLM-call boundary: the application must not invoke provider APIs, assistant CLIs/SDKs, or background assistant jobs. The user invokes Codex/Claude independently.

## Decisions and pitfalls

- Do not assume an assistant can hear a track or inspect a running 3D scene: provide audio-derived reports and visual artifacts it can consume.
- Resolve game version, Standard characteristic, map export schema, mod requirements, local non-LLM models, hardware, and storage budgets. Defaults remain explicit proposals.
- A stable local CLI is enough initially; justify any MCP server or plugin packaging separately.
- The user confirms the latest SteamVR Beat Saber installation and is willing to roll back if necessary and supported. Target that installation first; record its exact build when available. Verify any rollback mechanism before proposing it, and do not assume arbitrary Steam versions can be selected. Test v3 export compatibility instead of requiring rollback by default.
- Local DSP, beat models, and supervised tabular rankers are separate from generative LLMs. Learned text embeddings remain undecided and unnecessary for v0. User-invoked assistant labeling is allowed; application-triggered inference or assistant processes are not.

## Acceptance criteria

- [ ] An architecture decision record chooses a stack and first compatibility target, with tradeoffs and deferred features.
- [ ] Versioned example payloads connect analysis -> arrangement -> map -> feedback without ambiguous beats/seconds or score/map IDs.
- [ ] A boundary diagram identifies all permitted network operations and shows the independently operated assistant outside the app.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [Web Audio specification](https://www.w3.org/TR/webaudio/)

## Implementation evidence (2026-09-22)

The disposable slice is described in [the experiment workflow](../../docs/experiment-workflow.md) and [architecture contract](../../docs/architecture-v0.md). Run `python -m unittest discover -s tests -v` from the project directory. Synthetic fixtures exercise the format and scoped revision, but do not satisfy real-song, preview, import, or playtest criteria above.

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [docs/architecture.md](../../docs/architecture.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
