import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from sabermapper import blender
from sabermapper.__main__ import main

REPO = Path(__file__).resolve().parents[2]


class FakeBridge:
    """Speaks the MCP add-on's bridge protocol: one JSON request ending in NUL, one JSON reply ending in NUL."""

    def __init__(self, result):
        self.result, self.requests = result, []
        self.server = socket.create_server(("localhost", 0))
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                buf = bytearray()
                while b"\0" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                self.requests.append(json.loads(bytes(buf).split(b"\0", 1)[0]))
                conn.sendall(json.dumps({"status": "ok", "result": self.result}).encode() + b"\0")

    def close(self):
        self.server.close()


def free_port():
    with socket.create_server(("localhost", 0)) as probe:
        return probe.getsockname()[1]


class BlenderBridgeTests(unittest.TestCase):
    """Agents start, inspect and stop the Blender behind the Blender MCP server without touching the UI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patch = mock.patch.object(blender.tempfile, "gettempdir", return_value=self.temp.name)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["blender", *argv])
        return code, json.loads(out.getvalue())

    def test_ping_reads_what_the_bridge_has_open(self):
        bridge = FakeBridge({"version": "5.2.2 LTS", "file": "", "background": True, "objects": 3})
        self.addCleanup(bridge.close)
        self.assertEqual(blender.ping(port=bridge.port)["objects"], 3)
        self.assertEqual(bridge.requests[0]["type"], "execute")
        self.assertIn("bpy.app.version_string", bridge.requests[0]["code"])
        self.assertIsNone(blender.ping(port=free_port(), timeout=0.5))

    def test_headless_launch_passes_online_mode_before_the_bridge_command(self):
        command = blender.launch_command(Path("blender.exe"), blend=Path("scene.blend"), port=9877)
        self.assertEqual(command, ["blender.exe", "--background", "scene.blend", "--online-mode",
                                   "--command", "blender_mcp", "--port", "9877"])
        self.assertEqual(blender.launch_command(Path("blender.exe"), gui=True), ["blender.exe", "--online-mode"])

    def test_start_reuses_a_running_bridge_instead_of_opening_a_second_blender(self):
        bridge = FakeBridge({"version": "5.2.2 LTS", "file": "C:/a.blend", "background": False, "objects": 1})
        self.addCleanup(bridge.close)
        with mock.patch.object(blender.subprocess, "Popen") as popen:
            code, report = self.run_cli("start", "--port", str(bridge.port))
        popen.assert_not_called()
        self.assertEqual(code, 0)
        self.assertTrue(report["already_running"])
        self.assertEqual(report["bridge"]["file"], "C:/a.blend")

    def test_gui_bridge_listens_on_the_add_on_port_only(self):
        code, report = self.run_cli("start", "--gui", "--port", str(free_port()))
        self.assertEqual(code, 2)
        self.assertEqual(report["error"]["code"], "gui_port_fixed")

    def test_status_names_the_missing_install(self):
        with mock.patch.object(blender, "blender_path", return_value=None), \
                mock.patch.object(blender, "server_path", return_value=None):
            code, report = self.run_cli("status", "--port", str(free_port()))
        self.assertEqual(code, 0)
        self.assertFalse(report["bridge"]["reachable"])
        self.assertIn("blender, mcp_server", report["fix"])
        self.assertIn("blender-mcp.md", report["fix"])

    def test_stop_closes_only_a_blender_started_here(self):
        port = free_port()
        code, report = self.run_cli("stop", "--port", str(port))
        self.assertEqual((code, report["error"]["code"]), (2, "not_started_here"))
        state = Path(self.temp.name) / f"sabermapper-blender-{port}.json"
        state.write_text(json.dumps({"pid": 4242, "mode": "headless"}), encoding="utf-8")
        with mock.patch.object(blender, "_alive", return_value=False), \
                mock.patch.object(blender.subprocess, "run") as run:
            code, report = self.run_cli("stop", "--port", str(port))
        run.assert_not_called()
        self.assertEqual((code, report["stopped"], report["pid"]), (0, False, 4242))
        self.assertFalse(state.exists())

    def test_project_mcp_config_points_at_the_bridge_port(self):
        server = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["blender"]
        self.assertEqual(int(server["env"]["BLENDER_MCP_PORT"]), blender.DEFAULT_PORT)
        self.assertTrue(server["command"].endswith("Programs/BlenderMCP/Scripts/blender-mcp.exe"))
        self.assertTrue(server["env"]["BLENDER_PATH"].endswith("Programs/Blender/blender.exe"))


if __name__ == "__main__":
    unittest.main()
