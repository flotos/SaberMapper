"""Machine-wide Beat Saber lease shared by agents in every worktree, the studio and the bridge mod.

Protocol and schemas: docs/game-lease.md. The lease `token` is the bridge credential: the bridge mod
rereads the lease file on every command and rejects requests whose `X-SaberMapper-Lease` header differs,
so rotating the token on any ownership change revokes the previous holder immediately.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time

from .errors import GameError
from .process import find_game_pids, pid_alive

SCHEMA_VERSION = 1
STALE_AFTER = 600.0
LOCK_STALE_AFTER = 10.0
LOCK_TIMEOUT = 20.0
HEARTBEAT_EVERY = 30.0
LEASE_FILE, LOCK_FILE = "game-lease.json", "game-lease.lock"
REVOCATIONS_FILE, SESSIONS_DIR = "game-lease-revocations.jsonl", "sessions"
_SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_REVOCATIONS_KEPT = 500


def lease_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root)
    if os.environ.get("SABERMAPPER_LEASE_DIR"):
        return Path(os.environ["SABERMAPPER_LEASE_DIR"])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "SaberMapper"


def worktree_path(cwd: str | Path | None = None) -> Path:
    cwd = Path(cwd or os.getcwd())
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd.resolve()


def default_session(cwd: str | Path | None = None) -> str:
    if os.environ.get("SABERMAPPER_SESSION"):
        return check_session(os.environ["SABERMAPPER_SESSION"])
    path = str(worktree_path(cwd)).replace("\\", "/")
    return hashlib.sha1((path.lower() if os.name == "nt" else path).encode("utf-8")).hexdigest()


def default_holder(cwd: str | Path | None = None) -> str:
    return f"agent:{worktree_path(cwd).name}"


def check_session(session: str) -> str:
    if not isinstance(session, str) or not _SESSION_RE.match(session):
        raise GameError("lease_invalid", f"Invalid session id {session!r}",
                        fix="Use 1-128 characters from A-Z, a-z, 0-9, '_', '.', '-'")
    return session


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def _parse(value) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _retry(fn, attempts: int = 40):
    """Windows refuses replace/unlink while another process (the bridge) has the file open; retry briefly."""
    for attempt in range(attempts):
        try:
            return fn()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


class _FileLock:
    """Short-lived cross-process lock: exclusive create of game-lease.lock, stale after LOCK_STALE_AFTER."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT):
        self.path, self.timeout, self.stamp = path, timeout, f"{os.getpid()}:{secrets.token_hex(8)}"

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(self.stamp)
                return self
            except FileExistsError:
                self._break_if_stale()
            except PermissionError:  # being deleted by its previous owner
                pass
            if time.monotonic() > deadline:
                raise GameError("timeout", f"Could not take the lease lock {self.path} within {self.timeout:g} s",
                                {"lock": str(self.path)},
                                fix=f"If no SaberMapper command is running, delete {self.path}")
            time.sleep(0.01 + secrets.randbelow(20) / 1000)

    def _break_if_stale(self):
        try:
            age = time.time() - self.path.stat().st_mtime
            if age <= LOCK_STALE_AFTER:
                return
            content = self.path.read_text(encoding="utf-8", errors="replace")
            moved = self.path.with_name(f"{self.path.name}.stale-{secrets.token_hex(4)}")
            os.rename(self.path, moved)
            if moved.read_text(encoding="utf-8", errors="replace") != content:
                try:  # a fresh lock replaced the stale one between our read and rename: put it back
                    os.rename(moved, self.path)
                except OSError:
                    pass
            moved.unlink(missing_ok=True)
        except (FileNotFoundError, PermissionError):
            pass

    def __exit__(self, *_):
        try:
            if self.path.read_text(encoding="utf-8", errors="replace") == self.stamp:
                _retry(lambda: self.path.unlink(missing_ok=True))
        except FileNotFoundError:
            pass


