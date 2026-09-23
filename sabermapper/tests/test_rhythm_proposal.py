"""SM-036: rhythm drafts follow the critique's own rules, so an unedited draft raises none of its rhythm findings."""
import io
import json
from contextlib import redirect_stdout
from fractions import Fraction
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.arrangement import expanded_notes
from sabermapper.audio import _hash
from sabermapper.critique import critique_arrangement
from sabermapper.placement import place_arrangement
from sabermapper.projects import ProjectStore
from sabermapper.rhythm_proposal import TARGET_CODES, propose_rhythm
from sabermapper.validation import validate_arrangement

BEATS = 128  # 120 BPM: beat b sits at b / 2 seconds


def arrangement(*, arcs=(), lead_from=32, lead_to=96, tier=None):
    focus = [{"id": "riff", "start_beat": lead_from, "end_beat": lead_to, "lead": "guitar",
              "weights": {"guitar": 0.6, "drums": 0.4}, "intent": "Follow the offbeat guitar riff."}]
    difficulty = {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0}
    if tier:
        difficulty["target_tier"] = tier
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": difficulty, "motifs": {},
            "sections": [{"id": "s", "start_beat": 0, "length_beats": BEATS, "intent": "fixture", "locked": False,
                          "resolved": True, "patterns": [], "musical_focus": focus, "arcs": list(arcs),
                          "notes": []}]}


def events(layer, beats, strength=0.8, method="spectral_flux"):
    return [{"id": f"{layer}:{i}", "seconds": b / 2, "method": method, "strength": strength}
            for i, b in enumerate(beats)]


def report(*, sixteenths=False, seconds=BEATS / 2):
    """A soft intro (kick per beat), a loud body (kick per half beat, offbeat guitar riff), then a thin outro."""
    drums = [b / 2 for b in range(BEATS * 2) if (b / 2 < 32 and b % 2 == 0) or 32 <= b / 2 < 112]
    drums += [b for b in range(112, BEATS, 2)]
    guitar = [b + 0.5 for b in range(32, 96)]
    if sixteenths:
        guitar += [b + 0.25 for b in range(64, 96)] + [b + 0.75 for b in range(64, 96)]
    kicks = events("drums", [b for b in drums if b < seconds * 2], 0.8) + events(
        "drums", [b + 0.25 for b in range(32, 112) if b < seconds * 2], 0.35)
    riff = events("guitar", sorted(b for b in guitar if b < seconds * 2), 0.9)
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(int(seconds * 10))]

    def passage(t):
        if t < 16:
            return 0.45, 0.95
        if t >= 56:
            return 0.5, 0.4  # thin and soft: few drum hits
        return 1.0, 0.95
    return {"source": {"sha256": "fixture", "duration_seconds": seconds}, "created_at": "2026-09-23T00:00:00+00:00",
            "backend": "fixture", "preset": "balanced",
            "layers": {"mix": {"events": [], "energy_contour": contour}, "drums": {"events": kicks},
                       "guitar": {"events": riff}, "vocals": {"events": [], "sustains": []}},
            "passages": [{"start_seconds": t, "end_seconds": t + 2, "drum_onset_density": 2.0,
                          "energy_ratio": passage(t)[0], "support_score": passage(t)[1]}
                         for t in range(0, int(seconds), 2)]}


def target_findings(draft, evidence):
    placed = place_arrangement(draft)["arrangement"]
    warnings = critique_arrangement(placed, evidence)["warnings"]
    return placed, [w for w in warnings if w["code"] in TARGET_CODES]


