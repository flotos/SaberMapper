"""One hand streaming alone: flagged by the movement model; placement never creates it (test_placement).

Reported on End of You (0:02.5): three right-hand eighths at 190 BPM over the singer's speech while the left
hand held an arc; only the first sat on her syllable.
"""
from fractions import Fraction
import unittest

from sabermapper.movement import analyze_movement
from sabermapper.validation import validate_arrangement

BPM = 190


def seconds(beat):
    return beat * 60 / BPM


def note(nid, beat, color, direction, x=None, y=1):
    return {"id": nid, "beat": beat, "x": (1 if color == 0 else 2) if x is None else x, "y": y,
            "color": color, "direction": direction}


def arrangement(notes, *, lead="vocals", length=32):
    focus = [{"id": "lead", "start_beat": 0, "end_beat": length, "lead": lead, "weights": {lead: 1.0},
              "intent": "fixture"}]
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": BPM, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 18, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": length, "intent": "fixture",
                                        "locked": False, "resolved": True, "patterns": [], "musical_focus": focus,
                                        "notes": notes}]}


def report(layers, length=32):
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(int(seconds(length) * 10) + 1)]
    return {"source": {"sha256": "fixture", "duration_seconds": seconds(length)},
            "layers": {"mix": {"events": [], "energy_contour": contour},
                       **{name: {"events": [{"id": f"{name}:{i}", "seconds": seconds(b), "method": "spectral_flux",
                                             "strength": s} for i, (b, s) in enumerate(events)], "sustains": []}
                          for name, events in layers.items()}}}


# The left hand opens and closes the phrase; the right hand streams three eighths in between.
SPEECH = [note("l1", 4, 0, 1), note("r1", "15/2", 1, 0, y=0), note("r2", 8, 1, 1), note("r3", "17/2", 1, 0, x=3),
          note("l2", 12, 0, 0), note("r4", 14, 1, 1)]


def codes(arr):
    return [d["code"] for d in validate_arrangement(arr)]


class MovementTests(unittest.TestCase):
    def test_three_fast_swings_on_an_idle_pair_are_a_burst(self):
        warning = next(d for d in validate_arrangement(arrangement(SPEECH)) if d["code"] == "one_hand_burst")
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["object_ids"], ["s/note/r1", "s/note/r2", "s/note/r3"])
        self.assertIn("right hand swings 3 times", warning["message"])

    def test_the_other_hand_cutting_inside_the_run_is_not_a_burst(self):
        notes = SPEECH + [note("l3", "33/4", 0, 1, x=0)]
        self.assertNotIn("one_hand_burst", codes(arrangement(notes)))

    def test_eighths_at_a_moderate_tempo_are_not_a_burst(self):
        notes = [{"id": n, "beat": b, "x": x, "y": y, "color": 1, "direction": d}
                 for n, b, x, y, d in (("a", 0, 2, 1, 1), ("b", 0.5, 2, 0, 0), ("c", 1, 3, 1, 1))]
        self.assertEqual(analyze_movement(notes, bpm=120)["warnings"], [], "0.25 s apart")
        self.assertEqual([w["code"] for w in analyze_movement(notes, bpm=190)["warnings"]], ["one_hand_burst"])


if __name__ == "__main__":
    unittest.main()
