"""Signal-grounded evidence, focus validation, and revision integration."""
import copy
import io
import http.client
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from sabermapper.__main__ import main
from sabermapper.arrangement import compile_arrangement
from sabermapper.audio import _hash
from sabermapper.musical import analyze_layers, evidence_slice, seconds_to_beat, validate_focus
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.validation import validate_arrangement


def phrase():
    return {"id": "voice", "start_beat": 0, "end_beat": 4, "lead": "vocals",
            "weights": {"vocals": .8, "mix": .2}, "intent": "Follow vocal attacks; leave the breath empty",
            "evidence": ["run-id/vocals:spectral_flux:100"]}


class MusicalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "mix.wav"
        self.rate = 22050
        t = np.arange(self.rate * 4) / self.rate
        self.signal = np.zeros(len(t), dtype=np.float32)
        for onset in (.5, 1.5, 2.5):
            delta = t - onset
            self.signal += np.where((delta >= 0) & (delta < .15),
                                    .6 * np.sin(2*np.pi*440*delta) * np.exp(-np.maximum(delta, 0)*30), 0)
        sf.write(self.audio, self.signal, self.rate, subtype="FLOAT")

    def test_attacks_follow_signal_and_silence_has_no_events(self):
        report = analyze_layers(self.audio, self.root / "bands")
        events = report["layers"]["mix"]["events"]
        for method in ("spectral_flux", "energy_rise"):
            times = [e["seconds"] for e in events if e["method"] == method]
            for onset in (.5, 1.5, 2.5):
                self.assertTrue(any(abs(t-onset)<.04 for t in times), (method, onset, times))
        self.assertFalse(any(e["seconds"] > 3 for e in events))
        sf.write(self.root / "silence.wav", np.zeros(self.rate), self.rate)
        silent = analyze_layers(self.root / "silence.wav", self.root / "silent")
        self.assertTrue(all(not layer["events"] for layer in silent["layers"].values()))

    def test_hpss_reconstructs_and_preserves_zero_time(self):
        report = analyze_layers(self.audio, self.root / "hpss", backend="hpss")
        h, sr = sf.read(self.root / "hpss/harmonic.wav")
        p, _ = sf.read(self.root / "hpss/percussive.wav")
        self.assertEqual(sr, self.rate)
        self.assertEqual(len(h), len(self.signal))
        np.testing.assert_allclose(h+p, self.signal, atol=1e-6)
        self.assertEqual(set(report["layers"]), {"mix", "harmonic", "percussive"})

    def test_stereo_phase_cancellation_does_not_hide_attacks(self):
        sf.write(self.audio, np.column_stack([self.signal, -self.signal]), self.rate, subtype="FLOAT")
        result = analyze_layers(self.audio, self.root / "stereo")
        self.assertGreater(len(result["layers"]["mix"]["events"]), 0)

    def manifest(self, **changes):
        manifest = {"source_sha256": _hash(self.audio), "producer": "test separator / checkpoint-123",
                    "stems": {"vocals": "mix.wav"}}
        manifest.update(changes)
        path = self.root / "stems.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_import_identity_duration_and_immutable_runs(self):
        path = self.manifest()
        out = self.root / "imported"
        result = analyze_layers(self.audio, out, backend="import", manifest=path)
        self.assertEqual(result["layers"]["vocals"]["source"]["sha256"], _hash(self.audio))
        self.assertTrue((out / "vocals.wav").exists())
        with self.assertRaisesRegex(ValueError, "new output"):
            analyze_layers(self.audio, out)
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            analyze_layers(self.audio, self.root / "wrong", backend="import",
                           manifest=self.manifest(source_sha256="bad"))
        sf.write(self.root / "short.wav", np.zeros(1000), self.rate)
        with self.assertRaisesRegex(ValueError, "duration"):
            analyze_layers(self.audio, self.root / "short-run", backend="import",
                           manifest=self.manifest(stems={"vocals": "short.wav"}))
        self.assertFalse((self.root / "short-run/report.json").exists())
        with self.assertRaisesRegex(ValueError, "Stem names"):
            analyze_layers(self.audio, self.root / "bad-name", backend="import",
                           manifest=self.manifest(stems={"../escape": "mix.wav"}))

    def test_demucs_adapter_and_failed_run(self):
        out = self.root / "model"
        def fake_run(command, **kwargs):
            if command[1] == "-c":  # device auto-detection probes the separation Python's torch
                return type("Result", (), {"returncode": 0, "stdout": "cpu\n"})()
            self.assertEqual(command[:3], ["custom-python", "-m", "demucs.separate"])
            self.assertEqual(command[command.index("-d") + 1], "cpu")
            folder = out / "separated/htdemucs/mix"
            folder.mkdir(parents=True)
            for name in ("vocals", "drums", "bass", "other"):
                sf.write(folder / f"{name}.wav", self.signal, self.rate)
            return type("Result", (), {"returncode": 0})()
        with patch("sabermapper.musical.subprocess.run", side_effect=fake_run):
            report = analyze_layers(self.audio, out, backend="demucs", python="custom-python")
        self.assertEqual(len(report["layers"]), 5)
        with patch("sabermapper.musical.subprocess.run") as runner:
            runner.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, "Demucs failed"):
                analyze_layers(self.audio, self.root / "failed", backend="demucs", python="custom-python", device="cpu")
        self.assertFalse((self.root / "failed/report.json").exists())

    def test_tiny_audio(self):
        sf.write(self.root / "tiny.wav", np.zeros(1), self.rate)
        report = analyze_layers(self.root / "tiny.wav", self.root / "tiny", backend="hpss")
        self.assertEqual(report["layers"]["mix"]["events"], [])


class FocusIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = ProjectStore(cls.temp.name)
        cls.initial = cls.store.create(demo=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_focus_validation_does_not_change_compiled_notes(self):
        arrangement = copy.deepcopy(self.initial["arrangement"])
        original = compile_arrangement(arrangement)
        arrangement["sections"][0]["musical_focus"] = [phrase()]
        self.assertFalse([d for d in validate_arrangement(arrangement) if d["severity"] == "error"])
        self.assertEqual(compile_arrangement(arrangement), original)
        bad_phrases = [{"weights": {"vocals": -.1, "mix": 1.1}}, {"weights": {"vocals": float("nan")}},
                       {"weights": {"vocals": True}}, {"weights": {"vocals": .8}}, {"lead": "guitar"},
                       {"start_beat": True}, {"start_beat": "1/0"}, {"end_beat": 1000},
                       {"evidence": "invented"}, {"id": []}]
        for change in bad_phrases:
            with self.subTest(change=change):
                arrangement["sections"][0]["musical_focus"] = [{**phrase(), **change}]
                self.assertTrue(any(d["code"] == "invalid_musical_focus" for d in validate_arrangement(arrangement)))
        with self.assertRaises(ValueError):
            validate_focus([phrase(), {**phrase(), "id": "overlap"}], 16)

    def test_seconds_grid_and_missing_layers(self):
        arrangement = copy.deepcopy(self.initial["arrangement"])
        arrangement["song"].update(bpm=120, audio_offset_seconds=.25)
        arrangement["tempo_events"] = [{"beat": 4, "bpm": 60}]
        self.assertAlmostEqual(seconds_to_beat(3.25, arrangement), 5)
        self.assertAlmostEqual(seconds_to_beat(0, arrangement), -.5)
        arrangement["sections"][0]["musical_focus"] = [phrase()]
        report = {"source": {}, "layers": {"mix": {"kind": "audio_layer", "events": [
            {"id": "a", "seconds": 2.25}, {"id": "b", "seconds": 3.25}]}}, "limitations": []}
        section_start = float(arrangement["sections"][0]["start_beat"])
        excerpt = evidence_slice(report, arrangement, 0, max(8, section_start+4))
        self.assertEqual(excerpt["layers"]["mix"]["events"][1]["beat"], 5)
        self.assertEqual(excerpt["missing_focus_layers"], ["vocals"])

    def test_cli_evidence_and_revision_locked_focus(self):
        project = self.initial["project"]["id"]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["music", "analyze", project, "--workspace", self.temp.name]), 0)
        run = json.loads(output.getvalue())
        current = self.store.get(project)
        self.assertEqual(current["revision"], self.initial["revision"])
        self.assertTrue(any(r["id"] == run["id"] for r in current["musical_runs"]))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["music", "inspect", project, "--workspace", self.temp.name,
                                   "--run", run["id"], "--start", "0", "--end", "8"]), 0)
        self.assertIn("layers", json.loads(output.getvalue()))
        self.assertEqual(json.loads(output.getvalue())["revision"], current["revision"])
        self.assertTrue(json.loads(output.getvalue())["mapped_notes"])
        changed = copy.deepcopy(current["arrangement"])
        changed["sections"][0]["musical_focus"] = [phrase()]
        saved = self.store.save(project, changed, current["revision"])
        self.assertNotEqual(saved["revision"], current["revision"])
        section = changed["sections"][0]["id"]
        locked = self.store.set_lock(project, section, True, saved["revision"])
        locked_edit = copy.deepcopy(locked["arrangement"])
        locked_edit["sections"][0]["musical_focus"][0]["intent"] = "Change"
        with self.assertRaises(ConflictError):
            self.store.save(project, locked_edit, locked["revision"])

    def test_http_analysis_publication_and_model_boundary(self):
        from sabermapper.server import make_server
        server = make_server(self.temp.name, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        try:
            connection.request("GET", "/api/status")
            token = json.loads(connection.getresponse().read())["token"]
            project = self.initial["project"]["id"]
            headers = {"Content-Type": "application/json", "X-SaberMapper-Token": token}
            connection.request("POST", f"/api/projects/{project}/music", json.dumps({"backend": "demucs"}), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.request("POST", f"/api/projects/{project}/music", json.dumps({"backend": "hpss"}), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            result = json.loads(response.read())
            base = f"/api/projects/{project}/files/musical/{result['id']}"
            connection.request("GET", base + "/report.json")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("harmonic", json.loads(response.read())["layers"])
            connection.request("GET", base + "/percussive.wav", headers={"Range": "bytes=0-31"})
            response = connection.getresponse()
            self.assertEqual(response.status, 206)
            self.assertTrue(response.read().startswith(b"RIFF"))
            connection.request("GET", base + "/../../project.json")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()


class PitchAndPassageTests(unittest.TestCase):
    """Sustained pitch, settled pitch changes, attack profile and passage evidence."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = ProjectStore(cls.temp.name)
        cls.initial = cls.store.create(demo=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.rate = 22050

    def mix(self, name, signal, **options):
        path = self.root / f"{name}.wav"
        sf.write(path, np.asarray(signal, dtype=np.float32), self.rate, subtype="FLOAT")
        return analyze_layers(path, self.root / name, **options)["layers"]["mix"]

    def tone(self, hertz, seconds, amplitude=.5):
        return amplitude * np.sin(2*np.pi*hertz*np.arange(int(self.rate*seconds))/self.rate)

    def glide(self, low, high, seconds=1.0):
        steps = np.linspace(12*np.log2(low/440)+69, 12*np.log2(high/440)+69, int(self.rate*seconds))
        return .5 * np.sin(2*np.pi*np.cumsum(440*2**((steps-69)/12))/self.rate)

    def test_glide_and_flat_tones_report_one_sustain_each(self):
        for name, signal, shape, expected in (("up", self.glide(220, 293.66), "rise", 5),
                                              ("down", self.glide(293.66, 220), "fall", -5)):
            sustains = self.mix(name, signal)["sustains"]
            self.assertEqual(len(sustains), 1, sustains)
            self.assertAlmostEqual(sustains[0]["semitone_delta"], expected, delta=1.0)
            self.assertEqual(sustains[0]["pitch_shape"], shape)
            self.assertGreater(sustains[0]["confidence"], .5)
            self.assertEqual(sustains[0]["strength"], 1.0)
        flat = self.mix("flat", self.tone(220, 1))["sustains"]
        self.assertEqual(len(flat), 1, flat)
        self.assertLess(abs(flat[0]["semitone_delta"]), .5)
        self.assertEqual(flat[0]["pitch_shape"], "flat")
        self.assertAlmostEqual(flat[0]["median_hz"], 220, delta=4)

    def test_staccato_bursts_have_no_sustains_and_are_not_a_sustained_layer(self):
        seconds = np.arange(self.rate*4)/self.rate
        signal = np.zeros(len(seconds))
        for onset in (.5, 1.5, 2.5):
            delta = seconds - onset
            signal += np.where((delta >= 0) & (delta < .15),
                               .6 * np.sin(2*np.pi*440*delta) * np.exp(-np.maximum(delta, 0)*30), 0)
        layer = self.mix("staccato", signal)
        self.assertEqual(layer["sustains"], [])
        self.assertFalse(layer["attack_profile"]["sustained_layer"])
        held = self.mix("held", self.tone(330, 3))["attack_profile"]
        self.assertTrue(held["sustained_layer"])
        self.assertGreaterEqual(held["sustained_fraction"], .6)

    def test_settled_step_is_an_event_and_vibrato_is_not(self):
        phrase = np.concatenate([self.tone(220, .6), self.tone(261.63, .6)])
        changes = [e for e in self.mix("phrase", phrase)["events"] if e["method"] == "pitch_change"]
        self.assertEqual(len(changes), 1, changes)
        self.assertAlmostEqual(changes[0]["seconds"], .6, delta=.06)
        self.assertAlmostEqual(changes[0]["semitone_delta"], 3, delta=.5)
        self.assertGreater(changes[0]["to_midi"], changes[0]["from_midi"])
        self.assertTrue(changes[0]["id"].startswith("mix:pitch_change:"))
        seconds = np.arange(int(self.rate*1.5))/self.rate
        wobble = 220 * 2 ** (.5*np.sin(2*np.pi*6*seconds)/12)
        layer = self.mix("vibrato", .5*np.sin(2*np.pi*np.cumsum(wobble)/self.rate))
        self.assertEqual([e for e in layer["events"] if e["method"] == "pitch_change"], [])
        self.assertEqual(len(layer["sustains"]), 1, layer["sustains"])
        self.assertEqual(layer["sustains"][0]["pitch_shape"], "flat")

    def test_melody_steps_over_a_held_chord_are_melody_changes(self):
        # A pad holds A3 and E4 while the top voice steps A4 -> C5 -> B4 legato: the monophonic
        # tracker cannot follow one line through the chord, the predominant-pitch tracker can.
        def voice(hertz, seconds):
            return sum(a * self.tone(hertz * h, seconds, .3) for h, a in ((1, 1), (2, .5), (3, .3)))
        pad = self.tone(220, 2.4, .2) + self.tone(329.63, 2.4, .2)
        line = np.concatenate([voice(440, .8), voice(523.25, .8), voice(493.88, .8)])
        changes = [e for e in self.mix("pad", pad + line)["events"] if e["method"] == "melody_change"]
        self.assertEqual([(e["from_midi"], e["to_midi"]) for e in changes], [(69, 72), (72, 71)], changes)
        for event, expected in zip(changes, (.8, 1.6)):
            self.assertAlmostEqual(event["seconds"], expected, delta=.06)
            self.assertTrue(event["id"].startswith("mix:melody_change:"))
            self.assertGreater(event["strength"], .3)
        held = [e for e in self.mix("chord", pad + voice(440, 2.4))["events"] if e["method"] == "melody_change"]
        self.assertEqual(held, [], "a held chord has no melody change")
        # A soft line before a loud one: strength follows the surrounding level, not the song's loudest part.
        phrase = np.tile(pad + line, 3)
        soft = np.concatenate([.35 * phrase, phrase])
        found = [e for e in self.mix("soft", soft)["events"] if e["method"] == "melody_change" and e["seconds"] < 2.3]
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all(e["strength"] > .5 for e in found), found)

    def test_passages_mark_a_quiet_sustained_window_and_an_onset_dense_one(self):
        seconds = np.arange(int(self.rate*2))/self.rate
        pad = .05 * np.minimum(1, np.minimum(seconds, 2-seconds)/.5) * np.sin(2*np.pi*196*seconds)
        clicks, decay = np.zeros(int(self.rate*4)), np.arange(200)/self.rate
        for step in range(38):
            begin = int((.2 + step*.1) * self.rate)
            clicks[begin:begin+200] += np.sin(2*np.pi*1800*decay) * np.exp(-decay*400)
        path = self.root / "passages.wav"
        sf.write(path, np.concatenate([pad, clicks]).astype(np.float32), self.rate, subtype="FLOAT")
        report = analyze_layers(path, self.root / "passages")
        self.assertEqual([p["start_seconds"] for p in report["passages"]], [0.0, 2.0, 4.0])
        self.assertTrue(report["passages"][0]["low_intensity"], report["passages"][0])
        self.assertFalse(report["passages"][-1]["low_intensity"], report["passages"][-1])
        self.assertGreater(report["passages"][-1]["drum_onset_density"], 5)
        self.assertEqual(report["passage_thresholds"]["window_seconds"], 2.0)
        self.assertIn(report["passage_thresholds"]["drum_layer"], report["layers"])
        self.assertEqual(report["schema_version"], "1.3")

    def test_slice_returns_sustains_passages_and_one_layer(self):
        arrangement = copy.deepcopy(self.initial["arrangement"])
        arrangement["song"].update(bpm=120, audio_offset_seconds=.25)
        report = {"source": {}, "limitations": [], "layers": {
            "mix": {"kind": "audio_layer", "events": [], "attack_profile": {"sustained_layer": True},
                    "sustains": [{"id": "mix:sustain:0", "start_seconds": 2.25, "end_seconds": 3.25},
                                 {"id": "mix:sustain:900", "start_seconds": 90.0, "end_seconds": 92.0}]},
            "low": {"kind": "frequency_band", "events": [], "sustains": []}},
            "passages": [{"start_seconds": 2.25, "end_seconds": 3.25, "low_intensity": True}],
            "passage_thresholds": {"drum_layer": "low"}}
        excerpt = evidence_slice(report, arrangement, 0, 8)
        self.assertEqual([s["start_beat"] for s in excerpt["layers"]["mix"]["sustains"]], [4])
        self.assertEqual(excerpt["layers"]["mix"]["sustains"][0]["end_beat"], 6)
        self.assertTrue(excerpt["layers"]["mix"]["attack_profile"]["sustained_layer"])
        self.assertEqual([p["start_beat"] for p in excerpt["passages"]], [4])
        self.assertEqual(excerpt["passage_thresholds"]["drum_layer"], "low")
        self.assertEqual(set(evidence_slice(report, arrangement, 0, 8, "mix")["layers"]), {"mix"})
        with self.assertRaisesRegex(ValueError, "low, mix"):
            evidence_slice(report, arrangement, 0, 8, "vocals")
        legacy = {"source": {}, "limitations": [],
                  "layers": {"mix": {"kind": "audio_layer", "events": []}}}
        plain = evidence_slice(legacy, arrangement, 0, 8)
        self.assertEqual(plain["layers"]["mix"]["sustains"], [])
        self.assertEqual(plain["passages"], [])

    def test_cli_inspect_filters_one_layer(self):
        project = self.initial["project"]["id"]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["music", "analyze", project, "--workspace", self.temp.name]), 0)
        run = json.loads(output.getvalue())["id"]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["music", "inspect", project, "--workspace", self.temp.name,
                                   "--run", run, "--start", "0", "--end", "8", "--layer", "mix"]), 0)
        excerpt = json.loads(output.getvalue())
        self.assertEqual(set(excerpt["layers"]), {"mix"})
        self.assertIn("sustains", excerpt["layers"]["mix"])
        self.assertIn("passage_thresholds", excerpt)
        self.assertTrue(excerpt["passages"])


if __name__ == "__main__":
    unittest.main()
