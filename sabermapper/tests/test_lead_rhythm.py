"""Notes follow the bar's lead: its attacks carry notes and filler does not bury its syncopation."""
import copy
from fractions import Fraction
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from sabermapper.audio_repair import follow_lead, repair_audio
from sabermapper.critique import critique_arrangement, grid_alignment
from sabermapper.musical import analyze_layers, rhythm_grid
from sabermapper.validation import validate_arrangement


def note(i, beat):
    color = i % 2
    # Each hand alternates down/up so the fixture itself has no flow break.
    return {"id": f"n{i}", "beat": beat, "x": 1 + color, "y": 1, "color": color,
            "direction": 1 if (i // 2) % 2 == 0 else 0}


def arrangement(beats, *, lead="guitar", length=32):
    # 120 BPM, offset 0: beat b sits at b / 2 seconds.
    focus = [{"id": "riff", "start_beat": 0, "end_beat": length, "lead": lead,
              "weights": {lead: 0.6, "drums": 0.4} if lead != "drums" else {"drums": 1.0},
              "intent": "Follow the offbeat guitar riff."}]
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": length, "intent": "fixture",
                                        "locked": False, "resolved": True, "patterns": [], "musical_focus": focus,
                                        "notes": [note(i, b) for i, b in enumerate(beats)]}]}


def events(layer, beats, strength=0.8, method="spectral_flux", shift=0.0):
    return [{"id": f"{layer}:{i}", "seconds": b / 2 + shift, "method": method, "strength": strength}
            for i, b in enumerate(beats)]


def report(length=32):
    # Kick on every beat, guitar on every offbeat: the riff is syncopated against the drums.
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(length * 5)]
    return {"source": {"sha256": "fixture", "duration_seconds": length / 2},
            "layers": {"mix": {"events": [], "energy_contour": contour},
                       "drums": {"events": events("drums", range(length))},
                       "guitar": {"events": events("guitar", [b + 0.5 for b in range(length)])},
                       "vocals": {"events": [], "sustains": []}}}


def codes(result):
    return {w["code"] for w in result["warnings"]}


STREAM = [b / 2 for b in range(64)]           # every eighth: kicks and guitar merged into a metronome
OFFBEATS = [b + 0.5 for b in range(32)]       # the guitar riff itself
KICKS = list(range(32))                       # the drums only


class LeadRhythmCritiqueTests(unittest.TestCase):
    def test_an_even_stream_over_an_offbeat_riff_is_diluted(self):
        result = critique_arrangement(arrangement(STREAM), report())
        self.assertIn("lead_rhythm_diluted", codes(result))
        warning = next(w for w in result["warnings"] if w["code"] == "lead_rhythm_diluted")
        self.assertEqual(warning["beats"], [0, 32])
        self.assertEqual(len(warning["object_ids"]), 32, "each on-beat filler note is named")
        self.assertNotIn("drum_rhythm_unmapped", codes(result), "a declared guitar lead outranks the drums")

    def test_notes_on_the_drums_miss_the_declared_lead(self):
        result = critique_arrangement(arrangement(KICKS), report())
        self.assertIn("lead_rhythm_unmapped", codes(result))

    def test_following_the_riff_passes(self):
        result = critique_arrangement(arrangement(OFFBEATS), report())
        self.assertFalse(codes(result) & {"lead_rhythm_diluted", "lead_rhythm_unmapped", "drum_rhythm_unmapped"})
        bars = result["metrics"]["lead_rhythm"]["bars"]
        self.assertEqual({b["lead"] for b in bars}, {"guitar"})

    def test_notes_in_the_leads_gaps_are_not_filler(self):
        data = report()
        # The guitar rests through beats 8-12: other layers may fill that gap.
        data["layers"]["guitar"]["events"] = [e for e in data["layers"]["guitar"]["events"]
                                              if not 7.9 <= e["seconds"] * 2 < 12.5]
        beats = [b for b in OFFBEATS if not 8 <= b < 12.5] + [9, 10, 11]
        result = critique_arrangement(arrangement(sorted(beats)), data)
        self.assertNotIn("lead_rhythm_diluted", codes(result))

    def test_without_a_declared_lead_the_check_is_skipped(self):
        source = arrangement(STREAM)
        source["sections"][0]["musical_focus"] = []
        result = critique_arrangement(source, report())
        self.assertFalse(codes(result) & {"lead_rhythm_diluted", "lead_rhythm_unmapped"})
        self.assertEqual(result["metrics"]["lead_rhythm"]["bars"], [])

    def test_mix_lead_is_not_an_instrument_lead(self):
        source = arrangement(STREAM, lead="drums")
        source["sections"][0]["musical_focus"][0].update(lead="mix", weights={"mix": 1.0})
        self.assertFalse(critique_arrangement(source, report())["metrics"]["lead_rhythm"]["bars"])

    def test_singing_bars_are_led_by_the_voice(self):
        data = report()
        data["layers"]["vocals"] = {"events": events("vocals", [0, 1.25, 2, 3.25]),
                                    "sustains": [{"start_seconds": 0.0, "end_seconds": 2.0}]}
        result = critique_arrangement(arrangement(STREAM[:8]), data)
        bar = next(b for b in result["metrics"]["lead_rhythm"]["bars"] if b["start_beat"] == 0)
        self.assertEqual(bar["lead"], "vocals")
        self.assertEqual(bar["code"], "lead_rhythm_diluted")


