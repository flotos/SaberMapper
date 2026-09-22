# SM-027: Package the local toolkit and document the complete workflow

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Delivery.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-022, SM-025, SM-026

## Outcome

Make a reproducible local installation that the user can operate and maintain.

## Minimal v0 slice

Document a clean local setup for the successful slice and one primary assistant. Broader skills and a second host are optional expansion work.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Package dependencies, documented model downloads, CLI, visualizer, and separately installable skills; provide Windows setup and troubleshooting.
- Document project lifecycle, artifact locations, data/model version updates, corpus refresh, backups, and how to invoke each assistant independently.
- Provide sample projects and redistributable fixtures, supported-feature matrix, resource estimates, and release notes.

## Decisions and pitfalls

- Inspect networking so local project work does not contact LLM providers or secretly launch assistant clients. Document permitted download/metadata calls.
- A clean install must not depend on developer caches, the external reference repository, or private music files.
- Do not add plugin/MCP complexity unless the established CLI workflow demonstrates a concrete need.

## Acceptance criteria

- [ ] A fresh Windows environment completes the documented sample workflow and resumes a saved project.
- [ ] The primary mapping skill is discoverable through documented installation steps; research/review skills and secondary-host support are documented as optional additions until validated.
- [ ] The release documents known quality/compatibility limits and includes reproducible versions and measured resource requirements.

## References to check

- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
- [FFprobe documentation](https://ffmpeg.org/ffprobe.html)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [Start-SaberMapper.ps1](../../Start-SaberMapper.ps1). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
