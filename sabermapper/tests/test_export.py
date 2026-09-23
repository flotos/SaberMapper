import json
from io import BytesIO
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from zipfile import ZipFile

import numpy as np
import soundfile as sf

from sabermapper.export import ExportError, export_arrangement


def png():
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "#19252a").save(out, format="PNG")
    return out.getvalue()


def ogg():
    stream = BytesIO()
    sf.write(stream, np.zeros((44100 * 4, 2), dtype=np.float32), 44100, format="OGG", subtype="VORBIS")
    return stream.getvalue()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "input.ogg"
        self.cover = self.root / "art.png"
        self.audio.write_bytes(ogg())
        self.cover.write_bytes(png())
        self.arrangement = {"song": {"title": "Test", "artist": "Artist", "bpm": 120, "audio_offset_seconds": 0},
                            "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
                            "sections": [{"start_beat": 0}]}
        self.compiler = patch("sabermapper.export.compile_arrangement", return_value={"version": "3.3.0", "colorNotes": [{"b": 1, "x": 0, "y": 0, "c": 0, "d": 1}]})
        self.validator = patch("sabermapper.export.validate_arrangement", return_value=[])
        self.compiler.start()
        self.validator.start()
        self.addCleanup(self.compiler.stop)
        self.addCleanup(self.validator.stop)

    def test_archive_reproducible_and_linked(self):
        first, second = self.root / "a.zip", self.root / "b.zip"
        report = export_arrangement(self.arrangement, self.audio, self.cover, first)
        export_arrangement(self.arrangement, self.audio, self.cover, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), {"Info.dat", "Expert.dat", "song.ogg", "cover.png", "SaberMapper-report.json"})
            info = json.loads(archive.read("Info.dat"))
            beatmap = json.loads(archive.read("Expert.dat"))
            self.assertEqual(info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0]["_beatmapFilename"], "Expert.dat")
            self.assertTrue(beatmap["basicBeatmapEvents"])
            self.assertEqual(report["audio_sha256"], json.loads(archive.read("SaberMapper-report.json"))["audio_sha256"])

    def test_invalid_assets_and_no_overwrite(self):
        output = self.root / "out.zip"
        self.audio.write_bytes(b"OggS" + bytes(50))
        with self.assertRaisesRegex(ExportError, "Vorbis"):
            export_arrangement(self.arrangement, self.audio, self.cover, output)
        self.assertFalse(output.exists())
        self.audio.write_bytes(ogg())
        export_arrangement(self.arrangement, self.audio, self.cover, output)
        with self.assertRaisesRegex(ExportError, "already exists"):
            export_arrangement(self.arrangement, self.audio, self.cover, output)

    def test_positive_audio_offset_baked_into_beats(self):
        self.arrangement["song"]["audio_offset_seconds"] = 0.25
        output = self.root / "out.zip"
        report = export_arrangement(self.arrangement, self.audio, self.cover, output)
        with ZipFile(output) as archive:
            beatmap = json.loads(archive.read("Expert.dat"))
            self.assertEqual(beatmap["colorNotes"][0]["b"], 1.5)
            self.assertEqual(beatmap["basicBeatmapEvents"][0]["b"], 0.5)
        self.assertEqual(report["baked_audio_offset_seconds"], 0.25)

    def test_offset_shifts_tempo_and_arc_tails(self):
        self.arrangement["song"]["audio_offset_seconds"] = 0.25
        with patch("sabermapper.export.compile_arrangement", return_value={
            "version": "3.3.0", "colorNotes": [{"b": 1, "x": 0, "y": 0, "c": 0, "d": 1}],
            "bpmEvents": [{"b": 2, "m": 150}],
            "sliders": [{"b": 1, "tb": 2, "c": 0, "x": 0, "y": 0, "d": 1}],
            "burstSliders": [{"b": 1, "tb": 2, "c": 0, "x": 0, "y": 0, "d": 1}],
            "bombNotes": [{"b": 1, "x": 2, "y": 0}],
            "obstacles": [{"b": 1, "d": 1, "x": 3, "y": 0, "w": 1, "h": 3}],
        }):
            output = self.root / "shifted.zip"
            export_arrangement(self.arrangement, self.audio, self.cover, output)
        with ZipFile(output) as archive:
            beatmap = json.loads(archive.read("Expert.dat"))
            self.assertEqual(beatmap["bpmEvents"][0]["b"], 2.5)
            self.assertEqual(beatmap["sliders"][0]["tb"], 2.5)
            self.assertEqual(beatmap["burstSliders"][0]["tb"], 2.5)
            self.assertEqual(beatmap["obstacles"][0]["b"], 1.5)


