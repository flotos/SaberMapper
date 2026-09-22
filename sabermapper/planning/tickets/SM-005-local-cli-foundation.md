# SM-005: Grow a minimal local CLI from the playable slice

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Foundation.
Size: M; v0 slice: S (see backlog size legend).
Dependencies: SM-001

## Outcome

Make every later operation inspectable and reproducible on the user's machine.

## Minimal v0 slice

Keep only the commands and artifact directories needed to compile, check, and export the spike. Add caching/resume machinery when actual workload requires it.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Implement only commands used by the first track: compile, check, export, and simple artifact inspection. Add structured errors and configuration at the same time as the feature that needs them.
- Add content-addressed caches, cancellation, resumable corpus jobs, and atomic replacement when SM-006/008 introduce long-running work; these are not prerequisites to the first compile.
- Separate source code, downloaded corpus, model assets, user audio, generated projects, and research artifacts. Establish focused CI checks and small redistributable fixtures.

## Decisions and pitfalls

- Choose commands after the contracts are stable; ticket examples are conceptual rather than existing commands.
- Windows paths, Unicode, spaces, locked files, subprocess argument handling, and offline operation need explicit handling.
- Keep external-ideas-dont-trust outside imports and build paths. Reviewing its code later requires provenance and license assessment.

## Acceptance criteria

- [ ] A clean Windows setup runs the spike commands and reports useful errors; interruption/resume checks become acceptance criteria for the later corpus-job expansion.
- [ ] Changes to an input/configuration invalidate affected artifacts while preserving manual edits.
- [ ] No model-provider credential or assistant process is required to exercise local tools.

## References to check

- [FFprobe documentation](https://ffmpeg.org/ffprobe.html)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/__main__.py](../../sabermapper/__main__.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
