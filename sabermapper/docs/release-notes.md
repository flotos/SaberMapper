# Local development release notes

## Post-0.2 review fixes — 2026-09-22

Code-review fixes with regression tests in `tests/test_review_fixes.py` (51 tests total). The ranker no longer raises KeyError when human labels reference patterns that are not loaded or no longer exist; it records them as unresolved and returns no-go. Arrangements accept an optional top-level `mapper` string that becomes the Info.dat level author. Info.dat now declares the 2.1.0 `_environmentNames`, `_colorSchemes` and per-difficulty index fields it previously omitted; in-game acceptance still requires a playtest. Legacy v2 type-100 events without `_floatValue` are recorded as unsupported and exclude that difficulty from phrase extraction instead of failing the whole map. Studio retrieval reads the on-disk pattern catalog (cached by file signature) rather than deserializing every version's processing record, and catalog processing no longer holds raw map files in memory. The grid update endpoint checks the revision and locked sections before running audio analysis. Damaged UI glyphs were restored, the Pillow minimum is 10.1, and the project is now under version control.

## 0.2 studio implementation — 2026-09-22

Implemented software capabilities across all 31 planning tickets, with a persistent localhost studio, audio playback and timing analysis, section and arrangement editing, locks, revision history, feedback and playtest records, exact-version corpus processing and phrase retrieval, movement diagnostics, optional local ranking, portable assistant skills, and validated vanilla v3 ZIP export. The studio includes an original demo and a separate assistant-authored study with a scoped revision. Windows launchers and an installable wheel are included.

The ticket coverage record distinguishes implemented software from outstanding external acceptance evidence. Current player preferences, human pairwise labels, real-song listening review, and actual Beat Saber/VR playtests are not fabricated. The learned ranker remains inactive without sufficient labels. v4 and gameplay-mod charts are outside the supported vanilla extraction scope. See [verification](verification.md), [ticket coverage](ticket-coverage.json), and [supported features](supported-features.md).

## 0.1 pilot implementation — 2026-09-22

Introduced local JSON arrangement validation, motif expansion and deterministic Beat Saber v3 export; project revision storage and a localhost review UI; audio inspection, timing hypotheses, structure cues and Vorbis preparation; an original 48-second demo track; corpus import, map parsing, pattern retrieval, split/label records and an optional local ranker; and mapping, research and review skills. The ZIP includes a compatibility report with exact audio SHA-256. User data stays local except an explicitly invoked online corpus/profile operation.

The earlier planning tickets describe a larger program. This implementation is a development pilot, and a passing test suite does not complete the external editor/game import, a real-song timing check, or the intended player's before/after playtest. Record those results with the exact game build and artifacts before making a go/revise/stop decision. See [supported features](supported-features.md) and [evaluation protocol](evaluation-protocol.md).

The original demo and a separate [assistant-authored study](authored-study.md) both loaded in the [ArcViewer browser preview](arcviewer-verification.md), where timed 3D notes were visible. The authored study includes one scoped automated QA revision. These are browser preview observations, not Beat Saber gameplay results.
