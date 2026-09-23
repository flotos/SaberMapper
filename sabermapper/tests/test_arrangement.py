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


def held_notes():
    """Head/tail color notes matching the shared arc and chain fixtures."""
    return [{"id": "arc-head", "beat": 1, "x": 1, "y": 0, "color": 0, "direction": 0},
            {"id": "arc-tail", "beat": 2, "x": 2, "y": 1, "color": 0, "direction": 1},
            {"id": "chain-head", "beat": 2, "x": 2, "y": 0, "color": 1, "direction": 1}]


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

    def test_repeated_cut_blocks_unless_the_hand_rests(self):
        # Borrowed Waters: a full beat is no reset. Each cut must start where the previous
        # one left the saber until the hand has idled REST_SECONDS (2 s = 4 beats at 120 BPM).
        source = arrangement()
        source["sections"][0]["length_beats"] = 8
        for beat, expected in (("7/16", ["fast_direction_break"]), ("1", ["flow_parity_break"]),
                               ("2", ["flow_parity_break"]), ("15/4", ["flow_parity_break"]), ("4", [])):
            trial = copy.deepcopy(source)
            trial["sections"][0]["notes"].append(
                {"id": "repeat", "beat": beat, "x": 0, "y": 1, "color": 0, "direction": 1})
            codes = [d["code"] for d in validate_arrangement(trial) if d["severity"] == "error"]
            self.assertEqual(codes, expected, beat)

    def test_rest_is_measured_in_seconds_not_beats(self):
        # Two beats is 0.67 s at 180 BPM (a break) but 2.4 s at 50 BPM (a rest).
        for bpm, expected in ((180, ["flow_parity_break"]), (50, [])):
            source = arrangement()
            source["song"]["bpm"] = bpm
            source["sections"][0]["notes"].append(
                {"id": "repeat", "beat": "2", "x": 0, "y": 1, "color": 0, "direction": 6})
            codes = [d["code"] for d in validate_arrangement(source) if d["severity"] == "error"]
            self.assertEqual(codes, expected, bpm)

    def test_placement_alternates_a_hand_that_never_rests(self):
        from sabermapper.placement import place_arrangement
        source = arrangement()
        source["song"]["bpm"] = 180
        source["sections"][0]["patterns"] = []
        source["sections"][0]["length_beats"] = 12
        # Cuts 0.67 s apart never rest the hand: the placer alternates every one of them.
        source["sections"][0]["notes"] = [{"id": f"l{i}", "beat": 2 * i, "x": 1, "y": 1, "color": 0} for i in range(6)]
        placed = place_arrangement(source)["arrangement"]
        self.assertFalse([d for d in validate_arrangement(placed) if d["severity"] == "error"])
        from sabermapper.movement import flow_break
        directions = [n["direction"] for n in placed["sections"][0]["notes"]]
        self.assertFalse([pair for pair in zip(directions, directions[1:]) if flow_break(*pair, 0, 0.67, False)],
                         directions)

    def test_fast_non_reversing_cut_is_blocking(self):
        # 1/4 beat at 120 BPM is 0.125 s: only a near-reversal (>=135 degrees) is allowed.
        for direction, blocked in ((1, True), (2, True), (3, True), (0, False), (4, False), (5, False)):
            source = arrangement()
            source["sections"][0]["notes"].append(
                {"id": "next", "beat": "1/4", "x": 1, "y": 1, "color": 0, "direction": direction})
            codes = [d["code"] for d in validate_arrangement(source) if d["severity"] == "error"]
            self.assertEqual(codes == ["fast_direction_break"], blocked, direction)
            if blocked:
                with self.assertRaises(ValueError):
                    compile_arrangement(source)
        # Player report: sideways then down at a half beat (0.24 s at 125 BPM) forces a wrist reset.
        # 1/2 beat at 120 BPM is 0.25 s; 3/4 beat is 0.375 s, where an alternating 90-degree turn flows.
        # A full beat is no reset: down then down-left still repeats the forehand.
        for beat, direction, expected in (("1/2", 2, ["fast_direction_break"]),
                                          ("3/4", 2, []),
                                          ("3/4", 6, ["flow_parity_break"]),
                                          ("1", 6, ["flow_parity_break"]),
                                          ("1", 5, [])):
            source = arrangement()
            source["sections"][0]["notes"].append(
                {"id": "next", "beat": beat, "x": 0, "y": 1, "color": 0, "direction": direction})
            codes = [d["code"] for d in validate_arrangement(source) if d["severity"] == "error"]
            self.assertEqual(codes, expected, (beat, direction))

    def test_dot_counts_as_reversal(self):
        source = arrangement()
        source["sections"][0]["notes"] += [
            {"id": "dot", "beat": "3/4", "x": 0, "y": 1, "color": 0, "direction": 8},
            {"id": "again", "beat": "3/2", "x": 0, "y": 0, "color": 0, "direction": 0}]
        codes = [d["code"] for d in validate_arrangement(source) if d["severity"] == "error"]
        self.assertEqual(codes, ["flow_parity_break"])

    def test_locked_flow_break_is_reported_not_blocking(self):
        source = arrangement()
        source["sections"][0]["locked"] = True
        source["sections"][0]["notes"].append(
            {"id": "next", "beat": "1/2", "x": 0, "y": 1, "color": 0, "direction": 2})
        finding = next(d for d in validate_arrangement(source) if d["code"] == "fast_direction_break")
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("locked", finding["message"])

    def check_clears(self, source, code):
        """Every blocking ``code`` finding in project check carries suggestions, and each one clears it."""
        from sabermapper.check import apply_suggestion, check_arrangement
        found = [f for f in check_arrangement(source)["findings"] if f["code"] == code and f["blocking"]]
        self.assertTrue(found)
        for finding in found:
            self.assertTrue(finding["suggestions"], finding)
            for suggestion in finding["suggestions"]:
                after = validate_arrangement(apply_suggestion(source, suggestion))
                self.assertFalse([d for d in after if d["code"] == code and d["object_ids"] == finding["object_ids"]],
                                 suggestion)
        return found

    def test_check_suggests_cuts_that_clear_a_pickup_break(self):
        source = arrangement()
        source["sections"][0]["notes"] += [{"id": "pickup", "beat": "7/4", "x": 2, "y": 0, "color": 1, "direction": 0},
                                           {"id": "entry", "beat": "2", "x": 2, "y": 1, "color": 1, "direction": 2},
                                           {"id": "cut-a", "beat": "3", "x": 1, "y": 1, "color": 0, "direction": 3},
                                           {"id": "cut-b", "beat": "13/4", "x": 1, "y": 0, "color": 0, "direction": 1}]
        self.check_clears(source, "fast_direction_break")

    def test_check_edits_the_note_after_an_arc_tail_not_the_anchor(self):
        # The Revival 1:03: arc tail cuts right into the corner, then down from the same cell a half beat later.
        source = arrangement()
        section = source["sections"][0]
        section["patterns"] = []
        section["notes"] = [{"id": "head", "beat": "1/2", "x": 2, "y": 2, "color": 1, "direction": 2},
                            {"id": "tail", "beat": "2", "x": 3, "y": 2, "color": 1, "direction": 3},
                            {"id": "down", "beat": "5/2", "x": 3, "y": 2, "color": 1, "direction": 1}]
        section["arcs"] = [{"id": "hold", "beat": "1/2", "x": 2, "y": 2, "color": 1, "direction": 2,
                            "tail_beat": "2", "tail_x": 3, "tail_y": 2, "tail_direction": 3}]
        [finding] = self.check_clears(source, "fast_direction_break")
        self.assertTrue(all(s["object_id"] == "verse/note/down" for s in finding["suggestions"]))

    def test_a_rhythm_only_note_after_an_arc_tail_is_placed_to_flow(self):
        from sabermapper.placement import place_arrangement
        source = arrangement()
        section = source["sections"][0]
        section["patterns"] = []
        section["notes"] = [{"id": "head", "beat": "1/2"}, {"id": "tail", "beat": "2"}, {"id": "down", "beat": "5/2"}]
        section["arcs"] = [{"id": "hold", "beat": "1/2", "x": 2, "y": 2, "color": 1, "direction": 2,
                            "tail_beat": "2", "tail_x": 3, "tail_y": 2, "tail_direction": 3}]
        placed = place_arrangement(source)["arrangement"]
        self.assertFalse([d for d in validate_arrangement(placed) if d["severity"] == "error"])

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
                            "direction": 0, "tail_beat": 2, "tail_x": 2, "tail_y": 1, "tail_direction": 1}]
        section["chains"] = [{"id": "chain", "beat": 2, "x": 2, "y": 0, "color": 1,
                              "direction": 1, "tail_beat": 3, "tail_x": 2, "tail_y": 1, "slice_count": 3}]
        section["notes"].extend(held_notes())
        self.assertFalse([d for d in validate_arrangement(source) if d["severity"] == "error"])
        result = compile_arrangement(source)
        self.assertEqual(result["colorNotes"][0]["x"], 2)
        self.assertEqual(result["colorNotes"][0]["c"], 1)
        self.assertEqual(result["colorNotes"][0]["b"], 8.0)  # offset is baked by ZIP export
        self.assertEqual(result["bpmEvents"], [{"b": 10.0, "m": 150}])
        self.assertEqual([len(result[k]) for k in ("bombNotes", "obstacles", "sliders", "burstSliders")], [1] * 4)