class GameLease:
    """Lease operations bound to a lease directory and an (injectable) process view."""

    def __init__(self, root: str | Path | None = None, *, game_running=None, pid_alive=None,
                 stale_after: float | None = None, clock=time.time):
        self.root = lease_root(root)
        self.game_running = game_running or find_game_pids
        self.pid_alive = pid_alive or _default_pid_alive
        env_stale = os.environ.get("SABERMAPPER_LEASE_STALE_AFTER")
        self.stale_after = float(stale_after if stale_after is not None else env_stale or STALE_AFTER)
        self.clock = clock

    # ---- files ---------------------------------------------------------------------------------
    @property
    def lease_file(self) -> Path:
        return self.root / LEASE_FILE

    @property
    def revocations_file(self) -> Path:
        return self.root / REVOCATIONS_FILE

    def session_file(self, session: str) -> Path:
        return self.root / SESSIONS_DIR / f"{check_session(session)}.json"

    def _lock(self):
        return _FileLock(self.root / LOCK_FILE)

    def read(self) -> dict | None:
        """The lease dict, None when absent, or {"_invalid": reason, "_mtime": ...} when unreadable."""
        try:
            text = _retry(lambda: self.lease_file.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        try:
            lease = json.loads(text)
            if not isinstance(lease, dict) or not isinstance(lease.get("token"), str) or "session" not in lease:
                raise ValueError("missing token or session")
            return lease
        except ValueError as exc:
            try:
                mtime = self.lease_file.stat().st_mtime
            except FileNotFoundError:
                return None
            return {"_invalid": str(exc), "_mtime": mtime}

    def _write(self, lease: dict, *, create: bool) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(lease, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if create:
            fd = os.open(self.lease_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
            return
        fd, temporary = tempfile.mkstemp(prefix=".lease-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            _retry(lambda: os.replace(temporary, self.lease_file))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _delete(self) -> None:
        _retry(lambda: self.lease_file.unlink(missing_ok=True))

    def stored_token(self, session: str) -> str | None:
        try:
            return json.loads(self.session_file(session).read_text(encoding="utf-8")).get("token")
        except (FileNotFoundError, ValueError, AttributeError):
            return None

    def _store_session(self, lease: dict) -> None:
        path = self.session_file(lease["session"])
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"session": lease["session"], "holder": lease["holder"], "token": lease["token"],
                  "acquired_at": lease["acquired_at"]}
        fd, temporary = tempfile.mkstemp(prefix=".session-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream)
            _retry(lambda: os.replace(temporary, path))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def forget(self, session: str) -> None:
        _retry(lambda: self.session_file(session).unlink(missing_ok=True))

    def _revoke(self, lease: dict, by: str, at: str) -> dict:
        record = {"token_sha256": token_sha256(lease["token"]), "holder": lease.get("holder"),
                  "session": lease.get("session"), "revoked_at": at, "by": by}
        lines = []
        try:
            lines = self.revocations_file.read_text(encoding="utf-8").splitlines()[-(_REVOCATIONS_KEPT - 1):]
        except FileNotFoundError:
            pass
        lines.append(json.dumps(record, ensure_ascii=False))
        fd, temporary = tempfile.mkstemp(prefix=".revocations-", suffix=".jsonl", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
            _retry(lambda: os.replace(temporary, self.revocations_file))
        finally:
            Path(temporary).unlink(missing_ok=True)
        return record

    def revocation(self, token: str | None) -> dict | None:
        if not token:
            return None
        digest = token_sha256(token)
        try:
            lines = self.revocations_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return None
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("token_sha256") == digest:
                return record
        return None

    # ---- assessment ----------------------------------------------------------------------------
    def heartbeat_age(self, lease: dict) -> float | None:
        stamp = _parse(lease.get("heartbeat_at"))
        return None if stamp is None else max(0.0, self.clock() - stamp)

    def assess(self, lease: dict | None) -> dict:
        """{live, stale_reason, game_alive}; game_alive refers to the lease's recorded game_pid."""
        if lease is None:
            return {"live": False, "stale_reason": None, "game_alive": False}
        if "_invalid" in lease:
            young = self.clock() - lease["_mtime"] < 5.0  # possibly mid-write
            return {"live": young, "stale_reason": None if young else "invalid", "game_alive": False}
        game_pid = lease.get("game_pid")
        game_alive = bool(game_pid) and self.pid_alive(game_pid)
        if game_pid and not game_alive:
            return {"live": False, "stale_reason": "game_exited", "game_alive": False}
        age = self.heartbeat_age(lease)
        if age is None or age > self.stale_after:
            return {"live": False, "stale_reason": "heartbeat_expired", "game_alive": game_alive}
        return {"live": True, "stale_reason": None, "game_alive": game_alive}

    def _busy(self, lease: dict, reason: str, message: str, fix: str | None = None, **extra) -> GameError:
        details = {"reason": reason, "holder": lease.get("holder"), "holder_kind": lease.get("holder_kind"),
                   "session": lease.get("session"), "purpose": lease.get("purpose"),
                   "project": lease.get("project"), "worktree": lease.get("worktree"),
                   "game_pid": lease.get("game_pid"), "acquired_at": lease.get("acquired_at"),
                   "heartbeat_age_s": None if self.heartbeat_age(lease) is None else round(self.heartbeat_age(lease), 1),
                   **extra}
        return GameError("game_busy", message, details, fix)

    # ---- operations ----------------------------------------------------------------------------
    def acquire(self, holder: str | None = None, *, session: str | None = None, worktree: str | None = None,
                project: str | None = None, purpose: str = "", holder_kind: str = "agent", wait: float = 0.0,
                poll: float = 2.0) -> dict:
        if holder_kind not in ("agent", "human"):
            raise ValueError("holder_kind must be 'agent' or 'human'")
        session = check_session(session or default_session())
        holder = holder or (default_holder() if holder_kind == "agent" else "human:studio")
        if worktree is None and holder_kind == "agent":
            worktree = str(worktree_path())
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            try:
                with self._lock():
                    return self._acquire_locked(holder, session, worktree, project, purpose, holder_kind)
            except GameError as error:
                remaining = deadline - time.monotonic()
                if error.code != "game_busy" or remaining <= 0:
                    if error.code == "game_busy" and wait > 0:
                        error.details["waited_s"] = wait
                        error.message += f" (waited {wait:g} s)"
                    raise
            time.sleep(max(0.01, min(poll, remaining)))

    def _new_lease(self, holder, session, worktree, project, purpose, holder_kind, game_pid=None,
                   launched_by_agent=False, previous=None) -> dict:
        stamp = _iso(self.clock())
        return {"schema_version": SCHEMA_VERSION, "token": secrets.token_urlsafe(32), "holder": holder,
                "holder_kind": holder_kind, "session": session, "worktree": worktree, "project": project,
                "purpose": purpose, "game_pid": game_pid, "launched_by_agent": bool(launched_by_agent),
                "holder_pid": os.getpid(), "acquired_at": stamp, "heartbeat_at": stamp, "previous": previous}

    def _acquire_locked(self, holder, session, worktree, project, purpose, holder_kind) -> dict:
        lease = self.read()
        state = self.assess(lease)
        stamp = _iso(self.clock())
        if lease and "_invalid" not in lease and lease.get("session") == session:
            lease.update(heartbeat_at=stamp, holder_pid=os.getpid())
            if purpose:
                lease["purpose"] = purpose
            if project:
                lease["project"] = project
            if lease.get("game_pid") and state["stale_reason"] == "game_exited":
                lease.update(game_pid=None, launched_by_agent=False)
            self._write(lease, create=False)
            self._store_session(lease)
            return lease
        pids = self.game_running()
        if holder_kind == "human":
            previous = None
            game_pid, launched = None, False
            if lease and "_invalid" not in lease:
                reason = "preempted_by_human" if lease.get("holder_kind") == "agent" else "replaced_by_human"
                previous = {"holder": lease.get("holder"), "holder_kind": lease.get("holder_kind"),
                            "session": lease.get("session"), "revoked_at": stamp, "reason": reason,
                            "token_sha256": token_sha256(lease["token"])}
                self._revoke(lease, holder, stamp)
                if lease.get("game_pid") in pids:
                    game_pid, launched = lease["game_pid"], bool(lease.get("launched_by_agent"))
            if game_pid is None and pids:
                game_pid = pids[0]
            new = self._new_lease(holder, session, worktree, project, purpose, holder_kind, game_pid, launched,
                                  previous)
            self._write(new, create=lease is None)
            self._store_session(new)
            return new
        previous = None
        if lease is not None:
            if "_invalid" in lease:
                if state["live"]:
                    raise GameError("game_busy", "The lease file is being written; retry", {"reason": "lease_writing"})
                previous = {"holder": None, "session": None, "reclaimed_at": stamp, "reason": "invalid"}
            elif state["live"]:
                raise self._busy(lease, "held",
                                 f"The game is leased by {lease.get('holder')} ({lease.get('holder_kind')}) for "
                                 f"{lease.get('purpose') or 'an unspecified purpose'}",
                                 "Retry later, or pass --wait SECONDS to queue for the lease")
            elif state["game_alive"]:
                human = lease.get("holder_kind") == "human"
                raise self._busy(
                    lease, "human_game" if human else "orphaned_agent_game",
                    ("The user's game from an expired studio lease is still running" if human else
                     f"The lease of {lease.get('holder')} expired but the game it launched (pid "
                     f"{lease.get('game_pid')}) is still running; agents never adopt another holder's game"),
                    "Ask the user to close that Beat Saber window, then retry", stale_reason=state["stale_reason"])
            else:
                previous = {"holder": lease.get("holder"), "session": lease.get("session"), "reclaimed_at": stamp,
                            "reason": state["stale_reason"]}
        if pids:
            raise GameError("game_busy",
                            "Beat Saber is running without a lease: the user, or an agent that bypassed the lease, "
                            "is using it; agents never take over a game they did not launch",
                            {"reason": "unleased_game", "game_pids": pids},
                            "Wait for the user to close Beat Saber (or ask them to), then retry")
        new = self._new_lease(holder, session, worktree, project, purpose, holder_kind, previous=previous)
        try:
            self._write(new, create=lease is None)
        except FileExistsError:  # written by a process that bypassed the lock
            raise GameError("game_busy", "Another process created the lease concurrently; retry",
                            {"reason": "lease_race"}, "Retry, or pass --wait SECONDS") from None
        self._store_session(new)
        return new

    def own_lease(self, session: str | None = None) -> dict | None:
        session = check_session(session or default_session())
        lease, token = self.read(), self.stored_token(session)
        if lease and "_invalid" not in lease and token and lease.get("token") == token:
            return lease
        return None

    def check_owner(self, session: str | None = None) -> dict:
        """The owned lease, or GameError game_preempted / game_busy / lease_not_held."""
        session = check_session(session or default_session())
        lease, token = self.read(), self.stored_token(session)
        if lease and "_invalid" not in lease and lease.get("session") == session and (
                token is None or token == lease.get("token")):
            return lease
        revoked = self.revocation(token)
        if revoked:
            details = {"revoked_at": revoked.get("revoked_at"), "by": revoked.get("by"),
                       "holder": lease.get("holder") if lease and "_invalid" not in lease else None}
            raise GameError("game_preempted",
                            f"The user took the game over ({revoked.get('by')}); this is not a map defect",
                            details, "Retry the capture later, after the user's session ends (use --wait)")
        if lease and "_invalid" not in lease:
            previous = lease.get("previous") or {}
            extra = {"your_lease_reclaimed": previous.get("reason")} if previous.get("session") == session else {}
            raise self._busy(lease, "held", f"The game is leased by {lease.get('holder')}, not this session",
                             "Acquire the lease (with --wait) before driving the game", **extra)
        raise GameError("lease_not_held", "This session does not hold the game lease", {"session": session},
                        "Acquire it first: sabermapper game lease --acquire --purpose TEXT")

    def heartbeat(self, session: str | None = None) -> dict:
        session = check_session(session or default_session())
        with self._lock():
            lease = self.check_owner(session)
            lease["heartbeat_at"] = _iso(self.clock())
            self._write(lease, create=False)
            return lease

    def set_game_pid(self, session: str | None, pid: int | None, launched_by_agent: bool) -> dict:
        session = check_session(session or default_session())
        with self._lock():
            lease = self.check_owner(session)
            lease.update(game_pid=int(pid) if pid else None, launched_by_agent=bool(launched_by_agent),
                         heartbeat_at=_iso(self.clock()))
            self._write(lease, create=False)
            return lease

    def release(self, session: str | None = None) -> dict:
        """Delete this session's lease. A preempted session gets game_preempted info; the human's lease stays."""
        session = check_session(session or default_session())
        with self._lock():
            try:
                lease = self.check_owner(session)
            except GameError as error:
                if error.code == "game_busy":
                    raise GameError("lease_not_held", "This session does not hold the game lease; nothing released",
                                    {"session": session, "current": error.details}) from None
                if error.code != "game_preempted":
                    raise
                self.forget(session)
                return {"released": False, "reason": "game_preempted", "message": error.message,
                        "details": error.details, "fix": error.fix}
            self._delete()
            self.forget(session)
            return {"released": True, "holder": lease.get("holder"), "session": session,
                    "game_pid": lease.get("game_pid"), "launched_by_agent": lease.get("launched_by_agent")}

    def status(self, session: str | None = None) -> dict:
        session = check_session(session or default_session())
        lease = self.read()
        state = self.assess(lease)
        pids = self.game_running()
        own = bool(lease and "_invalid" not in lease and lease.get("session") == session
                   and self.stored_token(session) in (None, lease.get("token")))
        return {"lease": public_lease(lease, self), "live": state["live"], "stale_reason": state["stale_reason"],
                "game_running": bool(pids), "game_pids": pids, "own": own, "session": session,
                "lease_file": str(self.lease_file), "stale_after_s": self.stale_after}


def _default_pid_alive(pid):
    return pid_alive(pid)


def public_lease(lease: dict | None, manager: GameLease | None = None) -> dict | None:
    """Lease with the token redacted (status output ends up in transcripts)."""
    if lease is None:
        return None
    if "_invalid" in lease:
        return {"invalid": lease["_invalid"]}
    public = {key: value for key, value in lease.items() if key != "token"}
    public["token_sha256"] = token_sha256(lease["token"])
    if manager is not None:
        age = manager.heartbeat_age(lease)
        public["heartbeat_age_s"] = None if age is None else round(age, 1)
    return public


class LeaseHandle:
    """Yielded by held_lease: the owned lease plus a check before every bridge command."""

    def __init__(self, manager: GameLease, session: str, lease: dict):
        self.manager, self.session, self.lease, self.preempted = manager, session, lease, False

    @property
    def token(self) -> str:
        return self.lease["token"]

    def check(self) -> dict:
        try:
            self.lease = self.manager.check_owner(self.session)
        except GameError as error:
            self.preempted = error.code == "game_preempted" or self.preempted
            raise
        return self.lease

    def set_game_pid(self, pid: int | None, launched_by_agent: bool) -> dict:
        self.lease = self.manager.set_game_pid(self.session, pid, launched_by_agent)
        return self.lease


@contextmanager
def held_lease(holder: str | None = None, *, session: str | None = None, on_release=None,
               heartbeat_every: float = HEARTBEAT_EVERY, manager: GameLease | None = None, **acquire_args):
    """Acquire, heartbeat from a daemon thread, and on exit run on_release(lease) then release.

    on_release runs only while this session still owns the lease (never after a human preemption),
    so "close the game if launched_by_agent" can never close the user's game.
    """
    manager = manager or GameLease()
    session = check_session(session or default_session())
    lease = manager.acquire(holder, session=session, **acquire_args)
    handle = LeaseHandle(manager, session, lease)
    stop = threading.Event()

    def beat():
        while not stop.wait(heartbeat_every):
            try:
                handle.lease = manager.heartbeat(session)
            except GameError as error:
                if error.code in ("game_preempted", "game_busy", "lease_not_held"):
                    handle.preempted = True
                    return
            except OSError:
                pass

    thread = threading.Thread(target=beat, name="sabermapper-lease-heartbeat", daemon=True)
    thread.start()
    try:
        yield handle
    finally:
        stop.set()
        thread.join(timeout=5)
        owned = manager.own_lease(session)
        try:
            if owned is not None and on_release is not None:
                on_release(owned)
        finally:
            if owned is not None:
                manager.release(session)
            else:
                handle.preempted = handle.preempted or manager.revocation(lease["token"]) is not None
                manager.forget(session)


def _manager(root=None, game_running=None, pid_alive=None, stale_after=None) -> GameLease:
    return GameLease(root, game_running=game_running, pid_alive=pid_alive, stale_after=stale_after)


def acquire(holder=None, *, session=None, worktree=None, project=None, purpose="", holder_kind="agent",
            wait=0.0, root=None, game_running=None, pid_alive=None, stale_after=None, poll=2.0) -> dict:
    return _manager(root, game_running, pid_alive, stale_after).acquire(
        holder, session=session, worktree=worktree, project=project, purpose=purpose,
        holder_kind=holder_kind, wait=wait, poll=poll)


def heartbeat(session=None, *, root=None, **kw) -> dict:
    return _manager(root, **kw).heartbeat(session)


def set_game_pid(session, pid, launched_by_agent, *, root=None, **kw) -> dict:
    return _manager(root, **kw).set_game_pid(session, pid, launched_by_agent)


def release(session=None, *, root=None, **kw) -> dict:
    return _manager(root, **kw).release(session)


def status(session=None, *, root=None, **kw) -> dict:
    return _manager(root, **kw).status(session)


def own_lease(session=None, *, root=None, **kw) -> dict | None:
    return _manager(root, **kw).own_lease(session)


def check_owner(session=None, *, root=None, **kw) -> dict:
    return _manager(root, **kw).check_owner(session)
