"""The studio's 3D preview: ArcViewer boots in its tab while the map ZIP is exported."""

import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from sabermapper.server import make_server
from sabermapper.studio_supervisor import WorkerControl


class StudioPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        viewer = root / "arcviewer"
        (viewer / "Build").mkdir(parents=True)
        (viewer / "Build" / "ArcViewer.wasm").write_bytes(b"\0asm" + b"\0" * 64)
        (viewer / "index.html").write_text("<!doctype html><title>ArcViewer</title>", encoding="utf-8")
        self.control = WorkerControl()
        with mock.patch.dict(os.environ, {"SABERMAPPER_ARCVIEWER": str(viewer)}):
            self.server = make_server(root / "workspace", port=0, control=self.control)
        self.store = self.server.store
        self.project_id = self.store.create(demo=True)["project"]["id"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.token = json.loads(self.request("GET", "/api/status")[2])["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=30)
        body = None if data is None else json.dumps(data).encode()
        extra = {"X-SaberMapper-Token": self.token, "Content-Type": "application/json"} if data is not None else {}
        conn.request(method, path, body=body, headers={"Host": self.host, **extra, **(headers or {})})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def preview(self, **data):
        revision = self.store.get(self.project_id)["revision"]
        return self.request("POST", f"/api/projects/{self.project_id}/preview", {"revision": revision, "seconds": 3, **data})

    def test_preview_answers_before_the_export_and_the_viewer_waits_for_the_zip(self):
        release, export = threading.Event(), self.store.export

        def slow_export(*args, **kwargs):
            release.wait(10)
            return export(*args, **kwargs)

        with mock.patch.object(self.store, "export", side_effect=slow_export):
            started = time.monotonic()
            status, _, body = self.preview()
            self.assertEqual(status, 200, body)
            self.assertLess(time.monotonic() - started, 5)
            result = json.loads(body)
            self.assertFalse((self.store.directory(self.project_id) / "exports" / result["filename"]).exists())
            # A code reload drains the running export like any request.
            deadline = time.monotonic() + 2
            while self.control._inflight != 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.control._inflight, 1)
            map_url = parse_qs(urlparse(result["viewer_url"]).query)["url"][0]
            self.assertEqual(urlparse(map_url).path, result["status_url"].removesuffix(".json") + ".zip")
            waiting = {}
            viewer = threading.Thread(target=lambda: waiting.update(zip=self.request("GET", urlparse(map_url).path)))
            viewer.start()
            time.sleep(0.2)
            self.assertNotIn("zip", waiting)
            release.set()
            viewer.join(30)
        status, headers, archive = waiting["zip"]
        self.assertEqual(status, 200)
        self.assertTrue(archive.startswith(b"PK"))
        status, _, body = self.request("GET", result["status_url"])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["filename"], result["filename"])
        self.assertEqual(self.request("GET", result["url"])[2], archive)

    def test_preview_rejects_a_stale_revision_before_opening_the_viewer(self):
        status, _, body = self.request("POST", f"/api/projects/{self.project_id}/preview",
                                       {"revision": "stale", "seconds": 0})
        self.assertEqual(status, 409, body)

    def test_a_failed_export_reports_its_error_to_the_status_and_the_viewer(self):
        with mock.patch.object(self.store, "export", side_effect=ValueError("Cover is unreadable")):
            result = json.loads(self.preview()[2])
            status, _, body = self.request("GET", result["status_url"])
        self.assertEqual(status, 400)
        self.assertIn("Cover is unreadable", body.decode())
        self.assertEqual(self.request("GET", result["status_url"].removesuffix(".json") + ".zip")[0], 400)

    def test_a_job_from_before_a_reload_resolves_from_disk(self):
        filename = self.store.export(self.project_id)["filename"]
        job = filename.removesuffix(".zip")
        status, _, archive = self.request("GET", f"/api/projects/{self.project_id}/previews/{job}.zip")
        self.assertEqual((status, archive[:2]), (200, b"PK"))
        self.assertEqual(self.request("GET", f"/api/projects/{self.project_id}/previews/map-0000000000-000000.zip")[0], 404)

    def test_arcviewer_engine_revalidates_to_not_modified(self):
        status, headers, _ = self.request("GET", "/arcviewer/Build/ArcViewer.wasm")
        self.assertEqual(status, 200)
        tag = headers["ETag"]
        status, headers, body = self.request("GET", "/arcviewer/Build/ArcViewer.wasm", headers={"If-None-Match": tag})
        self.assertEqual((status, body, headers["ETag"]), (304, b"", tag))
        self.assertEqual(self.request("GET", "/arcviewer/Build/ArcViewer.wasm",
                                      headers={"If-None-Match": '"other"'})[0], 200)


if __name__ == "__main__":
    unittest.main()
