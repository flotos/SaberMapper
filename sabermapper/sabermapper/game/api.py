"""Game operations as plain dict-returning functions, shared by the `sabermapper game` CLI and the studio.

Agent commands (`launch`, `play_project`, `seek_to`, ...) take the caller's lease identity (`session`,
`holder`) and require that session to hold the machine-wide lease; they call `check_owner` and heartbeat
before every bridge command. The studio functions (`status`, `play`, `pause`, `resume`, `restart`, `seek`,
`stop`, `lease_status`) use the human session `studio`, whose lease preempts any agent. Every failure is a
`GameError` with a stable code. Protocol details: docs/game-bridge.md and docs/game-lease.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .bridge import BridgeClient
from .errors import GameError
from .install import install_project
from .launch import close_game, resolve_game_pid, start_game
from .lease import GameLease, check_session, default_session, lease_root, public_lease
from .process import find_game_pids, pid_alive

HUMAN_SESSION, HUMAN_HOLDER = "studio", "human:studio"
BOOT_TIMEOUT = 240.0
LOAD_TIMEOUT = 120.0
LAUNCH_RECORD = "game-launch.json"
BRIDGE_STATE_KEYS = ("scene", "level", "song_time", "song_length", "paused", "speed", "fps")


class Game:
    """Binds a lease directory, a game install and a lease session; injectable pieces for tests."""

    def __init__(self, *, session: str | None = None, holder: str | None = None, root=None, game_dir=None,
                 manager: GameLease | None = None, client_factory=None, launcher=None, closer=None,
                 find=find_game_pids, alive=pid_alive, boot_timeout: float = BOOT_TIMEOUT):
        self.manager = manager or GameLease(root)
        self.root = self.manager.root
        self.session = check_session(session or default_session())
        self.holder, self.game_dir = holder, game_dir
        self.client_factory = client_factory or (lambda token: BridgeClient(token, root=self.root))
        self.launcher = launcher or (lambda fpfc: resolve_game_pid(start_game(game_dir, fpfc=fpfc)))
        self.closer = closer or close_game
        self.find, self.alive, self.boot_timeout = find, alive, boot_timeout

    # ------------------------------------------------------------------ lease helpers
    def owned(self) -> dict:
        """check_owner + heartbeat; raises game_preempted / game_busy / lease_not_held."""
        self.manager.check_owner(self.session)
        return self.manager.heartbeat(self.session)

    def client(self, lease: dict | None = None) -> BridgeClient:
        lease = lease or self.owned()
        return self.client_factory(lease["token"])

    def launch_record(self) -> dict | None:
        try:
            return json.loads((Path(self.root) / LAUNCH_RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_launch_record(self, pid: int, fpfc: bool, holder_kind: str) -> None:
        path = Path(self.root)
        path.mkdir(parents=True, exist_ok=True)
        (path / LAUNCH_RECORD).write_text(json.dumps({
            "pid": pid, "fpfc": fpfc, "holder_kind": holder_kind, "session": self.session,
            "launched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2), encoding="utf-8")

    def running_mode(self, pid: int | None) -> str | None:
        """'fpfc' or 'vr' for a game this tooling launched, else None (unknown: started by the user)."""
        record = self.launch_record()
        if not pid or not record or record.get("pid") != pid:
            return None
        return "fpfc" if record.get("fpfc") else "vr"

    # ------------------------------------------------------------------ process
    def ensure_running(self, lease: dict, *, fpfc: bool, holder_kind: str = "agent") -> dict:
        """Start the game for this lease unless the lease's own game already runs. Returns launch info."""
        pids = self.find()
        pid = lease.get("game_pid")
        if pids and pid in pids:
            return {"launched": False, "pid": pid, "mode": self.running_mode(pid)}
        if pids:
            if holder_kind != "human":
                raise GameError("game_busy", "Beat Saber is running but not under this lease",
                                {"reason": "unleased_game", "game_pids": pids},
                                fix="Never take over a game you did not launch; retry later with --wait")
            self.manager.set_game_pid(self.session, pids[0], bool(lease.get("launched_by_agent")))
            return {"launched": False, "pid": pids[0], "mode": self.running_mode(pids[0])}
        pid = self.launcher(fpfc)
        self.manager.set_game_pid(self.session, pid, holder_kind == "agent")
        self._write_launch_record(pid, fpfc, holder_kind)
        return {"launched": True, "pid": pid, "mode": "fpfc" if fpfc else "vr"}

    def wait_ready(self, client: BridgeClient, pid: int, timeout: float | None = None) -> dict:
        """Wait for the bridge to answer and SongCore to finish loading the menu."""
        timeout = timeout or self.boot_timeout
        deadline = time.monotonic() + timeout
        health = client.wait_healthy(timeout, alive=lambda: self.alive(pid))
        state = client.wait_state(lambda s: s.get("songs_ready") and s.get("scene") in ("menu", "game", "results"),
                                  max(5.0, deadline - time.monotonic()), describe="the main menu",
                                  check=lambda: self.manager.check_owner(self.session))
        return {"health": health, "state": state}

    # ------------------------------------------------------------------ level
    def to_menu(self, client: BridgeClient, state: dict | None = None) -> dict:
        state = state or client.state()
        if state.get("scene") in ("game", "loading"):
            client.menu()
            state = client.wait_state(lambda s: s.get("scene") in ("menu", "results"), 60, describe="the menu",
                                      check=lambda: self.manager.check_owner(self.session))
        return state

    def install_refresh(self, client: BridgeClient, store, project_id: str, *, difficulty=None, revision=None) -> dict:
        """Export + install the revision, return to the menu and let SongCore reload (full refresh)."""
        installed = install_project(store, project_id, revision=revision, difficulty=difficulty, game_dir=self.game_dir)
        self.to_menu(client)
        refreshed = client.refresh(full=True, wait_ms=120000)
        if not refreshed.get("completed"):
            client.wait_state(lambda s: not s.get("songs_loading"), 120, describe="SongCore refresh")
        return {**installed, "refresh": refreshed}

    def install_and_load(self, client: BridgeClient, store, project_id: str, *, difficulty=None, revision=None,
                         at: float = 0.0, speed: float = 1.0, modifiers: str = "no_fail", hud: bool = True,
                         wait: bool = True) -> dict:
        installed = self.install_refresh(client, store, project_id, difficulty=difficulty, revision=revision)
        load = client.load(level_path=installed["level_path"], difficulty=installed["export"]["difficulty"],
                           start_time=at, speed=speed, modifiers=modifiers, hud=hud)
        state = self.wait_level(client, at) if wait else client.state()
        return {"install": installed, "refresh": installed["refresh"], "load": load, "state": _bridge_view(state)}

    def wait_level(self, client: BridgeClient, at: float, timeout: float = LOAD_TIMEOUT) -> dict:
        """Wait until the level plays at or after `at` (practice starts about a second early)."""
        return client.wait_state(lambda s: s.get("scene") == "game" and s.get("song_time") is not None
                                 and not s.get("paused") and s["song_time"] >= at - 0.05,
                                 timeout, describe=f"the level to play at {at:.2f} s",
                                 check=lambda: self.manager.check_owner(self.session))


