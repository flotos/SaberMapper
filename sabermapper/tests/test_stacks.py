"""Unison hits become stacks: one hand cuts two or three notes in a line along the cut, one longer note."""
from fractions import Fraction
import unittest

from sabermapper.arrangement import expanded_notes
from sabermapper.check import apply_suggestion, check_arrangement
from sabermapper.critique import critique_arrangement
from sabermapper.movement import analyze_movement, stack_line
from sabermapper.placement import place_arrangement
from sabermapper.rhythm_proposal import TARGET_CODES, propose_rhythm
from sabermapper.validation import validate_arrangement

from test_placement import arrangement, rhythm
from test_rhythm_proposal import song, song_arrangement

# (beat, stems joining the drums): a riff bar's three band hits, one with four stems, and a hit under the held
# vocal arc of the verse (beats 56-59.4), where the free hand takes it.
HITS = ((24, ("bass", "guitar")), (25, ("bass", "guitar", "other")), (26, ("bass", "guitar")),
        (58, ("bass", "guitar")))


def unison_song():
    evidence = song()
    layers = evidence["layers"]
    for name in ("bass", "other"):
        layers.setdefault(name, {"events": []})
    for name in ("drums", "guitar", "vocals", "bass", "other"):
        layers[name]["kind"] = "audio_layer"  # separated stems
    for index, (beat, stems) in enumerate(HITS):
        layers["mix"]["events"].append({"id": f"mix:hit:{index}", "seconds": beat / 2, "method": "spectral_flux",
                                        "strength": 0.95})
        layers["drums"]["events"].append({"id": f"drums:hit:{index}", "seconds": beat / 2 + 0.01,
                                          "method": "spectral_flux", "strength": 0.9})
        for name in stems:
            layers[name]["events"].append({"id": f"{name}:hit:{index}", "seconds": beat / 2 - 0.02,
                                           "method": "spectral_flux", "strength": 0.7})
    return evidence


def stacks_of(placed):
    """{beat: notes} for every beat carrying notes marked ``stack``."""
    marked = {(s["id"], n["id"]) for s in placed["sections"] for n in s["notes"] if n.get("stack")}
    found = {}
    for note in expanded_notes(placed):
        section, _, nid = note["id"].split("/", 2)
        if (section, nid) in marked:
            found.setdefault(note["beat"], []).append(note)
    return found


class PlacementTests(unittest.TestCase):
    def test_a_stack_is_one_hand_one_cut_in_a_line_along_it(self):
        notes = rhythm([0, 1, 2, 2.5, 3, 5, 6.5, 7])
        notes += [{"id": f"a{i}", "beat": 4, "stack": True} for i in range(3)]
        notes += [{"id": f"b{i}", "beat": 6, "stack": True} for i in range(2)]
        placed = place_arrangement(arrangement(notes))["arrangement"]
        stacks = stacks_of(placed)
        self.assertEqual(sorted(len(v) for v in stacks.values()), [2, 3])
        for beat, stack in stacks.items():
            self.assertEqual(len({n["color"] for n in stack}), 1, stack)
            self.assertEqual(len({n["direction"] for n in stack}), 1, stack)
            self.assertTrue(stack_line([(n["x"], n["y"]) for n in stack], stack[0]["direction"]), stack)
            self.assertEqual([n for n in expanded_notes(placed) if n["beat"] == beat and n not in stack], [])
        self.assertEqual([d for d in validate_arrangement(placed) if d["severity"] == "error"
                          or d["code"] == "stack_shape"], [])

    def test_unmarked_simultaneous_notes_stay_a_double(self):
        placed = place_arrangement(arrangement(rhythm([0, 1, 2, 2])))["arrangement"]
        pair = [n for n in expanded_notes(placed) if n["beat"] == 2]
        self.assertEqual(sorted(n["color"] for n in pair), [0, 1])

    def test_a_stack_under_a_held_arc_goes_to_the_free_hand(self):
        arc = {"id": "hold", "beat": 1, "x": 0, "y": 0, "color": 0, "direction": 0, "tail_beat": 5, "tail_x": 0,
               "tail_y": 2, "tail_direction": 1}
        notes = [{"id": "head", "beat": 1, "x": 0, "y": 0, "color": 0, "direction": 0},
                 {"id": "tail", "beat": 5, "x": 0, "y": 2, "color": 0, "direction": 1}]
        notes += [{"id": f"s{i}", "beat": 3, "stack": True} for i in range(3)]
        placed = place_arrangement(arrangement(notes, arcs=[arc]))["arrangement"]
        stack = stacks_of(placed)[3]
        self.assertEqual({n["color"] for n in stack}, {1})
        self.assertTrue(stack_line([(n["x"], n["y"]) for n in stack], stack[0]["direction"]))


    def test_a_stored_cell_moves_so_a_stack_lines_up(self):
        """A note already placed in a corner joins a stack: its stored cell gives way to the line."""
        stored = place_arrangement(arrangement(rhythm([0, 1, 2, 3])))["arrangement"]
        note = next(n for n in stored["sections"][0]["notes"] if n["beat"] == 2)
        note.update(x=0 if note["color"] == 0 else 3, y=0, direction=4 if note["color"] == 0 else 5, stack=True)
        stored["sections"][0]["notes"].append({"id": "partner", "beat": 2, "stack": True})
        stack = stacks_of(place_arrangement(stored, strict=False)["arrangement"])[2]
        self.assertTrue(stack_line([(n["x"], n["y"]) for n in stack], stack[0]["direction"]), stack)

    def test_a_stack_of_two_never_spans_a_gap_around_the_other_hand(self):
        """A stored note at (0,0) cutting up-right, the other hand at (1,1): the pair moves, it does not skip."""
        notes = [{"id": "other", "beat": 2, "x": 1, "y": 1, "color": 1, "direction": 5},
                 {"id": "kept", "beat": 2, "x": 0, "y": 0, "color": 0, "direction": 5, "stack": True,
                  "placed": ["x", "y", "direction"]},
                 {"id": "partner", "beat": 2, "color": 0, "stack": True}]
        stack = stacks_of(place_arrangement(arrangement(notes), strict=False)["arrangement"])[2]
        self.assertTrue(stack_line([(n["x"], n["y"]) for n in stack], stack[0]["direction"]), stack)


