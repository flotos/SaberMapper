# SaberMapper Bridge: driving and capturing Beat Saber from the agent

Ticket: `tickets/vivify/base-ticket.md`, milestones M0 (bridge spike), M1 CLI twins and M2 `game capture`.
Lease protocol: [game-lease.md](game-lease.md). Frame review of the captures: `sabermapper frames ...`.

The bridge is a BSIPA plugin (`SaberMapperBridge`) that runs inside Beat Saber and serves a JSON API on
**127.0.0.1 only**. The Python side (`sabermapper/game/`) exports and installs maps, launches the game
under the machine-wide lease, and drives the bridge. Every command except `GET /health` needs the
current lease token.

```
agent CLI / studio ──► sabermapper.game.api ──► BridgeClient (HTTP, X-SaberMapper-Lease) ──► SaberMapperBridge.dll
        │                     │                                                           (Unity main thread)
        │                     ├─ install.py: export ZIP ─► CustomWIPLevels/SaberMapper-<id>/
        │                     └─ launch.py: Beat Saber.exe [fpfc]
        └─ lease.py: %LOCALAPPDATA%/SaberMapper/game-lease.json (token = bridge credential)
```

## Build and install

No .NET SDK is installed, so the supported build calls Roslyn directly (`sabermapper/game/build.py`):

```
.venv/Scripts/python -m sabermapper game build-bridge [--install] [--csc PATH] [--game-dir DIR]
.venv/Scripts/python scripts/build_game_bridge.py --install        # same thing
```

- Compiler: `C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools/MSBuild/Current/Bin/Roslyn/csc.exe`
  (or `--csc`, `$SABERMAPPER_CSC`). Missing compiler: `{"error": {"code": "csc_missing", ...}}`.
- Flags: `-nostdlib+ -noconfig -target:library -langversion:latest -deterministic`, referencing the game's
  own `Beat Saber_Data/Managed/*.dll` (mscorlib/netstandard included) and `Plugins/SongCore.dll`
  (`build.REFERENCES`).
- BSIPA reads plugin metadata from an embedded resource whose name ends in `.manifest.json`
  (`IPA.Loader.PluginLoader.LoadMetadata`), so `manifest.json` is embedded as `SaberMapperBridge.manifest.json`.
- Output: `sabermapper/game-bridge/bin/SaberMapperBridge.dll` (git-ignored). `--install` copies it to
  `<game>/Plugins/` and refuses with `game_running` while the game is open (the DLL loads only at startup).
- Compile failures: `bridge_compile_failed` with `details.errors = [{file, line, column, severity, code, message}]`.
- `SaberMapperBridge.csproj` is kept for a future `dotnet build`; keep its references in sync with `build.REFERENCES`.

Manifest: `id`/`name` `SaberMapperBridge`, `gameVersion` 1.40.8, `dependsOn` BSIPA `^4.3.0` and SongCore
`^3.15.0`. No SiraUtil/Harmony dependency: game objects are found with `Resources.FindObjectsOfTypeAll`
(scene instances only) and private members through reflection.