def held_saber(inner_beat="7/2", red=((1, 1, 1, 1), (6, 0, 1, 1)), tail=(7, 1)):
    """End of You 0:42: a blue arc held from beat 2 to 7 with a blue cut inside it.

    ``red`` lists (beat, x, y, direction) left-hand notes around the hold; ``tail`` is
    the arc's (beat, direction).
    """
    notes = [{"id": "head", "beat": 2, "x": 3, "y": 2, "color": 1, "direction": 1},
             {"id": "inner", "beat": inner_beat, "x": 2, "y": 1, "color": 1, "direction": 0},
             {"id": "tail", "beat": tail[0], "x": 2, "y": 0, "color": 1, "direction": tail[1]}]
    notes += [{"id": f"red{i}", "beat": beat, "x": x, "y": y, "color": 0, "direction": d}
              for i, (beat, x, y, d) in enumerate(red)]
    return {"schema_version": "0.1",
            "song": {"title": "Held", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": 16, "intent": "hold",
                                        "locked": False, "resolved": True, "patterns": [], "notes": notes,
                                        "arcs": [{"id": "hold", "beat": 2, "x": 3, "y": 2, "color": 1, "direction": 1,
                                                  "tail_beat": tail[0], "tail_x": 2, "tail_y": 0,
                                                  "tail_direction": tail[1]}]}]}