class ProposalTests(unittest.TestCase):
    def test_an_unedited_draft_raises_no_rhythm_finding(self):
        evidence = report()
        result = propose_rhythm(arrangement(), evidence)
        self.assertEqual(result["remaining"], [])
        placed, found = target_findings(result["draft"], evidence)
        self.assertEqual(found, [])
        self.assertEqual([d for d in validate_arrangement(placed) if d["severity"] == "error"], [])
        self.assertGreater(result["note_count"], 100)
        notes = [n for bar in result["bars"] for n in bar["notes"]]
        self.assertEqual(len(notes), result["note_count"])
        self.assertTrue(all(n["evidence"]["layer"] and n["role"] for n in notes), "every time names its sound")

    def test_the_draft_follows_the_lead_and_the_loudness(self):
        result = propose_rhythm(arrangement(), report())
        bars = {b["start_beat"]: b for b in result["bars"]}
        riff = [Fraction(str(n["beat"])) for n in bars[48]["notes"]]
        self.assertTrue(all(beat.denominator == 2 for beat in riff if bars[48]["lead"] == "guitar"),
                        "the declared riff plays on the offbeats")
        self.assertEqual(bars[48]["lead"], "guitar")
        soft, loud = len(bars[8]["notes"]), len(bars[48]["notes"])
        self.assertLess(soft, loud, "the soft intro plays lighter than the heavy body")
        self.assertTrue(bars[116]["quiet"])
        self.assertLessEqual(len(bars[116]["notes"]), 4, "a thin outro takes one attack per beat at most")

    def test_the_draft_is_rhythm_only_and_keeps_arcs(self):
        arc = {"id": "hold", "beat": 40, "x": 1, "y": 0, "color": 0, "direction": 1, "tail_beat": 48, "tail_x": 1,
               "tail_y": 1, "tail_direction": 0}
        source = arrangement(arcs=[arc])
        source["sections"][0]["notes"] = [{"id": "head", "beat": 40, "x": 1, "y": 0, "color": 0, "direction": 1},
                                          {"id": "tail", "beat": 48, "x": 1, "y": 1, "color": 0, "direction": 0},
                                          {"id": "old", "beat": 41}]
        evidence = report()
        result = propose_rhythm(source, evidence)
        notes = result["draft"]["sections"][0]["notes"]
        self.assertIn("head", [n["id"] for n in notes])
        self.assertNotIn("old", [n["id"] for n in notes], "the range's free notes are replaced")
        drafted = [n for n in notes if n["id"].startswith("r-")]
        self.assertTrue(drafted and all(set(n) == {"id", "beat"} for n in drafted))
        placed, found = target_findings(result["draft"], evidence)
        self.assertEqual(found, [])
        inside = [n for n in expanded_notes(placed) if 40 < n["beat"] < 48]
        self.assertTrue(inside and all(n["color"] == 1 for n in inside), "the held hand stays free")

    def test_a_range_leaves_the_rest_of_the_map_alone(self):
        full = propose_rhythm(arrangement(), report())["draft"]
        start = {n["id"]: n for n in full["sections"][0]["notes"]}
        result = propose_rhythm(full, report(), start=64, end=80)
        after = {n["id"]: n for n in result["draft"]["sections"][0]["notes"]}
        for note_id, note in start.items():
            beat = Fraction(str(note["beat"]))
            if not 64 <= beat < 80:
                self.assertEqual(after.get(note_id), note, note_id)
        self.assertEqual(result["range"], [64, 80])

    def test_the_tier_sets_how_much_of_a_rolling_lead_is_drafted(self):
        evidence = report(sixteenths=True)
        easy = propose_rhythm(arrangement(tier="below_band"), evidence)
        hard = propose_rhythm(arrangement(tier="challenge"), evidence)
        count = lambda r: sum(len(b["notes"]) for b in r["bars"] if 64 <= b["start_beat"] < 96)
        self.assertLess(count(easy), count(hard))
        self.assertFalse([n for b in easy["bars"] for n in b["notes"] if n["role"] == "run"])
        self.assertEqual(target_findings(hard["draft"], evidence)[1], [])

    def test_without_evidence_the_proposal_refuses(self):
        with self.assertRaisesRegex(ValueError, "music analyze"):
            propose_rhythm(arrangement(), None)


class ProposalCommandTests(unittest.TestCase):
    def test_propose_writes_a_draft_that_saves_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(folder)
            created = store.create(demo=True)
            project, revision = created["project"]["id"], created["revision"]
            directory = store.directory(project)
            run = directory / "musical" / ("b" * 32)
            run.mkdir(parents=True)
            evidence = report(seconds=int(created["project"]["duration_seconds"]))
            evidence["source"]["sha256"] = _hash(directory / "song.ogg")
            (run / "report.json").write_text(json.dumps(evidence), encoding="utf-8")
            draft = directory.parent.parent / "draft.json"
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(main(["music", "rhythm", project, "--workspace", folder, "--propose",
                                       "--draft", str(draft)]), 0)
            result = json.loads(stream.getvalue())
            self.assertEqual(result["revision"], revision)
            self.assertTrue(draft.exists())
            check = store.check(project, arrangement=json.loads(draft.read_text(encoding="utf-8")))
            self.assertEqual(check["blocking_count"], 0, [f for f in check["findings"] if f["blocking"]])
            saved = store.save(project, json.loads(draft.read_text(encoding="utf-8")), revision)
            self.assertGreater(saved["placement"]["placed_notes"], 0)
            self.assertEqual(main(["music", "rhythm", project, "--workspace", folder]), 1, "a grid needs a range")


