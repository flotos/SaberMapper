# SM-020: Use ArcViewer playback and build a 2D review timeline

Status: Implemented · VR playtest remains separate. See implementation evidence below; unchecked acceptance items are not implied complete.
Phase: Review.
Size: M; v0 slice: S–M (see backlog size legend).
Dependencies: SM-001, SM-007, SM-014

## Outcome

Provide inexpensive playback review plus precise range selection and visual evidence for the assistant.

## Minimal v0 slice

Use ArcViewer externally for local ZIP playback and add a static 2D lane/time timeline for range selection. No custom 3D renderer.

## Expansion gate

Expand after the v0 slice is useful and its cost is measured. See the shared capacity budget and milestone gates in the backlog.

## Work

- Use ArcViewer as a separate existing tool to open exported local ZIPs; document the tested format and player settings. Avoid embedding or copying its renderer in v0.
- Implement a no-build static 2D lane-versus-time/beat timeline with hand colors, object IDs, range selection, and reproducible screenshots. Add waveform/audio only where needed for review.
- Add SM-019 diagnostic overlays and SM-030 motion annotations when available; basic viewing and selection must not wait for them.

## Decisions and pitfalls

- A custom synchronized 3D renderer is deferred until a documented gap in ArcViewer plus the 2D timeline justifies a separate ticket.
- ArcViewer's checked license is GPL-3.0; ChroMapper's checked default-branch license is GPL-2.0. These source observations do not themselves decide reuse compatibility; using a separate viewer avoids choosing source integration now.
- A 2D timeline must still use the project's time/beat conventions. Estimated motion is not measured player movement; incomplete diagnostics remain explicit.

## Acceptance criteria

- [ ] A supported local export opens in ArcViewer with reviewed timing; the setup instructions record tested viewer/game versions.
- [ ] The 2D timeline displays supported objects and lets the user export a selected range with stable IDs; screenshot labels are legible.
- [ ] Diagnostic overlays can be added without changing selection IDs, and unsupported formats/features produce a visible warning.

## References to check

- [ArcViewer source and capabilities](https://github.com/AllPoland/ArcViewer)
- [ChroMapper source and editor](https://github.com/Caeden117/ChroMapper)
- [Web Audio specification](https://www.w3.org/TR/webaudio/)
- [BSMG map format](https://bsmg.wiki/mapping/map-format.html)
- [ArcViewer license](https://github.com/AllPoland/ArcViewer/blob/main/LICENSE)
- [ChroMapper license](https://github.com/Caeden117/ChroMapper/blob/master/LICENSE)

## Full-app implementation evidence

The user explicitly requested implementation across all tickets, superseding the earlier expansion gates. The implemented component is [sabermapper/static/app.js](../../sabermapper/static/app.js). See [the coverage record](../../docs/ticket-coverage.json), [user guide](../../docs/user-guide.md), and reproducible checks in `tests/`. Human judgments, listened timing and VR gameplay evidence remain separate from automated software verification.
