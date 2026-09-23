"""Audio repair: notes move onto sounds, and unmapped salient sounds gain flow-safe notes."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from fractions import Fraction

from sabermapper.audio_grounding import note_support
from sabermapper.audio_repair import _grid_beat, ground_notes, insert_note, repair_audio, reweight_focus, thin_quiet
from sabermapper.critique import critique_arrangement
from sabermapper.validation import validate_arrangement


def note(i, beat, color=None, direction=None):
    color = i % 2 if color is None else color
    # Each hand alternates down/up so the fixture itself has no flow break.
    direction = (1 if (i // 2) % 2 == 0 else 0) if direction is None else direction
    return {"id": f"n{i}", "beat": beat, "x": 1 + color, "y": 1, "color": color, "direction": direction}


def arrangement(beats, *, length=64):
    # 120 BPM, offset 0: beat b sits at b / 2 seconds.
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": length, "intent": "fixture",
                                        "locked": False, "resolved": True, "patterns": [],
                                        "notes": [note(i, b) for i, b in enumerate(beats)]}]}


def report(drum_beats, *, vocals=(), sustains=(), seconds=32.0):
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(int(seconds * 10))]
    drums = [{"id": f"drums:{i}", "seconds": b / 2, "method": "spectral_flux", "strength": 0.8}
             for i, b in enumerate(drum_beats)]
    sung = [{"id": f"vocals:{i}", "seconds": b / 2, "method": "spectral_flux", "strength": 0.8}
            for i, b in enumerate(vocals)]
    return {"source": {"sha256": "fixture", "duration_seconds": seconds}, "created_at": "2026-09-22T00:00:00+00:00",
            "backend": "fixture", "preset": "balanced",
            "layers": {"mix": {"events": [], "energy_contour": contour}, "drums": {"events": drums},
                       "vocals": {"events": sung, "sustains": [{"start_seconds": s / 2, "end_seconds": e / 2}
                                                                for s, e in sustains]}}}


def errors(arrangement):
    return [d for d in validate_arrangement(arrangement) if d["severity"] == "error"]


class GridTests(unittest.TestCase):
    def test_snaps_to_the_coarsest_grid_on_the_sound(self):
        self.assertEqual(_grid_beat(3.02), Fraction(3))
        self.assertEqual(_grid_beat(3.49), Fraction(7, 2))
        self.assertEqual(_grid_beat(3.335), Fraction(10, 3))
        self.assertEqual(_grid_beat(3.26), Fraction(13, 4))


class MelodyBeatTests(unittest.TestCase):
    def test_melody_notes_take_whole_half_or_quarter_beats(self):
        from sabermapper.audio_repair import _melody_beat
        self.assertEqual(_melody_beat(9.04), 9)
        self.assertEqual(_melody_beat(8.55), Fraction(17, 2))
        self.assertEqual(_melody_beat(9.2), Fraction(37, 4))
        self.assertEqual(_melody_beat(7.66), Fraction(31, 4), "no triplet grid in a melodic bar")


class GroundNotesTests(unittest.TestCase):
    def test_off_sound_notes_move_onto_the_nearest_onset(self):
        # Drums on every beat; four notes were placed a quarter beat late.
        beats = list(range(10)) + [10.25, 12.25, 14.25, 16.25] + list(range(18, 40))
        source = arrangement(beats)
        result = ground_notes(source, report(range(64)))
        moved = {c["beat"]: c["to_beat"] for c in result["changes"] if c["action"] == "moved"}
        self.assertEqual(moved, {10.25: 10.0, 12.25: 12.0, 14.25: 14.0, 16.25: 16.0})
        self.assertEqual(note_support(result["arrangement"], report(range(64)))["share"], 1.0)
        self.assertEqual(errors(result["arrangement"]), [])
        self.assertEqual(source["sections"][0]["notes"][10]["beat"], 10.25, "input must not be mutated")

    def test_a_note_with_no_sound_in_reach_is_removed(self):
        drums = [b for b in range(64) if not 20 <= b <= 23]
        beats = [b for b in range(40) if b not in (20, 22, 23)]  # beat 21 has no sound within half a beat
        result = ground_notes(arrangement(beats), report(drums))
        self.assertEqual([(c["beat"], c["action"]) for c in result["changes"]], [(21.0, "removed")])
        self.assertEqual(errors(result["arrangement"]), [])

    def test_a_triplet_feel_moves_eighths_onto_the_stronger_triplet(self):
        # Onsets on each beat and its 2/3 point; a note on the off-beat eighth has no sound.
        drums = sorted([b for b in range(64)] + [b + Fraction(2, 3) for b in range(64)])
        result = ground_notes(arrangement(list(range(8)) + [8.5] + list(range(10, 30))), report(drums))
        self.assertEqual([(c["beat"], c["to_beat"]) for c in result["changes"]], [(8.5, float(Fraction(26, 3)))])

    def test_a_move_never_makes_the_hand_travel_too_fast(self):
        # Onsets at 10.5 and 11 are equally near the late note at 10.75. Moving it to 10.5 would carry the left
        # hand from (0,0) to (3,2) in 0.25 s (reach_proxy), so it takes 11 instead.
        drums = sorted(list(range(64)) + [10.5])
        source = arrangement([])
        source["sections"][0]["notes"] = [
            {"id": "a", "beat": 9, "x": 2, "y": 0, "color": 1, "direction": 1},
            {"id": "b", "beat": 10, "x": 0, "y": 0, "color": 0, "direction": 1},
            {"id": "c", "beat": "43/4", "x": 3, "y": 2, "color": 0, "direction": 0},
            {"id": "d", "beat": 12, "x": 2, "y": 0, "color": 1, "direction": 0},
            {"id": "e", "beat": 13, "x": 0, "y": 0, "color": 0, "direction": 1}]
        self.assertEqual([d for d in validate_arrangement(source) if d["code"] == "reach_proxy"], [])
        result = ground_notes(source, report(drums))
        self.assertEqual([(c["beat"], c.get("to_beat")) for c in result["changes"]], [(10.75, 11.0)])
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["code"] == "reach_proxy"], [])

    def test_arc_anchors_move_with_their_arc(self):
        source = arrangement(list(range(10)) + [10.25] + list(range(12, 30)))
        anchor = source["sections"][0]["notes"][10]
        source["sections"][0]["arcs"] = [{"id": "a1", "beat": 10.25, "x": anchor["x"], "y": 1,
                                          "color": anchor["color"], "direction": anchor["direction"],
                                          "tail_beat": 13, "tail_x": 1 + anchor["color"], "tail_y": 1,
                                          "tail_direction": source["sections"][0]["notes"][12]["direction"]}]
        self.assertEqual(source["sections"][0]["notes"][12]["color"], anchor["color"])
        self.assertEqual(errors(source), [])
        result = ground_notes(source, report(range(64)))
        self.assertEqual(result["arrangement"]["sections"][0]["arcs"][0]["beat"], 10)
        self.assertEqual(errors(result["arrangement"]), [])


class InsertNoteTests(unittest.TestCase):
    def test_a_new_note_never_adds_a_flow_break(self):
        source = arrangement([0, 1, 2, 3, 8, 9, 10, 11])
        change = insert_note(source, Fraction(5), "new")
        self.assertIsNotNone(change)
        self.assertEqual(errors(source), [])
        self.assertIn({"id": "new", "beat": 5, "x": change["x"], "y": change["y"], "color": change["color"],
                       "direction": change["direction"]}, source["sections"][0]["notes"])

    def test_a_crowded_onset_is_left_alone(self):
        self.assertIsNone(insert_note(arrangement([0, 1, 2, 3]), Fraction(17, 8), "new"),
                          "another note sits within a quarter beat")
        self.assertIsNone(insert_note(arrangement([0, 0.5, 1, 1.5, 2, 2.5]), Fraction(7, 4), "new"),
                          "both hands swing within half a beat")

    def test_locked_sections_are_not_filled(self):
        source = arrangement([0, 1, 8, 9])
        source["sections"][0]["locked"] = True
        self.assertIsNone(insert_note(source, Fraction(5), "new"))


class RepairAudioTests(unittest.TestCase):
    def test_an_unmapped_vocal_line_gains_notes(self):
        # The voice sings four onsets in beats 16-20 over a held sustain, and the map follows only the drums
        # on beats 0-15 and 21-39: the bar is flagged, then mapped.
        beats = list(range(16)) + list(range(21, 40))
        evidence = report(range(64), vocals=[16.5, 17.5, 18.5, 19.5], sustains=[(16.25, 20)])
        before = critique_arrangement(arrangement(beats), evidence)
        flagged = [w for w in before["warnings"] if w["code"] == "vocal_line_unmapped"]
        self.assertEqual(flagged[0]["beats"], [16, 20])
        result = repair_audio(arrangement(beats), evidence)
        added = [c["beat"] for c in result["changes"] if c["action"] == "added"]
        self.assertTrue({16.5, 17.5, 18.5, 19.5} & set(added))
        self.assertNotIn("vocal_line_unmapped", {w["code"] for w in result["remaining"]})
        self.assertEqual(errors(result["arrangement"]), [])

    def test_an_unmapped_melody_gains_notes_on_its_pitch_changes(self):
        # A drumless, voiceless intro: the pad's line changes pitch six times in two bars, but the map
        # plays only beats 0 and 7, then the band enters with drums from beat 8.
        beats = [0, 7] + list(range(8, 40))
        evidence = report(range(8, 64))
        evidence["layers"]["mix"]["events"] = [
            {"id": f"mix:melody_change:{b}", "seconds": b / 2, "method": "melody_change", "strength": 0.6}
            for b in (1, 2.15, 3, 4.5, 5.5, 6.5)]
        before = critique_arrangement(arrangement(beats), evidence)
        flagged = [w for w in before["warnings"] if w["code"] == "melody_unmapped"]
        self.assertEqual(flagged[0]["beats"], [0, 8])
        result = repair_audio(arrangement(beats), evidence)
        added = {c["beat"] for c in result["changes"] if c["action"] == "added" and c["code"] == "melody_unmapped"}
        # The late legato change at 2.15 takes the quarter beat nearest it, never a triplet or sixteenth.
        self.assertTrue(added <= {1, 2.25, 3, 4.5, 5.5, 6.5} and len(added) >= 4, result["changes"])
        self.assertNotIn("melody_unmapped", {w["code"] for w in result["remaining"]})
        self.assertEqual(errors(result["arrangement"]), [])

    def test_missing_evidence_is_an_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "music analyze"):
            repair_audio(arrangement([0, 1]), None)


def quiet_intro(*, intro_energy=0.4):
    """64 s at 120 BPM, a note every half beat on a melody onset; the first 16 s are thin and soft."""
    beats = [b / 2 for b in range(256)]
    evidence = report([], vocals=[4, 12])
    evidence["layers"]["other"] = {"events": [{"id": f"other:{i}", "seconds": b / 2, "method": "spectral_flux",
                                               "strength": 0.3 if b % 1 else 0.6} for i, b in enumerate(beats)]}
    evidence["source"]["duration_seconds"] = 64.0
    evidence["passages"] = [{"start_seconds": t, "end_seconds": t + 2,
                             "energy_ratio": intro_energy if t < 16 else 1.0,
                             "support_score": 0.2 if t < 16 else 1.0} for t in range(0, 64, 2)]
    return arrangement(beats, length=128), evidence


class QuietDensityTests(unittest.TestCase):
    def test_a_thin_quiet_intro_mapped_like_the_full_band_is_flagged(self):
        source, evidence = quiet_intro()
        flagged = [w for w in critique_arrangement(source, evidence)["warnings"]
                   if w["code"] == "density_exceeds_audio"]
        self.assertEqual(len(flagged), 1)
        # Windows straddling the intro's end still average as thin, so the run ends a little past beat 32.
        self.assertEqual(flagged[0]["beats"][0], 0)
        self.assertTrue(32 <= flagged[0]["beats"][1] <= 40)
        self.assertEqual(flagged[0]["threshold"], 1.5)
        self.assertGreater(flagged[0]["value"], 1.5)

    def test_a_loud_drumless_passage_is_not_quiet(self):
        source, evidence = quiet_intro(intro_energy=1.0)
        self.assertNotIn("density_exceeds_audio", {w["code"] for w in critique_arrangement(source, evidence)["warnings"]})

    def test_without_passages_the_check_does_not_run(self):
        source, evidence = quiet_intro()
        del evidence["passages"]
        self.assertEqual(critique_arrangement(source, evidence)["metrics"]["quiet_density"], {"checked": False})

    def test_repair_thins_the_intro_evenly_and_keeps_the_voice(self):
        source, evidence = quiet_intro()
        result = repair_audio(source, evidence)
        self.assertNotIn("density_exceeds_audio", {w["code"] for w in result["remaining"]})
        self.assertEqual(errors(result["arrangement"]), [])
        removed = [c["beat"] for c in result["changes"] if c["action"] == "removed"]
        self.assertTrue(removed and all(b < 32 for b in removed), "only the quiet intro is thinned")
        kept = sorted(float(n["beat"]) for n in result["arrangement"]["sections"][0]["notes"])
        self.assertTrue({4.0, 12.0} <= set(kept), "notes on vocal onsets stay")
        intro = [b for b in kept if b < 32]
        self.assertLessEqual(max(y - x for x, y in zip(intro, intro[1:])), 4, "no phrase empties")
        self.assertLessEqual(len(intro), 1.5 * 0.2 * 4 * 16 + 1)

    def test_notes_on_sung_onsets_do_not_count_as_excess(self):
        # A soft verse where the voice articulates every half beat: the notes follow the singing, not the grid.
        source, evidence = quiet_intro()
        evidence["layers"]["vocals"]["events"] = [{"id": f"vocals:{i}", "seconds": i / 4, "method": "spectral_flux",
                                                   "strength": 0.8} for i in range(64)]
        self.assertNotIn("density_exceeds_audio",
                         {w["code"] for w in critique_arrangement(source, evidence)["warnings"]})
        self.assertEqual(thin_quiet(source, evidence)["changes"], [])

    def test_locked_sections_are_not_thinned(self):
        source, evidence = quiet_intro()
        source["sections"][0]["locked"] = True
        self.assertEqual(thin_quiet(source, evidence)["changes"], [])

    def test_density_is_settled_after_the_lead_rebuild(self):
        # A soft intro sits within its allowance while the body is an eighth stream. Rebuilding the body on
        # its offbeat guitar lead halves the full-band reference density, pushing the intro over it: the
        # final thinning pass settles it (Living a Lie, 2026-09-23).
        intro = list(range(0, 32, 2))
        source = arrangement(intro + [b / 2 for b in range(64, 256)], length=128)
        source["sections"][0]["musical_focus"] = [{"id": "riff", "start_beat": 32, "end_beat": 128, "lead": "guitar",
                                                   "weights": {"guitar": 0.6, "drums": 0.4},
                                                   "intent": "offbeat guitar riff"}]
        evidence = report(range(32, 128))
        evidence["source"]["duration_seconds"] = 64.0
        evidence["layers"]["other"] = {"events": [{"id": f"o{b}", "seconds": b / 2, "method": "spectral_flux",
                                                   "strength": 0.6} for b in intro]}
        evidence["layers"]["guitar"] = {"events": [{"id": f"g{b}", "seconds": (b + 0.5) / 2,
                                                    "method": "spectral_flux", "strength": 0.8} for b in range(32, 128)]}
        evidence["passages"] = [{"start_seconds": t, "end_seconds": t + 2, "energy_ratio": 0.4 if t < 16 else 1.0,
                                 "support_score": 0.2 if t < 16 else 1.0} for t in range(0, 64, 2)]
        self.assertNotIn("density_exceeds_audio",
                         {w["code"] for w in critique_arrangement(source, evidence)["warnings"]})
        result = repair_audio(source, evidence)
        actions = {(c["action"], c.get("code")) for c in result["changes"]}
        self.assertIn(("rebuilt", "lead_rhythm_diluted"), actions)
        self.assertIn(("removed", "density_exceeds_audio"), actions)
        self.assertNotIn("density_exceeds_audio", {w["code"] for w in result["remaining"]})
        self.assertEqual(errors(result["arrangement"]), [])


class RepairAudioCommandTests(unittest.TestCase):
    def test_dry_run_reports_and_real_run_saves(self):
        from pathlib import Path
        from unittest import mock
        from sabermapper.__main__ import main
        from sabermapper.projects import ProjectStore
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder))
            created = store.create(demo=True)
            project, revision = created["project"]["id"], created["revision"]
            source = store.get(project)["arrangement"]
            first = source["sections"][0]
            start = Fraction(str(first["start_beat"]))
            evidence = report([float(start + Fraction(str(n["beat"]))) for s in source["sections"]
                               for n in s["notes"]], seconds=60)
            first["notes"][0]["beat"] = str(Fraction(str(first["notes"][0]["beat"])) + Fraction(1, 4))
            if errors(source):
                self.skipTest("demo shape changed; fixture edit introduced a structural error")
            revision = store.save(project, source, revision)["revision"]
            with mock.patch("sabermapper.musical.latest_run", return_value=("run", evidence)):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(["project", "repair-audio", project, "--workspace", folder,
                                           "--revision", revision, "--dry-run"]), 0)
                dry = json.loads(out.getvalue())
                self.assertFalse(dry["saved"])
                self.assertEqual(dry["summary"]["moved"], 1)
                self.assertEqual(store.get(project)["revision"], revision)
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(["project", "repair-audio", project, "--workspace", folder,
                                           "--revision", revision]), 0)
                saved = json.loads(out.getvalue())
                self.assertTrue(saved["saved"])
                self.assertEqual(store.get(project)["revision"], saved["revision"])


class ReweightFocusTests(unittest.TestCase):
    def fixture(self, lead, weights):
        arr = arrangement([0, 2, 4, 6], length=32)
        arr["sections"][0]["musical_focus"] = [{"id": "intro", "start_beat": 0, "end_beat": 16, "lead": lead,
                                                 "weights": weights, "intent": "fixture"}]
        contour = lambda quiet: [{"seconds": i / 10, "energy": (0.0005 if quiet and i < 80 else 1.0)}
                                 for i in range(160)]
        rep = {"layers": {"other": {"events": [], "energy_contour": contour(False)},
                          "vocals": {"events": [], "energy_contour": contour(True)}}}
        return arr, rep

    def test_absent_stem_is_dropped_from_the_weights(self):
        arr, rep = self.fixture("other", {"other": 0.6, "vocals": 0.4})
        result = reweight_focus(arr, rep)
        phrase = result["arrangement"]["sections"][0]["musical_focus"][0]
        self.assertEqual((phrase["lead"], phrase["weights"]), ("other", {"other": 1.0}))
        self.assertEqual(result["changes"][0]["absent"], ["vocals"])
        self.assertEqual(arr["sections"][0]["musical_focus"][0]["weights"], {"other": 0.6, "vocals": 0.4})

    def test_an_absent_lead_hands_over_to_the_most_active_stem(self):
        arr, rep = self.fixture("vocals", {"vocals": 1.0})
        phrase = reweight_focus(arr, rep)["arrangement"]["sections"][0]["musical_focus"][0]
        self.assertEqual((phrase["lead"], phrase["weights"]), ("other", {"other": 1.0}))
        self.assertIn("absent here", phrase["intent"])


if __name__ == "__main__":
    unittest.main()
