# Verification — 2026-09-22

SaberMapper 0.2.0 was implemented with three GPT-5.6-Sol subagents and integrated in the local Windows workspace. All 31 tickets have software implementation/evidence entries in [ticket coverage](ticket-coverage.json). External acceptance criteria remain explicit rather than being marked complete by software tests.

## Observed checks

- Python 3.14.4 on Windows: `python -m unittest discover -s tests -q` passed all 44 tests. Coverage includes parsing, arrangement/export validation, source preservation, corpus exclusions, split leakage, concurrent saves, locks and review evidence.
- Playwright Chromium: `python tests/browser_workflow.py` passed with zero page errors. It exercised demo creation, advancing audio playback, range feedback, section edits, locks, ZIP download/import, pattern extraction, active-song retrieval exclusion, research resources and mobile layout.
- The actual populated workspace successfully served the authored study, positive corpus retrieval and research screens. Desktop and mobile screenshots are retained under `artifacts/`.
- The final wheel was installed into a separate virtual environment. Python isolated mode confirmed imports from that environment's installed package, HTTP 200 for packaged UI assets and all research resource groups. An earlier clean-install smoke also created a demo and downloaded a valid export ZIP.
- Final wheel: `dist/sabermapper-0.2.0-py3-none-any.whl`; SHA-256 `1dad6f50942a1ec11e8d7ce9061d662db112c5d9e1fa26e6c892b1e61beae027`.
- Original and revised assistant-authored exports loaded in ArcViewer v0.8.1 and advanced to 0:07 with visible red/blue notes. See [preview evidence](arcviewer-verification.md).
- All three portable skills passed their validator. A 3,745-case malformed-arrangement mutation check produced no uncaught validator exceptions.

## Corpus and research evidence

The frozen 100-version pilot accepted 97 exact versions. Three v4 references failed hash verification and remain recorded failures. Offline regeneration of the accepted corpus completed without processing failures, producing 29,739 vanilla pattern windows and 21,043 motif groups. Eight difficulties with unsupported gameplay objects were excluded from phrase extraction while preserving their source and normalized maps.

All inspected pilot material is development data, not held-out evaluation. There are no invented human preference labels; the enjoyment ranker remains inactive with a no-go result. See [corpus research](corpus-research.md).

## Remaining external acceptance

No actual Beat Saber/VR playtest, player comfort assessment, real-song listening review or human preference study was performed. Steam's installed Beat Saber build was identified as 24925021 without launching or modifying it. ArcViewer and structural tests do not establish in-game playability. The app provides the journal and evidence workflow to record these observations. v4, gameplay mods, automatic variable-tempo tracking and stems remain outside the supported scope.

The final local service is available at http://127.0.0.1:8765; use `Start-SaberMapper.cmd` to reopen it.
