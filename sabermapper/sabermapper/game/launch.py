"""Start and stop Beat Saber for leased agent runs and the studio.

Launch method: the game executable is started directly with `SteamAppId=620980` in its environment (the same
way BSManager and ModAssistant-era launchers do), so launch arguments such as SiraUtil's `fpfc` survive and the
process id is known immediately. Steam must be running for ownership checks. See docs/game-bridge.md.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from .errors import GameError
from .logs import default_game_dir
from .process import GAME_EXE, find_game_pids, pid_alive

STEAM_APP_ID = "620980"


def launch_command(game_dir: str | Path | None = None, *, fpfc: bool = True, extra: list[str] | None = None) -> list[str]:
    exe = default_game_dir(game_dir) / GAME_EXE
    if not exe.is_file():
        raise GameError("game_not_found", f"No {GAME_EXE} in {exe.parent}", {"game_dir": str(exe.parent)},
                        fix="Pass --game-dir or set SABERMAPPER_GAME_DIR")
    return [str(exe), *(["fpfc"] if fpfc else []), *(extra or [])]


def launch_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    env.update({"SteamAppId": STEAM_APP_ID, "SteamGameId": STEAM_APP_ID, "SteamOverlayGameId": STEAM_APP_ID})
    return env


def start_game(game_dir: str | Path | None = None, *, fpfc: bool = True, popen=subprocess.Popen,
               find=find_game_pids) -> int:
    """Start the game and return its pid. Refuses when an instance already runs (never adopt a game)."""
    running = find()
    if running:
        raise GameError("game_busy", "Beat Saber is already running", {"reason": "unleased_game", "game_pids": running},
                        fix="Never take over a running game; wait for it to close or ask the user")
    command = launch_command(game_dir, fpfc=fpfc)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = popen(command, cwd=str(Path(command[0]).parent), env=launch_env(), close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return int(process.pid)


def resolve_game_pid(started_pid: int, *, timeout: float = 20.0, find=find_game_pids, alive=pid_alive) -> int:
    """The started pid, or the relaunched instance's pid if Steam restarted the game."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = find()
        if started_pid in pids:
            return started_pid
        if pids and not alive(started_pid):
            return pids[0]
        time.sleep(0.5)
    pids = find()
    if pids:
        return pids[0]
    raise GameError("game_not_running", "Beat Saber did not stay running after launch", {"started_pid": started_pid},
                    fix="Make sure Steam is running and signed in, then check `sabermapper game logs --all`")


def close_game(pid: int, *, timeout: float = 20.0, alive=pid_alive, run=subprocess.run) -> dict:
    """Close one game process the caller launched: polite WM_CLOSE first, then force after the timeout."""
    if not alive(pid):
        return {"closed": True, "pid": pid, "was_running": False, "forced": False}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=flags)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return {"closed": True, "pid": pid, "was_running": True, "forced": False}
        time.sleep(0.5)
    run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=flags)
    for _ in range(20):
        if not alive(pid):
            return {"closed": True, "pid": pid, "was_running": True, "forced": True}
        time.sleep(0.5)
    raise GameError("game_close_failed", f"Beat Saber (pid {pid}) did not exit", {"pid": pid},
                    fix="Close the game window manually")