class AudioSuggestionTests(unittest.TestCase):
    """project check suggests concrete edits for the audio codes; applying one clears its finding."""

    def check(self, draft, evidence):
        from sabermapper.check import check_arrangement
        return check_arrangement(draft, evidence)

    def apply(self, draft, suggestion):
        from sabermapper.check import apply_suggestion
        return apply_suggestion(draft, suggestion)

    def test_an_unmapped_stretch_gets_the_rhythm_draft_for_it(self):
        evidence = report()
        draft = propose_rhythm(arrangement(), evidence)["draft"]
        section = draft["sections"][0]
        section["notes"] = [n for n in section["notes"] if not 40 <= Fraction(str(n["beat"])) < 64]
        found = [f for f in self.check(draft, evidence)["findings"] if f["code"] == "audio_unmapped"]
        self.assertTrue(found and found[0]["blocking"])
        suggestion = found[0]["suggestions"][0]
        self.assertEqual(suggestion["op"], "add")
        fixed = self.apply(draft, suggestion)
        after = self.check(fixed, evidence)
        self.assertFalse([f for f in after["findings"] if f["code"] == "audio_unmapped"])
        self.assertEqual(after["blocking_count"], 0)

    def test_a_missed_lead_gets_its_attacks(self):
        evidence = report()
        draft = propose_rhythm(arrangement(), evidence)["draft"]
        section = draft["sections"][0]
        section["notes"] = [n for n in section["notes"]
                            if not (48 <= Fraction(str(n["beat"])) < 52 and Fraction(str(n["beat"])).denominator == 2)]
        found = [f for f in self.check(draft, evidence)["findings"] if f["code"] == "lead_rhythm_unmapped"]
        self.assertTrue(found)
        fixed = self.apply(draft, found[0]["suggestions"][0])
        self.assertFalse([f for f in self.check(fixed, evidence)["findings"] if f["code"] == "lead_rhythm_unmapped"
                          and f["beats"] == found[0]["beats"]])

    def test_a_note_off_every_sound_moves_onto_one(self):
        evidence = report()
        draft = propose_rhythm(arrangement(), evidence)["draft"]
        section = draft["sections"][0]
        for note in section["notes"]:
            beat = Fraction(str(note["beat"]))
            if 16 <= beat < 24:
                note["beat"] = str(beat + Fraction(3, 8))  # a grid shift that leaves the kicks
        found = [f for f in self.check(draft, evidence)["findings"] if f["code"] == "note_without_audio"]
        self.assertTrue(found)
        fixed = draft
        for suggestion in found[0]["suggestions"]:
            self.assertIn(suggestion["op"], ("retime", "remove"))
            fixed = self.apply(fixed, suggestion)
        self.assertFalse([f for f in self.check(fixed, evidence)["findings"] if f["code"] == "note_without_audio"])

    def test_a_focus_on_an_absent_stem_gets_new_weights(self):
        evidence = report()
        contour = [{"seconds": i / 10, "energy": 0.5} for i in range(BEATS * 5)]
        silent = [{"seconds": i / 10, "energy": 1e-6 if 16 <= i / 10 < 48 else 0.5} for i in range(BEATS * 5)]
        evidence["layers"]["guitar"].update(kind="audio_layer", energy_contour=silent)
        evidence["layers"]["drums"].update(kind="audio_layer", energy_contour=contour)
        draft = propose_rhythm(arrangement(), evidence)["draft"]
        found = [f for f in self.check(draft, evidence)["findings"] if f["code"] == "focus_on_quiet_stem"]
        self.assertTrue(found)
        suggestion = found[0]["suggestions"][0]
        self.assertEqual((suggestion["op"], suggestion["lead"]), ("set_weights", "drums"))
        fixed = self.apply(draft, suggestion)
        self.assertFalse([f for f in self.check(fixed, evidence)["findings"] if f["code"] == "focus_on_quiet_stem"])


if __name__ == "__main__":
    unittest.main()