Configuration (optional, read-only; the bridge never creates or rewrites UserData files):
`UserData/SaberMapperBridge.json` `{"port": 28765, "run_in_background": true}`, or `$SABERMAPPER_BRIDGE_PORT`.
At startup the bridge writes `%LOCALAPPDATA%/SaberMapper/bridge.json` `{port, pid, bridge_version,
game_version, started_at}` (removed on exit); the client takes the port from it. `$SABERMAPPER_LEASE_DIR`
moves both files (the game inherits the launcher's environment). `run_in_background` keeps Unity rendering
when the FPFC window loses focus (runtime only, not a saved setting).

## Launch method

`launch.py` starts `Beat Saber.exe` directly (cwd = game dir) with `SteamAppId`, `SteamGameId` and
`SteamOverlayGameId` = 620980 in its environment, plus the SiraUtil `fpfc` argument for agent runs.
Observed on 2026-09-23: the started pid is the game process itself (no Steam relaunch, so arguments survive
and `game_pid` is exact); Steam was running. The bridge answered `/health` about 12 s after launch and
reported the menu with SongCore ready at about 7 s of game realtime. The studio's human path launches the
same executable without `fpfc` (VR).

Closing: `close_game(pid)` sends `taskkill /PID` (WM_CLOSE), waits 20 s, then forces. The game always closed
politely in the experiments. Only a game the session launched and still leases is ever closed.

## HTTP API

Base `http://127.0.0.1:28765`. Bodies and answers are JSON. Errors: `{"error": {"code", "message",
"details"}}` with HTTP 4xx/5xx. Commands run on the Unity main thread (15 s timeout: `timeout`).

Lease check (every endpoint except `GET /health`): the bridge rereads `game-lease.json` per request
(`FileShare.ReadWrite | Delete`, retry after 50 ms on partial JSON) and compares `X-SaberMapper-Lease` with
its `token` in constant time. No file: 403 `lease_not_held`. Wrong or missing header: 403 `lease_invalid`.
The Python client turns a 403 after a human takeover into `game_preempted` via `lease.check_owner`.

| Endpoint | Body | Answer / notes |
| --- | --- | --- |
| `GET /health` | - | `{bridge_version, game_version, unity_version, scene, pid, port}` (no lease) |
| `GET /state` | `?wait_ms=N&since=V` | snapshot below; long-polls until `version` != `since` (or changes) or N ms (max 60 000) |
| `POST /refresh` | `{full=false, wait_ms=0}` | SongCore `RefreshSongs(full)`; waits for `SongsLoadedEvent`. Menu only: `not_in_menu` (409) in a level, because SongCore ignores refreshes during gameplay |
| `POST /load` | `{level_path \| level_id, characteristic="Standard", difficulty=hardest, start_time=0, speed=1, modifiers="no_fail"\|"player", hud=true}` | `{accepted, returning_to_menu, load}`; returns to the menu first when a level runs. Errors: `songs_loading`, `level_not_found` (lists WIP folders), `characteristic_not_found`, `difficulty_not_found` (lists available), `missing_requirement` (also logged as `missing requirement X for PATH`) |
| `POST /pause` / `POST /resume` | - | `PauseController.Pause()` / the pause menu's continue handler (about 1 s resume animation). `not_in_level` outside a level |
| `POST /restart` | `{start_time?}` | restart the current level, optionally at a new time |
| `POST /seek` | `{time}` | = restart at `time` (see *Seek strategy*) |
| `POST /menu` | - | `StandardLevelReturnToMenuController.ReturnToMenu()`; cancels a pending load |
| `POST /capture` | `{frames:[{time, name, reason?}], probe?:{start, end, fps, hide_notes=false}, out_dir, camera="player"\|"wide", width?, height?, hide_notes=false}` | starts a job; `capture_busy` if one runs. `hide_notes` hides notes on every frame, `probe.hide_notes` on probe frames only (see *Hidden notes*) |
| `GET /capture` | - | job status with every frame `{name, file, requested_time, song_time, frame, reason, written, notes_hidden, hidden_renderers, error?}` |
| `POST /capture/cancel` | - | cancels the running job |

`/state` snapshot (updated every frame; `version` increments on discrete changes):
`{scene: "menu"|"loading"|"game"|"results", level: {level_id, level_path, characteristic, difficulty,
song_name, practice_start_time}|null, song_time, song_length, paused, speed, fps, capture: {job_id, status,
requested, captured, written, pending, dropped, error, hide_notes, notes_hidden_frames, probe: {start, end, fps,
finished, hide_notes}}|null, autoplay: false, songs_loading,
songs_ready, pending_load, last_load, last_end_state, last_error, realtime, version}`.
`results` means the level the bridge started ended cleared/failed; the game shows no results screen
because the bridge, not the level-selection flow, owns the level.

Level markers: the bridge logs `[SaberMapperBridge] level_start <level_path>` **when it starts or restarts
a level, before the beatmap is deserialized**, so Heck/Vivify parse errors fall inside the level scope of
`sabermapper game logs --level`; and `level_end` when the level scene goes away. A level the user starts
from the game's own menus gets its marker when its audio starts.

### Deviation: polling instead of WebSocket

Mono's `HttpListener` in this Unity build has no WebSocket support. State is served by `GET /state` with
`wait_ms`/`since` long-polling, which is what the CLI and studio use. Median round trip in the
experiments: 3 ms.

## Level start, speed and modifiers

Levels start through `MenuTransitionsHelper.StartStandardLevel` with `PracticeSettings(start_time, speed)`.
Practice mode starts the audio about **1 s before** `start_time` (seek to 100 s: first sample 99.03 s), so
clients wait for `song_time >= start_time`. Agent loads use `modifiers="no_fail"` (no modifiers except
No Fail, so a run with nobody at the sabers never fails); the studio's human play uses the player's own
modifiers. `hud=false` sets `noTextsAndHuds` for cleaner frames. All bridge levels are practice runs. At
level end ScoreSaber still logged "Starting upload process" and "Replay written" for the WIP level;
`UserData/ScoreSaber/Replays` was unchanged and WIP levels have no leaderboard. Nothing further was verified.

## Seek strategy (M0 experiment 3)

`seek` and `restart --at` mutate the running level's `PracticeSettings.startSongTime` (creating one when the
level was not started in practice mode) and call `StandardLevelRestartController.RestartLevel()`: the game
reloads its gameplay scenes in about 0.5-0.6 s and plays from `time - 1 s`. When no level runs, the last
load is repeated at the new time. `AudioTimeSyncController.SeekTo` exists, but moving the audio would not
respawn notes/walls or rebuild Heck/Vivify state, so it is not used.

