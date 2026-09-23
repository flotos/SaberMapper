"""Hidden notes: a note too soon behind another in the same cell blocks; project check suggests the cell."""
import copy
import unittest
from fractions import Fraction

from sabermapper.movement import analyze_movement
from sabermapper.validation import validate_arrangement


def arrangement(notes, *, bpm=190, arcs=()):
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": bpm, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 18, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": 32, "intent": "fixture",
                                        "locked": False, "resolved": True, "patterns": [],
                                        "notes": notes, "arcs": list(arcs)}]}


def n(nid, beat, x, y, color, direction):
    return {"id": nid, "beat": beat, "x": x, "y": y, "color": color, "direction": direction}


def end_of_you():
    """End of You 0:24 (beats 77-78 at 190 BPM): blue right-left-right in cell (2,1), 0.158 s apart."""
    return arrangement([n("a", 4, 2, 1, 1, 3), n("b", "9/2", 2, 1, 1, 2), n("c", 5, 2, 1, 1, 3),
                        n("d", 6, 2, 0, 1, 1), n("red", "11/2", 0, 0, 0, 1)])


def hidden(source):
    return [d for d in validate_arrangement(source) if d["code"] == "hidden_note"]


def errors(source):
    return [d for d in validate_arrangement(source) if d["severity"] == "error"]


class HiddenNoteCheckTests(unittest.TestCase):
    def test_player_report_is_blocking(self):
        found = hidden(end_of_you())
        self.assertEqual([d["object_ids"] for d in found], [["s/note/a", "s/note/b"], ["s/note/b", "s/note/c"]])
        self.assertTrue(all(d["severity"] == "error" for d in found))
        self.assertIn("project check", found[0]["message"])

    def test_window_depends_on_the_line_of_sight(self):
        # (cell, gap in beats at 120 BPM, blocked): centre middle/top rows need 0.35 s, other cells 0.2 s.
        for cell, gap, blocked in (((1, 1), "1/2", True), ((2, 2), "5/8", True), ((1, 1), "3/4", False),
                                   ((1, 0), "3/8", True), ((1, 0), "1/2", False),
                                   ((0, 1), "3/8", True), ((3, 2), "1/2", False)):
            source = arrangement([n("front", 2, *cell, 0, 1), n("back", str(2 + Fraction(gap)), *cell, 0, 0)],
                                 bpm=120)
            self.assertEqual(bool(hidden(source)), blocked, (cell, gap))

    def test_either_hand_hides_the_other(self):
        source = arrangement([n("red", 2, 1, 1, 0, 1), n("blue", "5/2", 1, 1, 1, 0)], bpm=120)
        self.assertEqual(len(hidden(source)), 1)

    def test_neighbouring_cells_do_not_hide(self):
        source = arrangement([n("red", 2, 1, 1, 0, 1), n("blue", "9/4", 2, 1, 1, 1)], bpm=120)
        self.assertEqual(hidden(source), [])

    def test_locked_sections_report_without_blocking(self):
        source = end_of_you()
        source["sections"][0]["locked"] = True
        found = hidden(source)
        self.assertTrue(found and all(d["severity"] == "warning" for d in found))

    def test_movement_model_reports_the_pair(self):
        notes = [{"id": "front", "beat": 0, "x": 2, "y": 1, "color": 1, "direction": 3},
                 {"id": "back", "beat": 0.5, "x": 2, "y": 1, "color": 1, "direction": 2}]
        result = analyze_movement(notes, bpm=190, njs=18)
        self.assertEqual([(w["code"], w["note_ids"]) for w in result["warnings"]],
                         [("hidden_note", ["front", "back"])])


if __name__ == "__main__":
    unittest.main()
