"""Handover gate: `project verify` runs every agent check and blocks on the ones that must pass."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from sabermapper.__main__ import main
from sabermapper.projects import ProjectStore
from sabermapper.revisions import arrangement_revision
from sabermapper.storage import read_json, write_json
from sabermapper.verify import latest_capture, verify_project

PASSING_AUDIO = {"id": "audio", "status": "pass", "blocking": [], "warnings": [], "run_id": "r"}


def write_capture(directory: Path, revision: str, difficulty: str, *, dense=False, log=(), created="2026-09-23T10:00:00"):
    directory.mkdir(parents=True)
    frames = []
    times = [i / 30 for i in range(60)] if dense else [1.0, 2.0, 3.0]
    for i, time in enumerate(times):
        name = f"t{time:08.3f}.png"
        Image.new("RGB", (64, 36), (20, 20, 30)).save(directory / name)
        frames.append({"file": name, "requested_time": time, "song_time": time, "beat": time * 2,
                       "section_id": None, "reason": "probe" if dense else "requested"})
    write_json(directory / "capture.json", {
        "schema_version": 1, "project": "p", "revision": revision, "difficulty": difficulty, "camera": "player",
        "width": 64, "height": 36, "game_version": "1.40.8", "level_path": "x", "created_at": created,
        "frames": frames, "log_diagnostics": list(log)})
    return directory


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        self.project = self.store.create(demo=True)["project"]["id"]
        self.directory = self.store.directory(self.project)
        arrangement = read_json(self.store.arrangement_file(self.directory))
        self.revision, self.difficulty = arrangement_revision(arrangement), arrangement["difficulty"]["name"]

    def test_missing_audio_evidence_blocks_and_capture_is_optional_without_a_show(self):
        result = verify_project(self.store, self.project)
        self.assertFalse(result["ready_for_human"])
        self.assertIn("audio_evidence_missing", [b["code"] for b in result["blocking"]])
        self.assertEqual({"show", "capture", "frames", "game_log"}, set(result["skipped"]))
        self.assertTrue(result["next"][0].startswith("Fix audio/audio_evidence_missing"))

    def test_ready_when_every_check_passes_and_the_record_is_stored(self):
        with patch("sabermapper.verify._audio", return_value=PASSING_AUDIO), \
                patch("sabermapper.verify._structure",
                      return_value={"id": "structure", "status": "pass", "blocking": [], "warnings": []}):
            result = verify_project(self.store, self.project, record=True)
        self.assertTrue(result["ready_for_human"], result["blocking"])
        self.assertEqual(["structure", "audio"], result["ran"])
        self.assertEqual(result, read_json(Path(result["recorded"])) | {"recorded": result["recorded"]})

    def test_vivified_project_needs_a_capture_with_a_dense_probe_and_clean_logs(self):
        with patch("sabermapper.verify.load_show", create=True), \
                patch("sabermapper.show.load_show", return_value={"schema_version": "0.1", "primitives": []}), \
                patch("sabermapper.verify._show", return_value={"id": "show", "status": "pass", "blocking": [],
                                                                "warnings": []}), \
                patch("sabermapper.verify._audio", return_value=PASSING_AUDIO):
            missing = verify_project(self.store, self.project)
            self.assertIn("capture_missing", [b["code"] for b in missing["blocking"]])
            write_capture(self.directory / "captures" / "sparse", self.revision, self.difficulty)
            sparse = verify_project(self.store, self.project)
            self.assertIn("flash_unchecked", [b["code"] for b in sparse["blocking"]])
            error = {"severity": "error", "source": "Vivify", "code": "bundle_checksum_mismatch", "message": "CRC"}
            write_capture(self.directory / "captures" / "dense", self.revision, self.difficulty, dense=True,
                          log=[error], created="2026-09-23T11:00:00")
            self.assertEqual(self.directory / "captures" / "dense",
                             latest_capture(self.directory, self.revision, self.difficulty))
            dense = verify_project(self.store, self.project)
            codes = [b["code"] for b in dense["blocking"]]
            self.assertNotIn("flash_unchecked", codes)
            self.assertEqual(["bundle_checksum_mismatch"], codes)
            self.assertEqual("game_log", dense["blocking"][0]["check"])

    def test_captures_of_other_revisions_are_ignored(self):
        write_capture(self.directory / "captures" / "old", "0" * 64, self.difficulty)
        self.assertIsNone(latest_capture(self.directory, self.revision, self.difficulty))

    def test_cli_exit_code_reflects_the_verdict(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["project", "verify", self.project, "--workspace", self.temp.name])
        self.assertEqual(3, code)
        self.assertFalse(json.loads(out.getvalue())["ready_for_human"])


if __name__ == "__main__":
    unittest.main()
