"""SaberMapper Bridge client, install layout, capture planning/manifest, api.py flows and the csc build script.

A fake bridge (stdlib HTTP server) enforces the lease token the way the real mod does; no game is started.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile

from PIL import Image

from sabermapper.__main__ import main
from sabermapper.game import api, build, capture, install
from sabermapper.game.bridge import BridgeClient
from sabermapper.game.errors import GameError
from sabermapper.game.lease import GameLease
from sabermapper.projects import ProjectStore


class FakeBridge:
    """Minimal in-process stand-in for the C# bridge, including the lease check."""

    def __init__(self, lease_root: Path):
        self.lease_root = Path(lease_root)
        self.state = {"scene": "menu", "level": None, "song_time": None, "song_length": None, "paused": False,
                      "speed": None, "fps": 144.0, "capture": None, "autoplay": False, "songs_loading": False,
                      "songs_ready": True, "last_error": None, "version": 1}
        self.calls, self.job = [], None
        self.loaded_at = None
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                path = self.path.split("?")[0]
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                bridge.calls.append((method, path, body))
                if path != "/health":
                    lease_file = bridge.lease_root / "game-lease.json"
                    if not lease_file.exists():
                        return self._send(403, {"error": {"code": "lease_not_held", "message": "no lease", "details": {}}})
                    token = json.loads(lease_file.read_text())["token"]
                    if self.headers.get("X-SaberMapper-Lease") != token:
                        return self._send(403, {"error": {"code": "lease_invalid", "message": "bad token", "details": {}}})
                status, result = bridge.route(method, path, body)
                self._send(status, result)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _bump(self):
        self.state["version"] += 1

    def route(self, method, path, body):
        st = self.state
        if self.loaded_at is not None and st["scene"] == "game":
            st["song_time"] = round(self.start + (time.monotonic() - self.loaded_at), 4)
        if (method, path) == ("GET", "/health"):
            return 200, {"bridge_version": "0.1.0", "game_version": "1.40.8", "scene": st["scene"], "pid": 4242}
        if (method, path) == ("GET", "/state"):
            return 200, dict(st)
        if (method, path) == ("POST", "/refresh"):
            if st["scene"] != "menu":
                return 409, {"error": {"code": "not_in_menu", "message": "menu first", "details": {}}}
            return 200, {"refreshing": False, "completed": True, "full": body.get("full")}
        if (method, path) == ("POST", "/load"):
            if not Path(body["level_path"], "Info.dat").is_file():
                return 404, {"error": {"code": "level_not_found", "message": "nope", "details": {}}}
            self.start = float(body.get("start_time", 0))
            st.update(scene="game", song_time=self.start, song_length=200.0, speed=body.get("speed", 1.0),
                      level={"level_path": body["level_path"], "difficulty": body.get("difficulty")})
            self.loaded_at = time.monotonic()
            self._bump()
            return 200, {"accepted": True, "load": body}
        if (method, path) == ("POST", "/menu"):
            st.update(scene="menu", song_time=None, level=None)
            self.loaded_at = None
            self._bump()
            return 200, {"menu": True}
        if (method, path) in (("POST", "/pause"), ("POST", "/resume")):
            st["paused"] = path == "/pause"
            self._bump()
            return 200, {"paused": st["paused"]}
        if (method, path) in (("POST", "/seek"), ("POST", "/restart")):
            self.start = float(body.get("time", body.get("start_time", self.start)))
            self.loaded_at = time.monotonic()
            st["song_time"] = self.start
            self._bump()
            return 200, {"restarting": True, "start_time": self.start}
        if (method, path) == ("POST", "/capture"):
            out = Path(body["out_dir"])
            out.mkdir(parents=True, exist_ok=True)
            frames = []
            requests = [dict(f, reason=f.get("reason")) for f in body.get("frames", [])]
            probe = body.get("probe")
            if probe:
                count = int((probe["end"] - probe["start"]) * probe["fps"]) + 1
                requests += [{"time": probe["start"] + i / probe["fps"], "name": f"probe-{i:05d}.png", "reason": "probe"}
                             for i in range(count)]
            for request in requests:
                Image.new("RGB", (64, 36), (10, 20, 30)).save(out / request["name"])
                frames.append({"name": request["name"], "file": str(out / request["name"]),
                               "requested_time": request["time"], "song_time": round(request["time"] + 0.004, 4),
                               "frame": 1, "reason": request["reason"], "written": True})
            self.job = {"job_id": 1, "status": "done", "captured": len(frames), "written": len(frames),
                        "dropped": 0, "frames": frames}
            st["capture"] = {k: v for k, v in self.job.items() if k != "frames"}
            self._bump()
            return 200, {k: v for k, v in self.job.items() if k != "frames"}
        if (method, path) == ("GET", "/capture"):
            return 200, self.job
        if (method, path) == ("POST", "/capture/cancel"):
            return 200, {"cancelled": False}
        return 404, {"error": {"code": "not_found", "message": path, "details": {}}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.lease_root = root / "lease"
        self.game_dir = root / "Beat Saber"
        (self.game_dir / "Beat Saber_Data" / "CustomWIPLevels").mkdir(parents=True)
        (self.game_dir / "Logs").mkdir()
        (self.game_dir / "Logs" / "_latest.log").write_text("", encoding="utf-8")
        (self.game_dir / "BeatSaberVersion.txt").write_text("1.40.8_7379", encoding="utf-8")
        self.store = ProjectStore(root / "workspace")
        self.project_id = self.store.create(demo=True)["project"]["id"]
        self.bridge = FakeBridge(self.lease_root)
        self.pids, self.launched, self.closed = [], [], []
        self.manager = GameLease(self.lease_root, game_running=lambda: list(self.pids),
                                 pid_alive=lambda pid: pid in self.pids)

    def tearDown(self):
        self.bridge.close()
        self.tmp.cleanup()

    def launcher(self, fpfc):
        self.launched.append(fpfc)
        self.pids.append(4242)
        return 4242

    def closer(self, pid):
        self.closed.append(pid)
        if pid in self.pids:
            self.pids.remove(pid)
        return {"closed": True, "pid": pid, "was_running": True, "forced": False}

    def game(self, session="agent-a", holder="agent:test", **extra) -> api.Game:
        return api.Game(session=session, holder=holder, game_dir=self.game_dir, manager=self.manager,
                        client_factory=lambda token: BridgeClient(token, port=self.bridge.port, timeout=5),
                        launcher=self.launcher, closer=self.closer, find=lambda: list(self.pids),
                        alive=lambda pid: pid in self.pids, **extra)

    def options(self, game: api.Game) -> dict:
        return {"session": game.session, "holder": game.holder, "game_dir": self.game_dir, "manager": self.manager,
                "client_factory": game.client_factory, "launcher": self.launcher, "closer": self.closer,
                "find": game.find, "alive": game.alive}


class ClientTests(Fixture):
    def test_lease_token_is_required_and_errors_keep_their_code(self):
        client = BridgeClient(None, port=self.bridge.port)
        self.assertEqual(client.health()["scene"], "menu")
        with self.assertRaises(GameError) as caught:
            client.state()
        self.assertEqual(caught.exception.code, "lease_not_held")
        lease = self.manager.acquire("agent:test", session="agent-a", purpose="test")
        with self.assertRaises(GameError) as caught:
            BridgeClient("wrong", port=self.bridge.port).state()
        self.assertEqual(caught.exception.code, "lease_invalid")
        self.assertEqual(caught.exception.details["status"], 403)
        self.assertEqual(BridgeClient(lease["token"], port=self.bridge.port).state()["scene"], "menu")

    def test_unreachable_bridge_is_structured(self):
        with self.assertRaises(GameError) as caught:
            BridgeClient("t", port=1, timeout=1).health()
        self.assertEqual(caught.exception.code, "bridge_unreachable")
        self.assertIn("fix", caught.exception.to_dict()["error"])

    def test_port_comes_from_bridge_json(self):
        self.lease_root.mkdir(parents=True, exist_ok=True)
        (self.lease_root / "bridge.json").write_text(json.dumps({"port": 31337, "pid": 1}), encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SABERMAPPER_BRIDGE_PORT", None)
            self.assertEqual(BridgeClient("t", root=self.lease_root).port, 31337)


class InstallTests(Fixture):
    def _zip(self, entries: dict) -> Path:
        path = Path(self.tmp.name) / f"map-{len(entries)}-{time.monotonic_ns()}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return path

    def test_install_replaces_previous_folder_and_records_provenance(self):
        first = install.install_folder(self._zip({"Info.dat": "{}", "old.dat": "1"}), "SaberMapper-x",
                                       record={"project": "x", "revision": "a"}, game_dir=self.game_dir)
        second = install.install_folder(self._zip({"Info.dat": "{}", "ExpertPlus.dat": "{}"}), "SaberMapper-x",
                                        record={"project": "x", "revision": "b"}, game_dir=self.game_dir)
        self.assertEqual(first["level_path"], second["level_path"])
        self.assertEqual(second["files"], ["ExpertPlus.dat", "Info.dat", "sabermapper-install.json"])
        self.assertEqual(install.installed("SaberMapper-x", self.game_dir)["revision"], "b")
        wip = self.game_dir / "Beat Saber_Data" / "CustomWIPLevels"
        self.assertEqual(sorted(p.name for p in wip.iterdir()), ["SaberMapper-x"])  # no staging leftovers
        self.assertTrue(install.uninstall("SaberMapper-x", self.game_dir)["removed"])

    def test_install_rejects_unsafe_archives_and_names(self):
        with self.assertRaises(GameError) as caught:
            install.install_folder(self._zip({"Info.dat": "{}", "../evil.dat": "x"}), "SaberMapper-x", record={},
                                   game_dir=self.game_dir)
        self.assertEqual(caught.exception.code, "install_invalid")
        with self.assertRaises(GameError):
            install.install_folder(self._zip({"song.ogg": "x"}), "SaberMapper-x", record={}, game_dir=self.game_dir)
        with self.assertRaises(GameError):
            install.install_folder(self._zip({"Info.dat": "{}"}), "CustomLevel", record={}, game_dir=self.game_dir)
        self.assertEqual(list((self.game_dir / "Beat Saber_Data" / "CustomWIPLevels").iterdir()), [])

    def test_install_project_exports_current_revision_and_rejects_unknown_revisions(self):
        result = install.install_project(self.store, self.project_id, game_dir=self.game_dir)
        record = json.loads(Path(result["level_path"], "sabermapper-install.json").read_text(encoding="utf-8"))
        current = self.store.get(self.project_id)["revision"]
        self.assertEqual((record["project"], record["revision"], record["current_revision"]),
                         (self.project_id, current, True))
        self.assertTrue(Path(result["level_path"], "Info.dat").is_file())
        self.assertEqual(Path(result["level_path"]).name, f"SaberMapper-{self.project_id}")
        with self.assertRaises(GameError) as caught:
            install.install_project(self.store, self.project_id, revision="f" * 64, game_dir=self.game_dir)
        self.assertEqual(caught.exception.code, "stale_revision")

    def test_custom_event_detection(self):
        level = Path(self.tmp.name) / "lvl"
        level.mkdir()
        (level / "Info.dat").write_text(json.dumps({"_songName": "x"}), encoding="utf-8")
        (level / "ExpertPlus.dat").write_text(json.dumps({"version": "3.3.0", "colorNotes": []}), encoding="utf-8")
        self.assertFalse(install.uses_custom_events(level))
        (level / "ExpertPlus.dat").write_text(json.dumps({"customData": {"customEvents": [{"b": 0}]}}), encoding="utf-8")
        self.assertTrue(install.uses_custom_events(level))
        (level / "ExpertPlus.dat").write_text("{}", encoding="utf-8")
        (level / "Info.dat").write_text(json.dumps({"_customData": {"_requirements": ["Vivify"]}}), encoding="utf-8")
        self.assertTrue(install.uses_custom_events(level))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.arrangement = {"song": {"bpm": 120, "audio_offset_seconds": 0.5}, "tempo_events": [],
                            "sections": [{"id": "a", "start_beat": 0, "length_beats": 32},
                                         {"id": "b", "start_beat": 32, "length_beats": 32}]}

    def test_default_plan_has_sections_moments_and_grid_merged(self):
        plan = capture.capture_plan(self.arrangement, duration=40.0, every_beats=16,
                                    moments=[{"time": 16.52, "kind": "drop"}])
        times = [(p["time"], p["reason"]) for p in plan]
        self.assertIn((0.5, "section_start"), times)       # beat 0 == offset, section wins over grid
        self.assertIn((16.5, "section_start"), times)      # beat 32; the moment 20 ms later is merged away
        self.assertIn((8.5, "grid"), times)
        self.assertEqual(plan[0]["name"], "t0000.500.png")
        self.assertTrue(all(p["time"] <= 40.0 - capture.END_MARGIN for p in plan))
        self.assertEqual(len({p["time"] for p in plan}), len(plan))

    def test_explicit_times_replace_defaults(self):
        plan = capture.capture_plan(self.arrangement, duration=40.0, times=[3.0, 99.0])
        self.assertEqual([(p["time"], p["reason"]) for p in plan], [(3.0, "requested"), (39.75, "requested")])
        grid = capture.capture_plan(self.arrangement, duration=40.0, times=[3.0], every_beats=32, explicit_grid=True)
        self.assertEqual({p["reason"] for p in grid}, {"requested", "grid"})

    def test_parsers(self):
        self.assertEqual(capture.parse_times("1, 2.5,30"), [1.0, 2.5, 30.0])
        self.assertEqual(capture.parse_probe("40-43@25")["fps"], 25.0)
        self.assertEqual(capture.parse_probe("40-43")["fps"], capture.PROBE_FPS)
        for bad in ("43-40@30", "x-2", "1-2@500"):
            with self.assertRaises(GameError):
                capture.parse_probe(bad)
        with self.assertRaises(GameError):
            capture.parse_times("1,a")

    def test_default_probe_prefers_moments_else_densest_notes(self):
        probe = capture.default_probe(self.arrangement, duration=60, moments=[
            {"time": 10.0, "kind": "riser", "strength": 0.9}, {"time": 30.0, "kind": "drop", "strength": 0.4}])
        self.assertEqual((probe["start"], probe["end"], probe["fps"]), (30.0, 33.0, 30.0))
        arrangement = dict(self.arrangement, motifs={}, sections=[{"id": "a", "start_beat": 0, "length_beats": 64,
            "patterns": [], "notes": [{"id": str(i), "beat": b, "x": 1, "y": 0, "color": 0, "direction": 1}
                                      for i, b in enumerate([0, 40, 40.5, 41, 41.5, 42])]}])
        dense = capture.default_probe(arrangement, duration=60)
        self.assertLessEqual(dense["start"], 20.5)
        self.assertGreaterEqual(dense["end"], 21.5)

    def test_manifest_shape(self):
        results = [{"name": "t0001.000.png", "requested_time": 1.0, "song_time": 1.004, "written": True},
                   {"name": "probe-00000.png", "requested_time": 20.0, "song_time": 20.01, "reason": "probe",
                    "written": True},
                   {"name": "t0002.000.png", "requested_time": 2.0, "song_time": 2.0, "written": False}]
        manifest = capture.build_manifest(meta={"project": "p"}, results=results,
                                          plan=[{"name": "t0001.000.png", "reason": "section_start", "time": 1.0}],
                                          arrangement=self.arrangement, log_diagnostics=[])
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual([f["file"] for f in manifest["frames"]], ["t0001.000.png", "probe-00000.png"])
        first = manifest["frames"][0]
        self.assertEqual(set(first), {"file", "requested_time", "song_time", "beat", "section_id", "reason"})
        self.assertEqual((first["reason"], first["section_id"]), ("section_start", "a"))
        self.assertAlmostEqual(first["beat"], (1.004 - 0.5) * 2, places=3)
        self.assertEqual(manifest["frames"][1]["section_id"], "b")


class ApiTests(Fixture):
    def test_launch_play_seek_pause_and_close(self):
        game = self.game()
        launched = api.launch(**self.options(game))
        self.assertTrue(launched["launched"])
        self.assertEqual(self.launched, [True])  # FPFC
        self.assertEqual(self.manager.own_lease("agent-a")["game_pid"], 4242)
        played = api.play_project(self.store, self.project_id, at=30.0, **self.options(game))
        self.assertEqual(played["state"]["scene"], "game")
        self.assertGreaterEqual(played["state"]["song_time"], 30.0)
        self.assertTrue(Path(played["level_path"], "sabermapper-install.json").is_file())
        load = next(body for method, path, body in self.bridge.calls if path == "/load")
        self.assertEqual((load["start_time"], load["modifiers"]), (30.0, "no_fail"))
        self.assertGreaterEqual(api.seek_to(80.0, **self.options(game))["state"]["song_time"], 80.0)
        self.assertTrue(api.pause_game(**self.options(game))["state"]["paused"])
        self.assertFalse(api.resume_game(**self.options(game))["state"]["paused"])
        status = api.game_status(**self.options(game))
        self.assertEqual(status["bridge"]["scene"], "game")
        closed = api.close(**self.options(game))
        self.assertEqual((closed["pid"], closed["release"]["released"]), (4242, True))
        self.assertEqual(self.closed, [4242])

    def test_play_requires_a_running_leased_game(self):
        game = self.game()
        with self.assertRaises(GameError) as caught:
            api.play_project(self.store, self.project_id, **self.options(game))
        self.assertEqual(caught.exception.code, "lease_not_held")
        self.manager.acquire("agent:test", session="agent-a", purpose="x")
        with self.assertRaises(GameError) as caught:
            api.play_project(self.store, self.project_id, **self.options(game))
        self.assertEqual(caught.exception.code, "game_not_running")

    def test_never_adopts_an_unleased_game(self):
        self.pids.append(999)
        with self.assertRaises(GameError) as caught:
            api.launch(**self.options(self.game()))
        self.assertEqual(caught.exception.code, "game_busy")
        self.assertEqual(self.launched, [])

    def test_close_refuses_games_this_session_did_not_launch(self):
        self.manager.acquire("agent:test", session="agent-a", purpose="x")
        with self.assertRaises(GameError) as caught:
            api.close(**self.options(self.game()))
        self.assertEqual(caught.exception.code, "game_not_launched_by_agent")

    def test_human_play_preempts_agent_and_relaunches_fpfc_in_vr(self):
        agent = self.game()
        api.launch(**self.options(agent))
        human = self.game(session="studio", holder="human:studio")
        result = api.play(self.store, self.project_id, seconds=12.0, **self.options(human))
        self.assertTrue(result["played"])
        self.assertEqual(result["closed_agent_fpfc"]["pid"], 4242)
        self.assertEqual(self.launched, [True, False])  # agent FPFC, then human VR
        load = [body for method, path, body in self.bridge.calls if path == "/load"][-1]
        self.assertEqual((load["start_time"], load["modifiers"]), (12.0, "player"))
        with self.assertRaises(GameError) as caught:
            api.play_project(self.store, self.project_id, **self.options(agent))
        self.assertEqual(caught.exception.code, "game_preempted")
        status = api.status(**self.options(human))
        self.assertEqual(set(status) >= {"running", "lease", "bridge"}, True)
        self.assertEqual(status["bridge"]["scene"], "game")
        stopped = api.stop(**self.options(human))
        self.assertTrue(stopped["release"]["released"])
        self.assertEqual(self.pids, [4242])  # the user's VR game keeps running

    def test_studio_sees_live_agent_leases_only(self):
        from sabermapper.server import live_agent_lease
        agent = self.game()
        api.launch(**self.options(agent))
        human = self.options(self.game(session="studio", holder="human:studio"))
        self.assertEqual(live_agent_lease(api.lease_status(**human))["holder"], "agent:test")
        self.assertEqual(live_agent_lease(api.status(**human)["lease"])["holder"], "agent:test")
        self.pids.clear()  # the agent's game died: its lease is stale
        self.assertIsNone(live_agent_lease(api.lease_status(**human)))

    def test_watch_is_reported_unavailable_without_touching_the_game(self):
        result = api.play(self.store, self.project_id, mode="watch", **self.options(self.game(session="studio")))
        self.assertEqual(result["watch"], "unavailable")
        self.assertEqual(self.launched, [])
        self.assertIsNone(self.manager.read())

    def test_capture_run_writes_manifest_closes_game_and_releases(self):
        game = self.game()
        out = Path(self.tmp.name) / "cap"
        report = capture.run_capture(self.store, self.project_id, times=[2.0, 5.0], probe={"start": 3, "end": 3.2, "fps": 10},
                                     out=out, game=game)
        self.assertEqual((report["status"], report["launched"], report["closed"]), ("done", True, True))
        self.assertEqual(report["start_time"], 0.0)  # max(0, 2 - preroll): vanilla demo map has no custom events
        self.assertFalse(report["custom_events"])
        manifest = json.loads((out / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest) >= {"schema_version", "project", "revision", "difficulty", "camera", "width",
                                           "height", "game_version", "level_path", "created_at", "frames",
                                           "log_diagnostics"}, True)
        self.assertEqual((manifest["width"], manifest["height"], manifest["game_version"]), (64, 36, "1.40.8_7379"))
        reasons = [f["reason"] for f in manifest["frames"]]
        self.assertEqual(reasons.count("requested"), 2)
        self.assertEqual(reasons.count("probe"), 3)
        self.assertEqual(self.closed, [4242])
        self.assertIsNone(self.manager.read())
        from sabermapper.frames import load_capture
        self.assertEqual(len(load_capture(out)["frames"]), 5)

    def test_capture_keep_open_keeps_game_and_lease(self):
        game = self.game()
        report = capture.run_capture(self.store, self.project_id, times=[1.0], auto_probe=False, keep_open=True,
                                     out=Path(self.tmp.name) / "k", game=game)
        self.assertFalse(report["closed"])
        self.assertEqual(self.pids, [4242])
        self.assertEqual(self.manager.own_lease("agent-a")["game_pid"], 4242)


class BuildTests(unittest.TestCase):
    def test_command_embeds_manifest_and_references(self):
        command = build.csc_command(Path("csc.exe"), [Path("G/Managed/Main.dll")], [Path("src/Plugin.cs")],
                                    Path("bin/SaberMapperBridge.dll"), Path("manifest.json"))
        self.assertIn("-nostdlib+", command)
        self.assertIn("-target:library", command)
        self.assertIn(f"-resource:manifest.json,SaberMapperBridge.manifest.json", command)
        self.assertIn(f"-reference:{Path('G/Managed/Main.dll')}", command)
        self.assertEqual(command[-1], str(Path("src/Plugin.cs")))

    def test_parse_diagnostics(self):
        output = ("src\\GameController.cs(409,34): error CS0311: The type 'X' cannot be used\n"
                  "warning CS1701: Assuming assembly reference\n"
                  "noise line\n")
        diagnostics = build.parse_diagnostics(output)
        self.assertEqual(diagnostics[0], {"file": "src\\GameController.cs", "line": 409, "column": 34,
                                          "severity": "error", "code": "CS0311",
                                          "message": "The type 'X' cannot be used"})
        self.assertEqual((diagnostics[1]["severity"], diagnostics[1]["line"]), ("warning", None))

    def test_compile_errors_are_structured(self):
        class Result:
            returncode, stdout, stderr = 1, "src\\A.cs(3,5): error CS1002: ; expected\n", ""
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(build, "find_csc", return_value=Path("csc")), \
                unittest.mock.patch.object(build, "reference_paths", return_value=[]):
            bridge_dir = Path(tmp)
            (bridge_dir / "src").mkdir()
            (bridge_dir / "src" / "A.cs").write_text("class A { int x }", encoding="utf-8")
            with self.assertRaises(GameError) as caught:
                build.build(bridge_dir=bridge_dir, run=lambda *a, **k: Result())
        error = caught.exception
        self.assertEqual(error.code, "bridge_compile_failed")
        self.assertEqual(error.details["errors"][0]["code"], "CS1002")

    def test_missing_compiler_or_game_is_reported(self):
        with self.assertRaises(GameError) as caught:
            build.find_csc(Path("Z:/nowhere/csc.exe"))
        self.assertEqual(caught.exception.code, "csc_missing")
        with self.assertRaises(GameError) as caught:
            build.reference_paths(Path(tempfile.gettempdir()) / "no-beat-saber-here")
        self.assertEqual(caught.exception.code, "game_not_found")

    def test_real_compile_when_toolchain_present(self):
        try:
            build.find_csc()
            build.reference_paths()
        except GameError as error:
            self.skipTest(f"csc or game assemblies absent ({error.code})")
        with tempfile.TemporaryDirectory() as tmp:
            bridge_dir = Path(tmp) / "game-bridge"
            shutil.copytree(build.BRIDGE_DIR, bridge_dir, ignore=shutil.ignore_patterns("bin", "obj"))
            report = build.build(bridge_dir=bridge_dir)
            self.assertTrue(report["built"])
            self.assertGreater(report["size"], 10000)
            self.assertIsNone(report["installed"])


class CliTests(Fixture):
    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(list(argv))
        return code, json.loads(buffer.getvalue())

    def test_invalid_capture_arguments_print_json_errors(self):
        code, output = self.run_cli("game", "capture", self.project_id, "--workspace", str(self.store.root),
                                    "--probe", "9-3", "--lease-dir", str(self.lease_root))
        self.assertEqual(code, 2)
        self.assertEqual(output["error"]["code"], "capture_invalid")

    def test_build_bridge_reports_missing_compiler(self):
        code, output = self.run_cli("game", "build-bridge", "--csc", str(Path(self.tmp.name) / "csc.exe"))
        self.assertEqual((code, output["error"]["code"]), (2, "csc_missing"))


if __name__ == "__main__":
    unittest.main()