def _bridge_view(state: dict | None) -> dict | None:
    return None if state is None else {key: state.get(key) for key in BRIDGE_STATE_KEYS}


def _identity(session=None, holder=None, **options) -> Game:
    return Game(session=session, holder=holder, **options)


# ====================================================================== agent commands

def launch(*, fpfc: bool = True, wait: float = 0.0, purpose: str = "game launch", project: str | None = None,
           **options) -> dict:
    """Acquire this session's agent lease (queueing up to `wait` s), start the game, wait for the menu."""
    game = _identity(**options)
    lease = game.manager.acquire(game.holder, session=game.session, project=project, purpose=purpose, wait=wait)
    info = game.ensure_running(lease, fpfc=fpfc)
    lease = game.owned()
    ready = game.wait_ready(game.client(lease), info["pid"])
    return {**info, "fpfc": fpfc if info["launched"] else info.get("mode") == "fpfc", **ready,
            "lease": public_lease(game.manager.own_lease(game.session), game.manager)}


def game_status(**options) -> dict:
    """Process, lease and (when this session owns the lease) bridge state."""
    game = _identity(**options)
    lease_info = game.manager.status(game.session)
    pids = game.find()
    result = {"running": bool(pids), "game_pids": pids, "lease": lease_info, "health": None, "bridge": None,
              "mode": game.running_mode(pids[0]) if pids else None}
    if not pids:
        return result
    try:
        result["health"] = game.client_factory(None).health()
    except GameError as error:
        result["health_error"] = error.to_dict()["error"]
        return result
    own = game.manager.own_lease(game.session)
    if own:
        try:
            state = game.client_factory(own["token"]).state()
            result["bridge"] = _bridge_view(state)
            result["bridge_state"] = state
        except GameError as error:
            result["bridge_error"] = error.to_dict()["error"]
    return result


