"""Heavier audio plays harder: soft passages never out-demand the heavy ones (Living a Lie, 2026-09-23).

Feedback: "the intro is kinda hard but not that much, and it gets easier once the music starts and the sound
gets heavier. Heavier, louder, more compressed sound should use harder parts overall."
"""
import unittest

from sabermapper.audio_repair import ease_soft, harden_loud, repair_audio
from sabermapper.critique import critique_arrangement, intensity_bars
from sabermapper.validation import validate_arrangement


def note(i, beat):
    color = i % 2
    # Each hand alternates down/up so the fixture itself has no flow break.
    return {"id": f"n{i}", "beat": beat, "x": 1 + color, "y": 1, "color": color,
            "direction": 1 if (i // 2) % 2 == 0 else 0}


def arrangement(beats, *, length=128, locked=False):
    # 120 BPM, offset 0: beat b sits at b / 2 seconds; a 4-beat bar lasts 2 s.
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": length, "intent": "fixture",
                                        "locked": locked, "resolved": True, "patterns": [],
                                        "notes": [note(i, b) for i, b in enumerate(beats)]}]}


def report(*, soft_until=16.0, soft_energy=0.45, seconds=64.0, drums=None, vocals=()):
    """Drum hits on every beat of the soft intro and every half beat after; the first ``soft_until`` seconds
    play at ``soft_energy`` of the body's loudness."""
    if drums is None:
        drums = [b / 2 for b in range(int(seconds * 4)) if b / 2 >= soft_until * 2 or b % 2 == 0]
    hits = [{"id": f"d{i}", "seconds": b / 2, "method": "spectral_flux", "strength": 0.8 if b % 1 == 0 else 0.5}
            for i, b in enumerate(drums)]
    sung = [{"id": f"v{i}", "seconds": b / 2, "method": "spectral_flux", "strength": 1.0} for i, b in enumerate(vocals)]
    return {"source": {"sha256": "fixture", "duration_seconds": seconds}, "created_at": "2026-09-23T00:00:00+00:00",
            "backend": "fixture", "preset": "balanced",
            "layers": {"mix": {"events": [], "energy_contour": [{"seconds": i / 10, "energy": 0.5}
                                                                 for i in range(int(seconds * 10))]},
                       "drums": {"events": hits}, "vocals": {"events": sung, "sustains": []}},
            # Drums play throughout, so no passage is thin (support stays high): only loudness differs.
            "passages": [{"start_seconds": t, "end_seconds": t + 2, "drum_onset_density": 4.0,
                          "energy_ratio": soft_energy if t < soft_until else 1.0, "support_score": 0.95}
                         for t in range(0, int(seconds), 2)]}


def codes(arrangement, evidence):
    return [w for w in critique_arrangement(arrangement, evidence)["warnings"]
            if w["code"] in ("difficulty_exceeds_intensity", "intensity_underplayed")]


def errors(arrangement):
    return [d for d in validate_arrangement(arrangement) if d["severity"] == "error"]


def hard_intro():
    """A soft intro on every half beat (8 swings per bar) before a heavy body on every beat (4 per bar)."""
    return arrangement([b / 2 for b in range(64)] + list(range(32, 128))), report(drums=range(128), vocals=[4])


def sparse_heavy_run(*, intro_step=1.0, run_step=2.0):
    """Soft intro on every ``intro_step`` beats; heavy body on every half beat except beats 64-80."""
    intro = [i * intro_step for i in range(int(32 / intro_step))]
    body = [b / 2 for b in range(64, 256) if not 64 <= b / 2 < 80]
    run = [64 + i * run_step for i in range(int(16 / run_step))]
    return arrangement(intro + sorted(body + run)), report()


def far_rows(source, first, last):
    """Put the cuts in [first, last) on the far row: down cuts high, up cuts low (wide swings)."""
    for n in source["sections"][0]["notes"]:
        if first <= n["beat"] < last:
            n["y"] = 2 if n["direction"] == 1 else 0


class IntensityCheckTests(unittest.TestCase):
    def test_a_soft_intro_harder_than_the_heavy_body_is_flagged(self):
        source, evidence = hard_intro()
        found = codes(source, evidence)
        # Both sides of the inversion: the soft intro is too hard, and the heavy body plays easier than it.
        self.assertEqual([w["code"] for w in found], ["difficulty_exceeds_intensity", "intensity_underplayed"])
        self.assertEqual(found[0]["beats"], [0, 32])
        self.assertEqual(found[1]["beats"], [32, 128])
        self.assertGreater(found[0]["value"], 1.0)
        bars = critique_arrangement(source, evidence)["metrics"]["intensity"]["bars"]
        self.assertAlmostEqual(bars[0]["relative"], 0.45)
        self.assertEqual((bars[0]["demand"], bars[-1]["demand"]), (4.0, 2.0))

    def test_equal_loudness_is_never_flagged(self):
        source, evidence = hard_intro()
        self.assertEqual(codes(source, report(soft_energy=1.0)), [])

    def test_a_heavy_run_easier_than_the_soft_passages_is_flagged(self):
        source, evidence = sparse_heavy_run()
        found = codes(source, evidence)
        self.assertEqual([w["code"] for w in found], ["intensity_underplayed"])
        self.assertEqual(found[0]["beats"], [64, 80])
        self.assertLess(found[0]["value"], found[0]["threshold"])

    def test_hand_travel_raises_the_demand(self):
        source, evidence = hard_intro()
        _, still = intensity_bars(source, evidence)
        for n in source["sections"][0]["notes"]:
            if n["beat"] < 4:
                n["y"] = 0 if n["direction"] == 0 else 2  # up cuts low, down cuts high: the hand crosses the grid
        _, moving = intensity_bars(source, evidence)
        self.assertGreater(moving[0]["demand"], still[0]["demand"])
        self.assertEqual(moving[2]["demand"], still[2]["demand"])

    def test_without_passages_the_check_does_not_run(self):
        source, evidence = hard_intro()
        del evidence["passages"]
        self.assertEqual(critique_arrangement(source, evidence)["metrics"]["intensity"], {"checked": False})


