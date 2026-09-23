# SM-037: Recurring parts of a song play as recurring note themes

Status: Implemented (2026-09-23) · applied to Living a Lie; the other projects are checked, not yet changed.
Phase: Productize.
Size: M.
Dependencies: SM-010 (motif grouping), SM-016 (recurrence), SM-036 (placer and rhythm draft).
Raised: 2026-09-23, from the user's question whether the pipeline ensures "recurring notes pattern themes, for similar sounding parts" and that each song has "its own thing" thematically.

## Problem

The analysis found repetition (listen repetition groups, per-stem bar patterns) but nothing turned it into repeated notes. The rhythm draft drafted each bar on its own; the placer's novelty bonus and greedy path made a second chorus land on unrelated placements; the critique only warned about too much repetition. All eight workspace maps used zero motifs.

## Behaviour

- **Recurring audio** (`recurrence.py`): listen sections paired with the earliest section they repeat, and 16-beat phrases at least 32 beats apart whose drum and busiest-instrument attack grids reach cosine 0.85. Vocals are left out of the rhythm test: a returning chorus may carry new words.
- **Themes in the arrangement** (`themes`): a statement span and echo spans (optionally mirrored, at most as long as the statement), each with an intent that names the sound. Validation rejects overlapping or malformed spans (`invalid_theme`).
- **Placement echoes a theme** (`placement.py`): after a first placement, an open echo note whose time matches a statement note (a single on a single, a double on a double) prefers the statement note's hand, cut and cell (`ECHO` = 4.0, above comfort, below every rule and stored value). The beam's cuts and the greedy pass's cuts are compared by echo agreement, since the greedy pass can flip the parity a hand enters an echo with. A double inside an echo keeps both hands. The save report lists per-echo `rhythm` and `placement` agreement.
- **The rhythm draft declares themes** (`music rhythm --propose`, with the listen run when `music listen` has run): a transposed repeat and every second echo are mirrored.
- **`project check`** reports `repeat_unechoed` (an audio repeat covered by no theme, rhythm ≥ 0.5, placement < 0.35) with an `add_theme` suggestion, and `theme_unechoed` (a declared echo that pins keep from following). Both are warnings.
- **Skills**: `sabermapper-map` asks for the song's own themes on every map; `sabermapper-review` explains both findings.

## Out of scope

Echoing the rhythm itself (each occurrence keeps its own audio-grounded times), sharing themes across difficulties, blocking severity, and corpus-wide pattern atlases (SM-010).

## Evidence

Tests: `tests/test_recurrence.py`. A synthetic hook repeated after a different passage echoes 100% of its placements (direct and mirrored) with no movement finding; without the theme it echoes under 35%.
