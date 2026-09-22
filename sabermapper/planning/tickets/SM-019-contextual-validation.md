# SM-019: Validate correctness and diagnose mapping problems without flattening tech

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Authoring.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-007, SM-030

## Outcome

Detect mistakes while keeping stylistic heuristics distinct from structural failures.

## Minimal v0 slice

Check object overlaps, bounds, and a narrowly documented swing-state heuristic on the pilot; fuller technical diagnostics use SM-030 later.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Implement schema/export integrity checks, object conflicts, timing consistency, and supported-feature checks.
- Add contextual warnings for parity transitions, reach/rotation proxies, visibility, recovery, density spikes, repetition, and audio alignment.
- Return severity, affected IDs/beat ranges, evidence, confidence, and suggested review actions. Support explicit documented overrides for heuristic findings.

## Decisions and pitfalls

- Timing off a metronomic grid may be intentional; compare to the approved musical timing rather than blindly snapping.
- Unusual rotations, crossovers, or controlled resets can be intentional technical design. Calibrate false positives on good tech examples.
- A checker should not claim a map is safe, fun, or officially rankable solely because it passes.
- Use spot-checked ranked/curated tech as a low-cost source of likely-good fixtures, not a guarantee of no parity defects. Separate intended complexity, checker disagreements, and unsupported features.

## Acceptance criteria

- [ ] Known mechanical errors are caught with exact locations and no silent repairs.
- [ ] A separate approved-tech fixture set measures heuristic false positives; each rule states its applicability and limitations.
- [ ] Reports distinguish hard failures, warnings, and accepted exceptions and survive targeted revisions.

## References to check

- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [ScoreSaber ranking criteria](https://wiki.scoresaber.com/ranking/criteria)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/validation.py](../../sabermapper/validation.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
