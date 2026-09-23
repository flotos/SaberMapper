# SaberMapper for Claude

The user's profile is in `PLAYER.md` at the repository root. Read @PLAYER.md before authoring or revising maps; it records the user's ScoreSaber identity, skill calibration and preferences.

This workspace contains a local Beat Saber authoring studio in `sabermapper/`. The agent composes JSON arrangements; the app handles audio analysis, revision storage, reference retrieval, local ArcViewer preview and ZIP export. It does not call an LLM itself.

Read @AGENTS.md for shared commands, directory layout and authoring boundaries.

## Agent-first workflow

All map work is done by the agent, never by a human operator. The agent handles import, analysis, research, composition, edits, validation, revision management, and export. The user reviews saved revisions in the studio and ArcViewer on their own schedule and gives textual requests and feedback in Codex or Claude Code; the agent applies that feedback. Never open ArcViewer, the studio or a browser preview, and never hand a revision over for review, unless the user explicitly asks. The agent cannot see the rendered view, so opening it adds no evidence. One exception (user decision, 2026-09-23): the agent may open Beat Saber itself to capture frames, but only through the leased commands (`game capture`, `game launch`, `game play`), which refuse with `game_busy` when another agent or the user already has the game; the agent reads the captured frames, never a live view, and closes the game it launched. The ban on opening ArcViewer, the studio and browser previews stays.

Build every tool and feature for agent use first. Provide discoverable CLI or programmatic access, structured inputs and outputs, actionable errors, and revision-aware writes where applicable. Required mapping operations must be executable and inspectable by the agent without human UI interaction. Do not ask the user to edit arrangements, run commands, copy diagnostics, manage revisions, or operate studio controls. ArcViewer is the user's own visual review surface; the conversation is the interface for requests and feedback. Follow the shared agent-first product contract in @AGENTS.md when changing code, documentation, skills, or workflows.

## Audio first

The audio is always the focus: map the song's sounds to notes, never place notes that no sound supports, and never leave a playing stretch unmapped. Follow "Audio is the source of every note" in @AGENTS.md; `project save` blocks long unmapped audio, and `project check` reports the rest.

## General rules, never song-specific patches

A map problem found in one song is evidence of a rule every song needs. Trace each one found through feedback, review or validation to the general rule it breaks. Encode that rule, in this order of preference, as a verifier check that `project check` reports, a build-time placement or rhythm-draft rule or safer default (never a command that rewrites saved maps), or skill guidance, and add a regression test. Rerun it across every project in the workspace and update each affected arrangement through `project save`. Follow the full procedure in the "Systematic fixes" section of @AGENTS.md.

## Write descriptively, never "fix X"

State every rule, check, skill passage, ticket, script, docstring, commit message and code comment as the behaviour it establishes: what the map or tool does, and why. Write "notes sit on the lead's attacks; a kick between two guitar chugs stays unmapped", not "fix the kick filler" or "rework Living a Lie". Name modules, scripts, commands and branches after what they do, not after the problem that prompted them.

Build tools and scripts for the initial authoring flow, so that a first draft made with them already follows every rule. Never write a script that only reworks one song. A song's own decisions (section roles, moments the user named) belong in its arrangement or in a plan that a general tool reads, not in the tool's code. When a general tool for the job is already in progress, such as the SM-036 rhythm draft and placer, add the rule to that tool rather than building a second one.

## Code changes in worktrees

Make every code change (application code, tests, scripts, skills, docs) in a dedicated git worktree branched from `main`, never directly in the main checkout. Create worktrees under `C:\Users\floto\SaberMapperWorktrees\` (for example `git worktree add -b BRANCH C:/Users/floto/SaberMapperWorktrees/BRANCH main`), never in the Documents folder or next to the main checkout. Run the test suite inside the worktree, commit there, then merge the branch into `main` and remove the worktree.

Map work in a worktree runs against the worktree's own copy of the workspace, not the real one. `sabermapper/workspace/` in the main checkout is user data, shared by the studio and every agent. First, run `workspace clone` from the worktree's `sabermapper/` folder. It links the audio and copies everything else in about 15 s. Every project command with `--workspace workspace` (check, save, style save, lights, export) then reads and writes that clone, without waiting on other agents' locks. Once the code is committed and merged into `main`, run `workspace publish`. It copies only the files the worktree changed into the real workspace, then you remove the worktree. A project the real workspace also changed since the clone (a studio save, another agent's publish) is held back, never overwritten. Publish exits 2 and gives the `project save` command that reapplies the change. `workspace status` lists what would be published. Report the publish result along with the merge.

When a turn made code changes and they were committed and merged into `main`, end the final message with this exact line:

👉 commited and merged into main

Only write that line once the commit and merge have actually succeeded. If tests fail or the merge is blocked, say so instead.

## Player and skills

Read @PLAYER.md for the default player's confirmed ScoreSaber identity, historical skill evidence and mapping baseline. Apply this calibration when composing, including requests labeled “Expert”; consult `sabermapper/workspace/player-profile.json` for newer explicit preferences and overrides.

Claude skills are installed at the workspace root:

- `/sabermapper-map` — author a new map or arrangement.
- `/sabermapper-review` — inspect feedback and revise a scoped section.
- `/sabermapper-research` — research and retrieve reference patterns.
- `/sabermapper-vivify` — build, verify in the game and refine a vivified (Vivify) map.

Run application commands from `sabermapper/` using `.venv/Scripts/python`. Read the current project and revision before editing; preserve locks and save with `project save`. Finish work by saving and exporting, then report the project, revision and the checks actually run; do not launch ArcViewer or the studio preview. Canonical skill sources are in `sabermapper/skills/`; refresh both agent copies with `.venv/Scripts/python scripts/install_skills.py --update` from that directory.
