# Game lease and game log diagnostics

Several agents run in parallel worktrees on one machine, and the user can start Beat Saber from the
studio at any time. Only one party may drive the single Beat Saber instance. The **game lease** is a
machine-wide file that says who that party is, and its token is the credential the SaberMapper Bridge
mod accepts. Code: `sabermapper/game/lease.py`, `process.py`, `errors.py`; CLI: `sabermapper game lease`.

**Rule: the human always wins.** When the user presses *Play in game*, any agent lease is revoked.
The agent's next lease check fails with `game_preempted`, which means **retry later. It is never a map
defect** and must not trigger map changes.

## Files

All files live in `%LOCALAPPDATA%/SaberMapper/`, outside every worktree. Set `SABERMAPPER_LEASE_DIR`
to use another directory (tests do this). Every function also accepts an explicit `root`.

| File | Purpose |
| --- | --- |
| `game-lease.json` | The live lease, or absent when nobody holds the game |
| `game-lease.lock` | Short-lived lock around every read-modify-write (exclusive create, broken after 10 s) |
| `sessions/<session>.json` | `{session, holder, token, acquired_at}`: lets later CLI calls in a session prove ownership |
| `game-lease-revocations.jsonl` | One line per revoked token: `{token_sha256, holder, session, revoked_at, by}` (last 500 kept) |

The lease file is created with `os.open(O_CREAT|O_EXCL)`. Updates write a temp file and `os.replace`
it. Writers retry for up to 2 s when Windows refuses a replace because a reader has the file open.

## Lease schema (`schema_version` 1)

```json
{
  "schema_version": 1,
  "token": "<secrets.token_urlsafe(32)>",
  "holder": "agent:SaberMapper-vivify-lease",
  "holder_kind": "agent",
  "session": "<sha1 of the worktree path>",
  "worktree": "C:/Users/.../SaberMapper-vivify-lease",
  "project": "sm-demo",
  "purpose": "capture sm-demo",
  "game_pid": 12345,
  "launched_by_agent": true,
  "holder_pid": 6789,
  "acquired_at": "2026-09-23T10:00:00.000+00:00",
  "heartbeat_at": "2026-09-23T10:00:30.000+00:00",
  "previous": null
}
```

`holder_kind` is `agent` or `human`. `game_pid` is null until the holder launches or adopts the game.
`holder_pid` is informational. CLI calls are short-lived processes, so liveness never depends on it.
`previous` records the lease this one replaced:

- stale reclaim: `{holder, session, reclaimed_at, reason}`, with reason `game_exited`,
  `heartbeat_expired` or `invalid`;
- human takeover: `{holder, holder_kind, session, revoked_at, reason: "preempted_by_human"|"replaced_by_human", token_sha256}`.

## Sessions and holders

An agent's CLI calls are separate processes, so the holder is a *session*, not a process.

- Default session: the sha1 of the git worktree top-level path (lower-cased on Windows), or of the
  cwd when outside git. Override it with `--session` or `SABERMAPPER_SESSION` (`[A-Za-z0-9_.-]{1,128}`).
- Default holder: `agent:<worktree folder name>`. Override it with `--holder`.
- The studio uses its own session (for example `studio`) with `holder_kind="human"`.

`own_lease(session)` returns the lease only when the session's stored token equals the live token.

## Liveness and staleness

A lease is **live** unless:

1. `game_pid` is set and that process is dead (`game_exited`), or
2. `heartbeat_at` is older than `STALE_AFTER` (600 s by default; set it with the `stale_after` argument
   or `SABERMAPPER_LEASE_STALE_AFTER`) (`heartbeat_expired`).

Reclaiming replaces the stale lease. It **never kills anything**. If the heartbeat expired but the
recorded game is still running, the lease is not reclaimed: acquisition fails with `game_busy`
reason `orphaned_agent_game` (or `human_game`), and the fix asks the user to close that window.
Agents never adopt a game they did not launch.

`held_lease` heartbeats every 30 s. Commands that run longer than a few minutes outside `held_lease`
must call `heartbeat()` (`game lease --heartbeat`).

## Operations (Python, `sabermapper.game.lease`)

