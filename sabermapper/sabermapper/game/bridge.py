"""HTTP client for the SaberMapper Bridge mod (127.0.0.1 only). API reference: docs/game-bridge.md."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import GameError
from .lease import lease_root

DEFAULT_PORT = 28765
HEADER = "X-SaberMapper-Lease"


def bridge_port(root: str | Path | None = None) -> int:
    """Port from $SABERMAPPER_BRIDGE_PORT, else the bridge's own bridge.json, else the default."""
    if os.environ.get("SABERMAPPER_BRIDGE_PORT"):
        return int(os.environ["SABERMAPPER_BRIDGE_PORT"])
    info = bridge_info(root)
    return int(info.get("port") or DEFAULT_PORT) if info else DEFAULT_PORT


def bridge_info(root: str | Path | None = None) -> dict | None:
    path = lease_root(root) / "bridge.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class BridgeClient:
    def __init__(self, token: str | None = None, *, port: int | None = None, host: str = "127.0.0.1",
                 timeout: float = 15.0, root: str | Path | None = None):
        self.token, self.host, self.timeout = token, host, timeout
        self.port = port or bridge_port(root)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, body: dict | None = None, *, query: dict | None = None,
                timeout: float | None = None) -> dict:
        url = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else (b"{}" if method == "POST" else None)
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header(HEADER, self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8") or "{}").get("error") or {}
            except ValueError:
                payload = {}
            finally:
                error.close()
            raise GameError(payload.get("code") or f"bridge_http_{error.code}",
                            payload.get("message") or f"Bridge answered HTTP {error.code} for {method} {path}",
                            {"status": error.code, "endpoint": f"{method} {path}", **(payload.get("details") or {})},
                            fix=(payload.get("details") or {}).get("fix")) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            raise GameError("bridge_unreachable", f"SaberMapper Bridge did not answer at {self.url}: {error}",
                            {"url": self.url, "endpoint": f"{method} {path}"},
                            fix="Start the game through `sabermapper game launch`; check the bridge is installed "
                                "(`sabermapper game build-bridge --install`) and `sabermapper game logs`") from None

    # ------------------------------------------------------------------ endpoints
    def health(self, timeout: float = 3.0) -> dict:
        return self.request("GET", "/health", timeout=timeout)

    def state(self, *, wait_ms: int = 0, since: int | None = None) -> dict:
        query = {"wait_ms": int(wait_ms)} if wait_ms else {}
        if since is not None:
            query["since"] = int(since)
        return self.request("GET", "/state", query=query or None, timeout=self.timeout + wait_ms / 1000.0)

    def refresh(self, *, full: bool = True, wait_ms: int = 120000) -> dict:
        return self.request("POST", "/refresh", {"full": full, "wait_ms": wait_ms}, timeout=self.timeout + wait_ms / 1000.0)

    def load(self, *, level_path: str | None = None, level_id: str | None = None, characteristic: str = "Standard",
             difficulty: str | None = None, start_time: float = 0.0, speed: float = 1.0, modifiers: str = "no_fail",
             hud: bool = True) -> dict:
        body = {"level_path": level_path, "level_id": level_id, "characteristic": characteristic, "difficulty": difficulty,
                "start_time": float(start_time), "speed": float(speed), "modifiers": modifiers, "hud": hud}
        return self.request("POST", "/load", {k: v for k, v in body.items() if v is not None})

    def pause(self) -> dict:
        return self.request("POST", "/pause")

    def resume(self) -> dict:
        return self.request("POST", "/resume")

    def restart(self, start_time: float | None = None) -> dict:
        return self.request("POST", "/restart", {} if start_time is None else {"start_time": float(start_time)})

    def seek(self, time_s: float) -> dict:
        return self.request("POST", "/seek", {"time": float(time_s)})

    def menu(self) -> dict:
        return self.request("POST", "/menu")

    def capture(self, *, out_dir: str | Path, frames: list[dict] | None = None, probe: dict | None = None,
                camera: str = "player", width: int | None = None, height: int | None = None,
                hide_notes: bool = False) -> dict:
        """Start a capture job. `hide_notes` hides notes, bombs, chains and arcs on every frame; a probe's own
        `hide_notes` hides them on probe frames only (the bridge renders regular frames with notes separately)."""
        body = {"out_dir": str(out_dir), "camera": camera, "frames": frames or [], "probe": probe,
                "width": width, "height": height, "hide_notes": hide_notes or None}
        return self.request("POST", "/capture", {k: v for k, v in body.items() if v is not None})

    def capture_status(self) -> dict | None:
        return self.request("GET", "/capture")

    def capture_cancel(self) -> dict:
        return self.request("POST", "/capture/cancel")

    # ------------------------------------------------------------------ waiting
    def wait_healthy(self, timeout: float, *, alive=None, poll: float = 1.0) -> dict:
        """Poll /health until it answers; `alive()` returning False aborts early (the game process died)."""
        deadline, last = time.monotonic() + timeout, None
        while True:
            try:
                return self.health()
            except GameError as error:
                last = error
            if alive is not None and not alive():
                raise GameError("game_not_running", "Beat Saber exited before the bridge answered",
                                {"url": self.url}, fix="Check `sabermapper game logs --all` for the crash")
            if time.monotonic() >= deadline:
                raise GameError("timeout", f"The bridge did not answer within {timeout:.0f} s",
                                {"url": self.url, "last_error": last.to_dict()["error"] if last else None},
                                fix="Check the bridge is installed in Plugins and `sabermapper game logs --all`")
            time.sleep(poll)

    def wait_state(self, predicate, timeout: float, *, describe: str = "state", check=None) -> dict:
        """Long-poll /state until predicate(state) is true. `check()` runs each round (lease ownership)."""
        deadline = time.monotonic() + timeout
        state = self.state()
        while not predicate(state):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GameError("timeout", f"Timed out after {timeout:.0f} s waiting for {describe}",
                                {"state": state}, fix="Check `sabermapper game status` and `sabermapper game logs`")
            if check is not None:
                check()
            if state.get("last_error"):
                raise GameError("bridge_error", f"The bridge reported: {state['last_error']}", {"state": state})
            state = self.state(wait_ms=int(min(remaining, 1.0) * 1000), since=state.get("version"))
        return state