class QuietLeadTests(unittest.TestCase):
    """Intensity sets the density, the lead the placement: a thin, soft bar takes only the lead's strongest attacks."""

    def quiet(self):
        data = report()
        data["passages"] = [{"start_seconds": t, "end_seconds": t + 2, "energy_ratio": 0.3, "support_score": 0.2}
                            for t in range(0, 16, 2)]
        # Strong guitar attack on each offbeat, a weaker one on each sixteenth after it.
        data["layers"]["guitar"]["events"] += events("guitar", [b + 0.75 for b in range(32)], strength=0.5)
        return data

    def test_a_quiet_bar_does_not_demand_every_lead_attack(self):
        result = critique_arrangement(arrangement(OFFBEATS[::2]), self.quiet())
        self.assertNotIn("lead_rhythm_unmapped", codes(result))
        self.assertTrue(all(b["quiet"] for b in result["metrics"]["lead_rhythm"]["bars"]))
        self.assertIn("lead_rhythm_unmapped", codes(critique_arrangement(arrangement(OFFBEATS[::2]), report())))

    def test_a_quiet_rebuild_takes_one_attack_per_beat(self):
        result = follow_lead(arrangement(STREAM), self.quiet())
        beats = sorted(float(Fraction(str(n["beat"]))) for n in result["arrangement"]["sections"][0]["notes"])
        self.assertTrue(beats)
        self.assertTrue(all(b % 1 == 0.5 for b in beats), beats)
        self.assertTrue(all(y - x >= 1 for x, y in zip(beats, beats[1:])), beats)


class GridAlignmentTests(unittest.TestCase):
    def test_a_window_whose_onsets_drift_is_flagged(self):
        data = report(96)
        data["layers"]["drums"]["events"] = (events("drums", range(64))
                                             + events("drums", range(64, 96), shift=0.05))
        result = critique_arrangement(arrangement(OFFBEATS, length=96), data)
        self.assertIn("grid_drift", codes(result))
        windows = result["metrics"]["grid_alignment"]["windows"]
        self.assertEqual([round(w["median_offset_ms"]) for w in windows], [0, 0, 50])

    def test_a_steady_grid_passes(self):
        alignment = grid_alignment(arrangement(OFFBEATS, length=96), report(96))
        self.assertTrue(alignment["checked"])
        self.assertEqual(alignment["median_offset_ms"], 0.0)


class FollowLeadRepairTests(unittest.TestCase):
    def test_a_diluted_bar_is_rebuilt_on_the_leads_attacks(self):
        source = arrangement(STREAM)
        before = copy.deepcopy(source)
        result = follow_lead(source, report())
        self.assertEqual(source, before, "input must not be mutated")
        self.assertTrue(result["changes"])
        self.assertEqual({c["action"] for c in result["changes"]}, {"rebuilt"})
        beats = sorted(float(Fraction(str(n["beat"]))) for n in result["arrangement"]["sections"][0]["notes"])
        self.assertTrue(beats)
        self.assertTrue(all(b % 1 == 0.5 for b in beats), beats)
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["severity"] == "error"], [])
        self.assertNotIn("lead_rhythm_diluted", codes(critique_arrangement(result["arrangement"], report())))

    def test_an_even_stream_that_blocks_a_dense_lead_is_rebuilt(self):
        # The guitar plays syncopated sixteenths (beats x.25 and x.75); an eighth stream leaves no room for them.
        data = report()
        data["layers"]["guitar"]["events"] = events("guitar", [b + d for b in range(32) for d in (0.25, 0.75)])
        before = critique_arrangement(arrangement(STREAM), data)
        self.assertIn("lead_rhythm_unmapped", codes(before))
        self.assertNotIn("lead_rhythm_diluted", codes(before))
        result = follow_lead(arrangement(STREAM), data)
        self.assertEqual({c["code"] for c in result["changes"]}, {"lead_rhythm_unmapped"})
        after = critique_arrangement(result["arrangement"], data)
        self.assertNotIn("lead_rhythm_unmapped", codes(after))
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["severity"] == "error"], [])

    def test_a_rebuild_that_maps_no_more_of_the_lead_is_restored(self):
        # The guitar attacks sit where the drums already are, too close together for any hand to take more.
        data = report()
        data["layers"]["guitar"]["events"] = events("guitar", [b + d for b in range(32) for d in (0, 0.1, 0.2)])
        source = arrangement(KICKS)
        result = follow_lead(source, data)
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["arrangement"], source)

    def test_arc_anchors_survive_the_rebuild(self):
        source = arrangement(STREAM)
        section = source["sections"][0]
        # Consecutive left-hand cuts: no left note may sit inside the hold.
        head, tail = section["notes"][0], section["notes"][2]
        section["arcs"] = [{"id": "a1", "beat": head["beat"], "color": 0, "x": head["x"], "y": head["y"],
                            "direction": head["direction"], "tail_beat": tail["beat"], "tail_x": tail["x"],
                            "tail_y": tail["y"], "tail_direction": tail["direction"]}]
        result = repair_audio(source, report())
        notes = {(float(Fraction(str(n["beat"]))), n["color"]) for n in result["arrangement"]["sections"][0]["notes"]}
        self.assertIn((0.0, 0), notes)
        self.assertIn((1.0, 0), notes)


