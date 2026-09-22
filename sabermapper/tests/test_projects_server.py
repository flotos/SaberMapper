"""Real local project and HTTP boundary integration checks."""

import copy
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from zipfile import ZipFile

from sabermapper.mapio import parse_map
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.server import MAX_BODY, make_server


class ProjectStudioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.store = ProjectStore(cls.temporary.name)
        cls.created = cls.store.create(demo=True)
        cls.project_id = cls.created["project"]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_project_lifecycle_and_game_zip(self):
        project_id = self.project_id
        initial = self.store.get(project_id)
        self.assertTrue(Path(self.store.directory(project_id), "song.ogg").is_file())
        self.assertTrue(initial["notes"])
        self.assertEqual(initial["movement"]["model_version"], "1.2")
        old_revision = initial["revision"]

        arrangement = copy.deepcopy(initial["arrangement"])
        first = arrangement["sections"][0]
        first["intent"] = "Revision: softer opening"
        first["notes"][0]["direction"] = 4
        request = self.store.add_feedback(project_id, {"revision": old_revision,
                   "start_beat": 4, "end_beat": 5, "text": "Soften the first cut"})
        saved = self.store.save(project_id, arrangement, old_revision, request_id=request["id"])
        self.assertNotEqual(saved["revision"], old_revision)
        audit = [json.loads(path.read_text(encoding="utf-8")) for path in
                 (self.store.directory(project_id) / "revisions").glob("*.json")]
        self.assertTrue(any(item.get("request_id") == request["id"] and item.get("revision") == saved["revision"]
                            for item in audit))
        self.assertEqual(self.store.get(project_id)["arrangement"]["sections"][0]["intent"], "Revision: softer opening")
        with self.assertRaises(ConflictError):
            self.store.save(project_id, arrangement, old_revision)

        # A shared motif must be frozen when a referring section is locked.
        with_motif = copy.deepcopy(saved["arrangement"])
        with_motif["motifs"]["shared"] = [{"id": "m1", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1}]
        second = with_motif["sections"][1]
        second["patterns"] = [{"id": "repeat", "motif": "shared", "start_beat": 0}]
        placed = self.store.save(project_id, with_motif, saved["revision"])
        locked = self.store.set_lock(project_id, second["id"], True, placed["revision"])
        changed_motif = copy.deepcopy(locked["arrangement"])
        changed_motif["motifs"]["shared"][0]["direction"] = 0
        with self.assertRaises(ConflictError):
            self.store.save(project_id, changed_motif, locked["revision"])
        locked_edit = copy.deepcopy(locked["arrangement"])
        locked_edit["sections"][1]["intent"] = "Changed while locked"
        with self.assertRaises(ConflictError):
            self.store.save(project_id, locked_edit, locked["revision"])
        locked_timing = copy.deepcopy(locked["arrangement"])
        locked_timing["song"]["bpm"] = 130
        with self.assertRaises(ConflictError):
            self.store.save(project_id, locked_timing, locked["revision"])

        feedback = self.store.add_feedback(project_id, {"revision": locked["revision"],
                    "start_beat": 4, "end_beat": 5, "text": "First cut feels late"})
        self.assertTrue(feedback["object_ids"])
        self.assertEqual(feedback["revision"], locked["revision"])
        self.assertTrue(self.store.feedback(project_id))
        with self.assertRaises(ConflictError):
            self.store.add_feedback(project_id, {"revision": old_revision,
                            "start_beat": 4, "end_beat": 5, "text": "Stale"})
        for bad in ({"start_beat": 5, "end_beat": 5, "text": "No range"},
                    {"start_beat": 4, "end_beat": 5, "text": ""}):
            with self.assertRaises(ValueError):
                self.store.add_feedback(project_id, {"revision": locked["revision"], **bad})
        with self.assertRaises(ValueError):
            self.store.set_lock(project_id, second["id"], "yes", locked["revision"])

        unlocked = self.store.set_lock(project_id, second["id"], False, locked["revision"])
        restored = self.store.restore(project_id, placed["revision"], unlocked["revision"])
        self.assertEqual(restored["arrangement"], placed["arrangement"])
        timing = copy.deepcopy(restored["arrangement"])
        timing["song"]["audio_offset_seconds"] = 0.1
        retimed = self.store.save(project_id, timing, restored["revision"])
        self.assertFalse(retimed["project"]["timing_reviewed"])
        self.assertEqual(retimed["arrangement"]["song"]["audio_offset_seconds"], 0.1)

        exported = self.store.export(project_id)
        filename = exported["filename"]
        zip_path = self.store.directory(project_id) / "exports" / filename
        with ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            self.assertTrue({"Info.dat", "Expert.dat", "song.ogg", "cover.png"} <= names)
            info = json.loads(archive.read("Info.dat"))
            beatmap = json.loads(archive.read("Expert.dat"))
            self.assertEqual(info["_songTimeOffset"], 0)
            self.assertEqual(info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0]["_difficulty"], "Expert")
            ir = parse_map(beatmap, bpm=info["_beatsPerMinute"], provenance={"project_id": project_id})
            self.assertEqual(len(ir["notes"]), len(beatmap["colorNotes"]))
            self.assertAlmostEqual(beatmap["colorNotes"][0]["b"] - retimed["notes"][0]["beat"], 0.2)
            self.assertAlmostEqual(ir["notes"][0]["seconds"], 2.1)

    def test_http_static_api_ranges_and_write_boundary(self):
        server = make_server(self.temporary.name, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            host = f"127.0.0.1:{port}"

            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request(method, path, body=body, headers={"Host": host, **(headers or {})})
                response = conn.getresponse()
                output = response.read()
                result = response.status, dict(response.getheaders()), output
                conn.close()
                return result

            status, _, body = request("GET", "/api/status")
            self.assertEqual(status, 200)
            token = json.loads(body)["token"]
            self.assertTrue(token)
            self.assertEqual(request("GET", "/")[0], 200)
            self.assertEqual(request("GET", "/style.css")[0], 200)
            self.assertEqual(request("GET", "/api/projects")[0], 200)
            self.assertEqual(request("GET", f"/api/projects/{self.project_id}")[0], 200)
            audio_url = f"/api/projects/{self.project_id}/files/song.ogg"
            status, headers, chunk = request("GET", audio_url, headers={"Range": "bytes=0-31"})
            self.assertEqual((status, len(chunk)), (206, 32))
            self.assertTrue(headers["Content-Range"].startswith("bytes 0-31/"))
            self.assertEqual(request("GET", audio_url, headers={"Range": "bytes=999999999-"})[0], 416)
            self.assertEqual(request("GET", f"/api/projects/{self.project_id}/files/../project.json")[0], 400)
            self.assertEqual(request("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)

            payload = b"{}"
            self.assertEqual(request("POST", "/api/demo", payload,
                                     {"Content-Type": "application/json"})[0], 403)
            self.assertEqual(request("POST", "/api/demo", payload,
                                     {"X-SaberMapper-Token": token, "Origin": "https://evil.example"})[0], 403)
            valid_headers = {"X-SaberMapper-Token": token, "Origin": f"http://{host}",
                             "Content-Type": "application/json"}
            self.assertEqual(request("POST", "/api/demo", b"{bad", valid_headers)[0], 400)
            self.assertEqual(request("POST", "/api/demo", b"[]", valid_headers)[0], 400)
            self.assertEqual(request("POST", "/api/demo", payload,
                                     {**valid_headers, "Content-Length": str(MAX_BODY + 1)})[0], 400)
            current = json.loads(request("GET", f"/api/projects/{self.project_id}")[2])
            feedback = json.dumps({"revision": current["revision"], "start_beat": 4,
                                   "end_beat": 5, "text": "HTTP feedback"}).encode()
            status, _, reply = request("POST", f"/api/projects/{self.project_id}/feedback",
                                       feedback, valid_headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(reply)["text"], "HTTP feedback")
            self.assertEqual(request("GET", "/app.js")[0], 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
