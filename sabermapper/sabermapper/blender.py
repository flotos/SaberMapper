"""`blender` commands: start, inspect and stop the local Blender that the Blender MCP server drives.

The official Blender Lab MCP (https://www.blender.org/lab/mcp-server/) has two halves: an add-on inside Blender
that runs a TCP bridge (default localhost:9876), and the `blender-mcp` stdio server that `.mcp.json` registers for
the agent. The agent brings the Blender half up with `blender start` (headless by default, so modelling never
opens a window on the user's desktop), reads the model back through the MCP render tools, and closes the Blender
it started with `blender stop`. A Blender the user opened is reported but never stopped.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876  # the add-on's preference default; a GUI Blender listens here
START_TIMEOUT = 90.0
DOCS = "sabermapper/docs/blender-mcp.md"
_PING_CODE = ("import bpy\nresult = {'version': bpy.app.version_string, 'file': bpy.data.filepath, "
              "'background': bpy.app.background, 'objects': len(bpy.data.objects)}")


class BlenderError(Exception):
    def __init__(self, code: str, message: str, fix: str = ""):
        super().__init__(message)
        self.code, self.fix = code, fix


def _local_programs() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "Programs" if base else None


def blender_path() -> Path | None:
    """BLENDER_PATH, then the per-user install (%LOCALAPPDATA%/Programs/Blender), then PATH."""
    candidates = [os.environ.get("BLENDER_PATH")]
    if programs := _local_programs():
        candidates.append(str(programs / "Blender" / "blender.exe"))
    candidates.append(shutil.which("blender"))
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def server_path() -> Path | None:
    """BLENDER_MCP_SERVER, then the per-user venv (%LOCALAPPDATA%/Programs/BlenderMCP), then PATH."""
    candidates = [os.environ.get("BLENDER_MCP_SERVER")]
    if programs := _local_programs():
        candidates.append(str(programs / "BlenderMCP" / "Scripts" / "blender-mcp.exe"))
    candidates.append(shutil.which("blender-mcp"))
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def ping(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict | None:
    """What the Blender behind the bridge has open, or None when nothing answers on host:port."""
    request = json.dumps({"type": "execute", "code": _PING_CODE, "strict_json": True}) + "\0"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request.encode("utf-8"))
            buf = bytearray()
            while b"\0" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
    except OSError:
        return None
    try:
        reply = json.loads(bytes(buf).split(b"\0", 1)[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return reply.get("result") if reply.get("status") == "ok" else None


def _state_path(port: int) -> Path:
    return Path(tempfile.gettempdir()) / f"sabermapper-blender-{port}.json"


def _log_path(port: int) -> Path:
    return Path(tempfile.gettempdir()) / f"sabermapper-blender-{port}.log"


def _read_state(port: int) -> dict | None:
    try:
        return json.loads(_state_path(port).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(pid) -> bool:
    from .game.process import pid_alive
    return pid_alive(pid)


def launch_command(blender: Path, *, gui: bool = False, blend: Path | None = None,
                   port: int = DEFAULT_PORT) -> list[str]:
    """Headless: `blender --background [FILE] --online-mode --command blender_mcp --port N` (the add-on's
    blocking CLI server). GUI: Blender with online access for this session; the add-on auto-starts its bridge on
    its preference port. `--online-mode` grants the network permission for this run only, not in the prefs."""
    command = [str(blender)]
    if not gui:
        command.append("--background")
    if blend:
        command.append(str(blend))
    command.append("--online-mode")
    if not gui:
        command += ["--command", "blender_mcp", "--port", str(port)]
    return command


def status(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> dict:
    blender, server = blender_path(), server_path()
    reply = ping(host, port)
    state = _read_state(port)
    started = None
    if state:
        started = {**state, "alive": _alive(state.get("pid"))}
    report = {
        "blender": {"path": str(blender) if blender else None, "found": blender is not None},
        "mcp_server": {"path": str(server) if server else None, "found": server is not None},
        "bridge": {"host": host, "port": port, "reachable": reply is not None, **(reply or {})},
        "started_here": started,
    }
    missing = [name for name, part in (("blender", blender), ("mcp_server", server)) if part is None]
    if missing:
        report["fix"] = f"Install the missing part ({', '.join(missing)}) as described in {DOCS}"
    elif reply is None:
        report["fix"] = "Run `blender start` to open a headless Blender with the MCP bridge"
    return report


def start(port: int = DEFAULT_PORT, *, gui: bool = False, blend: Path | None = None,
          timeout: float = START_TIMEOUT, host: str = DEFAULT_HOST) -> dict:
    if gui and port != DEFAULT_PORT:
        raise BlenderError("gui_port_fixed", f"A GUI Blender's bridge listens on its add-on preference port "
                           f"({DEFAULT_PORT}); --port only applies to the headless bridge",
                           "Drop --port or omit --gui")
    if ping(host, port) is not None:
        return {**status(port, host), "started": False, "already_running": True}
    blender = blender_path()
    if blender is None:
        raise BlenderError("blender_missing", "No Blender executable found (BLENDER_PATH, "
                           "%LOCALAPPDATA%/Programs/Blender/blender.exe, PATH)", f"Install Blender as in {DOCS}")
    if blend is not None and not blend.is_file():
        raise BlenderError("blend_missing", f"{blend} does not exist", "Pass an existing .blend file or omit it")
    command = launch_command(blender, gui=gui, blend=blend, port=port)
    log = _log_path(port)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | (0 if gui else subprocess.CREATE_NO_WINDOW)
    with log.open("w", encoding="utf-8", errors="replace") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   creationflags=flags, close_fds=True)
    state = {"pid": process.pid, "mode": "gui" if gui else "headless", "blend": str(blend) if blend else None,
             "command": command, "log": str(log), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _state_path(port).write_text(json.dumps(state, indent=2), encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping(host, port, timeout=2.0) is not None:
            return {**status(port, host), "started": True, "already_running": False}
        if process.poll() is not None:
            break
        time.sleep(0.5)
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:] if log.exists() else []
    if process.poll() is None:
        process.terminate()
    _state_path(port).unlink(missing_ok=True)
    raise BlenderError("bridge_timeout", f"Blender did not open the MCP bridge on {host}:{port} within "
                       f"{timeout:.0f}s. Log tail:\n" + "\n".join(tail),
                       f"Check that the MCP add-on is installed and enabled ({DOCS}); `blender status` shows paths")


def stop(port: int = DEFAULT_PORT) -> dict:
    """Stops only the Blender that `blender start` launched on this port; a user's Blender is left running."""
    state = _read_state(port)
    if not state:
        raise BlenderError("not_started_here", f"No Blender started by `blender start` is recorded for port {port}",
                           "A Blender the user opened is theirs to close")
    pid = state.get("pid")
    was_alive = _alive(pid)
    if was_alive:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.kill(pid, 15)
    _state_path(port).unlink(missing_ok=True)
    return {"stopped": was_alive, "pid": pid, "mode": state.get("mode"), "port": port}