**Late starts are not exact for Heck/Vivify maps** (see the experiment below): object creation/destruction
events before the start are replayed, but property animations that finished before the start are not.
Consequences:

- Scrubbing for the human (studio slider, `game seek`) is restart-at-time: fast, and faithful for notes,
  but Vivify materials may differ from a from-zero run until the next keyframes.
- `game capture` plays **from 0 by default when the installed map has Heck-family requirements or
  `customEvents`** (`install.uses_custom_events`); vanilla maps start 3 s before the first frame.
  `--exact` forces 0, `--fast-start` forces the pre-roll start.

## Capture

Frames are grabbed in a `WaitForEndOfFrame` coroutine on the first rendered frame whose song time is at or
after each requested time, only while the level plays (never in pause or loading). `ScreenCapture.
CaptureScreenshotIntoRenderTexture` takes the final backbuffer, i.e. the FPFC view **after every image
effect, including Vivify `Blit` post-processing**. `AsyncGPUReadback` returns the pixels; PNG encoding
(`ImageConversion.EncodeArrayToPNG`, RGB) runs on worker threads so gameplay keeps its frame rate
(33 frames at 30 fps plus stills: 0 dropped at 144 fps). On D3D11 the screen copy arrives upside down
(`SystemInfo.graphicsUVStartsAtTop`) and is flipped; camera render textures arrive top row first.
`width`/`height` rescale with a GPU blit; default size is the game window (1280x720 in these runs).

- `camera="player"`: the desktop FPFC camera as shown on screen (the SiraUtil FPFC view; Camera2 is
  installed and Vivify logs "Enabling Vivify Cam2 post-processing on [Main]"; the captured screen showed
  the FPFC view with post-processing).
- `camera="wide"`: an extra camera at (0, 4.5, -8) looking at (0, 1.2, 14), 70° FOV, rendered with the main
  camera's settings. Vivify post-processing is attached to the main/Camera2 cameras, so **wide frames lack
  Vivify blits** (observed: glitch pass absent in the wide frame taken during a blit), and they skip the
  game's own bloom pass.
- A `main` mode (render `Camera.main` into a texture) was tried and removed: it bypasses the game's
  bloom/tonemapping and produced washed-out light-blue frames.
- Probe mode `{start, end, fps}` captures `probe-NNNNN.png` at a fixed rate for the flash check.
- Hidden notes (bridge 0.2.0): nobody cuts notes during a capture (there is no autoplay), so uncut notes fly
  through the FPFC camera and fill up to half the frame for a single frame each. A player cuts them about 1 m
  ahead and never sees that. On a frame with `hide_notes`, the bridge sets `Renderer.forceRenderingOff` on every
  renderer under the active `NoteController`s (notes, bombs, chains, including Vivify note prefabs parented under
  them) and `SliderController`s (arcs) at the first camera cull of that frame, after every `LateUpdate`, and
  turns exactly those renderers back on after the end-of-frame grab. Walls, sabers, the environment and Vivify
  scene objects stay visible, and gameplay is unchanged. Requests due in a frame are taken in `LateUpdate`; a
  regular frame that keeps notes and falls due together with a notes-hidden probe frame waits one render frame
  (about 7 ms at 144 fps), so it never shares that render. Each frame reports `notes_hidden` (hiding actually ran
  that frame) and `hidden_renderers`.
- Timing: captured `song_time` was within 7 ms after the requested time at 144 fps in every run.

## CLI

Every command prints JSON; errors print `{"error": {...}}` and exit 2. Identity: `--session`, `--holder`
(defaults from the lease module). `--game-dir` or `$SABERMAPPER_GAME_DIR` selects the install.

