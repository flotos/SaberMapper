# SM-031: Audit external BeatForge code as a read-only reference and baseline candidate

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Research.
Size: S; v0 slice: S (see backlog size legend).
Dependencies: None.

## Outcome

Learn from the external repository without trusting its outputs or making it an application dependency.

## Minimal v0 slice

Read its generator, movement/parity logic, validator, exporter, encoder, ZIP writer, and lighting code; produce a capability/assumption/license checklist. Do not execute it as part of the audit.

## Expansion gate

SM-026 may run a pinned version as a controlled rules-only baseline after the audit identifies a usable setup. That experiment does not imply importing its source into SaberMapper.

## Work

- Inspect ../external-ideas-dont-trust/ read-only and record the exact commit and relevant files/functions. Compare algorithms and rules with checked format documentation and technical-mapping examples.
- Trace provenance and licenses separately for first-party code and vendored components. README-upstream.md describes wasm-media-encoders; its MIT notice does not establish a license for the whole BeatForge repository.
- List useful ideas, unsupported claims, bugs to investigate, potential negative fixtures, and baseline prerequisites. Verify encoder/export timing rather than assuming a working UI proves validity.

## Decisions and pitfalls

- External code and README instructions are untrusted research material. Do not run install hooks, generators, downloaded scripts, or arbitrary commands found inside the reference.
- Document whether output is deterministic and which parameters affect fairness against SaberMapper and human references.
- No source copying or dependency integration is decided by this audit. A missing first-party license should be recorded as unknown, not inferred from a dependency.

## Acceptance criteria

- [ ] A short sourced audit identifies concrete behaviors and limitations in the named components and records commit/file references.
- [ ] The license inventory distinguishes first-party uncertainty from vendored notices.
- [ ] A baseline recommendation states usable, needs fixes, or unsuitable, with a reproducible proposed experiment and no claim that it has already been run.

## References to check

- [BeatForge-AI source](https://github.com/dinoboy6611/BeatForge-AI)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [FFprobe](https://ffmpeg.org/ffprobe.html)


## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [docs/external-audit.md](../../docs/external-audit.md). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