class IntensityRepairTests(unittest.TestCase):
    def test_the_soft_intro_is_eased_and_keeps_the_voice(self):
        source, evidence = hard_intro()
        result = ease_soft(source, evidence)
        removed = [c["beat"] for c in result["changes"] if c["action"] == "removed"]
        self.assertTrue(removed and all(b < 32 for b in removed), "only the soft intro is eased")
        self.assertEqual(codes(result["arrangement"], evidence), [])
        self.assertEqual(errors(result["arrangement"]), [])
        kept = {float(n["beat"]) for n in result["arrangement"]["sections"][0]["notes"]}
        self.assertIn(4.0, kept, "the note on the sung onset stays")
        self.assertTrue(all(any(b <= k < b + 4 for k in kept) for b in range(0, 32, 4)), "no bar empties")
        self.assertEqual(len(source["sections"][0]["notes"]), 160, "input must not be mutated")

    def test_a_locked_soft_section_is_reported_not_eased(self):
        source, evidence = hard_intro()
        source["sections"][0]["locked"] = True
        result = ease_soft(source, evidence)
        self.assertEqual(result["changes"], [])
        self.assertEqual({u["code"] for u in result["unresolved"]}, {"difficulty_exceeds_intensity"})

    def test_the_heavy_run_gains_notes_on_its_attacks(self):
        source, evidence = sparse_heavy_run()
        result = harden_loud(source, evidence)
        added = [c for c in result["changes"] if c["action"] == "added"]
        self.assertTrue(added)
        self.assertTrue(all(64 <= c["beat"] < 80 for c in added))
        self.assertEqual(codes(result["arrangement"], evidence), [])
        self.assertEqual(errors(result["arrangement"]), [])

    def test_hardening_never_buries_the_declared_lead(self):
        # The guitar leads the heavy run on each beat, all mapped; drum notes between its attacks would dilute
        # its rhythm, so the additions are restored. Wider swings alone cannot reach the soft peak, so the bar is
        # reported for re-authoring.
        source, evidence = sparse_heavy_run(intro_step=0.5, run_step=1.0)
        source["sections"][0]["musical_focus"] = [{"id": "riff", "start_beat": 64, "end_beat": 80, "lead": "guitar",
                                                   "weights": {"guitar": 1.0}, "intent": "riff on the beat"}]
        evidence["layers"]["guitar"] = {"events": [{"id": f"g{b}", "seconds": b / 2, "method": "spectral_flux",
                                                    "strength": 0.9} for b in range(64, 80)]}
        self.assertEqual({w["code"] for w in codes(source, evidence)},
                         {"intensity_underplayed", "difficulty_exceeds_intensity"})
        result = harden_loud(source, evidence)
        self.assertNotIn("added", {c["action"] for c in result["changes"]})
        self.assertEqual(sorted(float(n["beat"]) for n in result["arrangement"]["sections"][0]["notes"]),
                         sorted(float(n["beat"]) for n in source["sections"][0]["notes"]), "the rhythm stays")
        self.assertTrue(result["unresolved"])
        self.assertIn("musical_focus lead", result["unresolved"][0]["reason"])

    def test_a_heavy_run_with_every_attack_mapped_widens_its_movement(self):
        # Every drum hit of the run already carries a note, so only wider swings can raise it.
        source, evidence = sparse_heavy_run(intro_step=0.5, run_step=0.5)
        far_rows(source, 0, 64)
        far_rows(source, 80, 128)
        found = codes(source, evidence)
        flagged = [w["beats"] for w in found if w["code"] == "intensity_underplayed"]
        self.assertTrue(flagged and flagged[0][0] <= 64 and flagged[0][1] >= 80)
        result = harden_loud(source, evidence)
        self.assertEqual({c["action"] for c in result["changes"]}, {"moved"})
        moved = {i.split("/")[-1] for c in result["changes"] for i in c["object_ids"]}
        run = [n for n in result["arrangement"]["sections"][0]["notes"] if 64 <= n["beat"] < 80]
        self.assertTrue(moved and all(n["y"] == (2 if n["direction"] == 1 else 0) for n in run if n["id"] in moved))
        self.assertEqual([n["beat"] for n in run], [n["beat"] for n in source["sections"][0]["notes"]
                                                   if 64 <= n["beat"] < 80], "the rhythm stays")
        self.assertNotIn("intensity_underplayed", {w["code"] for w in codes(result["arrangement"], evidence)})
        self.assertEqual(errors(result["arrangement"]), [])

    def test_repair_audio_runs_both_passes(self):
        source, evidence = hard_intro()
        result = repair_audio(source, evidence)
        self.assertIn("difficulty_exceeds_intensity", {c.get("code") for c in result["changes"]})
        self.assertNotIn("difficulty_exceeds_intensity", {w["code"] for w in result["remaining"]})
        self.assertEqual(errors(result["arrangement"]), [])


if __name__ == "__main__":
    unittest.main()
