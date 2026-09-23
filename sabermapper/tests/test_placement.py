"""SM-036: maps built correct by construction, and one read-only check that save shares."""
import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from fractions import Fraction
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.arrangement import compile_arrangement, expanded_notes
from sabermapper.audio import _hash
from sabermapper.check import apply_suggestion, check_arrangement
from sabermapper.placement import PlacementError, pin_edits, place_arrangement
from sabermapper.projects import ProjectStore
from sabermapper.validation import validate_arrangement

BLOCKING_MOVEMENT = ("fast_direction_break", "flow_parity_break", "hidden_note", "arc_note_conflict",
                     "chain_note_conflict")


def arrangement(notes, *, bpm=120, length=64, arcs=(), chains=()):
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": bpm, "audio_offset_seconds": 0},
            "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {},
            "sections": [{"id": "a", "start_beat": 0, "length_beats": length, "intent": "fixture", "locked": False,
                          "resolved": True, "notes": [dict(n) for n in notes], "patterns": [],
                          "arcs": [dict(a) for a in arcs], "chains": [dict(c) for c in chains]}]}


def rhythm(beats, **pins):
    """Notes that carry only an ID and a beat (plus any fields in ``pins``)."""
    return [{"id": f"n{i:03d}", "beat": beat, **pins} for i, beat in enumerate(beats)]


def codes(arrangement_):
    """Movement codes the validator reports (errors and the one_hand_burst / reach warnings)."""
    return {d["code"] for d in validate_arrangement(arrangement_)
            if d["code"] in BLOCKING_MOVEMENT + ("one_hand_burst", "reach_proxy")}


def notes_by_id(arrangement_):
    return {n["id"]: n for n in arrangement_["sections"][0]["notes"]}