class HeldSaberConflictTests(unittest.TestCase):
    def diagnostics(self, source, code):
        return [d for d in validate_arrangement(source) if d["code"] == code]

    def test_same_color_note_inside_an_arc_blocks(self):
        source = held_saber()
        [finding] = self.diagnostics(source, "arc_note_conflict")
        self.assertEqual(finding["severity"], "error")
        self.assertEqual(finding["object_ids"], ["s/arcs/hold", "s/note/inner"])
        with self.assertRaises(ValueError):
            compile_arrangement(source)

    def test_other_hand_inside_and_same_hand_on_the_ends_are_allowed(self):
        source = held_saber()
        notes = source["sections"][0]["notes"]
        inner = next(n for n in notes if n["id"] == "inner")
        inner.update(color=0, x=1)
        notes.append({"id": "tail-chord", "beat": 7, "x": 3, "y": 0, "color": 1, "direction": 0})
        self.assertEqual(self.diagnostics(source, "arc_note_conflict"), [])

    def test_same_color_note_inside_a_chain_blocks(self):
        source = held_saber(inner_beat="5/2")
        section = source["sections"][0]
        section["arcs"] = []
        section["chains"] = [{"id": "burst", "beat": 2, "x": 3, "y": 2, "color": 1, "direction": 1,
                              "tail_beat": 3, "tail_x": 3, "tail_y": 0, "slice_count": 4}]
        self.assertEqual([d["severity"] for d in self.diagnostics(source, "chain_note_conflict")], ["error"])

    def test_locked_conflict_is_reported_not_blocking(self):
        source = held_saber()
        source["sections"][0]["locked"] = True
        [finding] = self.diagnostics(source, "arc_note_conflict")
        self.assertEqual(finding["severity"], "warning")

    def test_check_hands_the_inner_note_to_the_free_saber(self):
        from sabermapper.check import apply_suggestion, check_arrangement
        source = held_saber()
        [finding] = [f for f in check_arrangement(source)["findings"] if f["code"] == "arc_note_conflict"]
        self.assertEqual(finding["suggestions"][0]["to"]["color"], 0)
        fixed = apply_suggestion(source, finding["suggestions"][0])
        self.assertEqual(self.diagnostics(fixed, "arc_note_conflict"), [])

    def test_placement_keeps_an_unpinned_note_off_the_held_saber(self):
        from sabermapper.placement import place_arrangement
        source = held_saber()
        inner = next(n for n in source["sections"][0]["notes"] if n["id"] == "inner")
        for field in ("x", "y", "color", "direction"):
            del inner[field]
        placed = place_arrangement(source)["arrangement"]
        self.assertEqual(self.diagnostics(placed, "arc_note_conflict"), [])
        self.assertEqual(next(n for n in placed["sections"][0]["notes"] if n["id"] == "inner")["color"], 0)


