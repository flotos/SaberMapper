# SM-007: Parse map versions into a loss-aware internal representation

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Corpus.
Size: L; v0 slice: S–M (see backlog size legend).
Dependencies: SM-001, SM-005

## Outcome

Compare patterns consistently across formats without corrupting musical timing or object semantics.

## Minimal v0 slice

Import the pilot's v2/v3 notes, obstacles, and timing. Detect unsupported/custom-tempo data explicitly; full v4 support is a later expansion.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Prioritize v2/v3 imports for historical references and a v3 spike export after confirming the installed SteamVR game. Treat v4 as an explicitly gated adapter expansion, with unsupported inputs reported.
- Represent notes, directions, angle offsets, bombs, obstacles, arcs/chains, tempo mapping, jumps, and available lighting metadata with stable IDs.
- Preserve source fields and unknown custom data when feasible; mark unsupported mod features and do not flatten them into misleading vanilla patterns.

## Decisions and pitfalls

- Info, audio, beatmap, and lightshow files have separate schemas; one version label does not describe the whole archive.
- Beat/time conversion and source offset conventions must be explicit, especially for changing tempo.
- Parser success is not proof of playability. Do not drop difficult objects to make validation pass.
- Modern v4 audio timing and lightshow data are separate from gameplay objects; inspect each schema separately. Older customData tempo events may describe editor timing with different playback semantics. Never apply them blindly as native game tempo changes.

## Acceptance criteria

- [ ] Representative fixtures for each supported schema normalize into a documented IR with object counts and timestamps verified.
- [ ] Unsupported features produce actionable records; exact source map/version/difficulty can be recovered from each output.
- [ ] Round-trip or semantic-equivalence checks cover tempo boundaries, simultaneous notes, obstacles, and supported arcs/chains.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [ChroMapper source and editor](https://github.com/Caeden117/ChroMapper)
- [ArcViewer source and capabilities](https://github.com/AllPoland/ArcViewer)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/mapio.py](../../sabermapper/mapio.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
