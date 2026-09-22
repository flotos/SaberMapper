import unittest

from sabermapper.mapio import parse_map
from sabermapper.movement import analyze_movement
from sabermapper import compile_arrangement


class MapIOTests(unittest.TestCase):
    def test_v3_tempo_boundary_and_gameplay_objects(self):
        data = {"version": "3.3.0", "bpmEvents": [{"b": 4, "m": 60}],
                "colorNotes": [{"b": 4, "x": 1, "y": 1, "c": 0, "d": 0, "a": 15}],
                "bombNotes": [{"b": 5, "x": 2, "y": 0}],
                "obstacles": [{"b": 3, "d": 2, "x": 0, "y": 0, "w": 1, "h": 5}],
                "sliders": [{"c": 0, "b": 4, "x": 1, "y": 1, "d": 0, "mu": 1,
                             "tb": 5, "tx": 1, "ty": 2, "tc": 1, "tmu": 1, "m": 0}],
                "burstSliders": [{"c": 1, "b": 5, "x": 2, "y": 0, "d": 1,
                                  "tb": 5.5, "tx": 2, "ty": 1, "sc": 3, "s": 0.5}]}
        parsed = parse_map(data, bpm=120, provenance={"map": "fixture"})
        self.assertEqual(parsed["notes"][0]["seconds"], 2)
        self.assertEqual(parsed["bombs"][0]["seconds"], 3)
        self.assertEqual(parsed["obstacles"][0]["end_seconds"], 3)
        self.assertEqual([len(parsed[k]) for k in ("notes", "bombs", "obstacles", "arcs", "chains")], [1] * 5)
        self.assertEqual(parsed["source"], {"map": "fixture"})

    def test_v2_native_tempo_and_custom_data_are_loss_aware(self):
        data = {"_version": "2.6.0", "_notes": [
            {"_time": 2, "_lineIndex": 1, "_lineLayer": 0, "_type": 0, "_cutDirection": 1},
            {"_time": 2, "_lineIndex": 2, "_lineLayer": 1, "_type": 3, "_cutDirection": 0}],
            "_events": [{"_time": 1, "_type": 100, "_floatValue": 60}],
            "_customData": {"_BPMChanges": [{"_time": 1, "_BPM": 200}]}}
        parsed = parse_map(data, bpm=120, audio_offset_seconds=0.25)
        self.assertEqual(parsed["notes"][0]["seconds"], 1.75)
        self.assertEqual(parsed["bombs"][0]["seconds"], 1.75)
        self.assertTrue(any(row["path"] == "_customData" for row in parsed["unsupported"]))

    def test_v4_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            parse_map({"version": "4.0.0"})

    def test_v2_arc_normalized_and_unknown_chain_preserved(self):
        data = {"_version": "2.6.0", "_sliders": [{
            "_colorType": 1, "_headTime": 1, "_headLineIndex": 1, "_headLineLayer": 0,
            "_headCutDirection": 1, "_headControlPointLengthMultiplier": 1,
            "_tailTime": 2, "_tailLineIndex": 2, "_tailLineLayer": 2,
            "_tailCutDirection": 0, "_tailControlPointLengthMultiplier": 1,
            "_sliderMidAnchorMode": 0}], "_burstSliders": [{"unknown": 1}]}
        result = parse_map(data)
        self.assertEqual(result["arcs"][0]["tail_seconds"], 1)
        self.assertTrue(any(row["path"] == "_burstSliders[0]" for row in result["unsupported"]))

    def test_authored_objects_semantic_roundtrip(self):
        from test_arrangement import arrangement, held_notes
        source = arrangement()
        section = source["sections"][0]
        section["obstacles"] = [{"id": "wall", "beat": 1, "duration_beats": 1,
                                 "x": 0, "y": 0, "width": 1, "height": 5}]
        section["arcs"] = [{"id": "arc", "beat": 1, "x": 1, "y": 0, "color": 0,
                            "direction": 1, "tail_beat": 2, "tail_x": 2, "tail_y": 1, "tail_direction": 0}]
        section["chains"] = [{"id": "chain", "beat": 2, "x": 2, "y": 0, "color": 1,
                              "direction": 1, "tail_beat": 3, "tail_x": 2, "tail_y": 1, "slice_count": 3}]
        section["notes"].extend(held_notes())
        source["tempo_events"] = [{"beat": 9, "bpm": 60}]
        native = compile_arrangement(source)
        parsed = parse_map(native, bpm=120)
        self.assertEqual([len(parsed[key]) for key in ("notes", "obstacles", "arcs", "chains")], [5, 1, 1, 1])
        self.assertEqual(parsed["notes"][1]["seconds"], 4.25)
        self.assertEqual(parsed["obstacles"][0]["end_seconds"], 5.5)
        self.assertEqual(parsed["arcs"][0]["tail_beat"], 10.0)

    def test_real_corpus_edge_objects_are_loss_aware(self):
        data = {"version": "3.3.0", "colorNotes": [
            {"b": 4, "x": 2, "c": 1, "d": 1},
            {"b": 5, "x": 2, "y": 1, "c": 1, "d": 1}],
            "obstacles": [{"b": 9, "x": -1, "y": 0, "d": 0.048, "w": 1, "h": 1},
                          {"b": 10, "x": 8, "y": 2, "d": 0.25, "w": 1, "h": 3}],
            "sliders": [{"b": 86, "c": 0, "x": 1, "y": 0, "d": 0, "mu": 1,
                         "tb": 86, "tx": 1, "ty": 1, "tc": 0, "tmu": 1, "m": 0},
                        {"b": 87, "c": 0, "x": 1, "y": 0, "d": 0, "mu": 0,
                         "tb": 87.25, "tx": 1, "ty": 1, "tc": 0, "tmu": -0.1, "m": 0},
                        {"b": 88, "c": 0, "x": 1, "d": 1, "mu": 1,
                         "tb": 89, "tc": 4, "tmu": 1}],
            "bombNotes": [{"b": 67.25}]}
        result = parse_map(data)
        self.assertEqual([w["x"] for w in result["obstacles"]], [-1, 8])
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(len(result["arcs"]), 1)
        self.assertEqual(result["arcs"][0]["tail_multiplier"], -0.1)
        self.assertTrue({"colorNotes[0]", "sliders[0]", "sliders[2]", "bombNotes[0]"} <=
                        {item["path"] for item in result["unsupported"]})
        legacy = parse_map({"_version": "2.6.0", "_obstacles": [{
            "_time": 0, "_lineIndex": 0, "_type": 0, "_duration": 0, "_width": 0}]})
        self.assertEqual(len(legacy["obstacles"]), 0)
        self.assertEqual(legacy["unsupported"][0]["path"], "_obstacles[0]")