```
sabermapper game build-bridge [--install]
sabermapper game launch [--fpfc|--vr] [--wait S] [--purpose TEXT] [--project ID]
sabermapper game status
sabermapper game install PROJECT [--difficulty D] [--revision R] [--no-refresh] --workspace W
sabermapper game play PROJECT [--difficulty D] [--at S] [--speed X] [--revision R] [--no-hud] --workspace W
sabermapper game seek S | pause | resume | restart [--at S] | stop | refresh
sabermapper game close                     # only a game this session launched and still leases; releases
sabermapper game capture PROJECT [--difficulty D] [--revision R] [--times T1,T2] [--every-beats N]
        [--probe START-END@FPS | --no-probe] [--probe-with-notes] [--camera player|wide] [--width W] [--height H] [--out DIR]
        [--wait S] [--speed X] [--exact|--fast-start] [--keep-open] [--no-hud] --workspace W
```

`game install` exports the revision (`ProjectStore.export`, or an older saved revision through
`revision_arrangement`; unknown revisions: `stale_revision`), replaces
`CustomWIPLevels/SaberMapper-<project_id>/` atomically and writes `sabermapper-install.json`
`{project, revision, difficulty, export, current_revision, installed_at, source}`. `game play` also returns
to the menu, runs a **full** SongCore refresh (a non-full refresh skips folders it already knows, so a
replaced install would keep the old map) and loads at `--at`.

`game capture` is self-contained: `held_lease` (queue with `--wait`), launch FPFC if the session has no
game, install + refresh, load, capture, write `capture.json`, then close the game it launched and release
the lease in `finally` (unless `--keep-open`, which keeps both). Default frame set without `--times`: every
section start, every key moment from `listen.latest_listen` (when that module and a listen run exist),
every 16 beats; duplicates within 0.1 s merge (priority requested > section_start > moment > grid). A 3 s,
30 fps probe is added by default at the strongest moment (drops first), else at the densest 3 s of notes.
Probe frames are rendered with notes hidden (`probe.hide_notes`, see *Hidden notes*): the flash check measures
the scene the player sees, not uncut notes hitting the camera. `--probe-with-notes` keeps them. The report's
`probe_notes_hidden` counts the probe frames rendered without notes, and a `probe_notes_visible` warning names a
bridge that did not hide them (older than 0.2.0: rebuild and install it).
Default output: `<project>/captures/<revision[:10]>-<UTC timestamp>/`.

`capture.json` (schema 1, read by `frames.py`):
`{schema_version, project, revision, difficulty, camera, width, height, game_version, level_path,
created_at, start_time, exact, speed, probe, bridge_version, frames: [{file, requested_time, song_time,
beat, section_id, reason: section_start|moment|grid|requested|probe, notes_hidden?}], log_diagnostics: [...]}`
(`notes_hidden: true` only on frames rendered with notes hidden; `probe` records `hide_notes`) where
`log_diagnostics` is `game logs --level <level_path>` for this run.

Example (real run, project `4692e8dfb4df`, 48 s wall time including launch and close):

```
$ sabermapper game capture 4692e8dfb4df --workspace workspace --times 30,45,60 --probe 50-52@30
{"status": "done", "frames": 64, "start_time": 27.0, "exact": false, "custom_events": false,
 "launched": true, "closed": true, "dropped": 0, "log_errors": 0, "manifest": ".../capture.json", ...}
```

## Studio functions (`sabermapper.game.api`)

`status()`, `lease_status()`, `play(store, project_id, *, seconds=0.0, difficulty=None, revision=None,
mode="play"|"watch", human=True)`, `pause()`, `resume()`, `restart(seconds=None)`, `seek(seconds)`, `stop()`.
They use session `studio` with `holder_kind="human"`, so `play` preempts any agent lease (the agent's next
check fails with `game_preempted`). If no game runs, `play` launches it in VR and waits for the bridge.
If the running game is an FPFC instance started by this tooling (`game-launch.json` records pid and mode),
`play` closes it and relaunches in VR, because FPFC cannot be played in a headset. `stop()` returns to the
menu and releases the studio lease; the user's game keeps running. `mode="watch"` returns
`{"watch": "unavailable", "message": ...}` without touching the game until ghost autoplay exists (M6).

## M0 acceptance experiments (2026-09-23)

All runs: FPFC, game 1.40.8_7379, Unity 2022.3.33f1, bridge 0.1.0, leased by `agent:SaberMapper-vivify-bridge`,
game launched and closed by the agent. The EXSII files were installed only as
`CustomWIPLevels/SaberMapper-test-exsii-07/` and removed afterwards; their frames stay out of the repo.

