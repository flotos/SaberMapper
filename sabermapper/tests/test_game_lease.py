import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from sabermapper.__main__ import main
from sabermapper.game.errors import GameError
from sabermapper.game.lease import GameLease, held_lease, token_sha256

APP = Path(__file__).resolve().parents[1]


class FakeGame:
    def __init__(self, running=(), alive=()):
        self.running, self.alive = list(running), set(alive)

    def pids(self):
        return list(self.running)

    def is_alive(self, pid):
        return pid in self.alive or pid in self.running


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.game = FakeGame()
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def manager(self, **kw):
        return GameLease(self.root, game_running=self.game.pids, pid_alive=self.game.is_alive,
                         clock=kw.pop("clock", self.clock), **kw)

    def acquire(self, session, **kw):
        kw.setdefault("purpose", "capture")
        kw.setdefault("worktree", f"C:/wt/{session}")
        return self.manager().acquire(f"agent:{session}", session=session, **kw)

    def assertGameError(self, code, fn, *args, **kw):
        with self.assertRaises(GameError) as caught:
            fn(*args, **kw)
        self.assertEqual(caught.exception.code, code, caught.exception.to_dict())
        return caught.exception

    def test_acquire_writes_schema_and_is_idempotent_per_session(self):
        lease = self.acquire("a", project="p1")
        stored = json.loads((self.root / "game-lease.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["token"], lease["token"])
        for key in ("schema_version", "holder", "holder_kind", "session", "worktree", "project", "purpose",
                    "game_pid", "launched_by_agent", "holder_pid", "acquired_at", "heartbeat_at", "previous"):
            self.assertIn(key, stored)
        self.assertEqual((stored["holder_kind"], stored["project"], stored["game_pid"]), ("agent", "p1", None))
        self.clock.now += 5
        again = self.acquire("a")
        self.assertEqual(again["token"], lease["token"])
        self.assertNotEqual(again["heartbeat_at"], lease["heartbeat_at"])
        self.assertEqual(self.manager().own_lease("a")["token"], lease["token"])
        self.assertIsNone(self.manager().own_lease("b"))

    def test_other_live_holder_gets_game_busy_naming_holder(self):
        self.acquire("a", project="p1", purpose="capture p1")
        error = self.assertGameError("game_busy", self.acquire, "b")
        self.assertEqual(error.details["holder"], "agent:a")
        self.assertEqual(error.details["purpose"], "capture p1")
        self.assertEqual(error.details["reason"], "held")
        self.assertIn("heartbeat_age_s", error.details)
        self.assertIn("--wait", error.fix)

    def test_concurrent_threads_exactly_one_winner(self):
        barrier = threading.Barrier(8)
        results = []

        def worker(index):
            barrier.wait()
            try:
                self.manager().acquire(f"agent:{index}", session=f"s{index}", worktree=None, purpose="race")
                results.append("ok")
            except GameError as error:
                results.append(error.code)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(results.count("game_busy"), 7, results)

    def test_concurrent_processes_exactly_one_winner(self):
        script = (
            "import sys\n"
            "from sabermapper.game.lease import GameLease\n"
            "from sabermapper.game.errors import GameError\n"
            "m = GameLease(sys.argv[1], game_running=lambda: [], pid_alive=lambda pid: False)\n"
            "import time\n"
            "start = float(sys.argv[3])\n"
            "time.sleep(max(0, start - time.time()))\n"
            "try:\n"
            "    m.acquire('agent:' + sys.argv[2], session=sys.argv[2], worktree=None, purpose='race')\n"
            "    print('ok')\n"
            "except GameError as e:\n"
            "    print(e.code)\n")
        start = time.time() + 2.0
        env = {**os.environ, "PYTHONPATH": str(APP)}
        procs = [subprocess.Popen([sys.executable, "-c", script, str(self.root), f"p{i}", str(start)], cwd=APP,
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for i in range(5)]
        outputs = [proc.communicate(timeout=60) for proc in procs]
        results = [out.strip() for out, _ in outputs]
        self.assertEqual(results.count("ok"), 1, outputs)
        self.assertEqual(results.count("game_busy"), 4, outputs)

    def test_stale_reclaim_when_game_pid_dead(self):
        self.acquire("a")
        self.manager().set_game_pid("a", 111, True)
        self.game.alive = set()  # the agent's game exited, nothing running
        lease = self.acquire("b")
        self.assertEqual(lease["session"], "b")
        self.assertEqual(lease["previous"]["reason"], "game_exited")
        self.assertEqual(lease["previous"]["session"], "a")
        error = self.assertGameError("game_busy", self.manager().check_owner, "a")
        self.assertEqual(error.details["your_lease_reclaimed"], "game_exited")

    def test_stale_reclaim_when_heartbeat_expired(self):
        self.acquire("a")
        self.clock.now += 601
        lease = self.acquire("b")
        self.assertEqual(lease["previous"]["reason"], "heartbeat_expired")

    def test_heartbeat_keeps_lease_live(self):
        self.acquire("a")
        self.clock.now += 400
        self.manager().heartbeat("a")
        self.clock.now += 400
        self.assertGameError("game_busy", self.acquire, "b")

    def test_orphaned_agent_game_is_refused_not_adopted(self):
        self.acquire("a")
        self.manager().set_game_pid("a", 222, True)
        self.game.running = [222]
        self.clock.now += 700
        error = self.assertGameError("game_busy", self.acquire, "b")
        self.assertEqual(error.details["reason"], "orphaned_agent_game")
        self.assertIn("close", error.fix)
        self.assertEqual(json.loads((self.root / "game-lease.json").read_text())["session"], "a")

    def test_unleased_running_game_is_refused(self):
        self.game.running = [333]
        error = self.assertGameError("game_busy", self.acquire, "a")
        self.assertEqual(error.details["reason"], "unleased_game")
        self.assertEqual(error.details["game_pids"], [333])
        self.assertFalse((self.root / "game-lease.json").exists())

    def test_stale_lease_with_unleased_game_is_refused(self):
        self.acquire("a")
        self.clock.now += 700
        self.game.running = [999]  # the user started the game after the agent's lease went stale
        error = self.assertGameError("game_busy", self.acquire, "b")
        self.assertEqual(error.details["reason"], "unleased_game")

    def test_human_preempts_agent_and_adopts_its_game(self):
        agent = self.acquire("a")
        self.manager().set_game_pid("a", 444, True)
        self.game.running = [444]
        human = self.manager().acquire("human:studio", session="studio", holder_kind="human", purpose="play")
        self.assertEqual((human["holder_kind"], human["game_pid"], human["launched_by_agent"]), ("human", 444, True))
        self.assertNotEqual(human["token"], agent["token"])
        self.assertEqual(human["previous"]["reason"], "preempted_by_human")
        self.assertEqual(human["previous"]["token_sha256"], token_sha256(agent["token"]))
        revocations = (self.root / "game-lease-revocations.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(revocations[-1])["token_sha256"], token_sha256(agent["token"]))
        self.assertEqual(json.loads(revocations[-1])["by"], "human:studio")
        error = self.assertGameError("game_preempted", self.manager().check_owner, "a")
        self.assertIn("not a map defect", error.message)
        self.assertGameError("game_preempted", self.manager().heartbeat, "a")
        result = self.manager().release("a")
        self.assertEqual((result["released"], result["reason"]), (False, "game_preempted"))
        self.assertEqual(json.loads((self.root / "game-lease.json").read_text())["session"], "studio")
        self.assertGameError("game_busy", self.acquire, "a")

    def test_human_adopts_users_own_running_game(self):
        self.game.running = [555]
        human = self.manager().acquire("human:studio", session="studio", holder_kind="human", purpose="play")
        self.assertEqual((human["game_pid"], human["launched_by_agent"]), (555, False))

    def test_wait_queues_until_holder_releases(self):
        self.acquire("a")

        def release_later():
            time.sleep(0.3)
            self.manager().release("a")

        thread = threading.Thread(target=release_later)
        thread.start()
        lease = self.manager().acquire("agent:b", session="b", purpose="capture", wait=10, poll=0.05)
        thread.join()
        self.assertEqual(lease["session"], "b")

    def test_wait_times_out_with_game_busy(self):
        self.acquire("a")
        error = self.assertGameError("game_busy", self.manager().acquire, "agent:b", session="b", wait=0.2,
                                     poll=0.05)
        self.assertEqual(error.details["waited_s"], 0.2)

    def test_release_requires_own_lease(self):
        self.assertGameError("lease_not_held", self.manager().release, "a")
        self.acquire("a")
        self.assertGameError("lease_not_held", self.manager().release, "b")
        self.assertTrue(self.manager().release("a")["released"])
        self.assertFalse((self.root / "game-lease.json").exists())
        self.assertGameError("lease_not_held", self.manager().check_owner, "a")

    def test_held_lease_runs_on_release_and_releases_on_exception(self):
        self.game.running = []
        calls = []
        with self.assertRaises(RuntimeError):
            with held_lease("agent:a", session="a", purpose="capture", manager=self.manager(),
                            on_release=calls.append) as handle:
                handle.set_game_pid(777, True)
                raise RuntimeError("capture failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["game_pid"], calls[0]["launched_by_agent"]), (777, True))
        self.assertFalse((self.root / "game-lease.json").exists())
        self.assertFalse((self.root / "sessions" / "a.json").exists())

    def test_held_lease_preempted_mid_run_keeps_human_lease_and_game(self):
        calls = []
        with held_lease("agent:a", session="a", purpose="capture", manager=self.manager(),
                        on_release=calls.append) as handle:
            handle.set_game_pid(888, True)
            self.game.running = [888]
            self.manager().acquire("human:studio", session="studio", holder_kind="human", purpose="play")
            self.assertGameError("game_preempted", handle.check)
        self.assertEqual(calls, [])
        self.assertTrue(handle.preempted)
        lease = json.loads((self.root / "game-lease.json").read_text())
        self.assertEqual((lease["session"], lease["game_pid"]), ("studio", 888))

    def test_held_lease_heartbeats_in_background(self):
        manager = GameLease(self.root, game_running=self.game.pids, pid_alive=self.game.is_alive)
        with held_lease("agent:a", session="a", purpose="capture", manager=manager, heartbeat_every=0.05) as handle:
            first = handle.lease["heartbeat_at"]
            deadline = time.time() + 5
            while time.time() < deadline:
                if json.loads((self.root / "game-lease.json").read_text())["heartbeat_at"] != first:
                    break
                time.sleep(0.05)
            self.assertNotEqual(json.loads((self.root / "game-lease.json").read_text())["heartbeat_at"], first)

    def test_stale_lock_file_is_broken(self):
        lock = self.root / "game-lease.lock"
        lock.write_text("dead:1")
        old = time.time() - 60
        os.utime(lock, (old, old))
        self.assertEqual(self.acquire("a")["session"], "a")
        self.assertFalse(lock.exists())

    def test_invalid_lease_file_is_reclaimed_once_old(self):
        path = self.root / "game-lease.json"
        path.write_text("{not json")
        old = time.time() - 60
        os.utime(path, (old, old))
        self.clock.now = time.time()
        lease = self.acquire("a")
        self.assertEqual(lease["previous"]["reason"], "invalid")

    def test_status_redacts_token_and_reports_ownership(self):
        lease = self.acquire("a")
        status = self.manager().status("a")
        self.assertTrue(status["own"] and status["live"])
        self.assertNotIn("token", status["lease"])
        self.assertEqual(status["lease"]["token_sha256"], token_sha256(lease["token"]))
        self.assertFalse(self.manager().status("b")["own"])

    def test_invalid_session_id_is_rejected(self):
        self.assertGameError("lease_invalid", self.acquire, "../evil")


class LeaseCliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["game", "lease", *argv])
        return code, json.loads(out.getvalue())

    def test_cli_status_acquire_release_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("SABERMAPPER_LEASE_DIR")
            os.environ["SABERMAPPER_LEASE_DIR"] = tmp
            try:
                code, body = self.run_cli("--release", "--session", "cli")
                self.assertEqual(code, 2)
                self.assertEqual(body["error"]["code"], "lease_not_held")
                self.assertIn("fix", body["error"])
                code, body = self.run_cli("--acquire", "--session", "cli", "--holder", "agent:cli")
                self.assertEqual((code, body["error"]["code"]), (2, "lease_invalid"))
                from unittest import mock
                with mock.patch("sabermapper.game.lease.find_game_pids", return_value=[]):
                    code, body = self.run_cli("--acquire", "--session", "cli", "--holder", "agent:cli",
                                              "--purpose", "test", "--project", "p")
                    self.assertEqual(code, 0)
                    self.assertNotIn("token", body["lease"])
                    code, body = self.run_cli("--session", "cli")
                    self.assertEqual((code, body["own"], body["lease"]["holder"]), (0, True, "agent:cli"))
                    code, body = self.run_cli("--heartbeat", "--session", "cli")
                    self.assertEqual(code, 0)
                    code, body = self.run_cli("--release", "--session", "cli")
                    self.assertEqual((code, body["released"]), (0, True))
            finally:
                if old is None:
                    os.environ.pop("SABERMAPPER_LEASE_DIR", None)
                else:
                    os.environ["SABERMAPPER_LEASE_DIR"] = old


if __name__ == "__main__":
    unittest.main()