class MovementTests(unittest.TestCase):
    def test_group_reset_and_ambiguous_dot(self):
        notes = [{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                 {"id": "b", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1},
                 {"id": "c", "beat": 2, "x": 2, "y": 1, "color": 0, "direction": 8}]
        result = analyze_movement(notes)
        self.assertEqual(result["model_version"], "1.3")
        self.assertEqual(len(result["swings"]), 2)
        self.assertEqual(result["swings"][0]["note_ids"], ["a", "b"])
        self.assertTrue(result["swings"][1]["reset"])
        self.assertEqual(result["swings"][1]["parity"], "ambiguous")

    def test_late_window_native_seconds_and_proxies(self):
        notes = [{"id": "a", "beat": 100, "seconds": 50, "x": 0, "y": 0, "color": 0, "direction": 1},
                 {"id": "b", "beat": 101, "seconds": 51, "x": 3, "y": 1, "color": 0, "direction": 0},
                 {"id": "c", "beat": 101.5, "seconds": 51.25, "x": 0, "y": 0, "color": 1, "direction": 3}]
        result = analyze_movement(notes, bpm=120, njs=16, spawn_offset_beats=-0.5)
        self.assertEqual(result["timing_source"], "note_seconds")
        self.assertAlmostEqual(result["metrics"]["swing_rate_per_second"], 2 / 1.25)
        self.assertEqual(result["metrics"]["crossover_demand_count"], 2)
        self.assertEqual(result["metrics"]["mean_angular_change_degrees"], 180)
        self.assertAlmostEqual(result["metrics"]["reaction_time_proxy_seconds"], 0.75)
        self.assertEqual(result["swings"][0]["exit_state"], "forehand")
        self.assertEqual(result["swings"][1]["entry_state"], "unconstrained")

    def test_incompatible_same_hand_chord_is_reported(self):
        notes = [{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                 {"id": "b", "beat": 0, "x": 1, "y": 1, "color": 0, "direction": 0}]
        result = analyze_movement(notes)
        self.assertEqual(len(result["swings"]), 2)
        self.assertIn("simultaneous_direction_conflict", [w["code"] for w in result["warnings"]])


if __name__ == "__main__":
    unittest.main()
