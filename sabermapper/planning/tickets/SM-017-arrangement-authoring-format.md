# SM-017: Co-design the plain-text arrangement with the mapping skill

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Authoring.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-001

## Outcome

Let an assistant express musical choices and targeted edits with stable, inspectable artifacts.

## Minimal v0 slice

Draft a diff-friendly YAML or JSON arrangement that the assistant edits directly. Test motif references plus literal phrases with the prototype skill before stabilizing the schema.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Design a human-readable YAML or JSON file the assistant edits directly: sections, intent, motifs, literal custom phrases, variation, and entry/exit constraints. Use stable IDs and field order for clear diffs.
- Support pattern references and explicit custom objects so authoring is not limited to library stitching.
- Use file revisions and lightweight schema checks; reserve commands for compilation, validation, and preview. Test the draft format jointly with SM-022 during SM-029 before freezing it.

## Decisions and pitfalls

- A constrained vocabulary improves reliability but must still express technical movement and deliberate exceptions.
- Store seeds, configuration, referenced pattern/model versions, and rational beat subdivisions where appropriate.
- Allow a section to remain unresolved when timing or transitions are uncertain; do not pretend every arrangement compiles successfully.

## Acceptance criteria

- [ ] The real primary assistant authors and revises a draft from a song report and 15-20 phrase examples. Observed authoring errors drive the v0 schema; richer examples come later.
- [ ] A local edit changes one identified section while retaining unrelated objects and manual locks.
- [ ] Round-trip editing preserves intent and rejects stale or invalid patches with an actionable explanation.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG mapping glossary](https://bsmg.wiki/mapping/glossary.html)

## Implementation evidence (2026-09-22)

The disposable slice is described in [the experiment workflow](../../docs/experiment-workflow.md) and [architecture contract](../../docs/architecture-v0.md). Run `python -m unittest discover -s tests -v` from the project directory. Synthetic fixtures exercise the format and scoped revision, but do not satisfy real-song, preview, import, or playtest criteria above.

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/arrangement.py](../../sabermapper/arrangement.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