1. **Vanilla play and song time: passed.** `game play 4692e8dfb4df --at 60` (vanilla export, revision
   `516baeec6e`) started the level with `practice_start_time` 60.0 (first sample 60.04 s after the 1 s
   lead-in). Three `game status` calls one second apart reported 61.12, 62.12 and 63.15 s. Sixty `/state`
   samples at 50 ms spacing fitted song time = wall time x 1.00002 with a maximum residual of 9.8 ms and a
   median round trip of 3 ms, well inside the 0.1 s requirement.
2. **Vivify in FPFC: renders.** EXSII *luminescent* (`07-43a26`, ExpertPlus, Noodle + Chroma + Vivify, the
   2021 bundle from LunarRepo) loaded without bundle, CRC or shader errors in Unity 2022.3.33. Frames read:
   t=20 s (galaxy skybox prefab and star field, full frame), 37.2 s (Blit glitch/pixelate/VHS passes over the
   whole screen, colour-fringed kaleidoscope), 55 s (fractal skybox), 62 s (speckles skybox), 75 s (blit
   distortion). No magenta/missing shaders, no black or one-eye/half-frame output: the single-pass-instanced
   shaders rendered correctly on the non-VR FPFC camera. Heck logged two map-data errors at deserialization,
   `Could not parse custom data for custom event [AnimateTrack] at [103.5]` and `[199.5]`
   (`Could not find track [MainNoteTrack]`). Vivify logged no warnings or errors during the level.
3. **Late start: not exact.** Same song times, from-zero run vs late starts:
   - Vivify's debug log shows every `InstantiatePrefab`/`DestroyPrefab` before the start replayed in the
     first frame (late start at 60 s: Sky1/Stars created and destroyed, Sky2 created, Sky3 created), and
     the late-start frame at 62 s shows the Sky3 speckles like the from-zero frame.
   - `SetMaterialProperty` animations that ended before the start are **not** applied: `star.mat
     _StarBright` animates 0->1 over beats 6-14 (2.1-4.9 s). At 20 s the from-zero frame shows the star
     field; the frame from a start at 15 s shows the galaxy but no stars.
   - The fractal skybox at 55 s had a different shape in the from-zero run and in a start at 50 s,
     consistent with materials animated by Unity time rather than song time; pixel-exact comparisons
     across runs are not meaningful for such materials.
   Decision: seek = restart-at-time; captures of Heck/Vivify maps play from 0 (see *Seek strategy*).

## Deviations from the ticket

- **Game 1.40.8_7379** (the installed build) instead of 1.45.1; APIs were checked against these assemblies.
- **Roslyn csc instead of `dotnet build`**: no .NET SDK is installed; the csproj is kept for later.
- **Polling (`/state?wait_ms=`) instead of a WebSocket stream**: Mono's HttpListener has no WebSockets.
- **Seek is restart-at-time**, not an in-level seek, and not exact for Heck/Vivify state (measured above).
- The "wide" camera exists but has no Vivify post-processing; the "player" camera is the verification view.

## Ghost autoplay (M6): findings, not implemented

- BeatLeader 0.9.33 (installed) can play replays in-game: `BeatLeader.Models.Replay.ReplayDecoder.
  DecodeReplay(byte[])` parses a BSOR file and `BeatLeader.Replayer.ReplayerLauncher.StartReplay(
  ReplayLaunchData, Action)` launches it (`ReplayLaunchData.Init(replay, comparator, settings, level, key,
  environment)`). The shortest path to *Watch* is: the agent writes a BSOR (open format: head and saber poses
  per frame plus note events) from the `movement.py` path, and the bridge launches it through reflection
  (a soft dependency; `watch_unavailable` when BeatLeader is missing).
- Alternative without BeatLeader: in FPFC, override the saber transforms each frame (`SaberManager` /
  `VRController` positions in `LateUpdate`). This needs Harmony or SiraUtil hooks to beat the FPFC mouse
  controller and gives no hit/miss scoring.
- Either way, frames with moving sabers come from the same capture path.

## Limitations and notes

- Captures run only while the level plays; a job whose level ends early is cancelled and reports
  `not_reached` frames.
- SongCore refreshes only in the menu, and a full refresh costs more as the song library grows (4 songs
  here: under 0.1 s).
- Agent runs are FPFC desktop renders: no VR scale, comfort or performance evidence. The human playtest
  stays the ground truth.
- The bridge must be rebuilt for each game update (`installed-game-target.json` pins the version).