class CliIntegrationTests(unittest.TestCase):
    def test_cli_with_real_compiler_and_fractional_lighting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            arrangement = {
                "schema_version": "0.1",
                "song": {"title": "Pilot", "artist": "Artist", "bpm": 120, "audio_offset_seconds": 0},
                "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
                "motifs": {},
                "sections": [{"id": "intro", "start_beat": "1/2", "length_beats": 4,
                              "intent": "opening", "locked": False, "resolved": True,
                              "notes": [{"id": "a", "beat": 0, "x": 0, "y": 1, "color": 0, "direction": 1}],
                              "patterns": []}],
            }
            source = root / "arrangement.json"
            source.write_text(json.dumps(arrangement), encoding="utf-8")
            audio = root / "song.ogg"
            audio.write_bytes(ogg())
            cover = root / "cover.png"
            cover.write_bytes(png())
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

            def run(*args):
                return subprocess.run([sys.executable, "-m", "sabermapper", *map(str, args)],
                                      capture_output=True, text=True, env=env, cwd=root)

            self.assertEqual(run("validate", source).returncode, 0)
            compiled = root / "Expert.dat"
            self.assertEqual(run("compile", source, "--output", compiled).returncode, 0)
            before = compiled.read_bytes()
            self.assertNotEqual(run("compile", source, "--output", compiled).returncode, 0)
            self.assertEqual(compiled.read_bytes(), before)
            archive_path = root / "map.zip"
            result = run("export", source, "--audio", audio, "--cover", cover, "--output", archive_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            with ZipFile(archive_path) as archive:
                beatmap = json.loads(archive.read("Expert.dat"))
                self.assertEqual(beatmap["basicBeatmapEvents"][0]["b"], 0.5)
                self.assertEqual(beatmap["colorNotes"][0]["b"], 0.5)
            self.assertNotEqual(run("export", source, "--audio", audio, "--cover", cover, "--output", archive_path).returncode, 0)
            arrangement["song"]["audio_offset_seconds"] = 0.25
            source.write_text(json.dumps(arrangement), encoding="utf-8")
            shifted = root / "shifted.zip"
            result = run("export", source, "--audio", audio, "--cover", cover, "--output", shifted)
            self.assertEqual(result.returncode, 0, result.stderr)
            with ZipFile(shifted) as archive:
                beatmap = json.loads(archive.read("Expert.dat"))
                self.assertEqual(beatmap["colorNotes"][0]["b"], 1.0)
                self.assertEqual(beatmap["basicBeatmapEvents"][0]["b"], 1.0)
            arrangement["sections"][0]["resolved"] = False
            source.write_text(json.dumps(arrangement), encoding="utf-8")
            invalid = run("validate", source)
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("unresolved_section", invalid.stdout)


if __name__ == "__main__":
    unittest.main()


class Utf8OutputTests(unittest.TestCase):
    def test_non_latin_text_prints_through_a_legacy_code_page_stdout(self):
        import io
        import sys
        from sabermapper.__main__ import emit, utf8_output
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        original = sys.stdout
        sys.stdout = stream
        try:
            utf8_output()
            emit({"text": "בא לי בית מלון"})
            stream.flush()
        finally:
            sys.stdout = original
        self.assertIn("בא לי בית מלון", raw.getvalue().decode("utf-8"))