`GameLease(root=None, *, game_running=None, pid_alive=None, stale_after=None, clock=time.time)` binds a
lease directory and an injectable process view. Module-level wrappers take the same arguments.

- `acquire(holder, *, session, worktree, project, purpose, holder_kind="agent", wait=0.0)`:
  - same session already holds it: refreshes the heartbeat and returns it (idempotent, same token);
  - another live holder: `game_busy` (reason `held`) naming holder, holder_kind, purpose, project,
    acquired_at and heartbeat age;
  - no lease but `Beat Saber.exe` running: `game_busy` reason `unleased_game`. The user, or an agent
    that bypassed the lease, is using the game;
  - stale lease: see above;
  - `wait > 0`: polls every 2 s until free or the deadline, then `game_busy` with `details.waited_s`;
  - `holder_kind="human"`: always succeeds. It replaces any lease with a new token, appends the old
    token to the revocations file, and adopts a running game (`game_pid` = the running pid;
    `launched_by_agent` is kept when it is the previous holder's game, else false).
- `heartbeat(session)`, `set_game_pid(session, pid, launched_by_agent)`: holder only.
- `check_owner(session)`: call before **every** bridge command. It returns the lease, or raises
  `game_preempted` (the session's token was revoked), `game_busy` (someone else holds it;
  `details.your_lease_reclaimed` when your stale lease was reclaimed) or `lease_not_held`.
- `release(session)`: deletes this session's lease. A preempted session gets
  `{"released": false, "reason": "game_preempted", ...}` and the human's lease stays. Any other
  non-holder gets `lease_not_held`.
- `status(session)`: `{lease (token redacted to token_sha256), live, stale_reason, game_running, game_pids, own, ...}`.
- `held_lease(holder, *, session, on_release, heartbeat_every=30, manager=None, **acquire_args)`: a
  context manager for capture runs. It acquires, heartbeats from a daemon thread, and on exit
  (including exceptions) calls `on_release(lease)` and then releases. `on_release` runs **only if the
  session still owns the lease**, so "close the game if `launched_by_agent`" can never close the
  user's game after a preemption. The yielded handle has `.lease`, `.token`, `.check()`,
  `.set_game_pid()` and `.preempted`.

Process helpers (`sabermapper.game.process`): `find_game_pids()` (ctypes Toolhelp snapshot, with a
`tasklist` fallback) and `pid_alive(pid)` (OpenProcess + GetExitCodeProcess == STILL_ACTIVE).

## Bridge contract

The token **is** the bridge credential.

- `game launch` passes the token to the game. The bridge still rereads `game-lease.json` on every
  command and rejects any request whose `X-SaberMapper-Lease` header differs from `token`. Tokens
  rotate on every ownership change, so a preempted agent is rejected immediately, with no message
  needed.
- The bridge opens the file with `FileShare.ReadWrite | FileShare.Delete` and keeps it open only
  briefly. If JSON parsing fails (it caught a write mid-way), it retries after about 50 ms before
  rejecting.
- A missing lease file authorizes nobody: reject every command. The studio acquires a human lease
  before it drives the game, so every legitimate command carries a token. The user playing through
  the game's own menus never touches the bridge API.
- The bridge logs `[SaberMapperBridge] level_start <level_path>` when a level starts and
  `[SaberMapperBridge] level_end` when it ends. These are the authoritative markers for `game logs`.

## Studio contract

*Play in game* first calls `status()`. If an agent holds a live lease, the studio shows the holder,
purpose, project and heartbeat age. Continuing calls `acquire(holder_kind="human", session="studio")`,
which revokes the agent (its capture fails with `game_preempted`). The studio heartbeats while it plays
and releases when done.

## Error codes (`sabermapper.game.errors.GameError`)

The CLI prints `{"error": {"code", "message", "details", "fix"}}` on stdout and exits **2**. Other
exceptions keep the `error: ...` stderr line and exit 1.

| Code | Meaning | Agent action |
| --- | --- | --- |
| `game_busy` | Another live holder, an unleased running game (`unleased_game`), or an orphaned game (`orphaned_agent_game`/`human_game`) | Retry later or `--wait`; never kill or adopt the game |
| `game_preempted` | The user took the game over | **Retry later. Not a map defect**; do not change the map |
| `lease_not_held` | This session holds no lease | Acquire first |
| `lease_invalid` | Bad session id or missing required option | Fix the call |
| `game_not_found` | Game install or log missing | Pass `--game-dir`/`--log` or set `SABERMAPPER_GAME_DIR` |
| `game_not_running` | Beat Saber is not running | Launch it through the leased commands |
| `bridge_unreachable` | The bridge mod did not answer | Check the bridge install and `game logs` |
| `timeout` | Deadline passed (for example the lease lock) | Retry; delete a stuck lock only if no command runs |

## CLI

```
sabermapper game lease                                   # status JSON
sabermapper game lease --acquire --purpose TEXT [--project ID] [--wait SECONDS]
sabermapper game lease --heartbeat
sabermapper game lease --release                         # own lease only
  common: --session ID --holder NAME
```

## `game logs`

```
sabermapper game logs [--log PATH | --game-dir DIR] [--since-level | --level PATH] [--all] [--info] [--limit N]
```

This parses the BSIPA log (`GAME_DIR/Logs/_latest.log`, `SABERMAPPER_GAME_DIR` or the Steam path by
default). Line format: `[LEVEL @ HH:MM:SS | Source] message`. BSIPA prefixes each line of an
exception, so indented stack lines, and an exception header that directly follows a message from the
same logger, are grouped into `trace`. Unprefixed lines are continuations.

Output: `{log, game_version, level, scope, counts:{error, warning}, codes, total, truncated, diagnostics}`.
Each diagnostic is `{severity, source, logger, code, time, line, message, trace, fix, level_scope}`.

- Mod filter: Heck, Chroma, NoodleExtensions, Vivify, CustomJSONData, SongCore, SiraUtil and
  SaberMapperBridge. It also keeps any classified failure and any error-level exception from any
  source. `--all` disables the filter. Only errors and warnings are listed unless `--info` is passed.
- Level scope: the bridge `level_start` marker is authoritative. Without it, the fallback is Heck's
  TRACE line `Deserializing BeatmapData` (DeserializerManager), which BSIPA shows only when trace
  logging is enabled. `--since-level` keeps records from the last start marker on (`scope.found=false`
  and no diagnostics when there is none). `--level PATH` keeps the last run of that level, matched by
  full path or folder name. `level_scope` flags records after the last start marker.
- Classified codes. Wording comes from Aeroluna/Vivify, Aeroluna/Heck, Kylemc1413/SongCore and Unity
  player messages:

| Code | Matches |
| --- | --- |
| `bundle_checksum_mismatch` | Unity `CRC Mismatch. Provided ..., calculated ...` |
| `bundle_checksum_missing` | Vivify `Checksum not defined` (no `_assetBundle._windows2021` in Info.dat) |
| `bundle_missing` | Vivify `[bundleWindows2021.vivify] not found`, `... not found, attempting to download remotely` |
| `bundle_load_failed` | Vivify `Failed to load [path]`; Unity `Unable to open archive file`, wrong version/build target |
| `asset_not_found` | Vivify `Could not find <Type> [name]`, `Found X, but was null or not [Type]`, `No prefab with id [id] detected` |
| `shader_error` | Unity `Shader Unsupported`, `is not supported on this GPU`, shader compile errors |
| `custom_data_parse_error` | Heck `Could not parse custom data for ... at [beat]` (+ exception trace) |
| `json_parse_error` | Newtonsoft `JsonReaderException`/`JsonSerializationException`; SongCore `Error loading beatmap version.` |
| `level_load_failed` | SongCore `Failed to load custom level/song/song folder`, `Error in Level`, unknown characteristic |
| `custom_event_invalid` | Vivify `[key] not recognized`, `No track defined`; Heck duplicate event/point definition |
| `missing_requirement` | Any line containing "missing requirement". SongCore shows this only in its UI, so the bridge logs it |
| `harmony_patch_failed` | `HarmonyException`, `Patching exception in method` |
| `exception` | Any other exception |
| `log_error` / `log_warning` | Unclassified error or warning lines |
