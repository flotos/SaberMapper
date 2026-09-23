"""Spectrogram views, ensemble separation, bleed gating, layer entries and ensemble weight under the lead."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PIL import Image

from sabermapper import musical
from sabermapper.critique import critique_arrangement
from sabermapper.musical import (analyze_layers, analyze_project, gate_bleed, layer_entries, latest_run,
                                 rhythm_grid, separation_python, split_by_masks)
from sabermapper.projects import ProjectStore
from sabermapper.spectrogram import project_view

from test_lead_rhythm import OFFBEATS, STREAM, arrangement, codes, events, report


def stems_report(length=32, *, drums=(), guitar=OFFBEATS, drum_contour=None):
    """A report whose layers are separated stems (kind audio_layer), 120 BPM (beat b at b / 2 s)."""
    base = report(length)
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(length * 5)]
    heard = sorted(set(drums) | set(guitar))  # every stem attack is also an attack in the mix
    base["layers"] = {"mix": {"kind": "audio_layer", "events": events("mix", heard), "energy_contour": contour},
                      "drums": {"kind": "audio_layer", "events": events("drums", drums, 0.9),
                                "energy_contour": drum_contour or contour},
                      "guitar": {"kind": "audio_layer", "events": events("guitar", guitar), "energy_contour": contour},
                      "vocals": {"kind": "audio_layer", "events": [], "sustains": [], "energy_contour": []}}
    return base


DOWNBEATS = list(range(0, 32, 4))


class EnsembleWeightTests(unittest.TestCase):
    def test_notes_on_the_lead_alone_miss_the_bands_heavy_hits(self):
        result = critique_arrangement(arrangement(OFFBEATS), stems_report(drums=DOWNBEATS))
        found = [w for w in result["warnings"] if w["code"] == "ensemble_unmapped"]
        self.assertEqual([w["beats"] for w in found], [[0, 16], [16, 32]])
        self.assertEqual(len(found[0]["targets"]), 1, "a bit of the band: 20% of four accents is one note")
        self.assertIn("drums", found[0]["message"])

    def test_a_few_ensemble_notes_satisfy_it_and_are_not_filler(self):
        result = critique_arrangement(arrangement(sorted(OFFBEATS + DOWNBEATS)), stems_report(drums=DOWNBEATS))
        self.assertFalse(codes(result) & {"ensemble_unmapped", "lead_rhythm_diluted"})
        self.assertEqual(result["metrics"]["ensemble"]["windows"][0]["mapped"], 4)

    def test_an_even_stream_over_every_kick_is_still_diluted(self):
        # Kicks on every beat are accents, but only one per bar may excuse a note off the lead.
        result = critique_arrangement(arrangement(STREAM), stems_report(drums=range(32)))
        self.assertIn("lead_rhythm_diluted", codes(result))

    def test_a_stem_swell_the_mix_does_not_hear_is_no_accent(self):
        # Bass pumping back after each sidechain duck peaks in the bass stem only (Lullaby, 2026-09-23).
        evidence = stems_report(drums=DOWNBEATS)
        evidence["layers"]["bass"] = {"kind": "audio_layer", "energy_contour": evidence["layers"]["drums"]["energy_contour"],
                                      "events": events("bass", [b + 2 / 3 for b in range(32)], 0.9)}
        result = critique_arrangement(arrangement(sorted(OFFBEATS + DOWNBEATS)), evidence)
        self.assertNotIn("ensemble_unmapped", codes(result))
        self.assertEqual(result["metrics"]["ensemble"]["windows"][0]["accents"], 4, "only the drums' audible hits")

    def test_frequency_bands_and_mix_are_not_ensemble_stems(self):
        bands = stems_report(drums=DOWNBEATS)
        bands["layers"]["drums"]["kind"] = "frequency_band"
        result = critique_arrangement(arrangement(OFFBEATS), bands)
        self.assertNotIn("ensemble_unmapped", codes(result))

    def test_check_suggests_the_heaviest_hits(self):
        from sabermapper.check import apply_suggestion, check_arrangement
        base, evidence = arrangement(OFFBEATS), stems_report(drums=DOWNBEATS)
        found = [f for f in check_arrangement(base, evidence)["findings"] if f["code"] == "ensemble_unmapped"]
        self.assertTrue(found)
        suggestion = found[0]["suggestions"][0]
        self.assertEqual([n["beat"] for n in suggestion["notes"]], [found[0]["targets"][0][0]])
        fixed = apply_suggestion(base, suggestion)
        remaining = [f for f in check_arrangement(fixed, evidence)["findings"] if f["code"] == "ensemble_unmapped"]
        self.assertNotIn(found[0]["beats"], [f["beats"] for f in remaining])


class DrumEntryTests(unittest.TestCase):
    def evidence(self):
        silent_then_loud = [{"seconds": i / 10, "energy": 0.0001 if i < 100 else 0.5} for i in range(160)]
        return stems_report(drums=range(20, 32), drum_contour=silent_then_loud)

    def test_entries_come_from_energy_and_snap_to_the_first_hit(self):
        entries = layer_entries(self.evidence())
        drums = [e for e in entries if e["layer"] == "drums"]
        self.assertEqual(len(drums), 1)
        self.assertAlmostEqual(drums[0]["seconds"], 10.0)
        self.assertGreaterEqual(drums[0]["silent_before_seconds"], 9)
        self.assertEqual(drums[0]["event_id"], "drums:0")

    def test_an_ignored_drum_entry_is_flagged_and_mapping_it_clears_it(self):
        result = critique_arrangement(arrangement(OFFBEATS), self.evidence())
        warning = next(w for w in result["warnings"] if w["code"] == "drum_entry_unmapped")
        self.assertAlmostEqual(warning["beats"][0], 20 - 0.13)
        followed = critique_arrangement(arrangement(sorted(OFFBEATS + [20, 21, 22, 23])), self.evidence())
        self.assertNotIn("drum_entry_unmapped", codes(followed))
        entry = next(e for e in followed["metrics"]["layer_entries"]["entries"] if e["layer"] == "drums")
        self.assertEqual((entry["hits"], entry["mapped"]), (4, 4))

    def test_rhythm_grid_names_entering_stems(self):
        grid = rhythm_grid(self.evidence(), arrangement(OFFBEATS), 16, 28)
        self.assertEqual([b["entering"] for b in grid["bars"]], [[], ["drums"], []])


class BleedGateTests(unittest.TestCase):
    def test_events_far_below_the_mix_are_dropped(self):
        mix = [{"seconds": i / 10, "energy": 1.0} for i in range(100)]
        piano = [{"seconds": i / 10, "energy": 0.01 if i < 50 else 0.5} for i in range(100)]
        layers = {"mix": {"kind": "audio_layer", "events": [], "energy_contour": mix},
                  "piano": {"kind": "audio_layer", "energy_contour": piano,
                            "events": events("piano", [2, 4, 12, 14]),  # 1 s, 2 s bleed; 6 s, 7 s real
                            "sustains": [{"start_seconds": 1.0, "end_seconds": 2.0}]},
                  "low": {"kind": "frequency_band", "energy_contour": piano, "events": events("low", [2])}}
        gate_bleed(layers)
        self.assertEqual([e["seconds"] for e in layers["piano"]["events"]], [6.0, 7.0])
        self.assertEqual(layers["piano"]["sustains"], [])
        self.assertEqual(layers["piano"]["bleed_gate"]["removed_events"], 2)
        self.assertEqual(len(layers["low"]["events"]), 1, "frequency bands share the mix and are never gated")


class EnsembleSeparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rate = 22050
        t = np.arange(self.rate * 3) / self.rate
        self.signal = (0.3 * np.sin(2 * np.pi * 220 * t) + 0.3 * (np.sin(2 * np.pi * 2 * t) > .95)).astype(np.float32)
        self.audio = self.root / "mix.wav"
        sf.write(self.audio, self.signal, self.rate)

    def tearDown(self):
        self.temp.cleanup()

    def test_mask_split_sums_to_the_target_and_follows_the_guides(self):
        t = np.arange(self.rate * 2) / self.rate
        low, high = np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 3000 * t)
        target = np.stack([low + high] * 2, axis=1)
        parts = split_by_masks(target, [np.stack([low] * 2, 1), np.stack([high] * 2, 1), np.zeros_like(target)])
        np.testing.assert_allclose(sum(parts), target, atol=1e-3)
        middle = slice(self.rate // 2, -self.rate // 2)
        self.assertGreater(np.corrcoef(parts[0][middle, 0], low[middle])[0, 1], 0.99)
        self.assertGreater(np.corrcoef(parts[1][middle, 0], high[middle])[0, 1], 0.99)

    def test_ensemble_backend_combines_two_models(self):
        out = self.root / "ensemble"
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            model = command[command.index("-n") + 1]
            folder = out / "separated" / model / "mix"
            folder.mkdir(parents=True)
            names = ("drums", "bass", "other", "vocals") + (("guitar", "piano") if model == "htdemucs_6s" else ())
            for name in names:
                sf.write(folder / f"{name}.wav", np.stack([self.signal] * 2, 1), self.rate)
            return type("Result", (), {"returncode": 0})()
        with patch("sabermapper.musical.subprocess.run", side_effect=fake_run):
            result = analyze_layers(self.audio, out, backend="ensemble", python="custom-python", device="cuda")
        self.assertEqual([c[c.index("-n") + 1] for c in commands], ["htdemucs_ft", "htdemucs_6s"])
        self.assertEqual(commands[0][commands[0].index("--shifts") + 1], "2")
        self.assertEqual(set(result["layers"]), {"mix", "drums", "bass", "vocals", "guitar", "piano", "other"})
        self.assertEqual(result["producer"]["models"], ["htdemucs_ft", "htdemucs_6s"])
        split = sum(sf.read(out / "separated/ensemble" / f"{n}.wav")[0] for n in ("guitar", "piano", "other"))
        np.testing.assert_allclose(split, sf.read(out / "separated/htdemucs_ft/mix/other.wav")[0], atol=1e-3)
        self.assertTrue((out / result["views"]["overview"]).exists())
        self.assertIn("bleed_gate", result["layers"]["guitar"])
        self.assertIn("layer_entries", result)

    def test_the_separation_environment_is_found_without_flags(self):
        venv = self.root / ".venv-separation" / "Scripts"
        venv.mkdir(parents=True)
        (venv / "python.exe").touch()
        with patch.object(musical, "APP_DIRECTORY", self.root), \
                patch("importlib.util.find_spec", return_value=None):
            self.assertEqual(separation_python(), venv / "python.exe")
            (venv / "python.exe").unlink()
            with self.assertRaisesRegex(ValueError, "venv-separation"):
                separation_python()
        self.assertEqual(separation_python("given"), Path("given"))


class SpectrogramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = ProjectStore(cls.temp.name)
        cls.project = cls.store.create(demo=True)
        cls.analysis = analyze_project(cls.store, cls.project["project"]["id"], backend="hpss")
        cls.directory = cls.store.directory(cls.project["project"]["id"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_run_writes_an_overview_image(self):
        image = Image.open(self.analysis["overview_image"])
        self.assertGreater(image.width, 2000)
        self.assertIn("layer_entries", self.analysis)

    def test_a_beat_range_view_with_the_notes(self):
        run_id, evidence = latest_run(self.directory)
        view = project_view(self.directory, self.project["arrangement"], evidence, run_id, start_beat=8, end_beat=24)
        image = Image.open(view["image"])
        self.assertEqual((image.width, image.height), (view["width"], view["height"]))
        self.assertEqual([p["layer"] for p in view["panels"]], ["mix", "harmonic", "percussive"])
        self.assertAlmostEqual(view["start_beat"], 8, places=3)
        self.assertEqual(view["plot_width"], 16 * 64, "short ranges get the widest beat spacing")
        self.assertTrue(Path(view["image"]).is_relative_to(self.directory / "views"))
        pixels = np.asarray(image.convert("RGB"))[view["panels"][0]["top"]:view["panels"][0]["bottom"]]
        self.assertGreater(pixels.std(), 10, "the mix panel shows a spectrogram, not a flat fill")

    def test_errors_are_actionable(self):
        run_id, evidence = latest_run(self.directory)
        with self.assertRaisesRegex(ValueError, "drawable layers"):
            project_view(self.directory, self.project["arrangement"], evidence, run_id, layers=["vocals"])
        with self.assertRaisesRegex(ValueError, "both --start and --end"):
            project_view(self.directory, self.project["arrangement"], evidence, run_id, start_beat=4)


if __name__ == "__main__":
    unittest.main()
