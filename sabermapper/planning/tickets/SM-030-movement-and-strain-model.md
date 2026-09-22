# SM-030: Own shared swing inference, transitions, and difficulty proxies

Status: Implemented · Heuristic; not biomechanics. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Foundation.
Size: L; v0 slice: M (see backlog size legend).
Dependencies: SM-007

## Outcome

Supply one versioned movement interpretation shared by extraction, compilation, validation, retrieval, and visual annotations.

## Minimal v0 slice

Model supported notes as swing candidates with uncertain entry/exit states; cover simple parity, simultaneous strokes, and explicit resets on the pilot. Survey existing implementations before writing a new model.

## Expansion gate

Add technical rotations, ambiguous dot notes, bomb/wall-induced motion, arcs/chains, and measured difficulty proxies incrementally. This is a high-uncertainty ticket; the spike uses a smaller documented heuristic.

## Work

- Survey JoshaParity, its refactor, and ChroMapper's parity logic; pin commits, inspect licenses, and compare capabilities, assumptions, known issues, and the cost of reuse or an independent implementation.
- Define swing grouping, direction/angle changes, parity hypotheses, resets, hand positions, entry/exit state, and inferred repositioning. Represent uncertainty and multiple valid interpretations rather than enforcing a single guessed path.
- Own measurable proxies for swing rate, distance, angular change, recovery time, crossover demand, sustained bursts, and visibility/reaction context. Calibrate against examples and optionally BeatLeader components while retaining provider/version labels.
- Expose stable results consumed by SM-009/013/018/019/020. Keep note timing and spawn/jump parameters explicit so callers cannot silently use conflicting models.

## Decisions and pitfalls

- Implied motion is not a biomechanics simulator or safety guarantee. A low strain proxy does not prove comfort, and a difficult motion does not prove a mapping defect.
- Ranked technical examples are useful review seeds with known context, not incontrovertible ground truth. Inspect errors, intentional exceptions, and checker disagreement.
- JoshaParity and its refactor currently report MIT; ChroMapper's checked default-branch license is GPL-2.0. Verify exact dependencies and commits before reuse; language differences may make direct integration undesirable.

## Acceptance criteria

- [ ] An implementation survey records tested/potential reuse paths, license evidence, and a reasoned narrow v0 model.
- [ ] Versioned fixtures cover ordinary flow, explicit resets, multi-note swings, and at least one ambiguous technical phrase; results include uncertainty and rationale.
- [ ] All downstream consumers use the same model version and identify unsupported motion rather than silently applying their own parity logic.
- [ ] Proxy measurements and their limitations are documented, with user/fixture calibration and no unsupported physical-safety or official-star claims.

## References to check

- [JoshaParity](https://github.com/Joshabi/JoshaParity)
- [JoshaParity refactor](https://github.com/Joshabi/JoshaParity-Refactor)
- [ChroMapper license](https://github.com/Caeden117/ChroMapper/blob/master/LICENSE)
- [BeatLeader RatingAPI](https://github.com/BeatLeader/RatingAPI)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)


## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/movement.py](../../sabermapper/movement.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