class HeldObjectConnectionTests(unittest.TestCase):
    def source(self):
        source = arrangement()
        section = source["sections"][0]
        section["notes"].extend(held_notes())
        section["arcs"] = [{"id": "arc", "beat": 1, "x": 1, "y": 0, "color": 0,
                            "direction": 0, "tail_beat": 2, "tail_x": 2, "tail_y": 1, "tail_direction": 1}]
        section["chains"] = [{"id": "chain", "beat": 2, "x": 2, "y": 0, "color": 1,
                              "direction": 1, "tail_beat": 3, "tail_x": 2, "tail_y": 1, "slice_count": 3}]
        return source

    def codes(self, source):
        return {d["code"] for d in validate_arrangement(source) if d["severity"] == "error"}

    def test_connected_arc_and_chain_compile(self):
        source = self.source()
        self.assertFalse([d for d in validate_arrangement(source) if d["severity"] == "error"])
        result = compile_arrangement(source)
        self.assertEqual([len(result["sliders"]), len(result["burstSliders"])], [1, 1])

    def test_dangling_head_tail_and_chain_head_are_errors(self):
        for note_id, code in (("arc-head", "arc_head_without_note"),
                              ("arc-tail", "arc_tail_without_note"),
                              ("chain-head", "chain_head_without_note")):
            source = self.source()
            section = source["sections"][0]
            section["notes"] = [n for n in section["notes"] if n["id"] != note_id]
            with self.subTest(note_id=note_id):
                self.assertIn(code, self.codes(source))
                with self.assertRaises(ValueError):
                    compile_arrangement(source)

    def test_direction_mismatch_is_reported_per_end(self):
        for note_id, code in (("arc-head", "arc_head_direction_mismatch"),
                              ("arc-tail", "arc_tail_direction_mismatch"),
                              ("chain-head", "chain_head_direction_mismatch")):
            source = self.source()
            note = next(n for n in source["sections"][0]["notes"] if n["id"] == note_id)
            note["direction"] = 8
            with self.subTest(note_id=note_id):
                diagnostic = next(d for d in validate_arrangement(source) if d["code"] == code)
                self.assertEqual(len(diagnostic["object_ids"]), 2)

    def test_notes_with_errors_suppress_connection_checks(self):
        source = self.source()
        source["sections"][0]["notes"][0]["x"] = 9
        codes = self.codes(source)
        self.assertIn("invalid_note", codes)
        self.assertFalse({c for c in codes if c.startswith(("arc_", "chain_"))})


if __name__ == "__main__":
    unittest.main()


class ExampleArrangementTests(unittest.TestCase):
    def test_shipped_examples_pass_validation(self):
        # docs/experiment-workflow.md validates and compiles these; a rule change must update them too.
        import json
        from pathlib import Path
        examples = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*arrangement*.json"))
        self.assertTrue(examples)
        for path in examples:
            with self.subTest(path.name):
                source = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual([d["code"] for d in validate_arrangement(source) if d["severity"] == "error"], [])
