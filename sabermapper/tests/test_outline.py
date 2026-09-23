"""The map explained to the player: the style paragraph, section summaries, `project outline` and the viewer page."""
import copy
import http.client
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import threading
import unittest

from sabermapper.__main__ import main
from sabermapper.critique import critique_arrangement
from sabermapper.outline import SUMMARY_LIMIT, fallback_summary, outline
from sabermapper.placement import place_arrangement
from sabermapper.projects import ProjectStore
from sabermapper.server import make_server
from sabermapper.style import arrangement_style, validate_document
from sabermapper.validation import validate_arrangement
from tests.test_style import document, stream

STATIC = Path(__file__).resolve().parents[1] / "sabermapper" / "static"


def explained():
    arrangement = place_arrangement(stream())["arrangement"]
    arrangement["sections"][0]["intent"] = ("Gallop riff: kick triplets locked to the guitar. Evidence run "
                                            "148f9ae3 (ensemble stems), guitar onsets 0.3+.")
    arrangement["style"] = {"idea": "One idea.", "summary": "A paragraph for the player.", "grounding": ["x"],
                            "settings": {}}
    arrangement["themes"] = [{"id": "hook", "intent": "the hook", "spans": [{"start_beat": 0, "end_beat": 16},
                                                                          {"start_beat": 32, "end_beat": 48}]}]
    return arrangement


class SummaryTests(unittest.TestCase):
    def test_the_fallback_is_the_intent_first_sentence_without_its_evidence(self):
        self.assertEqual(fallback_summary("Band enters on beat 57 (drums, bass). Gallop riff: union of guitar."),
                         "Band enters on beat 57 (drums, bass).")
        self.assertEqual(fallback_summary("Choir intro, soft. Evidence run 148f9ae3 (ensemble stems)."),
                         "Choir intro, soft.")
        self.assertLessEqual(len(fallback_summary("x" * 500)), SUMMARY_LIMIT)

    def test_validation_takes_one_sentence_per_section_and_one_paragraph_per_style(self):
        arrangement = explained()
        arrangement["sections"][0]["summary"] = "The gallop kicks in: chop along with the guitar."
        self.assertEqual([d for d in validate_arrangement(arrangement) if d["code"] in ("invalid_summary", "invalid_style")], [])
        for broken in ("two lines\nhere", "x" * (SUMMARY_LIMIT + 1), "", 3):
            arrangement["sections"][0]["summary"] = broken
            self.assertIn("invalid_summary", {d["code"] for d in validate_arrangement(arrangement)}, broken)
        del arrangement["sections"][0]["summary"]
        arrangement["style"]["summary"] = ""
        self.assertIn("invalid_style", {d["code"] for d in validate_arrangement(arrangement)})

    def test_the_selected_candidate_carries_its_summary_paragraph(self):
        brainstorm = document()
        brainstorm["candidates"][0]["summary"] = "Why the map plays this way."
        self.assertTrue(validate_document(brainstorm)["saveable"])
        self.assertEqual(arrangement_style(brainstorm)["summary"], "Why the map plays this way.")

    def test_project_check_asks_for_the_player_facing_texts(self):
        arrangement = explained()
        warnings = [w for w in critique_arrangement(arrangement, None)["warnings"] if w["code"] == "summary_missing"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 of 1 sections", warnings[0]["message"])
        arrangement["sections"][0]["summary"] = "The gallop kicks in."
        self.assertNotIn("summary_missing", [w["code"] for w in critique_arrangement(arrangement, None)["warnings"]])


class OutlineTests(unittest.TestCase):
    def test_outline_gives_seconds_summaries_evidence_and_themes(self):
        result = outline(explained(), 40.0)
        section, = result["sections"]
        self.assertEqual((section["start_seconds"], section["end_seconds"]), (0.0, 25.6))  # 64 beats at 150 BPM
        self.assertEqual(section["summary"], "Gallop riff: kick triplets locked to the guitar.")
        self.assertEqual(section["summary_source"], "intent")
        self.assertIn("Evidence run", section["evidence"])
        self.assertEqual(section["themes"], ["hook"])
        self.assertEqual(result["style"]["summary"], "A paragraph for the player.")
        self.assertEqual([s["role"] for s in result["themes"][0]["spans"]], ["statement", "echo"])

    def test_cli_and_studio_serve_the_outline_and_the_viewer(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(temp)
            project = store.create(demo=True)["project"]["id"]
            out = io.StringIO()
            with redirect_stdout(out):
                main(["project", "outline", project, "--workspace", temp])
            cli = json.loads(out.getvalue())
            self.assertTrue(cli["sections"])
            arcviewer = Path(temp) / "arcviewer"
            (arcviewer / "Build").mkdir(parents=True)
            (arcviewer / "Build" / "ArcViewer.wasm").write_bytes(b"\0")
            previous = os.environ.get("SABERMAPPER_ARCVIEWER")
            os.environ["SABERMAPPER_ARCVIEWER"] = str(arcviewer)
            try:
                server = make_server(temp, port=0)
            finally:
                if previous is None:
                    os.environ.pop("SABERMAPPER_ARCVIEWER", None)
                else:
                    os.environ["SABERMAPPER_ARCVIEWER"] = previous
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host = f"127.0.0.1:{server.server_port}"

                def request(method, path, body=None, headers=None):
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
                    conn.request(method, path, body=body, headers={"Host": host, **(headers or {})})
                    response = conn.getresponse()
                    result = response.status, response.read()
                    conn.close()
                    return result
                status, body = request("GET", f"/api/projects/{project}/outline")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["sections"], cli["sections"])
                status, page = request("GET", "/viewer/?project=x")
                self.assertEqual(status, 200)
                self.assertIn(b'id="arcviewer"', page)
                self.assertIn(b'id="rail-track"', page)
                self.assertEqual(request("GET", "/viewer.js")[0], 200)
                self.assertEqual(request("GET", "/viewer.css")[0], 200)
                token = json.loads(request("GET", "/api/status")[1])["token"]
                revision = store.get(project)["revision"]
                status, reply = request("POST", f"/api/projects/{project}/preview",
                                        json.dumps({"revision": revision, "seconds": 3}).encode(),
                                        {"X-SaberMapper-Token": token, "Origin": f"http://{host}",
                                         "Content-Type": "application/json"})
                self.assertEqual(status, 200, reply)
                result = json.loads(reply)
                self.assertTrue(result["viewer_url"].startswith(f"/viewer/?project={project}"))
                self.assertIn("t=3", result["viewer_url"])
                self.assertTrue(result["arcviewer_url"].startswith("/arcviewer/?"))
                request("GET", result["status_url"])  # let the background export finish before cleanup
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_the_viewer_reads_arcviewer_song_clock_and_the_studio_opens_it_per_section(self):
        viewer = (STATIC / "viewer.js").read_text(encoding="utf-8")
        for name in ("soundStartTime", "lastPlayed", "playbackSpeed", "SongCtx", "/outline"):
            self.assertIn(name, viewer)
        # Every section is a row that jumps there; only the current one unfolds.
        self.assertIn("track.querySelectorAll('.rail-item').forEach(b => b.onclick = () => jump(", viewer)
        self.assertIn("b.setAttribute('aria-expanded', String(current))", viewer)
        css = (STATIC / "viewer.css").read_text(encoding="utf-8")
        self.assertIn(".rail-body{display:none}", css)
        self.assertIn(".rail-item.active .rail-body{display:flex", css)
        studio = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("openPreview(Number(c.dataset.at))", studio)
        self.assertIn("function sectionSummary", studio)


if __name__ == "__main__":
    unittest.main()
