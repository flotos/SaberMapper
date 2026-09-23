"""Studio verification console: timestamped notes, CLI twins and game endpoints (with a fake game API)."""

from contextlib import redirect_stdout
from copy import deepcopy
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from sabermapper.__main__ import main
from sabermapper.projects import ProjectStore
from sabermapper.revisions import arrangement_revision
from sabermapper.server import make_server
from sabermapper.storage import read_json, write_json

STATIC = Path(__file__).resolve().parents[1] / "sabermapper" / "static"


def fixture_project(root):
    """A demo project retimed to 120 BPM with a 0.5 s offset and a switch to 150 BPM at beat 64."""
    store = ProjectStore(root)
    project_id = store.create(demo=True)["project"]["id"]
    path = store.directory(project_id)
    arrangement = read_json(path / "arrangement.json")
    template = arrangement["sections"][0]
    arrangement["song"].update(bpm=120.0, audio_offset_seconds=0.5)
    arrangement["tempo_events"] = [{"beat": 64, "bpm": 150.0}]
    arrangement["sections"] = [{**deepcopy(template), "id": section_id, "start_beat": start, "length_beats": length,
                                "intent": intent, "notes": [], "patterns": [], "locked": False}
                               for section_id, start, length, intent in (
                                   ("intro", 0, 64, "Sparse intro"), ("verse", 64, 96, "Verse riff"),
                                   ("chorus", 160, 128, "Final chorus"))]
    for key in ("bombs", "obstacles", "arcs", "chains", "musical_focus"):
        for section in arrangement["sections"]:
            section.pop(key, None)
    write_json(path / "arrangement.json", arrangement)
    write_json(path / "history" / (arrangement_revision(arrangement) + ".json"), arrangement)
    meta = read_json(path / "project.json")
    meta["duration_seconds"] = 200.0
    write_json(path / "project.json", meta)
    return store, project_id, arrangement


class FakeGameError(Exception):
    def __init__(self, code, message="game error"):
        super().__init__(message)
        self.code = code

    def to_dict(self):
        return {"error": {"code": self.code, "message": str(self), "details": None, "fix": "Retry later"}}