class NaiveRhythmIsPlacedCleanlyTests(unittest.TestCase):
    """For each movement rule: a rhythm a naive placement (one hand, one cut, one cell) breaks is placed cleanly."""

    def assert_clean(self, draft):
        placed = place_arrangement(draft)["arrangement"]
        self.assertEqual([d for d in validate_arrangement(placed) if d["severity"] == "error"], [])
        self.assertEqual(codes(placed), set())
        compile_arrangement(draft)  # the draft compiles as written: placement happens inside
        return placed

    def naive(self, draft):
        for note in draft["sections"][0]["notes"]:
            note.update(x=1, y=1, color=0, direction=1)
        return draft

    def test_fast_eighths_alternate_and_reverse(self):
        draft = arrangement(rhythm([i / 2 for i in range(32)]), bpm=150)  # 0.2 s apart
        self.assertIn("fast_direction_break", codes(self.naive(copy.deepcopy(draft))))
        self.assert_clean(draft)

    def test_dotted_rhythm_keeps_parity(self):
        draft = arrangement(rhythm([i * 0.75 for i in range(24)]), bpm=100)  # 0.45 s apart
        self.assertIn("flow_parity_break", codes(self.naive(copy.deepcopy(draft))))
        self.assert_clean(draft)

    def test_sixteenths_never_hide_behind_each_other(self):
        draft = arrangement(rhythm([i / 4 for i in range(48)]), bpm=120)  # 0.125 s apart
        self.assertIn("hidden_note", codes(self.naive(copy.deepcopy(draft))))
        placed = self.assert_clean(draft)
        colors = [n["color"] for n in expanded_notes(placed)]
        self.assertTrue(all(a != b for a, b in zip(colors, colors[1:])), "fast notes alternate hands")

    def test_notes_inside_an_arc_go_to_the_free_hand(self):
        arc = {"id": "hold", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1, "tail_beat": 4, "tail_x": 1,
               "tail_y": 1, "tail_direction": 0}
        draft = arrangement(rhythm([0, 1, 2, 3, 4, 5]), arcs=[arc])
        placed = self.assert_clean(draft)
        by_beat = {float(n["beat"]): n for n in expanded_notes(placed)}
        self.assertEqual([by_beat[b]["color"] for b in (1, 2, 3)], [1, 1, 1])
        self.assertEqual((by_beat[0]["x"], by_beat[0]["y"], by_beat[0]["color"], by_beat[0]["direction"]),
                         (1, 0, 0, 1), "the arc head's note takes the arc's hand, cut and cell")
        self.assertEqual((by_beat[4]["x"], by_beat[4]["y"], by_beat[4]["direction"]), (1, 1, 0))
        self.assertEqual(notes_by_id(placed)["n000"]["placed"], ["x", "y", "color", "direction"])

    def test_notes_inside_a_chain_go_to_the_free_hand(self):
        chain = {"id": "run", "beat": 0, "x": 2, "y": 0, "color": 1, "direction": 1, "tail_beat": 2, "tail_x": 2,
                 "tail_y": 2, "slice_count": 4}
        draft = arrangement(rhythm([0, 0.5, 1, 1.5, 3]), chains=[chain])
        placed = self.assert_clean(draft)
        inside = [n for n in expanded_notes(placed) if 0 < n["beat"] < 2]
        self.assertEqual({n["color"] for n in inside}, {0})

    def test_fast_single_line_never_streams_on_one_hand(self):
        draft = arrangement(rhythm([i / 4 for i in range(24)]), bpm=150)  # 0.1 s apart
        naive = self.naive(copy.deepcopy(draft))
        for index, note in enumerate(naive["sections"][0]["notes"]):
            note.update(x=index % 2, y=index % 3 // 2, direction=(1, 0)[index % 2])
        self.assertIn("one_hand_burst", codes(naive))
        self.assert_clean(draft)

    def test_a_whole_song_rhythm_places_without_findings(self):
        beats = sorted({i / 2 for i in range(0, 128)} | {i + 0.75 for i in range(40, 60)} | {i / 4 for i in range(200, 240)})
        placed = self.assert_clean(arrangement(rhythm(beats), bpm=128, length=128))
        placements = {(n["x"], n["y"], n["color"], n["direction"]) for n in expanded_notes(placed)}
        self.assertGreaterEqual(len(placements), 30, "the placer varies its placements")


class PinnedConflictTests(unittest.TestCase):
    """A pinned choice that breaks a rule is an infeasibility error naming the beat, notes, rule and alternatives."""

    def infeasible(self, draft, rule):
        with self.assertRaises(PlacementError) as caught:
            place_arrangement(draft)
        errors = [e for e in caught.exception.errors if e["rule"] == rule]
        self.assertTrue(errors, [e["rule"] for e in caught.exception.errors])
        error = errors[0]
        self.assertEqual(error["code"], "placement_infeasible")
        self.assertIsInstance(error["beat"], float)
        self.assertGreaterEqual(len(error["object_ids"]), 1)
        self.assertTrue(error["alternatives"], "at least one feasible alternative")
        self.assertIn(rule, error["message"])
        for alternative in error["alternatives"]:  # every listed alternative really places cleanly there
            fixed = apply_suggestion(draft, alternative)
            result = place_arrangement(fixed, strict=False)
            self.assertFalse([e for e in result["errors"] if set(e["object_ids"]) & set(error["object_ids"])
                              and e["rule"] == rule], alternative)
        return error

    def test_a_pinned_cut_that_breaks_fast_flow(self):
        draft = arrangement(rhythm([0, 0.5], color=0, direction=1))  # red down twice, 0.25 s apart
        error = self.infeasible(draft, "fast_direction_break")
        self.assertEqual(error["beat"], 0.5)
        self.assertIn({"op": "unpin", "object_id": "a/note/n001", "fields": ["direction"],
                       "placer_choice": {"direction": 0}}, error["alternatives"])

    def test_a_pinned_cut_that_breaks_parity(self):
        self.infeasible(arrangement(rhythm([0, 0.75], color=0, direction=1), bpm=100), "flow_parity_break")

    def test_a_pinned_cell_right_behind_another(self):
        error = self.infeasible(arrangement(rhythm([0, 0.25], x=1, y=1)), "hidden_note")
        self.assertTrue(any(a["op"] == "unpin" and a["fields"] == ["x", "y"] for a in error["alternatives"]))

    def test_a_pinned_hand_inside_its_own_arc(self):
        arc = {"id": "hold", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1, "tail_beat": 4, "tail_x": 1,
               "tail_y": 1, "tail_direction": 0}
        notes = rhythm([0, 4]) + [{"id": "inside", "beat": 2, "color": 0}]
        error = self.infeasible(arrangement(notes, arcs=[arc]), "arc_note_conflict")
        self.assertIn("a/note/inside", error["object_ids"])

    def test_a_pinned_hand_inside_its_own_chain(self):
        chain = {"id": "run", "beat": 0, "x": 2, "y": 0, "color": 1, "direction": 1, "tail_beat": 2, "tail_x": 2,
                 "tail_y": 2, "slice_count": 4}
        notes = rhythm([0]) + [{"id": "inside", "beat": 1, "color": 1}]
        self.infeasible(arrangement(notes, chains=[chain]), "chain_note_conflict")

    def test_three_fast_sounds_while_the_other_hand_holds(self):
        arc = {"id": "hold", "beat": 0, "x": 2, "y": 0, "color": 1, "direction": 1, "tail_beat": 8, "tail_x": 2,
               "tail_y": 1, "tail_direction": 0}
        notes = rhythm([0, 8]) + [{"id": f"f{i}", "beat": 2 + i / 4} for i in range(3)]
        error = self.infeasible(arrangement(notes, arcs=[arc], bpm=150), "one_hand_burst")
        self.assertTrue(any(a["op"] == "remove" for a in error["alternatives"]))

    def test_conflicts_between_fully_pinned_notes_are_left_to_validation(self):
        notes = [{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                 {"id": "b", "beat": 0.5, "x": 1, "y": 0, "color": 0, "direction": 1}]
        draft = arrangement(notes)
        self.assertIs(place_arrangement(draft)["arrangement"], draft)
        self.assertIn("fast_direction_break", codes(draft))


class PinsLocalityAndDeterminismTests(unittest.TestCase):
    BEATS = [i / 2 for i in range(64)]

    def test_pinned_fields_never_change(self):
        notes = rhythm(self.BEATS)
        for index, note in enumerate(notes):
            if index % 5 == 0:
                note["color"] = index // 5 % 2
            if index % 7 == 0:
                note["y"] = 2
            if index % 11 == 0:
                note.update(x=0 if index % 2 == 0 else 3, color=0 if index % 2 == 0 else 1)
        placed = notes_by_id(place_arrangement(arrangement(notes))["arrangement"])
        for note in notes:
            result = placed[note["id"]]
            for field in ("x", "y", "color", "direction"):
                if field in note:
                    self.assertEqual(result[field], note[field], (note["id"], field))
                    self.assertNotIn(field, result["placed"])
                else:
                    self.assertIn(field, result["placed"])

    def test_placement_is_deterministic_and_ignores_note_order(self):
        first = place_arrangement(arrangement(rhythm(self.BEATS)))["arrangement"]
        again = place_arrangement(arrangement(rhythm(self.BEATS)))["arrangement"]
        shuffled = arrangement(list(reversed(rhythm(self.BEATS))))
        third = place_arrangement(shuffled)["arrangement"]
        self.assertEqual(first, again)
        self.assertEqual(notes_by_id(first), notes_by_id(third))

    def test_a_stored_placement_is_a_fixed_point(self):
        placed = place_arrangement(arrangement(rhythm(self.BEATS)))["arrangement"]
        self.assertEqual(place_arrangement(placed)["arrangement"], placed)
        self.assertEqual(compile_arrangement(placed), compile_arrangement(arrangement(rhythm(self.BEATS))))

    def test_a_rhythm_edit_in_one_bar_leaves_the_rest_alone(self):
        beats = [b for b in self.BEATS if not 16 <= b < 20]  # bar 5 rests
        placed = place_arrangement(arrangement(rhythm(beats)))["arrangement"]
        edited = copy.deepcopy(placed)
        edited["sections"][0]["notes"] += [{"id": "new1", "beat": 17}, {"id": "new2", "beat": 18}]
        replaced = place_arrangement(edited)["arrangement"]
        before, after = notes_by_id(placed), notes_by_id(replaced)
        for note_id, note in before.items():
            self.assertEqual(after[note_id], note, note_id)
        self.assertEqual(codes(replaced), set())
        self.assertEqual(place_arrangement(edited)["report"]["rechosen"], [])

    def test_retiming_a_note_rechooses_only_what_breaks(self):
        placed = place_arrangement(arrangement(rhythm(self.BEATS)))["arrangement"]
        edited = copy.deepcopy(placed)
        edited["sections"][0]["notes"][10]["beat"] = 5.25  # between 5 and 5.5, where it now crowds its neighbours
        result = place_arrangement(edited)
        after = notes_by_id(result["arrangement"])
        self.assertEqual(codes(result["arrangement"]), set())
        unchanged = [i for i, n in notes_by_id(placed).items() if after[i] == {**n, "beat": after[i]["beat"]}]
        self.assertGreaterEqual(len(unchanged), len(self.BEATS) - 8, result["report"]["rechosen"])

    def test_editing_a_placed_value_pins_it(self):
        placed = place_arrangement(arrangement(rhythm(self.BEATS)))["arrangement"]
        edited = copy.deepcopy(placed)
        note = edited["sections"][0]["notes"][20]
        note["y"] = 2 if note["y"] != 2 else 0
        pinned = pin_edits(placed, edited)["sections"][0]["notes"][20]
        self.assertNotIn("y", pinned["placed"])
        self.assertIn("x", pinned["placed"])

    def test_fully_specified_arrangements_compile_unchanged(self):
        notes = [{"id": f"n{i}", "beat": i, "x": i % 2 * 3, "y": 0, "color": i % 2, "direction": 1} for i in range(8)]
        draft = arrangement(notes)
        self.assertIs(place_arrangement(draft)["arrangement"], draft)
        self.assertEqual([n["b"] for n in compile_arrangement(draft)["colorNotes"]], list(map(float, range(8))))

    def test_motifs_are_placed_once(self):
        draft = arrangement([])
        draft["motifs"]["figure"] = rhythm([0, 0.5, 1, 1.5])
        draft["sections"][0]["patterns"] = [{"id": "p1", "motif": "figure", "start_beat": 0},
                                            {"id": "p2", "motif": "figure", "start_beat": 4, "mirror": True}]
        placed = place_arrangement(draft)
        self.assertEqual(placed["report"]["motifs"], ["figure"])
        motif = placed["arrangement"]["motifs"]["figure"]
        self.assertTrue(all(set(n) >= {"x", "y", "color", "direction"} for n in motif))
        self.assertEqual(codes(placed["arrangement"]), set())


class CheckAndSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        created = self.store.create(demo=True)
        self.project_id, self.revision = created["project"]["id"], created["revision"]
        self.arrangement = created["arrangement"]
        self.directory = self.store.directory(self.project_id)

    def snapshot(self):
        return {str(p.relative_to(self.directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.directory.rglob("*")) if p.is_file()}

    def rhythm_only(self):
        draft = copy.deepcopy(self.arrangement)
        for section in draft["sections"]:
            for note in section["notes"]:
                for field in ("x", "y", "color", "direction"):
                    note.pop(field, None)
        return draft

    def test_check_writes_nothing(self):
        before = self.snapshot()
        self.store.check(self.project_id)
        self.store.check(self.project_id, arrangement=self.rhythm_only(), metrics=True)
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["project", "check", self.project_id, "--workspace", self.temp.name]), 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["revision"], self.revision)
        self.assertEqual(self.snapshot(), before)

    def test_a_rhythm_only_draft_saves_placed_with_its_pins_recorded(self):
        draft = self.rhythm_only()
        check = self.store.check(self.project_id, arrangement=draft)
        self.assertEqual(check["blocking_count"], 0)
        saved = self.store.save(self.project_id, draft, self.revision)
        self.assertGreater(saved["placement"]["placed_notes"], 0)
        stored = [n for s in saved["arrangement"]["sections"] for n in s["notes"]]
        self.assertTrue(all(n["placed"] == ["x", "y", "color", "direction"] for n in stored))
        self.assertEqual([d for d in saved["diagnostics"] if d["severity"] == "error"], [])

    def test_save_refuses_exactly_what_check_marks_blocking(self):
        draft = copy.deepcopy(self.arrangement)
        section = next(s for s in draft["sections"] if s["notes"])
        first = section["notes"][0]
        section["notes"].append({"id": "behind", "beat": first["beat"], "x": first["x"], "y": first["y"],
                                 "color": first["color"], "direction": first["direction"]})
        check = self.store.check(self.project_id, arrangement=draft)
        blocking = [f for f in check["findings"] if f["blocking"]]
        self.assertEqual({f["code"] for f in blocking}, {"overlapping_cell"})
        with self.assertRaisesRegex(ValueError, "notes overlap"):
            self.store.save(self.project_id, draft, self.revision)
        fine = self.store.check(self.project_id, arrangement=self.rhythm_only())
        self.assertEqual(fine["blocking_count"], 0)
        self.store.save(self.project_id, self.rhythm_only(), self.revision)

    def test_audio_blocking_findings_match_the_save_gate(self):
        from tests.test_audio_grounding import report
        run = self.directory / "musical" / ("a" * 32)
        run.mkdir(parents=True)
        seconds = self.store.get(self.project_id)["project"]["duration_seconds"]
        (run / "report.json").write_text(json.dumps(report(seconds, sha256=_hash(self.directory / "song.ogg"))),
                                         encoding="utf-8")
        emptied = copy.deepcopy(self.arrangement)
        for section in emptied["sections"][:3]:
            section["notes"], section["patterns"] = [], []
        check = self.store.check(self.project_id, arrangement=emptied)
        self.assertEqual({f["code"] for f in check["findings"] if f["blocking"]}, {"audio_unmapped"})
        with self.assertRaisesRegex(ValueError, "Audio left unmapped"):
            self.store.save(self.project_id, emptied, self.revision)

    def test_placement_errors_block_save_with_alternatives(self):
        draft = self.rhythm_only()
        section = next(s for s in draft["sections"] if len(s["notes"]) >= 2)
        section["notes"][0].update(color=0, direction=1)
        clash = f'{Fraction(str(section["notes"][0]["beat"])) + Fraction(1, 4)}'
        section["notes"].insert(1, {"id": "clash", "beat": clash, "color": 0, "direction": 1})
        check = self.store.check(self.project_id, arrangement=draft)
        blocking = [f for f in check["findings"] if f["blocking"]]
        self.assertTrue(blocking)
        self.assertTrue(all(f["suggestions"] for f in blocking if f["source"] == "placement"))
        with self.assertRaises(ValueError):
            self.store.save(self.project_id, draft, self.revision)


class SuggestionTests(unittest.TestCase):
    CASES = {
        "fast_direction_break": ([{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                                  {"id": "b", "beat": 0.5, "x": 1, "y": 0, "color": 0, "direction": 1}], {}),
        "flow_parity_break": ([{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                               {"id": "b", "beat": 0.75, "x": 1, "y": 0, "color": 0, "direction": 6}], {"bpm": 100}),
        "hidden_note": ([{"id": "a", "beat": 0, "x": 1, "y": 1, "color": 0, "direction": 1},
                         {"id": "b", "beat": 0.25, "x": 1, "y": 1, "color": 1, "direction": 1}], {}),
        "arc_note_conflict": ([{"id": "h", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1},
                               {"id": "in", "beat": 2, "x": 0, "y": 1, "color": 0, "direction": 0},
                               {"id": "t", "beat": 4, "x": 1, "y": 1, "color": 0, "direction": 0}],
                              {"arcs": [{"id": "hold", "beat": 0, "x": 1, "y": 0, "color": 0, "direction": 1,
                                         "tail_beat": 4, "tail_x": 1, "tail_y": 1, "tail_direction": 0}]}),
        "chain_note_conflict": ([{"id": "h", "beat": 0, "x": 2, "y": 0, "color": 1, "direction": 1},
                                 {"id": "in", "beat": 1, "x": 3, "y": 1, "color": 1, "direction": 0}],
                                {"chains": [{"id": "run", "beat": 0, "x": 2, "y": 0, "color": 1, "direction": 1,
                                             "tail_beat": 2, "tail_x": 2, "tail_y": 2, "slice_count": 4}]}),
    }

    def test_every_blocking_movement_finding_has_a_suggestion_that_clears_it(self):
        for code, (notes, options) in self.CASES.items():
            with self.subTest(code=code):
                draft = arrangement(notes, **options)
                report = check_arrangement(draft)
                found = [f for f in report["findings"] if f["code"] == code]
                self.assertTrue(found and all(f["blocking"] for f in found), report["findings"])
                for finding in found:
                    self.assertTrue(finding["suggestions"], finding)
                    for suggestion in finding["suggestions"]:
                        fixed = apply_suggestion(draft, suggestion)
                        after = validate_arrangement(fixed)
                        self.assertFalse([d for d in after if d["code"] == code
                                          and d["object_ids"] == finding["object_ids"]], suggestion)
                        self.assertFalse([d for d in after if d["severity"] == "error"], (suggestion, after))


if __name__ == "__main__":
    unittest.main()
