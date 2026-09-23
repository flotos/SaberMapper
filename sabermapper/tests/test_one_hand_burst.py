"""One hand streaming alone: flagged by the movement model, split or thinned by repair-audio.

Reported on End of You (0:02.5): three right-hand eighths at 190 BPM over the singer's speech while the left
hand held an arc; only the first sat on her syllable.
"""
from fractions import Fraction
import unittest

from sabermapper.audio_repair import insert_note, split_bursts
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


class SplitBurstTests(unittest.TestCase):
    def test_notes_off_the_voice_are_removed(self):
        # The singer speaks only on beat 7.5; the eighths after it sit on faint bass bleed.
        evidence = report({"vocals": [(7.45, 0.8), (11.95, 0.7)], "bass": [(8, 0.25), (8.5, 0.23)]})
        result = split_bursts(arrangement(SPEECH), evidence)
        kept = {n["id"] for n in result["arrangement"]["sections"][0]["notes"]}
        self.assertEqual(kept, {"l1", "r1", "l2", "r4"})
        self.assertEqual({c["action"] for c in result["changes"]}, {"removed"})
        self.assertNotIn("one_hand_burst", codes(result["arrangement"]))
        self.assertEqual(len(SPEECH), 6, "input untouched")

    def test_a_burst_on_the_lead_hands_its_middle_note_to_the_idle_hand(self):
        # Strong drum eighths lead: every note is on the lead, so the rhythm stays and the hands alternate.
        evidence = report({"drums": [(b / 2, 0.8) for b in range(64)]})
        result = split_bursts(arrangement(SPEECH, lead="drums"), evidence)
        moved = [c for c in result["changes"] if c["action"] == "moved_hand"]
        self.assertEqual(len(moved), 1, result)
        self.assertEqual((moved[0]["beat"], moved[0]["color"]), (8.0, 0))
        times = sorted(float(Fraction(str(n["beat"]))) for n in result["arrangement"]["sections"][0]["notes"])
        self.assertEqual(times, [4, 7.5, 8, 8.5, 12, 14])
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["severity"] == "error"], [])
        self.assertNotIn("one_hand_burst", codes(result["arrangement"]))

    def test_a_soft_bar_drops_the_note_instead_of_handing_it_over(self):
        # Four loud bars set the demand; the burst sits in a bar at half their loudness (difficulty_exceeds_intensity).
        loud = [note(f"x{b}", b, b % 2, 1 if (b // 2) % 2 == 0 else 0) for b in range(16)]
        burst = [note("l1", 18, 0, 1), note("r1", 20, 1, 1, y=0), note("r2", "41/2", 1, 0), note("r3", 21, 1, 1, x=3),
                 note("l2", 24, 0, 0)]
        evidence = report({"drums": [(b / 2, 0.8) for b in range(64)]})
        evidence["passages"] = [{"start_seconds": seconds(start), "end_seconds": seconds(start + 16),
                                 "support_score": 0.9, "energy_ratio": energy} for start, energy in ((0, 1.0), (16, 0.5))]
        source = arrangement(loud + burst, lead="drums")
        self.assertIn("one_hand_burst", codes(source))
        result = split_bursts(source, evidence)
        self.assertEqual([(c["action"], c["beat"]) for c in result["changes"]], [("removed", 20.5)])
        self.assertNotIn("one_hand_burst", codes(result["arrangement"]))

    def test_dropping_the_middle_reverses_the_cut_after_it(self):
        # A soft triplet down-up-down on the voice: without the up-cut the two down-cuts come 0.21 s apart,
        # so the last cut turns up and starts where the first one left the saber.
        notes = [note("l1", 4, 0, 1), note("r1", "23/3", 1, 1), note("r2", 8, 1, 0, y=0), note("r3", "25/3", 1, 1, x=3),
                 note("l2", 12, 0, 0), note("r4", 16, 1, 1)]
        evidence = report({"vocals": [(23 / 3, 0.8), (8, 0.8), (25 / 3, 0.8)]})
        evidence["passages"] = [{"start_seconds": 0.0, "end_seconds": seconds(32), "support_score": 0.2,
                                 "energy_ratio": 0.4}]
        result = split_bursts(arrangement(notes), evidence)
        self.assertEqual([(c["action"], c["object_ids"]) for c in result["changes"]], [("removed", ["s/note/r2"])])
        directions = {n["id"]: n["direction"] for n in result["arrangement"]["sections"][0]["notes"]}
        self.assertEqual((directions["r1"], directions["r3"], directions["r4"]), (1, 0, 1))
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["severity"] == "error"], [])
        self.assertNotIn("one_hand_burst", codes(result["arrangement"]))

    def test_a_note_added_inside_a_phrase_reverses_the_cuts_after_it(self):
        # Borrowed Waters: a cut added between two alternating cuts must start where the previous
        # one left the saber, so the hand's later cuts turn over rather than repeat.
        from sabermapper.audio_repair import _errors, _reflow
        source = arrangement([note("l1", 4, 0, 1), note("l2", 6, 0, 0, y=0), note("l3", 8, 0, 1),
                              note("r1", 24, 1, 1)])
        baseline = _errors(source)
        change = insert_note(source, Fraction(5), "new", hands=(0,))
        self.assertEqual((change["color"], change["direction"]), (0, 0))
        self.assertTrue(_reflow(source, baseline))
        left = sorted((n for n in source["sections"][0]["notes"] if n["color"] == 0),
                      key=lambda n: Fraction(str(n["beat"])))
        self.assertEqual([(n["id"], n["direction"]) for n in left], [("l1", 1), ("new", 0), ("l2", 1), ("l3", 0)])
        self.assertEqual([d for d in validate_arrangement(source) if d["severity"] == "error"], [])

    def test_repair_audio_reports_the_reversed_cuts(self):
        from sabermapper.audio_repair import _reversals
        before = arrangement([note("r1", 4, 1, 1), note("r2", 5, 1, 0), note("r3", 6, 1, 1), note("r4", 7, 1, 0)])
        after = arrangement([note("r1", 4, 1, 1), note("r3", 6, 1, 0), note("r4", 7, 1, 1)])
        records = _reversals(before, after, [{"action": "removed", "object_ids": ["s/note/r2"]}])
        self.assertEqual([(r["action"], r["object_ids"]) for r in records],
                         [("reversed_phrase", ["s/note/r3", "s/note/r4"])])

    def test_locked_bursts_are_reported_not_changed(self):
        source = arrangement(SPEECH)
        source["sections"][0]["locked"] = True
        result = split_bursts(source, report({"vocals": [(7.45, 0.8)]}))
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["unresolved"][0]["code"], "one_hand_burst")


class InsertNoteTests(unittest.TestCase):
    def test_a_fill_never_creates_a_burst(self):
        source = arrangement([note("r1", "15/2", 1, 0, y=0), note("r2", 8, 1, 1)])
        change = insert_note(source, Fraction(17, 2), "new")
        self.assertTrue(change is None or change["color"] == 0, change)
        self.assertNotIn("one_hand_burst", codes(source))


if __name__ == "__main__":
    unittest.main()
