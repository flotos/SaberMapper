# SaberMapper for Claude

The user's profile is in `PLAYER.md` at the repository root. Read @PLAYER.md before authoring or revising maps; it records the user's ScoreSaber identity, skill calibration and preferences.

This workspace contains a local Beat Saber authoring studio in `sabermapper/`. The agent composes JSON arrangements; the app handles audio analysis, revision storage, reference retrieval, local ArcViewer preview and ZIP export. It does not call an LLM itself.

Read @AGENTS.md for shared commands, directory layout and authoring boundaries.

## Agent-first workflow

All map work is done by the agent, never by a human operator. The agent handles import, analysis, research, composition, edits, validation, revision management, export, and opening the correct saved revision in ArcViewer. The user only views ArcViewer and gives textual requests and feedback in Codex or Claude Code; the agent applies that feedback and prepares the next preview.

Build every tool and feature for agent use first. Provide discoverable CLI or programmatic access, structured inputs and outputs, actionable errors, and revision-aware writes where applicable. Required mapping operations must be executable and inspectable by the agent without human UI interaction. Do not ask the user to edit arrangements, run commands, copy diagnostics, manage revisions, or operate studio controls. ArcViewer is the user-facing visual review surface; the conversation is the interface for requests and feedback. Follow the shared agent-first product contract in @AGENTS.md when changing code, documentation, skills, or workflows.

## Audio first

The audio is always the focus: map the song's sounds to notes, never place notes that no sound supports, and never leave a playing stretch unmapped. Follow "Audio is the source of every note" in @AGENTS.md; `project save` blocks long unmapped audio, and `project critique` reports the rest.

## Systematic fixes

Never fix a map problem for only one song. Trace each problem found through feedback, review or validation to its root cause. Encode the fix as a verifier check, an automated pipeline correction or a skill update, in that order of preference, and add a regression test. Rerun it across every project in the workspace and correct all affected arrangements through `project save`. Follow the full procedure in the "Systematic fixes" section of @AGENTS.md.

## Code changes in worktrees

Make every code change (application code, tests, scripts, skills, docs) in a dedicated git worktree branched from `main`, never directly in the main checkout. Run the test suite inside the worktree, commit there, then merge the branch into `main` and remove the worktree. Map data operations (`project save`, export, preview) still target the real workspace in the main checkout, because `sabermapper/workspace/` is user data.

When a turn made code changes and they were committed and merged into `main`, end the final message with this exact line:

👉 commited and merged into main

Only write that line once the commit and merge have actually succeeded. If tests fail or the merge is blocked, say so instead.

## Player and skills

Read @PLAYER.md for the default player's confirmed ScoreSaber identity, historical skill evidence and mapping baseline. Apply this calibration when composing, including requests labeled “Expert”; consult `sabermapper/workspace/player-profile.json` for newer explicit preferences and overrides.

Claude skills are installed at the workspace root:

- `/sabermapper-map` — author a new map or arrangement.
- `/sabermapper-review` — inspect feedback and revise a scoped section.
- `/sabermapper-research` — research and retrieve reference patterns.

Run application commands from `sabermapper/` using `.venv/Scripts/python`. Read the current project and revision before editing; preserve locks and save with `project save`. Prepare local ArcViewer playback for the user; if using the studio's **3D preview** button, operate it yourself. Canonical skill sources are in `sabermapper/skills/`; refresh both agent copies with `.venv/Scripts/python scripts/install_skills.py --update` from that directory.
