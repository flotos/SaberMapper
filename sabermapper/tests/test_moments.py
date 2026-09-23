"""Moments and listen.json from synthetic stems with known drops, builds, silences and a key change."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from sabermapper.__main__ import main
from sabermapper.audio import _hash, _write_vorbis
from sabermapper.listen import derive, latest_listen, listen_project, measure, segment, spectral_features
from sabermapper.moments import _final_chorus, detect_moments
from sabermapper.projects import ProjectStore
from sabermapper.storage import read_json, write_json

RATE = 22050
DURATION = 64.0
DROP, SILENCE, KEY = 20.0, (30.0, 32.0), 46.0


def _chord(t, root_midi, level, minor=False):
    intervals = (0, 3, 7) if minor else (0, 4, 7)
    return level * sum(np.sin(2 * np.pi * 440 * 2 ** ((root_midi + i - 69) / 12) * t) for i in intervals) / 3


def synthetic_song():
    """Stems (name -> mono float32) of a 64 s song: pad intro, 10 s riser, drop at 20 s, silence at
    30-32 s, then loud until a +2 semitone key change at 46 s; vocals enter at 22 s."""
    t = np.arange(int(DURATION * RATE)) / RATE
    rng = np.random.default_rng(7)
    loud = (t >= DROP) & ~((t >= SILENCE[0]) & (t < SILENCE[1]))
    progression = [(60, False), (65, False), (67, False), (57, True)]  # C F G Am, one chord per 2 s
    other = np.zeros_like(t)
    for index in range(int(DURATION / 2)):
        left, right = index * 2 * RATE, (index + 1) * 2 * RATE
        root, minor = progression[index % 4]
        shift = 2 if index * 2 >= KEY else 0
        level = .03 if index * 2 < DROP else .12
        other[left:right] = _chord(t[left:right], root + shift, level, minor)
    other[~loud & (t >= DROP)] = 0
    riser = np.zeros_like(t)
    window = (t >= 10) & (t < DROP)
    ramp = (t[window] - 10) / 10
    noise = rng.standard_normal(window.sum())
    # Brightening noise: mix of lowpassed and raw noise, rising level.
    smooth = np.convolve(noise, np.ones(32) / 32, mode="same")
    riser[window] = (.01 + .08 * ramp ** 2) * ((1 - ramp) * smooth * 4 + ramp * noise)
    drums = np.zeros_like(t)
    for beat in np.arange(DROP, DURATION, .5):
        if SILENCE[0] <= beat < SILENCE[1]:
            continue
        start = int(beat * RATE)
        length = int(.12 * RATE)
        envelope = np.exp(-np.arange(length) / (.03 * RATE))
        drums[start:start + length] += .6 * envelope * np.sin(2 * np.pi * 60 * np.arange(length) / RATE)
        drums[start:start + length] += .15 * envelope * rng.standard_normal(length)
    bass = np.where(loud, .15 * np.sin(2 * np.pi * 55 * t), 0)
    vocals = np.where(loud & (t >= 22), .08 * np.sin(2 * np.pi * 330 * t) * (1 + .3 * np.sin(2 * np.pi * 5 * t)), 0)
    return {"drums": drums, "bass": bass, "other": other + riser, "vocals": vocals}


def build_run(directory):
    """Write stems, the mix as song.ogg and a minimal evidence report; returns (run_id, report)."""
    stems = synthetic_song()
    mix = np.clip(sum(stems.values()), -1, 1).astype(np.float32)
    (directory / "song.ogg").unlink(missing_ok=True)
    _write_vorbis(directory / "song.ogg", mix[:, None], RATE)
    run_id = "ab" * 16
    run = directory / "musical" / run_id
    run.mkdir(parents=True)
    layers = {"mix": {"kind": "audio_layer", "events": [], "energy_contour": []}}
    for name, signal in stems.items():
        sf.write(run / f"{name}.wav", signal.astype(np.float32), RATE, subtype="FLOAT")
        layers[name] = {"kind": "audio_layer", "audio_file": f"{name}.wav", "events": []}
    kicks = [b for b in np.arange(DROP, DURATION, .5) if not SILENCE[0] <= b < SILENCE[1]]
    layers["mix"]["events"] = [{"id": f"mix:spectral_flux:{i}", "seconds": float(b), "method": "spectral_flux",
                                "strength": 1.0 if b in (DROP, SILENCE[1]) else .6} for i, b in enumerate(kicks)]
    layers["vocals"]["events"] = [{"id": "vocals:spectral_flux:1", "seconds": 22.0, "method": "spectral_flux",
                                   "strength": .9}]
    report = {"schema_version": "1.3", "created_at": "2026-09-23T00:00:00+00:00", "backend": "import",
              "source": {"sha256": _hash(directory / "song.ogg"), "duration_seconds": DURATION},
              "layers": layers,
              "layer_entries": [{"layer": "vocals", "seconds": 22.0, "silent_before_seconds": 22.0,
                                 "event_id": "vocals:spectral_flux:1"},
                                {"layer": "drums", "seconds": DROP, "silent_before_seconds": DROP, "event_id": None}]}
    write_json(run / "report.json", report)
    return run_id, report


ARRANGEMENT = {"song": {"title": "Synthetic", "artist": "Test", "bpm": 120.0, "audio_offset_seconds": 0.0},
               "tempo_events": [], "sections": [{"id": "s1", "start_beat": 0, "length_beats": 128}]}


class MomentDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.run_id, cls.report = build_run(cls.root)
        cls.frames = measure(cls.root / "song.ogg", cls.root / "musical" / cls.run_id, cls.report)
        cls.document = derive(cls.frames, cls.run_id, cls.report, ARRANGEMENT)
        cls.moments = cls.document["moments"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def of(self, kind):
        return [m for m in self.moments if m["kind"] == kind]

    def test_drop_lands_on_the_drop_after_a_build(self):
        drops = self.of("drop")
        self.assertTrue(any(abs(m["time"] - DROP) <= .3 for m in drops), drops)
        drop = min(drops, key=lambda m: abs(m["time"] - DROP))
        self.assertIn("build", drop["evidence"]["after"])
        self.assertAlmostEqual(drop["beat"], DROP * 2, delta=.7)
        builds = self.of("build")
        self.assertTrue(any(abs(m["evidence"]["resolves_at"] - DROP) <= .5 and m["time"] < 15 for m in builds), builds)

    def test_silence_and_return(self):
        silences = self.of("silence")
        self.assertTrue(any(abs(m["time"] - SILENCE[0]) <= .3 and 1.5 <= m["duration"] <= 2.5 for m in silences),
                        silences)
        self.assertFalse(any(m["time"] < 1 for m in silences), "leading silence is not a moment")

    def test_key_change_found_near_the_modulation(self):
        changes = self.of("key_change")
        self.assertTrue(any(abs(m["time"] - KEY) <= 4 and m["evidence"]["semitones"] == 2 for m in changes), changes)

    def test_entries_ending_and_ids(self):
        self.assertEqual([m["time"] for m in self.of("vocal_entry")], [22.0])
        self.assertEqual(len(self.of("ending")), 1)
        ids = [m["id"] for m in self.moments]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.moments, sorted(self.moments, key=lambda m: m["time"]))
        for moment in self.moments:
            self.assertTrue(0 <= moment["strength"] <= 1)
            self.assertIn("rule", moment["evidence"])
            self.assertIsNotNone(moment["section_id"])
        self.assertEqual(self.of("drop")[0]["id"], "drop-1")

    def test_deterministic(self):
        again = derive(self.frames, self.run_id, self.report, ARRANGEMENT)
        self.assertEqual(again["moments"], self.moments)
        self.assertEqual(again["sections"], self.document["sections"])

    def test_sections_cover_the_song_with_boundaries_near_changes(self):
        sections = self.document["sections"]
        self.assertEqual(sections[0]["start"], 0.0)
        self.assertAlmostEqual(sections[-1]["end"], DURATION, delta=.1)
        for left, right in zip(sections, sections[1:]):
            self.assertEqual(left["end"], right["start"])
        starts = [s["start"] for s in sections]
        self.assertTrue(any(abs(s - DROP) <= 2 for s in starts), starts)

    def test_without_arrangement_uses_pseudo_beats(self):
        sections, _ = segment(self.frames, None)
        self.assertGreater(len(sections), 1)
        moments = detect_moments(self.frames, sections, self.report, None)
        self.assertTrue(all(m["beat"] is None for m in moments))


class SpectralFeatureTests(unittest.TestCase):
    def test_flatness_stays_bounded_on_near_silent_stems(self):
        rng = np.random.default_rng(1)
        for signal in (np.zeros(RATE * 2, dtype=np.float32), 1e-9 * rng.standard_normal(RATE * 2).astype(np.float32),
                       .3 * rng.standard_normal(RATE * 2).astype(np.float32)):
            features = spectral_features(signal, 40)
            for name in ("flatness", "presence_flatness"):
                self.assertTrue(np.all((features[name] >= 0) & (features[name] <= 1 + 1e-6)), name)
        noise = spectral_features(.3 * rng.standard_normal(RATE * 2).astype(np.float32), 40)
        t = np.arange(RATE * 2) / RATE
        harmonic = sum(np.sin(2 * np.pi * 220 * k * t) / k for k in range(1, 40)).astype(np.float32) * .1
        tone = spectral_features(harmonic, 40)  # partials fill the 1-6 kHz band but leave gaps between them
        self.assertGreater(np.median(noise["presence_flatness"]), 10 * np.median(tone["presence_flatness"]))


class FinalChorusTests(unittest.TestCase):
    def section(self, index, group, level):
        return {"id": f"sec-{index:02d}", "start": index * 10.0, "end": index * 10.0 + 10, "group": group,
                "level_db": level}

    def test_last_occurrence_of_most_repeated_loud_group(self):
        sections = [self.section(0, "A", -20), self.section(1, "B", -12), self.section(2, "C", -8),
                    self.section(3, "B", -12), self.section(4, "C", -8), self.section(5, "C", -7),
                    self.section(6, "D", -18)]
        moment, = _final_chorus(sections)
        self.assertEqual(moment["time"], 50.0)
        self.assertEqual(moment["evidence"]["occurrences"], 3)

    def test_quiet_repeats_do_not_count_and_fallback_is_labelled(self):
        sections = [self.section(0, "A", -20), self.section(1, "A", -20), self.section(2, "B", -8),
                    self.section(3, "C", -9), self.section(4, "D", -6), self.section(5, "E", -10)]
        moment, = _final_chorus(sections)
        self.assertTrue(moment["evidence"]["fallback"])
        self.assertEqual(moment["time"], 40.0)


class ListenProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        self.project = self.store.create(demo=True)["project"]["id"]
        self.directory = self.store.directory(self.project)
        self.run_id, _ = build_run(self.directory)
        arrangement = read_json(self.directory / "arrangement.json")
        arrangement["song"].update(bpm=120.0, audio_offset_seconds=0.0)
        arrangement["tempo_events"] = []
        write_json(self.directory / "arrangement.json", arrangement)

    def test_listen_writes_into_the_run_and_latest_listen_reads_it(self):
        self.assertFalse(latest_listen(self.directory)["available"])
        result = listen_project(self.store, self.project)
        self.assertEqual(result["run_id"], self.run_id)
        self.assertFalse(result["reused"])
        path = self.directory / "musical" / self.run_id / "listen.json"
        self.assertTrue(path.exists())
        stored = read_json(path)
        self.assertEqual(stored["source_sha256"], _hash(self.directory / "song.ogg"))
        self.assertTrue(listen_project(self.store, self.project)["reused"])
        loaded = latest_listen(self.directory)
        self.assertTrue(loaded["available"])
        self.assertEqual(loaded["run_id"], self.run_id)
        self.assertIsNone(loaded["lyrics"])
        self.assertEqual([m["id"] for m in loaded["moments"]], [m["id"] for m in stored["moments"]])
        self.assertIn("sections", loaded["mood"])

    def test_beats_follow_a_changed_grid(self):
        listen_project(self.store, self.project)
        arrangement = read_json(self.directory / "arrangement.json")
        arrangement["song"]["bpm"] = 60.0
        write_json(self.directory / "arrangement.json", arrangement)
        drop = next(m for m in latest_listen(self.directory)["moments"] if m["kind"] == "drop")
        self.assertAlmostEqual(drop["beat"], drop["time"], delta=.01)

    def test_cli_listen_summary_and_structured_errors(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["music", "listen", self.project, "--workspace", self.temp.name])
        self.assertEqual(code, 0)
        summary = json.loads(out.getvalue())
        self.assertTrue(summary["moments"] and summary["sections"])
        self.assertIn("valence", summary["sections"][0])
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            main(["music", "listen", self.project, "--workspace", self.temp.name, "--run", "cd" * 16])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "run_unknown")

    def test_changed_audio_invalidates_the_run(self):
        (self.directory / "song.ogg").unlink()
        _write_vorbis(self.directory / "song.ogg", np.zeros((RATE, 1), dtype=np.float32), RATE)
        self.assertIsNone(latest_listen(self.directory)["run_id"])
        with self.assertRaises(ValueError):
            listen_project(self.store, self.project)


if __name__ == "__main__":
    unittest.main()