def register_blender(commands):
    root = commands.add_parser("blender", help="Local Blender for the Blender MCP server: start it headless (or "
                                               "with --gui), report the bridge, stop the Blender started here")
    actions = root.add_subparsers(dest="blender_action", required=True)
    helps = {"status": "Blender and MCP server paths, whether the bridge answers, and the Blender started here",
             "start": "Open Blender with the MCP bridge and wait until it answers (reuses a running bridge)",
             "stop": "Close the Blender that `blender start` opened; a Blender the user opened is left alone"}
    for action in ("status", "start", "stop"):
        parser = actions.add_parser(action, help=helps[action])
        parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                            help=f"Bridge port (default {DEFAULT_PORT}; .mcp.json's BLENDER_MCP_PORT must match)")
        if action == "start":
            parser.add_argument("--gui", action="store_true",
                                help="Open the Blender window (needed for the MCP screenshot tools); default headless")
            parser.add_argument("--blend", type=Path, help="Open this .blend file (default: the startup scene)")
            parser.add_argument("--timeout", type=float, default=START_TIMEOUT, help="Seconds to wait for the bridge")


def dispatch_blender(args, emit):
    if args.command != "blender":
        return None
    try:
        if args.blender_action == "status":
            emit(status(args.port))
        elif args.blender_action == "start":
            emit(start(args.port, gui=args.gui, blend=args.blend, timeout=args.timeout))
        else:
            emit(stop(args.port))
        return 0
    except BlenderError as exc:
        emit({"error": {"code": exc.code, "message": str(exc), "fix": exc.fix}})
        return 2