class RhythmGridTests(unittest.TestCase):
    def test_bars_show_each_layer_beside_the_notes(self):
        grid = rhythm_grid(report(), arrangement(STREAM), 0, 8, layers=["guitar", "drums"])
        self.assertEqual(grid["cells_per_bar"], 16)
        first = grid["bars"][0]
        self.assertEqual(first["notes"], "x.x.x.x.x.x.x.x.")
        self.assertEqual(first["layers"]["guitar"], "..9...9...9...9.")
        self.assertEqual(first["layers"]["drums"], "9...9...9...9...")
        self.assertEqual(first["lead"], "guitar")
        self.assertEqual([b["patterns"]["guitar"] for b in grid["bars"]], ["A", "A"])
        self.assertEqual(grid["grid_fit"]["guitar"]["on_sixteenth_grid"], 1.0)

    def test_triplet_division_and_errors(self):
        grid = rhythm_grid(report(), arrangement(STREAM), 0, 4, division=3)
        self.assertEqual(grid["cells_per_bar"], 12)
        with self.assertRaises(ValueError):
            rhythm_grid(report(), arrangement(STREAM), 0, 4, division=5)
        with self.assertRaises(ValueError):
            rhythm_grid(report(), arrangement(STREAM), 0, 4, layers=["piano"])


class ChordChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def chords(self):
        rate, seconds = 22050, 4.0
        t = np.arange(int(rate * seconds)) / rate
        signal = np.zeros(len(t))
        # C major, F major, G major, C major: one strummed chord per second.
        for index, chord in enumerate(([261.63, 329.63, 392.0], [349.23, 440.0, 523.25],
                                       [392.0, 493.88, 587.33], [261.63, 329.63, 392.0])):
            delta = t - index
            inside = (delta >= 0) & (delta < 1)
            for hz in chord:
                signal += np.where(inside, 0.2 * np.sin(2 * np.pi * hz * delta) * np.exp(-delta * 1.5), 0)
        return signal.astype(np.float32), rate

    def test_chord_changes_follow_the_harmony(self):
        signal, rate = self.chords()
        sf.write(self.root / "chords.wav", signal, rate, subtype="FLOAT")
        report = analyze_layers(self.root / "chords.wav", self.root / "run")
        changes = [e for e in report["layers"]["mix"]["events"] if e["method"] == "chord_change"]
        times = [e["seconds"] for e in changes]
        for boundary in (1.0, 2.0, 3.0):
            self.assertTrue(any(abs(t - boundary) < 0.06 for t in times), (boundary, times))
        self.assertTrue(all(abs(t - round(t)) < 0.06 for t in times), times)
        first = min(changes, key=lambda e: abs(e["seconds"] - 1.0))
        self.assertIn("C", first["from_pitch_classes"])
        self.assertIn("F", first["to_pitch_classes"])
        self.assertEqual(report["schema_version"], "1.2")
        self.assertFalse([e for layer in ("low", "mid", "high")
                          for e in report["layers"][layer]["events"] if e["method"] == "chord_change"],
                         "frequency bands share the mix signal")

    def test_rerun_reanalyzes_an_earlier_runs_stems(self):
        signal, rate = self.chords()
        sf.write(self.root / "chords.wav", signal, rate, subtype="FLOAT")
        first = analyze_layers(self.root / "chords.wav", self.root / "hpss", backend="hpss")
        again = analyze_layers(self.root / "chords.wav", self.root / "again", backend="rerun",
                               source_run=self.root / "hpss")
        self.assertEqual(set(again["layers"]), set(first["layers"]))
        self.assertEqual(again["producer"]["rerun_of"], "hpss")
        self.assertTrue(any(e["method"] == "chord_change" for e in again["layers"]["harmonic"]["events"]))
        self.assertFalse(any(e["method"] == "chord_change" for e in again["layers"]["percussive"]["events"]))
        with self.assertRaises(ValueError):
            analyze_layers(self.root / "chords.wav", self.root / "bad", backend="rerun")
        sf.write(self.root / "other.wav", signal[::-1].copy(), rate, subtype="FLOAT")
        with self.assertRaises(ValueError):
            analyze_layers(self.root / "other.wav", self.root / "mismatch", backend="rerun",
                           source_run=self.root / "hpss")


if __name__ == "__main__":
    unittest.main()