def install(store, project_id: str, *, difficulty=None, revision=None, refresh: bool = True, **options) -> dict:
    """Export + install into CustomWIPLevels; refresh SongCore when this session drives a running game."""
    game = _identity(**options)
    result = install_project(store, project_id, revision=revision, difficulty=difficulty, game_dir=game.game_dir)
    result["refresh"] = None
    if refresh and game.manager.own_lease(game.session) and game.find():
        client = game.client()
        state = client.state()
        if state.get("scene") != "menu":
            result["refresh"] = {"skipped": True, "scene": state.get("scene"),
                                 "fix": "SongCore reloads only in the menu; `game play` returns to it and refreshes"}
        else:
            result["refresh"] = client.refresh(full=True, wait_ms=120000)
    return result


def refresh(**options) -> dict:
    """Return to the menu if needed, then full SongCore refresh."""
    game = _identity(**options)
    client = game.client()
    game.to_menu(client)
    return client.refresh(full=True, wait_ms=120000)


def play_project(store, project_id: str, *, difficulty=None, revision=None, at: float = 0.0, speed: float = 1.0,
                 modifiers: str = "no_fail", hud: bool = True, **options) -> dict:
    """Install the revision, refresh and start it at `at` seconds in the game this session leases."""
    game = _identity(**options)
    lease = game.owned()
    if not lease.get("game_pid") or lease["game_pid"] not in game.find():
        raise GameError("game_not_running", "The leased game is not running", {"game_pid": lease.get("game_pid")},
                        fix="Run `sabermapper game launch` first")
    result = game.install_and_load(game.client(lease), store, project_id, difficulty=difficulty, revision=revision,
                                   at=at, speed=speed, modifiers=modifiers, hud=hud)
    return {"project": project_id, "revision": result["install"]["record"]["revision"],
            "difficulty": result["install"]["record"]["difficulty"], "level_path": result["install"]["level_path"],
            "at": at, "speed": speed, **result}


def _drive(action: str, *args, wait_for=None, **options) -> dict:
    game = _identity(**options)
    client = game.client()
    result = getattr(client, action)(*args)
    state = wait_for(game, client) if wait_for else client.state()
    return {"action": action, "result": result, "state": _bridge_view(state)}


def seek_to(seconds: float, **options) -> dict:
    return _drive("seek", seconds, wait_for=lambda game, client: game.wait_level(client, seconds), **options)


def pause_game(**options) -> dict:
    return _drive("pause", **options)


def resume_game(**options) -> dict:
    return _drive("resume", wait_for=lambda game, client: client.wait_state(
        lambda s: not s.get("paused"), 10, describe="resume"), **options)


def restart_game(at: float | None = None, **options) -> dict:
    return _drive("restart", at, wait_for=lambda game, client: game.wait_level(client, at or 0.0), **options)


def menu(**options) -> dict:
    return _drive("menu", wait_for=lambda game, client: client.wait_state(
        lambda s: s.get("scene") in ("menu", "results"), 60, describe="the menu"), **options)


def close(**options) -> dict:
    """Close the game this session launched and still leases, then release the lease."""
    game = _identity(**options)
    lease = game.manager.check_owner(game.session)
    pid = lease.get("game_pid")
    if not lease.get("launched_by_agent") or not pid:
        raise GameError("game_not_launched_by_agent", "This session's lease does not record a game it launched",
                        {"game_pid": pid, "launched_by_agent": lease.get("launched_by_agent")},
                        fix="Only games started with `game launch`/`game capture` are closed; release with "
                            "`game lease --release`")
    closed = game.closer(pid)
    return {**closed, "release": game.manager.release(game.session)}


