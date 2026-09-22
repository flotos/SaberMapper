import copy
import unittest

from sabermapper import compile_arrangement, validate_arrangement


def arrangement():
    return {
        "schema_version": "0.1",
        "song": {"title": "Pilot", "artist": "Mapper", "bpm": 120, "audio_offset_seconds": 0},
        "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
        "motifs": {"opening": [{"id": "left", "beat": "0", "x": 1, "y": 0, "color": 0, "direction": 1}]},
        "sections": [{"id": "verse", "start_beat": 8, "length_beats": 4, "intent": "opening pulse",
                      "locked": False, "resolved": True,
                      "notes": [{"id": "right", "beat": "1/2", "x": 2, "y": 1, "color": 1, "direction": 0}],
                      "patterns": [{"id": "opening-a", "motif": "opening", "start_beat": 0}]}],
    }


class ArrangementTests(unittest.TestCase):
    def test_deterministic_motif_and_literal_expansion(self):
        source = arrangement()
        first = compile_arrangement(source)
        self.assertEqual(first, compile_arrangement(copy.deepcopy(source)))
        self.assertEqual(first["version"], "3.3.0")
        self.assertEqual(first["colorNotes"], [
            {"b": 8.0, "x": 1, "y": 0, "c": 0, "d": 1, "a": 0},
            {"b": 8.5, "x": 2, "y": 1, "c": 1, "d": 0, "a": 0}])

    def test_overlap_between_literal_and_motif_is_hard_failure(self):
        source = arrangement()
        source["sections"][0]["notes"][0].update(beat=0, x=1, y=0)
        diagnostics = validate_arrangement(source)
        collision = next(d for d in diagnostics if d["code"] == "overlapping_cell")
        self.assertEqual(len(collision["object_ids"]), 2)
        with self.assertRaises(ValueError):
            compile_arrangement(source)

    def test_unsupported_object_and_unresolved_section_rejected(self):
        source = arrangement()
        source["sections"][0]["unsupported_objects"] = []
        source["sections"][0]["resolved"] = False
        codes = {d["code"] for d in validate_arrangement(source)}
        self.assertIn("unsupported_field", codes)
        self.assertIn("unresolved_section", codes)

    def test_rapid_repeated_cut_is_warning_only(self):
        source = arrangement()
        source["sections"][0]["notes"].append(
            {"id": "repeat", "beat": "1/4", "x": 0, "y": 1, "color": 0, "direction": 1})
        warnings = [d for d in validate_arrangement(source) if d["severity"] == "warning"]
        self.assertEqual([d["code"] for d in warnings], ["rapid_repeat_cut"])
        self.assertEqual(len(compile_arrangement(source)["colorNotes"]), 3)

    def test_malformed_nested_json_returns_diagnostics(self):
        cases = []
        source = arrangement()
        source["motifs"]["opening"][0]["id"] = ["bad"]
        cases.append(source)
        source = arrangement()
        source["sections"][0]["id"] = ["bad"]
        cases.append(source)
        source = arrangement()
        source["sections"][0]["notes"][0]["id"] = {"bad": True}
        cases.append(source)
        source = arrangement()
        source["sections"][0]["patterns"][0]["id"] = ["bad"]
        cases.append(source)
        source = arrangement()
        source["sections"][0]["notes"][0]["beat"] = "1e10000"
        cases.append(source)
        source = arrangement()
        source["sections"][0]["id"] = "bad/id"
        cases.append(source)
        for source in cases:
            with self.subTest(source=source):
                diagnostics = validate_arrangement(source)
                self.assertTrue(any(d["severity"] == "error" for d in diagnostics))
                with self.assertRaises(ValueError):
                    compile_arrangement(source)

    def test_extreme_numeric_values_return_diagnostics(self):
        for field in ("bpm",):
            source = arrangement()
            source["song"][field] = 10 ** 400
            self.assertIn("invalid_bpm", {d["code"] for d in validate_arrangement(source)})
        for field, code in (("njs", "invalid_njs"), ("spawn_offset_beats", "invalid_spawn_offset")):
            source = arrangement()
            source["difficulty"][field] = 10 ** 400
            self.assertIn(code, {d["code"] for d in validate_arrangement(source)})
        source = arrangement()
        source["sections"][0]["start_beat"] = "1e308"
        source["sections"][0]["notes"][0]["beat"] = "1e308"
        self.assertIn("unexportable_beat", {d["code"] for d in validate_arrangement(source)})
        with self.assertRaises(ValueError):
            compile_arrangement(source)

    def test_optional_objects_tempo_mirror_and_difficulty(self):
        source = arrangement()
        source["difficulty"] = {"name": "Hard", "rank": 5, "njs": 14, "spawn_offset_beats": 0}
        source["song"]["audio_offset_seconds"] = 0.25
        source["tempo_events"] = [{"beat": 10, "bpm": 150}]
        section = source["sections"][0]
        section["patterns"][0]["mirror"] = True
        section["bombs"] = [{"id": "bomb", "beat": 1, "x": 0, "y": 0}]
        section["obstacles"] = [{"id": "wall", "beat": 1, "duration_beats": 1,
                                 "x": 0, "y": 0, "width": 1, "height": 5}]
        section["arcs"] = [{"id": "arc", "beat": 1, "x": 1, "y": 0, "color": 0,
                            "direction": 1, "tail_beat": 2, "tail_x": 2, "tail_y": 1, "tail_direction": 0}]
        section["chains"] = [{"id": "chain", "beat": 2, "x": 2, "y": 0, "color": 1,
                              "direction": 1, "tail_beat": 3, "tail_x": 2, "tail_y": 1, "slice_count": 3}]
        self.assertFalse([d for d in validate_arrangement(source) if d["severity"] == "error"])
        result = compile_arrangement(source)
        self.assertEqual(result["colorNotes"][0]["x"], 2)
        self.assertEqual(result["colorNotes"][0]["c"], 1)
        self.assertEqual(result["colorNotes"][0]["b"], 8.0)  # offset is baked by ZIP export
        self.assertEqual(result["bpmEvents"], [{"b": 10.0, "m": 150}])
        self.assertEqual([len(result[k]) for k in ("bombNotes", "obstacles", "sliders", "burstSliders")], [1] * 4)


if __name__ == "__main__":
    unittest.main()