class FakeGame:
    def __init__(self):
        self.calls, self.lease, self.fail = [], None, {}

    def _call(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.fail:
            raise self.fail[name]
        return {"ok": True, "action": name}

    def status(self):
        if "status" in self.fail:
            raise self.fail["status"]
        return {"running": True, "lease": self.lease,
                "bridge": {"scene": "GameCore", "level": {"level_id": "x", "level_path": "p", "characteristic": "Standard",
                                                           "difficulty": "Expert"},
                           "song_time": 12.5, "song_length": 200.0, "paused": False, "speed": 1.0, "fps": 90}}

    def lease_status(self):
        return {"lease": self.lease}

    def play(self, store, project_id, **kwargs):
        self._call("play", project_id, **kwargs)
        if kwargs.get("mode") == "watch":
            return {"watch": "unavailable", "message": "ghost autoplay (M6) is not built yet"}
        return {"playing": True, "project": project_id, "seconds": kwargs["seconds"]}

    def pause(self):
        return self._call("pause")

    def resume(self):
        return self._call("resume")

    def stop(self):
        return self._call("stop")

    def restart(self, seconds=None):
        return self._call("restart", seconds)

    def seek(self, seconds):
        return self._call("seek", seconds)


class TimestampedNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store, self.pid, self.arrangement = fixture_project(self.temp.name)
        self.revision = arrangement_revision(self.arrangement)

    def test_note_at_1_23_has_beat_and_section_through_tempo_change(self):
        # 0.5 s offset + 64 beats at 120 BPM = 32.5 s; then 50.5 s at 150 BPM = 126.25 beats -> beat 190.25.
        note = self.store.add_note(self.pid, song_time=83.0, text="Chorus lights too dark", source="studio")
        self.assertEqual((note["beat"], note["section"], note["section_label"]), (190.25, "chorus", "Final chorus"))
        self.assertEqual((note["kind"], note["project"], note["revision"], note["stale"]), ("note", self.pid, self.revision, False))
        self.assertEqual(self.store.add_note(self.pid, song_time=20.5, text="Intro")["beat"], 40.0)
        self.assertEqual(self.store.add_note(self.pid, song_time=0.25, text="Pre-roll")["section"], None)
        self.assertIn(note["id"], [f["id"] for f in self.store.get(self.pid)["feedback"]])

    def test_note_on_older_revision_is_kept_and_flagged_stale(self):
        path = self.store.directory(self.pid)
        newer = deepcopy(self.arrangement)
        newer["sections"][2]["start_beat"], newer["sections"][1]["length_beats"] = 200, 136
        write_json(path / "arrangement.json", newer)
        write_json(path / "history" / (arrangement_revision(newer) + ".json"), newer)
        note = self.store.add_note(self.pid, song_time=83.0, text="Seen on the old one", revision=self.revision)
        self.assertTrue(note["stale"])
        self.assertEqual((note["revision"], note["current_revision"]), (self.revision, arrangement_revision(newer)))
        self.assertEqual(note["section"], "chorus")  # sections of the reviewed revision, not the newer one
        self.assertEqual(self.store.add_note(self.pid, song_time=83.0, text="Current")["section"], "verse")
        listed = self.store.list_feedback(self.pid, kind="note")["feedback"]
        self.assertEqual([row["on_current_revision"] for row in listed if row["text"] == "Seen on the old one"], [False])

    def test_note_validation(self):
        for kwargs in ({"song_time": -1, "text": "x"}, {"song_time": 201, "text": "x"},
                       {"song_time": float("nan"), "text": "x"}, {"song_time": True, "text": "x"},
                       {"song_time": 10, "text": "   "}, {"song_time": 10, "text": "x" * 2001},
                       {"song_time": 10, "text": "x", "revision": "f" * 64},
                       {"song_time": 10, "text": "x", "revision": "not-a-sha"},
                       {"song_time": 10, "text": "x", "source": "agent"}):
            with self.assertRaises(ValueError, msg=kwargs):
                self.store.add_note(self.pid, **kwargs)
        with self.assertRaises(FileNotFoundError):
            self.store.add_note(self.pid, song_time=10, text="x", difficulty="Easy")

    def test_list_mixes_notes_and_ranges_sorted_by_song_time_with_filters(self):
        self.store.add_note(self.pid, song_time=83.0, text="late")
        ranged = self.store.add_feedback(self.pid, {"revision": self.revision, "start_beat": 8, "end_beat": 12,
                                                    "text": "early range"})
        self.store.add_note(self.pid, song_time=40.0, text="middle")
        result = self.store.list_feedback(self.pid)
        self.assertEqual([row["text"] for row in result["feedback"]], ["early range", "middle", "late"])
        first = result["feedback"][0]
        self.assertEqual((first["kind"], first["song_time"], first["section"], first["end_song_time"]),
                         ("range", 4.5, "intro", 6.5))
        self.assertEqual(result["current_revisions"], {"Expert": self.revision})
        self.assertEqual(len(self.store.list_feedback(self.pid, kind="note")["feedback"]), 2)
        self.assertEqual([r["id"] for r in self.store.list_feedback(self.pid, kind="range")["feedback"]], [ranged["id"]])
        self.assertEqual(self.store.list_feedback(self.pid, revision=self.revision[:10])["count"], 3)
        self.assertEqual(self.store.list_feedback(self.pid, revision="0000")["count"], 0)
        self.assertEqual(self.store.list_feedback(self.pid, since="2999-01-01")["count"], 0)
        self.assertEqual(self.store.list_feedback(self.pid, since="2000-01-01T00:00:00Z")["count"], 3)
        self.assertEqual(self.store.list_feedback(self.pid, difficulty="ExpertPlus")["count"], 0)
        for bad in ({"kind": "other"}, {"since": "yesterday"}, {"difficulty": "Hardest"}):
            with self.assertRaises(ValueError):
                self.store.list_feedback(self.pid, **bad)

    def test_cli_project_feedback_add_and_list(self):
        workspace = self.temp.name

        def cli(*argv):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(list(argv))
            self.assertEqual(code, 0)
            return json.loads(out.getvalue())
        added = cli("project", "feedback", "add", self.pid, "--workspace", workspace, "--at", "83",
                    "--text", "Chorus lights too dark")
        self.assertEqual((added["source"], added["beat"], added["section"]), ("cli", 190.25, "chorus"))
        cli("project", "feedback", "add", self.pid, "--workspace", workspace, "--at", "10", "--text", "Intro ok",
            "--revision", self.revision, "--difficulty", "Expert")
        listed = cli("project", "feedback", "list", self.pid, "--workspace", workspace, "--kind", "note")
        self.assertEqual([(r["song_time"], r["beat"], r["section"]) for r in listed["feedback"]],
                         [(10.0, 19.0, "intro"), (83.0, 190.25, "chorus")])
        self.assertEqual(cli("project", "feedback", "list", self.pid, "--workspace", workspace,
                             "--revision", self.revision, "--difficulty", "Expert", "--since", "2000-01-01")["count"], 2)
        # The existing top-level range command keeps working.
        cli("feedback", self.pid, "--workspace", workspace, "--start", "4", "--end", "8", "--text", "range",
            "--revision", self.revision)
        self.assertEqual(cli("project", "feedback", "list", self.pid, "--workspace", workspace)["count"], 3)
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(main(["project", "feedback", "add", self.pid, "--workspace", workspace,
                                   "--at", "999", "--text", "x"]), 1)
        self.assertIn("song duration", err.getvalue())


class GameConsoleServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store, self.pid, self.arrangement = fixture_project(self.temp.name)
        self.revision = arrangement_revision(self.arrangement)

    def serve(self, game):
        server = make_server(self.temp.name, port=0, game=game)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=5)))
        host = f"127.0.0.1:{server.server_port}"

        def request(method, path, data=None, token=True):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            headers = {"Host": host, "Content-Type": "application/json", "Origin": f"http://{host}"}
            if token and self.token:
                headers["X-SaberMapper-Token"] = self.token
            conn.request(method, path, body=None if data is None else json.dumps(data).encode(), headers=headers)
            response = conn.getresponse()
            body = json.loads(response.read() or b"null")
            conn.close()
            return response.status, body
        self.token = None
        self.token = request("GET", "/api/status")[1]["token"]
        return request

    def test_agent_lease_needs_confirmation_then_human_play_preempts(self):
        game = FakeGame()
        request = self.serve(game)
        game.lease = {"holder": "claude-worktree-a", "holder_kind": "agent", "purpose": "capture chorus",
                      "project": "other", "acquired_at": "2026-09-23T10:00:00+00:00"}
        body = {"project": self.pid, "revision": self.revision, "seconds": 83.0, "mode": "play"}
        status, reply = request("POST", "/api/game/play", body)
        self.assertEqual(status, 409)
        self.assertEqual(reply["error"]["code"], "game_busy")
        self.assertTrue(reply["error"]["details"]["preemptable"])
        self.assertIn("claude-worktree-a", reply["error"]["message"])
        self.assertIn("capture chorus", reply["error"]["message"])
        self.assertEqual(game.calls, [])
        status, reply = request("POST", "/api/game/play", {**body, "confirm_preempt": True})
        self.assertEqual((status, reply["playing"]), (200, True))
        name, args, kwargs = game.calls[-1]
        self.assertEqual((name, args), ("play", (self.pid,)))
        self.assertEqual(kwargs, {"seconds": 83.0, "difficulty": "Expert", "revision": self.revision,
                                  "mode": "play", "human": True})
        # A stale lease or one the human already holds never asks for confirmation.
        for lease in ({**game.lease, "stale": True}, {**game.lease, "holder_kind": "human"}):
            game.lease = lease
            self.assertEqual(request("POST", "/api/game/play", body)[0], 200)

    def test_play_validation_watch_and_status(self):
        game = FakeGame()
        request = self.serve(game)
        status, reply = request("GET", "/api/game/status")
        self.assertEqual((status, reply["available"], reply["bridge"]["song_time"]), (200, True, 12.5))
        status, reply = request("POST", "/api/game/play", {"project": self.pid, "mode": "watch"})
        self.assertEqual((status, reply["watch"]), (200, "unavailable"))
        self.assertEqual(game.calls[-1][2]["revision"], self.revision)
        self.assertEqual(request("POST", "/api/game/play", {"project": self.pid, "mode": "fly"})[0], 400)
        self.assertEqual(request("POST", "/api/game/play", {"project": self.pid, "seconds": 500})[0], 400)
        self.assertEqual(request("POST", "/api/game/play", {"project": self.pid, "seconds": -2})[0], 400)
        status, reply = request("POST", "/api/game/play", {"project": self.pid, "revision": "a" * 64})
        self.assertEqual((status, reply["error"]["code"]), (409, "stale_revision"))
        self.assertEqual(request("POST", "/api/game/play", {"project": "missing", "seconds": 1})[0], 404)
        self.assertEqual(request("POST", "/api/game/play", {"project": self.pid}, token=False)[0], 403)

    def test_transport_passthrough_and_error_mapping(self):
        game = FakeGame()
        request = self.serve(game)
        for action, data, expected in (("pause", {}, ()), ("resume", {}, ()), ("stop", {}, ()),
                                       ("restart", {}, (None,)), ("restart", {"seconds": 30}, (30.0,)),
                                       ("seek", {"seconds": 83.5}, (83.5,))):
            status, reply = request("POST", f"/api/game/{action}", data)
            self.assertEqual((status, reply["action"]), (200, action))
            self.assertEqual(game.calls[-1][:2], (action, expected))
        self.assertEqual(request("POST", "/api/game/seek", {})[0], 400)
        self.assertEqual(request("POST", "/api/game/seek", {"seconds": "soon"})[0], 400)
        self.assertEqual(request("POST", "/api/game/dance", {})[0], 400)
        for code, expected in (("game_preempted", 409), ("game_not_running", 409), ("lease_not_held", 409),
                               ("game_busy", 409), ("bridge_unreachable", 503), ("bridge_missing", 503),
                               ("something_new", 400)):
            game.fail["pause"] = FakeGameError(code, f"{code} happened")
            status, reply = request("POST", "/api/game/pause", {})
            self.assertEqual((status, reply["error"]["code"], reply["error"]["fix"]), (expected, code, "Retry later"))
        game.fail["status"] = FakeGameError("bridge_unreachable", "Bridge is not answering")
        status, reply = request("GET", "/api/game/status")
        self.assertEqual((status, reply["available"], reply["running"], reply["error"]["code"]),
                         (200, True, False, "bridge_unreachable"))

    def test_missing_game_module_reports_bridge_missing(self):
        with mock.patch.dict(sys.modules, {"sabermapper.game": None, "sabermapper.game.api": None}):
            request = self.serve(None)
            status, reply = request("GET", "/api/game/status")
            self.assertEqual((status, reply["available"], reply["error"]["code"]), (200, False, "bridge_missing"))
            for action in ("play", "pause", "seek"):
                status, reply = request("POST", f"/api/game/{action}", {"project": self.pid, "seconds": 1})
                self.assertEqual((status, reply["error"]["code"]), (503, "bridge_missing"))
                self.assertTrue(reply["error"]["fix"])

    def test_http_note_and_feedback_listing(self):
        request = self.serve(FakeGame())
        status, note = request("POST", f"/api/projects/{self.pid}/note",
                               {"song_time": 83.0, "text": "Too dark", "revision": self.revision})
        self.assertEqual((status, note["source"], note["beat"], note["section"]), (200, "studio", 190.25, "chorus"))
        self.assertEqual(request("POST", f"/api/projects/{self.pid}/note", {"song_time": 83.0, "text": ""})[0], 400)
        status, listed = request("GET", f"/api/projects/{self.pid}/feedback?kind=note")
        self.assertEqual((status, listed["count"], listed["feedback"][0]["id"]), (200, 1, note["id"]))
        status, project = request("GET", f"/api/projects/{self.pid}")
        self.assertEqual([f["kind"] for f in project["feedback"]], ["note"])


class StudioConsoleMarkupTests(unittest.TestCase):
    def test_index_and_app_include_the_verification_console(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        for element in ("verify-console", "verify-revision", "game-play-start", "game-play-playhead", "game-watch",
                        "game-pause", "game-resume", "game-restart", "song-slider", "slider-markers",
                        "lease-indicator", "note-button", "note-form", "note-text", "note-list", "preempt-dialog",
                        "confirm-preempt", "preview-map"):
            self.assertIn(f'id="{element}"', html)
            if element != "verify-console":
                self.assertIn(f"'{element}'", script)
        for call in ("/api/game/play", "/api/game/status", "/api/game/${action}", "confirm_preempt",
                     "/note`", "mode==='watch'", "setTimeout(refreshGame,400)", "300)"):
            self.assertIn(call, script)
        self.assertNotIn("<script>", html)  # CSP script-src 'self': no inline scripts
        self.assertNotIn(" style=", html)
        self.assertIn('aria-label="Song time in seconds"', html)


if __name__ == "__main__":
    unittest.main()
