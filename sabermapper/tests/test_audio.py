import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from sabermapper.audio import analyze_audio, generate_demo_audio, inspect_audio, prepare_audio
from sabermapper.timing import BeatGrid


class AudioTests(unittest.TestCase):
    def test_grid_inverse(self):
        grid = BeatGrid(123, 0.1875)
        for beat in (0, 1.5, 64, 317.25):
            self.assertAlmostEqual(grid.time_to_beat(grid.beat_to_time(beat)), beat)

    def test_demo_analysis_and_vorbis_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "demo.ogg"
            metadata = generate_demo_audio(fixture, seconds=16, bpm=120)
            self.assertAlmostEqual(metadata["duration_seconds"], 16, places=2)
            report = analyze_audio(fixture, bpm=120, offset_seconds=0)
            self.assertEqual(report["timing"]["bpm"], 120)
            self.assertGreaterEqual(len(report["structure"]["accent_candidates"]), 10)
            self.assertEqual(report["audio"]["source_sha256"], metadata["source_sha256"])
            wav = root / "original.wav"
            samples, rate = sf.read(fixture, dtype="float32")
            sf.write(wav, samples, rate)
            export = root / "prepared.ogg"
            provenance = prepare_audio(wav, export)
            self.assertTrue(export.exists())
            self.assertLess(provenance["duration_drift_seconds"], 0.025)
            self.assertEqual(inspect_audio(export)["source_sha256"], provenance["export_sha256"])

    def test_default_demo_is_full_song(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.ogg"
            metadata = generate_demo_audio(path)
            self.assertAlmostEqual(metadata["duration_seconds"], 48, places=2)
            self.assertEqual(len(metadata["fixture"]["sections"]), 3)
            self.assertGreater(metadata["peak"], 0.1)

    def test_silence_and_malformed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            silent = root / "silent.wav"
            sf.write(silent, np.zeros(44100), 44100)
            report = analyze_audio(silent)
            self.assertEqual(report["timing"]["status"], "silent")
            bad = root / "broken.mp3"
            bad.write_bytes(b"bad audio")
            with self.assertRaises(ValueError):
                inspect_audio(bad)


if __name__ == "__main__":
    unittest.main()
