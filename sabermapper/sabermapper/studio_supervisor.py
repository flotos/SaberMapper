"""Keep the running studio on the newest code without interrupting the user.

`serve` runs this supervisor. It keeps one session token for its whole life and
runs the HTTP server in a worker process. When the package source changes (an
agent merged into main), it waits for the files to settle, checks that the new
code compiles and imports, tells the worker to finish its in-flight requests,
and starts a fresh worker on the same port and token. Open studio pages keep
working and show a "reload when ready" banner; they never reload themselves,
and ArcViewer tabs, which load their map once, are untouched.

Supervisor -> worker control is line-based on the worker's stdin:
`state <json>` updates the update status the worker reports at /api/status, and
`drain` asks it to exit once no request is in flight. Closing stdin also drains.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

PACKAGE = Path(__file__).resolve().parent
WATCHED_SUFFIXES = {".py", ".js", ".css", ".html"}
TOKEN_ENV = "SABERMAPPER_STUDIO_TOKEN"
VERSION_ENV = "SABERMAPPER_STUDIO_CODE"
POLL_SECONDS = 2.0
SETTLE_SECONDS = 3.0


def code_fingerprint(root: Path = PACKAGE) -> str:
    """Hash of every served source file; changes exactly when the studio's code does."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.suffix not in WATCHED_SUFFIXES or "__pycache__" in path.parts or not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue  # Mid-write during a merge; the settle wait catches the final state.
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + content + b"\0")
    return digest.hexdigest()[:12]


def code_commit(root: Path = PACKAGE) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                                timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    return result.stdout.strip() or None


def preflight(python: str = sys.executable) -> str | None:
    """Compile every module and import the server in a fresh interpreter; return the error, or None."""
    script = ("import compileall, sys; from pathlib import Path; import sabermapper; "
              "root = Path(sabermapper.__file__).parent; "
              "sys.exit(0 if compileall.compile_dir(str(root), quiet=1, force=False, legacy=False) else 3)")
    checks = (["-c", script], ["-c", "import sabermapper.server, sabermapper.projects, sabermapper.validation"])
    for args in checks:
        try:
            result = subprocess.run([python, *args], cwd=PACKAGE.parent, capture_output=True, text=True, timeout=120,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Update check could not run: {exc}"
        if result.returncode:
            output = (result.stderr or result.stdout).strip().splitlines()
            return output[-1] if output else f"Update check failed with exit code {result.returncode}"
    return None


class WorkerControl:
    """Worker side: supervisor state for /api/status and a drain that waits for in-flight requests."""

    def __init__(self):
        self.version = os.environ.get(VERSION_ENV) or code_fingerprint()
        self.commit = code_commit()
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.supervised = bool(os.environ.get(TOKEN_ENV))
        self.update = {"state": "current"}
        self._inflight = 0
        self._lock = threading.Condition()

    def status(self) -> dict:
        return {"version": self.version, "commit": self.commit, "started_at": self.started_at,
                "auto_update": self.supervised, "update": dict(self.update)}

    @contextmanager
    def request(self):
        """Count a request as in flight so a drain waits for it."""
        with self._lock:
            self._inflight += 1
        try:
            yield
        finally:
            with self._lock:
                self._inflight -= 1
                self._lock.notify_all()

    def wait_idle(self, quiet: float = 0.3):
        """Block until no request has been in flight for `quiet` seconds."""
        with self._lock:
            while True:
                self._lock.wait_for(lambda: self._inflight == 0)
                if not self._lock.wait_for(lambda: self._inflight > 0, timeout=quiet):
                    return

    def listen(self, server, stream=None):
        """Follow supervisor commands on stdin; drain and stop the server on `drain` or EOF."""
        stream = stream or sys.stdin

        def run():
            for line in stream:
                command, _, payload = line.strip().partition(" ")
                if command == "state":
                    try:
                        self.update = json.loads(payload)
                    except json.JSONDecodeError:
                        pass
                elif command == "drain":
                    break
            self.wait_idle()
            server.shutdown()

        threading.Thread(target=run, name="studio-control", daemon=True).start()


class Supervisor:
    def __init__(self, workspace: Path, port: int, python: str = sys.executable, poll: float = POLL_SECONDS,
                 settle: float = SETTLE_SECONDS, log=print):
        self.workspace, self.port, self.python = Path(workspace).resolve(), port, python
        self.poll, self.settle, self.log = poll, settle, log
        self.token = secrets.token_urlsafe(32)
        self.worker: subprocess.Popen | None = None
        self.version = ""
        self.update = {"state": "current"}
        self.stopping = threading.Event()

    def _send(self, line: str):
        try:
            self.worker.stdin.write(line + "\n")
            self.worker.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def _set_update(self, **update):
        self.update = update
        self._send("state " + json.dumps(update))

    def _ready(self, version: str, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.worker.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/status", timeout=2) as response:
                    if json.load(response).get("code", {}).get("version") == version:
                        return True
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        return False

    def start_worker(self, version: str) -> bool:
        env = {**os.environ, TOKEN_ENV: self.token, VERSION_ENV: version, "PYTHONUTF8": "1"}
        self.worker = subprocess.Popen(
            [self.python, "-m", "sabermapper", "serve", "--workspace", str(self.workspace), "--port", str(self.port),
             "--worker"], cwd=PACKAGE.parent, env=env, stdin=subprocess.PIPE, text=True, encoding="utf-8")
        self.version = version
        if not self._ready(version):
            return False
        if self.update.get("state") != "current":
            self._send("state " + json.dumps(self.update))
        return True

    def stop_worker(self, timeout: float | None = None):
        if not self.worker or self.worker.poll() is not None:
            return
        self._send("drain")
        try:
            self.worker.stdin.close()
        except OSError:
            pass
        try:
            self.worker.wait(timeout)
        except subprocess.TimeoutExpired:
            self.worker.kill()
            self.worker.wait()

    def _settled(self, seen: str) -> str:
        """Wait until the source stops changing (a merge writes many files); return the final fingerprint."""
        while not self.stopping.wait(self.settle):
            now = code_fingerprint()
            if now == seen:
                return now
            seen = now
        return seen

    def reload(self, version: str) -> bool:
        self._set_update(state="pending", detected_version=version)
        error = preflight(self.python)
        if error:
            self.log(f"Studio update {version} not loaded; still serving {self.version}: {error}", flush=True)
            self._set_update(state="failed", detected_version=version, error=error)
            return False
        self.log(f"Studio code changed ({self.version} -> {version}); restarting when idle", flush=True)
        self.update = {"state": "current"}
        self.stop_worker()
        if not self.start_worker(version):
            self.log("Updated studio worker did not start; retrying on the next change", flush=True)
            self.update = {"state": "failed", "detected_version": version, "error": "Updated studio did not start"}
            return False
        return True

    def run(self) -> int:
        if not self.start_worker(code_fingerprint()):
            self.stop_worker(timeout=5)
            print("Studio did not start. Is the port already in use?", file=sys.stderr, flush=True)
            return 1
        rejected = None
        try:
            while not self.stopping.wait(self.poll):
                if self.worker.poll() is not None:
                    self.log("Studio worker exited unexpectedly; restarting", flush=True)
                    if not self.start_worker(code_fingerprint()):
                        self.stopping.wait(5)
                    continue
                current = code_fingerprint()
                if current in (self.version, rejected):
                    continue
                current = self._settled(current)
                if self.stopping.is_set():
                    break
                if current != self.version and not self.reload(current):
                    rejected = current
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_worker(timeout=30)
        return 0
