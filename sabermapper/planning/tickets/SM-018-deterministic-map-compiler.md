# SM-018: Compile arrangements into reproducible map objects

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Authoring.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-017, SM-007

## Outcome

Turn assistant decisions into exact map data with valid transitions and reproducible revisions.

## Minimal v0 slice

Compile the spike arrangement to v3 notes using explicit rhythm and hand-state rules. Report unsupported intent; do not silently flatten it.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Expand motifs and transformations, place objects on the reviewed grid, enforce selected compatibility constraints, and emit traceable map IR.
- Check neighboring sections and entry/exit states; provide deterministic bridge options or a diagnostic when no compatible transition is available.
- Produce previewable output, compilation reports, configuration/model hashes, and section/object lineage.

## Decisions and pitfalls

- Do not silently simplify technical choices to satisfy a heuristic; explain conflicts and let the assistant/user revise intent.
- Compilation determinism starts from saved inputs, not from repeating an LLM conversation.
- New motifs and transformed patterns must be checked at the actual tempo, jump settings, and neighboring context.
- SM-030 owns the production movement model; the spike may use a documented narrow heuristic. Do not make conflicting swing inference in the compiler.

## Acceptance criteria

- [ ] Identical saved inputs and versioned dependencies yield semantically identical map output with stable object identities.
- [ ] Fixtures cover cross-section state, tempo changes, mirrored patterns, impossible placement, and locked sections.
- [ ] Every compiled phrase points back to its arrangement decision and reference source or identifies it as newly authored.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [ChroMapper source and editor](https://github.com/Caeden117/ChroMapper)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/arrangement.py](../../sabermapper/arrangement.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