class DemandTests(unittest.TestCase):
    def test_a_stack_demands_its_span(self):
        from sabermapper.critique import intensity_bars
        evidence = {"passages": [{"start_seconds": 0, "end_seconds": 8, "energy_ratio": 1.0, "support_score": 1.0}]}
        single = [{"id": "a", "beat": Fraction(1), "x": 0, "y": 0, "color": 0, "direction": 1}]
        stack = single + [{"id": "b", "beat": Fraction(1), "x": 0, "y": 1, "color": 0, "direction": 1}]
        demand = [intensity_bars(arrangement([]), evidence, notes)[1][0]["demand"] for notes in (single, stack)]
        self.assertGreater(demand[1], demand[0])


class ValidationTests(unittest.TestCase):
    def placed(self, notes):
        return validate_arrangement(arrangement(notes))

    def test_a_stack_holds_two_or_three_notes_of_one_hand_and_cut(self):
        full = {"direction": 1, "y": 0}
        four = [{"id": f"n{x}", "beat": 0, "x": x, "color": 0, "stack": True, **full} for x in range(4)]
        self.assertIn("invalid_stack", {d["code"] for d in self.placed(four)})
        mixed = [{"id": "a", "beat": 0, "x": 0, "color": 0, "stack": True, **full},
                 {"id": "b", "beat": 0, "x": 3, "color": 1, "stack": True, **full}]
        self.assertIn("invalid_stack", {d["code"] for d in self.placed(mixed)})
        alone = [{"id": "a", "beat": 0, "x": 0, "color": 0, "stack": True, **full}]
        self.assertIn("invalid_stack", {d["code"] for d in self.placed(alone)})
        flag = [{"id": "a", "beat": 0, "x": 0, "color": 0, "stack": "yes", **full}]
        self.assertIn("invalid_stack", {d["code"] for d in self.placed(flag)})
        good = [{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1, "stack": True},
                {"id": "b", "beat": 0, "x": 0, "y": 1, "color": 0, "direction": 1, "stack": True}]
        self.assertEqual([d for d in self.placed(good) if "stack" in d["code"]], [])


