# SM-009: Extract contextual patterns and movement features

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Learning.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-007, SM-030

## Outcome

Represent technical patterns as meaningful movements and rhythms, not anonymous note windows.

## Minimal v0 slice

Extract 15-20 pilot phrases with rhythm and entry/exit context. Label them development data; no full research protocol is required to explore.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Extract multiple phrase scales using rests, rhythm boundaries, and later audio sections; keep neighboring notes and entry/exit state.
- Compute rhythm intervals, per-hand swing candidates, direction changes, position/spacing, crossovers, rotations, walls/bombs, density, and recovery time.
- Attach source beat ranges, tempo context, transformation metadata, uncertainty, and optional aligned musical features. Keep feature versions and extraction configuration.

## Decisions and pitfalls

- Multiple notes may form one swing, so NPS is not swing speed. Dot notes and implied hand paths may be ambiguous.
- Mirroring must swap hands, positions, and directions consistently. Rotation/translation or tempo normalization can erase playability differences.
- Use physical strain features as proxies requiring calibration, not as proof of bodily safety.
- SM-030 owns motion/swing inference and strain proxies; extraction consumes that versioned output rather than inventing a second parity algorithm. Pilot exploration is allowed before the full guide/corpus pass.

## Acceptance criteria

- [ ] The 15-20 phrase pilot verifies source and entry/exit extraction. Expand toward 30 examples only within the annotation budget; previously reviewed material can be reused without crossing evaluation splits.
- [ ] Equivalent supported encodings yield equivalent features; distinct setup or tempo contexts remain distinguishable.
- [ ] Ambiguous motion is represented rather than silently forced into one parity interpretation.

## References to check

- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)
- [BSMG mapping glossary](https://bsmg.wiki/mapping/glossary.html)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/patterns.py](../../sabermapper/patterns.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
