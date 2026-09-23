"""Non-blocking critique metrics: density, repetition, seams and movement objects."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import random
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.critique import beat_to_seconds, critique_arrangement
from sabermapper.projects import ProjectStore


def arrangement(sections, *, bpm=120, offset=0.0):
    return {"schema_version": 1,
            "song": {"title": "Fixture", "artist": "Tests", "bpm": bpm, "audio_offset_seconds": offset},
            "difficulty": {"name": "ExpertPlus", "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": sections}


def section(section_id, start_beat, length_beats, notes):
    return {"id": section_id, "start_beat": start_beat, "length_beats": length_beats,
            "intent": "fixture", "locked": False, "resolved": True, "notes": notes, "patterns": []}


def note(index, beat, placement):
    x, y, color, direction = placement
    return {"id": f"n{index}", "beat": beat, "x": x, "y": y, "color": color, "direction": direction}


def codes(result):
    return {warning["code"] for warning in result["warnings"]}


class CritiqueMetricTests(unittest.TestCase):
    def assert_warning_only(self, result):
        self.assertEqual(result["model_version"], "1.0")
        for warning in result["warnings"]:
            self.assertEqual(warning["severity"], "warning")
            self.assertEqual(set(warning) - {"beats"}, {"severity", "code", "message", "section_id",
                                                        "object_ids", "value", "threshold"})
            if "beats" in warning:  # absolute beat range for automated repair
                self.assertLessEqual(warning["beats"][0], warning["beats"][1])
            self.assertIn(warning["code"], result["definitions"])

    def looping(self):
        # Four placements in an uneven eight-note cycle, none on the top row.
        cycle = [(0, 0, 0, 1), (0, 0, 0, 1), (3, 0, 1, 1), (0, 0, 0, 1),
                 (1, 1, 0, 0), (0, 0, 0, 1), (3, 0, 1, 1), (2, 1, 1, 0)]
        notes = [note(i, i * 0.5, cycle[i % 8]) for i in range(200)]
        return arrangement([section("loop", 0, 128, notes)])

    def test_looping_arrangement_flags_repetition_and_flat_rows(self):
        result = critique_arrangement(self.looping())
        self.assert_warning_only(result)
        self.assertLessEqual({"repetitive_cycle", "top_row_starved", "low_placement_variety"},
                             codes(result))
        repetition = result["metrics"]["repetition"]
        self.assertEqual(repetition["cycle_coverage"]["k"], 8)
        self.assertEqual(repetition["cycle_coverage"]["coverage"], 1.0)
        self.assertEqual(repetition["distinct_placements"], 4)
        self.assertEqual(repetition["top_row_share"], 0.0)
        self.assertEqual(repetition["row_histogram"]["2"], 0)
        self.assertLess(repetition["placement_entropy"]["median"], 2.5)
        self.assertEqual(result["metrics"]["note_count"], 200)

    def test_varied_arrangement_has_no_warnings(self):
        rng = random.Random(7)
        notes, index = [], 0
        for part in range(2):
            part_notes = []
            for step in range(128):
                part_notes.append(note(index, step * 0.5,
                                       (rng.randrange(4), rng.randrange(3), rng.randrange(2), rng.randrange(9))))
                index += 1
            notes.append(section(f"part{part}", part * 64, 64, part_notes))
        result = critique_arrangement(arrangement(notes))
        self.assert_warning_only(result)
        self.assertEqual(result["warnings"], [])
        repetition = result["metrics"]["repetition"]
        self.assertLess(repetition["cycle_coverage"]["coverage"], 0.6)
        self.assertGreaterEqual(repetition["placement_entropy"]["median"], 2.5)
        self.assertGreaterEqual(repetition["top_row_share"], 0.05)
        self.assertEqual(len(result["metrics"]["density"]["section_nps"]), 2)

    def test_density_collapse_flags_the_emptying_section(self):
        rng = random.Random(3)
        placement = lambda: (rng.randrange(4), rng.randrange(3), rng.randrange(2), rng.randrange(9))
        dense = [note(i, i * 0.5, placement()) for i in range(112)]  # beats 0..55.5
        dense.append(note(900, 58, placement()))  # one note inside the last four seconds
        tail = [note(1000 + i, i * 0.25, placement()) for i in range(120)]
        result = critique_arrangement(arrangement([section("S", 0, 64, dense),
                                                   section("T", 64, 32, tail)]))
        self.assert_warning_only(result)
        collapse = [w for w in result["warnings"] if w["code"] == "density_collapse"]
        self.assertEqual(len(collapse), 1)
        self.assertEqual(collapse[0]["section_id"], "S")
        self.assertLess(collapse[0]["value"], 0.6)
        self.assertEqual(collapse[0]["threshold"], 0.6)
        self.assertTrue(all(i.startswith("S/") for i in collapse[0]["object_ids"]))
        self.assertIn("sparsest 2 s window", collapse[0]["message"])

    def test_an_arc_held_through_the_sparse_window_is_not_a_collapse(self):
        rng = random.Random(3)
        placement = lambda: (rng.randrange(4), rng.randrange(3), rng.randrange(2), rng.randrange(9))
        dense = [note(i, i * 0.5, placement()) for i in range(112)]  # beats 0..55.5
        dense.append(note(900, 56, (1, 0, 0, 0)))
        dense.append(note(901, 63, (1, 2, 0, 1)))
        tail = [note(1000 + i, i * 0.25, placement()) for i in range(120)]
        body = section("S", 0, 64, dense)
        # The held sound from beat 56 to 63 is played as an arc: the hand is busy, not resting.
        body["arcs"] = [{"id": "hold", "beat": 56, "x": 1, "y": 0, "color": 0, "direction": 0,
                         "tail_beat": 63, "tail_x": 1, "tail_y": 2, "tail_direction": 1}]
        result = critique_arrangement(arrangement([body, section("T", 64, 32, tail)]))
        self.assertNotIn("density_collapse", {w["code"] for w in result["warnings"]})
        body["arcs"] = []
        result = critique_arrangement(arrangement([body, section("T", 64, 32, tail)]))
        self.assertIn("density_collapse", {w["code"] for w in result["warnings"]}, "without the arc it empties")

    def seam_fixture(self, note_on_seam):
        rng = random.Random(11)
        placement = lambda: (rng.randrange(4), rng.randrange(3), rng.randrange(2), rng.randrange(9))
        opening = [note(i, i, placement()) for i in range(16)]
        following = [note(100 + i, i if note_on_seam else i + 1, placement()) for i in range(15)]
        return arrangement([section("opening", 0, 16, opening), section("next", 16, 16, following)])

    def report(self, seconds):
        return {"source": {}, "limitations": [],
                "layers": {"piano": {"kind": "audio_layer", "energy_contour": [],
                                     "events": [{"id": "piano:spectral_flux:1", "seconds": seconds,
                                                 "method": "spectral_flux", "strength": 1.0}]}}}

    def test_boundary_accent_flags_only_an_unmapped_seam(self):
        # Beat 16 at 120 bpm with no audio offset is second 8.
        flagged = critique_arrangement(self.seam_fixture(False), self.report(8.0))
        self.assert_warning_only(flagged)
        seam = [w for w in flagged["warnings"] if w["code"] == "boundary_accent_unmapped"]
        self.assertEqual(len(seam), 1)
        self.assertEqual(seam[0]["section_id"], "next")
        self.assertEqual(seam[0]["object_ids"], ["piano:spectral_flux:1"])
        self.assertEqual(seam[0]["threshold"], 0.25)
        self.assertEqual(flagged["metrics"]["boundary_accents"],
                         {"checked": True, "unmapped_sections": ["next"]})
        mapped = critique_arrangement(self.seam_fixture(True), self.report(8.0))
        self.assert_warning_only(mapped)
        self.assertNotIn("boundary_accent_unmapped", codes(mapped))
        self.assertFalse(critique_arrangement(self.seam_fixture(False))["metrics"]["boundary_accents"]["checked"])

    def test_energy_rise_and_weak_events_are_not_seam_accents(self):
        weak = self.report(8.0)
        weak["layers"]["piano"]["events"][0]["strength"] = 0.5
        self.assertNotIn("boundary_accent_unmapped", codes(critique_arrangement(self.seam_fixture(False), weak)))
        rise = self.report(8.0)
        rise["layers"]["piano"]["events"][0]["method"] = "energy_rise"
        self.assertNotIn("boundary_accent_unmapped", codes(critique_arrangement(self.seam_fixture(False), rise)))

    def test_empty_arrangement_reports_zeros_without_warnings(self):
        result = critique_arrangement(arrangement([section("empty", 0, 32, [])]))
        self.assert_warning_only(result)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["metrics"]["note_count"], 0)
        self.assertEqual(result["metrics"]["density"]["overall_nps"], 0.0)
        self.assertEqual(result["metrics"]["density"]["rolling_nps"], [])
        self.assertEqual(result["metrics"]["repetition"]["distinct_placements"], 0)
        self.assertEqual(result["metrics"]["movement_objects"]["arc_count"], 0)

    def test_beat_to_seconds_follows_tempo_events(self):
        data = arrangement([section("s", 0, 8, [])], bpm=120, offset=0.25)
        data["tempo_events"] = [{"beat": 4, "bpm": 240}]
        self.assertAlmostEqual(beat_to_seconds(0, data), 0.25)
        self.assertAlmostEqual(beat_to_seconds(4, data), 2.25)
        self.assertAlmostEqual(beat_to_seconds(8, data), 3.25)

    def test_movement_objects_count_arcs_chains_and_vocal_sustains(self):
        body = section("s", 0, 16, [note(0, 0, (1, 0, 0, 1))])
        body["arcs"] = [{"id": "a1", "beat": 0, "color": 0, "x": 1, "y": 0, "direction": 1,
                         "tail_beat": 2, "tail_x": 1, "tail_y": 2, "tail_direction": 0}]
        body["chains"] = [{"id": "c1", "beat": 4, "color": 1, "x": 2, "y": 0, "direction": 1,
                           "tail_beat": 5, "tail_x": 2, "tail_y": 1, "slice_count": 3}]
        report = self.report(8.0)
        report["layers"]["vocals"] = {"kind": "audio_layer", "events": [], "energy_contour": [],
                                      "sustains": [{"start_seconds": 0.1, "end_seconds": 1.4, "strength": 0.9},
                                                   {"start_seconds": 5.0, "end_seconds": 5.2, "strength": 0.8},
                                                   {"start_seconds": 6.0, "end_seconds": 7.5, "strength": 0.7}]}
        movement = critique_arrangement(arrangement([body]), report)["metrics"]["movement_objects"]
        self.assertEqual((movement["arc_count"], movement["chain_count"]), (1, 1))
        self.assertEqual(movement["arc_vertical_travel"], {"2": 1})
        self.assertEqual(movement["long_vocal_sustains"], 2)
        self.assertEqual(movement["sustains_covered_by_arcs"], 1)
        # A run without sustains simply omits the optional keys.
        plain = critique_arrangement(arrangement([body]))["metrics"]["movement_objects"]
        self.assertNotIn("long_vocal_sustains", plain)


class SalienceTests(unittest.TestCase):
    """Articulated singing leads; a strong drum pattern leads while the voice holds or rests."""

    def report(self):
        # 120 BPM, offset 0: beat b sits at b / 2 seconds. Bar 0-4 is sung, bar 4-8 is a held
        # vocal over an eighth-note drum pattern.
        flux = lambda layer, beat: {"id": f"{layer}:{beat}", "seconds": beat / 2,
                                    "method": "spectral_flux", "strength": 0.8}
        vocals = [flux("vocals", b) for b in (0, 1, 1.5, 2.5, 3)]
        drums = [flux("drums", b) for b in (4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5)]
        return {"layers": {"vocals": {"events": vocals,
                                      "sustains": [{"start_seconds": 0.0, "end_seconds": 4.0}]},
                           "drums": {"events": drums}}}

    def result(self, beats):
        notes = [note(i, b, (i % 4, 0, i % 2, 1)) for i, b in enumerate(beats)]
        return critique_arrangement(arrangement([section("s", 0, 8, notes)]), self.report())

    def test_notes_on_drums_under_singing_and_off_drums_under_a_hold_are_flagged(self):
        result = self.result([0.5, 2, 4.25, 6.25])
        self.assertEqual(codes(result) & {"vocal_line_unmapped", "drum_rhythm_unmapped"},
                         {"vocal_line_unmapped", "drum_rhythm_unmapped"})
        bars = result["metrics"]["salience"]["bars"]
        self.assertEqual([b["salient"] for b in bars], ["vocals", "drums"])
        for warning in result["warnings"]:
            self.assertIn(warning["code"], result["definitions"])

    def test_a_sung_sustain_held_by_an_arc_counts_as_mapped(self):
        # Held singing is authored as an arc (standing user rule): one hand holds the voice from beat 0 to 3.5
        # while the other plays off the vocal onsets. The arc maps the voice.
        notes = [note(0, 0, (1, 2, 0, 1)), note(1, 0.5, (2, 0, 1, 1)), note(2, 3.5, (0, 0, 0, 0))]
        body = section("s", 0, 8, notes)
        body["arcs"] = [{"id": "a1", "beat": 0, "color": 0, "x": 1, "y": 2, "direction": 1,
                         "tail_beat": 3.5, "tail_x": 0, "tail_y": 0, "tail_direction": 0}]
        result = critique_arrangement(arrangement([body]), self.report())
        self.assertNotIn("vocal_line_unmapped", codes(result))
        body["arcs"] = []
        result = critique_arrangement(arrangement([body]), self.report())
        self.assertIn("vocal_line_unmapped", codes(result), "without the arc the voice is unmapped")

    def test_following_the_salient_layer_passes(self):
        result = self.result([0, 1, 1.5, 2.5, 3, 4, 5, 5.5, 6, 7])
        self.assertFalse(codes(result) & {"vocal_line_unmapped", "drum_rhythm_unmapped"})

    def test_dense_sixteenth_drums_are_judged_per_half_beat_slot(self):
        report = self.report()
        report["layers"]["drums"]["events"] = [
            {"id": f"d{i}", "seconds": (4 + i / 4) / 2, "method": "spectral_flux",
             "strength": 0.9 if i % 2 == 0 else 0.4} for i in range(17)]
        notes = [note(i, b, (i % 4, 0, i % 2, 1)) for i, b in enumerate([0, 1, 1.5, 2.5, 3, 4, 5, 5.5, 6, 7])]
        result = critique_arrangement(arrangement([section("s", 0, 8, notes)]), report)
        self.assertNotIn("drum_rhythm_unmapped", codes(result))
        self.assertEqual(result["metrics"]["salience"]["bars"][1]["onsets"], 8)

    def test_without_vocal_and_drum_layers_the_check_is_skipped(self):
        result = critique_arrangement(arrangement([section("s", 0, 8, [note(0, 0, (0, 0, 0, 1))])]),
                                      {"layers": {"mix": {"events": []}}})
        self.assertFalse(result["metrics"]["salience"]["checked"])


class FocusStemTests(unittest.TestCase):
    """A focus weighted on a stem that is absent there follows separator bleed or a mislabeled instrument."""

    @staticmethod
    def contour(level_at):
        return [{"seconds": i / 10, "energy": level_at(i / 10)} for i in range(160)]

    def report(self):
        # 120 BPM: beats 0-16 are seconds 0-8. Vocals only sing from 8 s; bass always reads 100x drums.
        return {"layers": {
            "other": {"events": [], "energy_contour": self.contour(lambda t: 1.0)},
            "vocals": {"events": [], "energy_contour": self.contour(lambda t: 0.0005 if t < 8 else 1.0)},
            "bass": {"events": [], "energy_contour": self.contour(lambda t: 100.0)},
            "drums": {"events": [], "energy_contour": self.contour(lambda t: 1.0)}}}

    def critique(self, focus):
        body = section("s", 0, 32, [note(0, 0, (0, 0, 0, 1))])
        body["musical_focus"] = focus
        return critique_arrangement(arrangement([body]), self.report())

    def test_bleed_weighted_in_an_instrumental_intro_is_flagged(self):
        result = self.critique([{"id": "intro", "start_beat": 0, "end_beat": 16, "lead": "other",
                                 "weights": {"other": 0.6, "vocals": 0.4}, "intent": "fixture"}])
        flagged = [w for w in result["warnings"] if w["code"] == "focus_on_quiet_stem"]
        self.assertEqual(len(flagged), 1)
        self.assertIn("vocals", flagged[0]["message"])
        self.assertEqual(flagged[0]["beats"], [0.0, 16.0])
        self.assertLessEqual(flagged[0]["value"], -20)

    def test_active_stems_pass_even_beside_a_louder_stem(self):
        result = self.critique([{"id": "verse", "start_beat": 16, "end_beat": 32, "lead": "vocals",
                                 "weights": {"vocals": 0.7, "drums": 0.3}, "intent": "fixture"}])
        self.assertNotIn("focus_on_quiet_stem", codes(result))
        phrase = result["metrics"]["focus_stems"]["phrases"][0]
        self.assertEqual(phrase["db_vs_own_level"]["drums"], 0.0)


class CritiqueCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_main(self, argv):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(argv), 0)
        return json.loads(stream.getvalue())

    def test_standalone_and_project_commands_emit_metrics(self):
        created = ProjectStore(self.root).create(demo=True)
        project_id = created["project"]["id"]
        result = self.run_main(["project", "critique", project_id, "--workspace", str(self.root)])
        self.assertIn("metrics", result)
        self.assertEqual(result["revision"], created["revision"])
        self.assertIsNone(result["run_id"])
        self.assertTrue(all(w["severity"] == "warning" for w in result["warnings"]))
        path = self.root / "fixture.json"
        path.write_text(json.dumps(ProjectStore(self.root).get(project_id)["arrangement"]), encoding="utf-8")
        standalone = self.run_main(["critique", str(path)])
        self.assertEqual(standalone["metrics"], result["metrics"])
        output = self.root / "critique.json"
        self.assertEqual(main(["critique", str(path), "--output", str(output)]), 0)
        self.assertIn("definitions", json.loads(output.read_text(encoding="utf-8")))

    def test_project_critique_rejects_a_malformed_run_id(self):
        project_id = ProjectStore(self.root).create(demo=True)["project"]["id"]
        self.assertEqual(main(["project", "critique", project_id, "--workspace", str(self.root),
                               "--run", "not-a-run"]), 1)


if __name__ == "__main__":
    unittest.main()
