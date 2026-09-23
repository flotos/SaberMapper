"""The studio follows code updates without breaking open pages or in-flight requests."""

import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request

from sabermapper import studio_supervisor
from sabermapper.server import make_server
from sabermapper.studio_supervisor import Supervisor, WorkerControl, code_fingerprint


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def status(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as response:
        return json.load(response)


def wait_until(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


class FingerprintTests(unittest.TestCase):
    def test_changes_with_served_source_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "static").mkdir()
            (root / "server.py").write_text("A = 1\n")
            (root / "static" / "app.js").write_text("let a;\n")
            first = code_fingerprint(root)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "server.cpython-311.pyc").write_bytes(b"compiled")
            (root / "notes.txt").write_text("not served")
            self.assertEqual(code_fingerprint(root), first)
            (root / "static" / "app.js").write_text("let b;\n")
            self.assertNotEqual(code_fingerprint(root), first)


class WorkerControlTests(unittest.TestCase):
    def test_drain_waits_for_in_flight_requests(self):
        control, server = WorkerControl(), mock.Mock()
        release, entered = threading.Event(), threading.Event()

        def slow_request():
            with control.request():
                entered.set()
                release.wait(5)

        threading.Thread(target=slow_request, daemon=True).start()
        entered.wait(5)
        control.listen(server, io.StringIO('state {"state": "failed", "error": "boom"}\ndrain\n'))
        time.sleep(0.5)
        server.shutdown.assert_not_called()
        self.assertEqual(control.status()["update"], {"state": "failed", "error": "boom"})
        release.set()
        self.assertTrue(wait_until(lambda: server.shutdown.called, 5))

    def test_status_reports_code_and_keeps_supervisor_token(self):
        with tempfile.TemporaryDirectory() as folder:
            control = WorkerControl()
            server = make_server(folder, port=0, token="kept-token", control=control)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                info = status(server.server_port)
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(info["token"], "kept-token")
        self.assertEqual(info["code"]["version"], control.version)
        self.assertEqual(info["code"]["update"], {"state": "current"})


class SupervisorTests(unittest.TestCase):
    """A real worker process on a real port; the code version is simulated."""

    def start(self, version, preflight_error=None):
        self.version = [version]
        patches = [mock.patch.object(studio_supervisor, "code_fingerprint", lambda root=None: self.version[0]),
                   mock.patch.object(studio_supervisor, "preflight", lambda python=None: preflight_error)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.port = free_port()
        self.supervisor = Supervisor(Path(folder.name), self.port, poll=0.1, settle=0.1, log=lambda *a, **k: None)
        thread = threading.Thread(target=self.supervisor.run, daemon=True)
        thread.start()

        def stop():
            self.supervisor.stopping.set()
            thread.join(60)
        self.addCleanup(stop)
        self.assertTrue(wait_until(lambda: status(self.port)["code"]["version"] == version), "worker did not start")
        return status(self.port)

    def test_code_change_swaps_worker_and_keeps_token(self):
        before = self.start("v1")
        self.assertTrue(before["code"]["auto_update"])
        first_worker = self.supervisor.worker.pid
        self.version[0] = "v2"
        self.assertTrue(wait_until(lambda: status(self.port)["code"]["version"] == "v2"), "worker was not replaced")
        after = status(self.port)
        self.assertEqual(after["token"], before["token"])
        self.assertEqual(after["code"]["update"], {"state": "current"})
        self.assertNotEqual(self.supervisor.worker.pid, first_worker)

    def test_broken_update_keeps_serving_previous_code(self):
        self.start("v1", preflight_error="SyntaxError: invalid syntax")
        first_worker = self.supervisor.worker.pid
        self.version[0] = "v2"
        self.assertTrue(wait_until(lambda: status(self.port)["code"]["update"]["state"] == "failed"))
        info = status(self.port)
        self.assertEqual(info["code"]["version"], "v1")
        self.assertEqual(info["code"]["update"]["error"], "SyntaxError: invalid syntax")
        self.assertEqual(self.supervisor.worker.pid, first_worker)


if __name__ == "__main__":
    unittest.main()