class MovementTests(unittest.TestCase):
    def shape(self, cells, direction):
        notes = [{"id": f"n{i}", "beat": 0, "x": x, "y": y, "color": 0, "direction": direction}
                 for i, (x, y) in enumerate(cells)]
        return [w for w in analyze_movement(notes)["warnings"] if w["code"] == "stack_shape"]

    def test_a_stack_lies_in_an_unbroken_line_along_its_cut(self):
        self.assertEqual(self.shape([(0, 0), (0, 1)], 1), [])            # vertical, down cut
        self.assertEqual(self.shape([(0, 0), (1, 1), (2, 2)], 6), [])    # diagonal, down-left cut
        self.assertEqual(self.shape([(0, 0), (1, 0)], 8), [])            # a dot stack in any line
        self.assertTrue(self.shape([(0, 0), (1, 0)], 1))                 # side by side on a down cut
        self.assertTrue(self.shape([(0, 0), (0, 2)], 1))                 # a gap in the line
        self.assertTrue(self.shape([(0, 0), (1, 0), (2, 0), (3, 0)], 2))  # four notes

    def test_notes_a_sixteenth_apart_are_no_stack(self):
        notes = [{"id": "a", "beat": 0, "x": 0, "y": 0, "color": 0, "direction": 1},
                 {"id": "b", "beat": 1 / 16, "x": 2, "y": 0, "color": 0, "direction": 1}]
        self.assertEqual([w for w in analyze_movement(notes)["warnings"] if w["code"] == "stack_shape"], [])


class DraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = unison_song()
        cls.result = propose_rhythm(song_arrangement(), cls.evidence, held=[36.0])
        cls.times = {Fraction(str(n["beat"])): n for b in cls.result["bars"] for n in b["notes"]}
        cls.placed = place_arrangement(cls.result["draft"])["arrangement"]

    def test_unison_hits_become_stacks_sized_by_the_instruments(self):
        self.assertEqual({t: self.times[t].get("stack") for t in (24, 25, 26)}, {24: 2, 25: 3, 26: 2})
        self.assertFalse(self.times[24].get("double"), "a stack takes the place of the crash double")
        stacks = stacks_of(self.placed)
        for beat, size in ((24, 2), (25, 3), (26, 2)):
            stack = stacks[beat]
            self.assertEqual(len(stack), size)
            self.assertEqual(len({(n["color"], n["direction"]) for n in stack}), 1, stack)
            self.assertTrue(stack_line([(n["x"], n["y"]) for n in stack], stack[0]["direction"]), stack)

    def test_under_a_held_arc_the_free_hand_cuts_the_stack(self):
        arc = next(a for s in self.placed["sections"] for a in s.get("arcs", [])
                   if s["id"] == "verse" and Fraction(str(a["beat"])) + 48 == 56)
        stack = stacks_of(self.placed)[58]
        self.assertEqual({n["color"] for n in stack}, {1 - arc["color"]})

    def test_the_draft_raises_none_of_the_checked_findings(self):
        warnings = critique_arrangement(self.placed, self.evidence)["warnings"]
        self.assertEqual([w["code"] for w in warnings if w["code"] in TARGET_CODES + ("unison_hit_unstacked",)], [])
        self.assertEqual([d for d in validate_arrangement(self.placed)
                          if d["severity"] == "error" or d["code"] == "stack_shape"], [])


class CheckTests(unittest.TestCase):
    def test_an_unstacked_unison_hit_is_reported_and_its_suggestion_stacks_it(self):
        evidence = unison_song()
        draft = propose_rhythm(song_arrangement(), evidence, held=[36.0])["draft"]
        for section in draft["sections"]:  # the hits lose their stacks: one plain note each
            kept = []
            for note in section["notes"]:
                if note.pop("stack", False) and any(n["beat"] == note["beat"] for n in kept):
                    continue
                kept.append(note)
            section["notes"] = kept
        found = [f for f in check_arrangement(draft, evidence)["findings"] if f["code"] == "unison_hit_unstacked"]
        self.assertEqual(sorted(round(f["beats"][0]) for f in found), [24, 25, 26, 58])
        fixed = draft
        for finding in found:
            suggestion = finding["suggestions"][0]
            self.assertEqual(suggestion["op"], "stack")
            fixed = apply_suggestion(fixed, suggestion)
        report = check_arrangement(fixed, evidence)
        self.assertEqual([f for f in report["findings"] if f["code"] in ("unison_hit_unstacked", "stack_shape")], [])
        self.assertEqual(report["blocking_count"], 0)


if __name__ == "__main__":
    unittest.main()
