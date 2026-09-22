# SaberMapper for Claude

The user's profile is in `PLAYER.md` at the repository root. Read @PLAYER.md before authoring or revising maps; it records the user's ScoreSaber identity, skill calibration and preferences.

This workspace contains a local Beat Saber authoring studio in `sabermapper/`. The agent composes JSON arrangements; the app handles audio analysis, revision storage, reference retrieval, local ArcViewer preview and ZIP export. It does not call an LLM itself.

Read @AGENTS.md for shared commands, directory layout and authoring boundaries.

Read @PLAYER.md for the default player's confirmed ScoreSaber identity, historical skill evidence and mapping baseline. Apply this calibration when composing, including requests labeled “Expert”; consult `sabermapper/workspace/player-profile.json` for newer explicit preferences and overrides.

Claude skills are installed at the workspace root:

- `/sabermapper-map` — author a new map or arrangement.
- `/sabermapper-review` — inspect feedback and revise a scoped section.
- `/sabermapper-research` — research and retrieve reference patterns.

Run application commands from `sabermapper/` using `.venv/Scripts/python`. Read the current project and revision before editing; preserve locks and save with `project save`. Use the studio's **3D preview** button for local ArcViewer playback. Canonical skill sources are in `sabermapper/skills/`; refresh both agent copies with `.venv/Scripts/python scripts/install_skills.py --update` from that directory.
