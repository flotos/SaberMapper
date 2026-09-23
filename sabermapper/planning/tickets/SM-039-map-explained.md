# SM-039: The studio and the viewer explain the map in plain language

Status: Implemented (2026-09-23) · Living a Lie has its texts; other projects fall back to their intents.
Phase: Productize.
Size: M.
Dependencies: SM-038 (map style), SM-037 (themes), the studio preview (ArcViewer).
Raised: 2026-09-23, from the user's request for "a one paragraph explanation of song mapping goal and chosen approach / style" in the studio, one short sentence per section with the evidence hidden, a click that opens ArcViewer at the passage, and ArcViewer with the section's description on the left and a top-to-bottom timeline on the side.

## Behaviour

- **Texts**: the style's `summary` (one paragraph on the mapping goal and approach) and each section's `summary` (one sentence, at most 240 characters). `intent` keeps the evidence. Validation reports malformed texts (`invalid_summary`, `invalid_style`); `project check` reports missing ones (`summary_missing`). Without a summary, a section shows the first sentence of its intent, with the evidence trimmed off.
- **`project outline`** (CLI, and `GET /api/projects/ID/outline`): the style, and each section's summary, evidence, themes and start and end in song seconds.
- **Studio**: a *Map idea* panel; section cards show the summary with the evidence folded away, open the viewer at the section on click, and keep editing behind ✎.
- **Viewer** (`/viewer/`, opened by 3D preview and the section cards): ArcViewer (a compiled Unity build, left unmodified) in an iframe from the same origin, the map's explanation and current section on the left, and a clickable top-to-bottom timeline with theme bars and a playhead on the right. It reads ArcViewer's song clock from its window (`soundStartTime + (SongCtx.currentTime - lastPlayed) * playbackSpeed` while playing) and jumps by reloading ArcViewer with a new `t`.

## Limits

While ArcViewer is paused, the panel keeps the last time it heard; a scrub made while paused shows once playback resumes. The viewer was built without being opened by the agent; the user reviews it.
