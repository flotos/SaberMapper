# SM-025: Add basic lighting and reliable Beat Saber export

Status: Implemented · In-game compatibility needs playtest. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Delivery.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-001, SM-014, SM-018, SM-019

## Outcome

Package an authored map that loads and plays in the agreed target environment.

## Minimal v0 slice

Export one Standard difficulty with OGG Vorbis audio, cover, metadata, fixed reviewed timing, NJS/spawn choices, and minimal visible lighting.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Define minimal environment/lighting support, with musical section/accent intent authored by the assistant and deterministic event generation in tools.
- Serialize the selected map schema, audio, cover, metadata, difficulties, and lighting into a local export with integrity checks.
- Preserve audio alignment and necessary dependencies; produce a compatibility report and manual install/playtest instructions.
- Own NJS, jump distance, and note jump/start offset choices and their readable defaults. Keep audio timing offset distinct from note spawn offset; allow user-specific review settings.

## Decisions and pitfalls

- Pin game/schema/mod targets rather than promising universal compatibility. Validate actual output in the chosen editor and game.
- Keep functional lighting separate from ambitious environment animation; do not let a lightshow delay gameplay evaluation.
- Export is not publishing: uploading to BeatSaver or redistributing reference audio is a separate future action.
- Require OGG Vorbis for the first export, record trim/padding/re-encoding transforms, and check decoded audio against the timing grid. Do not rely on negative audio offsets. Use minimal visible lighting initially; rich lightshows are deferred.

## Acceptance criteria

- [ ] An exported fixture and one authored track import successfully in the selected editor and game with matching timing and object counts.
- [ ] Missing assets, unsupported features, and unresolved hard validation failures produce clear failures.
- [ ] Basic lighting is visible and synchronized, and export can be repeated from saved artifacts without LLM access.

## References to check

- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [BSMG basic lighting](https://bsmg.wiki/mapping/basic-lighting.html)
- [BSMG audio preparation](https://bsmg.wiki/mapping/basic-audio.html)
- [ChroMapper source and editor](https://github.com/Caeden117/ChroMapper)

## Implementation evidence (2026-09-22)

The disposable slice is described in [the experiment workflow](../../docs/experiment-workflow.md) and [architecture contract](../../docs/architecture-v0.md). Run `python -m unittest discover -s tests -v` from the project directory. Synthetic fixtures exercise the format and scoped revision, but do not satisfy real-song, preview, import, or playtest criteria above.

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/export.py](../../sabermapper/export.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