# ====================================================================== studio (human) functions

def _human(**options) -> Game:
    options.setdefault("session", HUMAN_SESSION)
    options.setdefault("holder", HUMAN_HOLDER)
    return Game(**options)


def _with_liveness(info: dict) -> dict:
    """Lease status whose inner lease also carries `live`/`stale` (the studio ignores dead leases)."""
    if isinstance(info.get("lease"), dict):
        info = {**info, "lease": {**info["lease"], "live": info.get("live"), "stale": not info.get("live")}}
    return info


def status(**options) -> dict:
    """Studio poll: {running, lease, bridge: {scene, level, song_time, song_length, paused, speed, fps}|null}."""
    game = _human(**options)
    result = game_status(session=game.session, holder=game.holder, manager=game.manager,
                         client_factory=game.client_factory, find=game.find, alive=game.alive)
    return {"running": result["running"], "lease": _with_liveness(result["lease"]), "bridge": result["bridge"],
            "health": result["health"], "mode": result["mode"]}


def lease_status(**options) -> dict:
    game = _human(**options)
    return _with_liveness(game.manager.status(game.session))


def play(store, project_id: str, *, seconds: float = 0.0, difficulty: str | None = None, revision: str | None = None,
         mode: str = "play", human: bool = True, **options) -> dict:
    """One-click *Play in game*: human lease (preempts agents), VR launch if needed, install, load at `seconds`.

    An agent's FPFC instance cannot be played in a headset, so it is closed and the game relaunched in VR.
    `mode="watch"` needs ghost autoplay (M6), which does not exist yet: it returns {"watch": "unavailable"}.
    """
    if mode not in ("play", "watch"):
        raise ValueError("mode must be play or watch")
    if mode == "watch":
        return {"watch": "unavailable", "message": "Ghost autoplay (Watch) is not implemented yet; use Play.",
                "project": project_id}
    game = _human(**options) if human else _identity(**options)
    kind = "human" if human else "agent"
    lease = game.manager.acquire(game.holder, session=game.session, project=project_id, holder_kind=kind,
                                 purpose=f"play {project_id}")
    pids = game.find()
    relaunched = None
    if human and pids and game.running_mode(pids[0]) == "fpfc":
        relaunched = game.closer(pids[0])
        lease = game.manager.set_game_pid(game.session, None, False)
    info = game.ensure_running(lease, fpfc=not human, holder_kind=kind)
    client = game.client()
    ready = game.wait_ready(client, info["pid"])
    result = game.install_and_load(client, store, project_id, difficulty=difficulty, revision=revision, at=seconds,
                                   modifiers="player" if human else "no_fail")
    return {"played": True, "project": project_id, "revision": result["install"]["record"]["revision"],
            "difficulty": result["install"]["record"]["difficulty"], "seconds": seconds,
            "level_path": result["install"]["level_path"], "launched": info["launched"], "mode": info["mode"],
            "closed_agent_fpfc": relaunched, "bridge": result["state"], "health": ready["health"]}


def pause(**options) -> dict:
    return pause_game(**{"session": HUMAN_SESSION, "holder": HUMAN_HOLDER, **options})


def resume(**options) -> dict:
    return resume_game(**{"session": HUMAN_SESSION, "holder": HUMAN_HOLDER, **options})


def restart(seconds: float | None = None, **options) -> dict:
    return restart_game(seconds, **{"session": HUMAN_SESSION, "holder": HUMAN_HOLDER, **options})


def seek(seconds: float, **options) -> dict:
    return seek_to(seconds, **{"session": HUMAN_SESSION, "holder": HUMAN_HOLDER, **options})


def stop(**options) -> dict:
    """Return to the menu and end the studio session (the game keeps running for the user)."""
    game = _human(**options)
    result = {"menu": None}
    if game.find():
        try:
            result["menu"] = menu(session=game.session, holder=game.holder, manager=game.manager,
                                  client_factory=game.client_factory, find=game.find, alive=game.alive)
        except GameError as error:
            if error.code not in ("bridge_unreachable", "not_in_level"):
                raise
            result["menu_error"] = error.to_dict()["error"]
    result["release"] = game.manager.release(game.session)
    return result


def default_lease_root() -> Path:
    return lease_root()
