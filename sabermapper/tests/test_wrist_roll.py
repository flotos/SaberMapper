"""Angled cuts zig-zag about the reversal: a hand's cuts never spin round the clock faster than the wrist unwinds."""
import copy
import unittest

from sabermapper.check import apply_suggestion, check_arrangement
from sabermapper.movement import (ROLL_LIMIT_DEGREES, UNWIND_DEGREES_PER_SECOND, analyze_movement, next_roll,
                                  roll_degrees)
from sabermapper.placement import place_arrangement
from sabermapper.validation import validate_arrangement
from test_placement import arrangement, rhythm

# Left hand: each cut turns 45 degrees short of a clean reversal, always the same way (R, UL, D, UR, L, DR, U, DL).
SPIN = (3, 4, 1, 5, 2, 7, 0, 6)
ZIGZAG = (3, 4, 3, 4, 3, 4, 3, 4)  # the same 45-degree angle, alternating sides
CELLS = ((0, 1), (1, 0), (0, 2), (1, 1), (0, 0), (1, 2), (0, 1), (1, 0))


def one_hand(directions, gap_seconds, bpm=120):
    step = gap_seconds * bpm / 60
    return [{"id": f"n{i}", "beat": i * step, "x": x, "y": y, "color": 0, "direction": d}
            for i, (d, (x, y)) in enumerate(zip(directions, CELLS))]


def rolls(notes, bpm=120):
    return [w for w in analyze_movement(notes, bpm)["warnings"] if w["code"] == "wrist_roll"]


class WristRollTests(unittest.TestCase):
    def test_turn_off_the_reversal_is_signed(self):
        self.assertEqual(roll_degrees(1, 0), 0)  # down then up: a clean reversal
        self.assertEqual(roll_degrees(3, 4), -roll_degrees(3, 6))  # UL and DL sit on either side of L
        self.assertEqual(abs(roll_degrees(3, 4)), 45)
        self.assertEqual(roll_degrees(3, 4), roll_degrees(4, 1))  # the spin keeps turning the same way

    def test_roll_unwinds_linearly_with_time(self):
        for gap in (0.1, 0.2, 0.3, 0.4):
            roll, found = next_roll(-40.0, 3, 4, gap, False)  # previous R, cut UL (45 degrees short)
            self.assertIsNone(found)
            self.assertAlmostEqual(roll, -40 + UNWIND_DEGREES_PER_SECOND * gap - 45)
        self.assertEqual(next_roll(-80.0, 3, 4, 5.0, True), (0.0, None))  # a rest returns the wrist to neutral
        self.assertEqual(next_roll(-80.0, 3, 2, 0.25, False)[0], -80 + 22.5)  # a clean reversal only unwinds

    def test_fast_spin_forces_a_wrist_flip(self):
        found = rolls(one_hand(SPIN, 0.25))
        self.assertTrue(found)
        self.assertEqual(found[0]["note_ids"], ["n3", "n4"])  # -45, -67.5, -90, then past the limit
        self.assertEqual(found[0]["severity"], "error")
        self.assertGreater(ROLL_LIMIT_DEGREES, 67.5)

    def test_the_same_angles_zigzag_or_slow_never_build_up(self):
        self.assertEqual(rolls(one_hand(ZIGZAG, 0.25)), [])
        self.assertEqual(rolls(one_hand(SPIN, 0.5)), [])  # the wrist unwinds 45 degrees between swings

    def test_a_pinned_spin_blocks_save_and_check_offers_cuts_that_clear_it(self):
        pinned = arrangement(one_hand(SPIN, 0.25))
        self.assertIn("wrist_roll", {d["code"] for d in validate_arrangement(pinned) if d["severity"] == "error"})
        finding = next(f for f in check_arrangement(pinned)["findings"] if f["code"] == "wrist_roll")
        self.assertTrue(finding["suggestions"])
        fixed = apply_suggestion(pinned, finding["suggestions"][0])
        self.assertNotIn(tuple(finding["object_ids"]),
                         {tuple(w["note_ids"]) for w in rolls(fixed["sections"][0]["notes"])})


class AngularPlacementZigzagsTests(unittest.TestCase):
    def test_angular_style_keeps_angled_cuts_without_spinning(self):
        # Hands alternate, so each hand swings every 0.25 s (the speed that spun Living a Lie) up to 0.74 s.
        for bpm, step in ((122, 0.25), (122, 1 / 3), (150, 0.5), (122, 0.75)):
            draft = arrangement(rhythm([i * step for i in range(96)]), bpm=bpm, length=96)
            draft["style"] = {"idea": "Sharp angled cuts on a driving riff.", "grounding": ["tempo"],
                              "settings": {"flow": "angular"}}
            placed = place_arrangement(copy.deepcopy(draft))["arrangement"]
            self.assertEqual([d for d in validate_arrangement(placed) if d["severity"] == "error"], [], (bpm, step))
            notes = sorted(({**n, "beat": float(n["beat"])} for n in placed["sections"][0]["notes"]),
                           key=lambda n: n["beat"])
            self.assertEqual(rolls(notes, bpm), [])
            for hand in (0, 1):
                cuts = [n["direction"] for n in notes if n["color"] == hand]
                turns = [roll_degrees(a, b) for a, b in zip(cuts, cuts[1:]) if 8 not in (a, b)]
                self.assertGreater(sum(1 for t in turns if t), 10, "the angular style still angles its cuts")
                if step == 0.25:  # four swings in a row, 0.25 s apart, never all turn the same way (a spin)
                    runs = [turns[i:i + 4] for i in range(len(turns) - 3)]
                    self.assertFalse(any(all(a > 0 for a in r) or all(a < 0 for a in r) for r in runs),
                                     "fast angled cuts alternate sides instead of spinning")

if __name__ == "__main__":
    unittest.main()
