# SM-006: Implement bounded BeatSaver discovery and downloads

Status: Implemented · local evidence available. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Corpus.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-004, SM-005

## Outcome

Acquire the planned corpus reliably with auditable provenance.

## Minimal v0 slice

Fetch explicit pilot IDs/hashes, validate archives, and record per-map audio retention before any broad discovery.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Implement metadata discovery, exact-hash lookup, version selection, downloads, caching, and manifest status updates against the current API.
- Handle pagination, timeouts, missing hashes, changed metadata, rate limits, backoff, and interrupted transfers; use configurable request/storage budgets.
- Validate downloaded archives before extraction: contain paths within the corpus directory, reject traversal and links, bound expanded sizes, and never execute included files.

## Decisions and pitfalls

- Verify live API documentation and service guidance during implementation instead of assuming an undocumented bulk endpoint.
- Hash resolution must not silently substitute a newer map for the one a player scored.
- Prefer metadata-first filtering and selective audio retention; audio may be needed for representation research but is expensive to retain.
- The manifest owns a per-map retain-audio policy and measured byte counts. Verify hashes and persist needed features before any configured cleanup; retained calibration/evaluation audio is protected.

## Acceptance criteria

- [ ] The pilot manifest is fetched with exact versions or explicit unresolved reasons and a complete provenance trail.
- [ ] A second run avoids unchanged downloads; a cancelled run resumes without corrupt records.
- [ ] Meaningful fixtures cover paging, throttling, corrupt archives, traversal, missing maps, and budget exhaustion.

## References to check

- [BeatSaver API](https://api.beatsaver.com/docs/)
- [ScoreSaber API](https://scoresaber.com/api/docs)
- [BeastSaber discovery and curation](https://bsaber.com/getting-started/custom-songs)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/corpus.py](../../sabermapper/corpus.py). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
