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
        self.assertEqual(sum(2 if n.get("double") else 1 for n in notes), result["note_count"])
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


def song():
    """96 beats at 120 BPM: a quiet opening on melody changes, a guitar riff over sixteenth kicks with crashes,
    a sung verse with a held note and a gap in the voice, then the riff again."""
    def ev(layer, beats, strength, method="spectral_flux"):
        return [{"id": f"{layer}:{method}:{i}", "seconds": b / 2, "method": method, "strength": strength}
                for i, b in enumerate(sorted(beats))]
    riff_bars = [b for b in range(16, 48)] + [b for b in range(80, 96)]
    chugs = [b + off for b in riff_bars if b % 4 != 3 for off in (0, 0.5)]
    kicks = [b + off for b in riff_bars for off in (0, 0.25, 0.5, 0.75)]
    crashes = [b for b in riff_bars if b % 4 == 0]
    verse_drums = [b + off for b in range(48, 80) for off in (0, 0.5)]
    syllables = [b + off for b in range(48, 80) for off in (0, 0.5)
                 if not (56 < b + off < 59.5) and not (64 < b + off < 67)]
    sustains = [{"id": f"s{i}", "start_seconds": a / 2, "end_seconds": b / 2, "strength": 0.3}
                for i, (a, b) in enumerate([(48.1, 49.3), (52.1, 53.3), (60.1, 61.3), (64.1, 65.3), (68.1, 69.3),
                                            (76.1, 77.3)])]
    sustains += [{"id": "held", "start_seconds": 28.0, "end_seconds": 29.7, "strength": 0.4},   # beats 56-59.4
                 {"id": "named", "start_seconds": 36.0, "end_seconds": 36.45, "strength": 0.3}]  # beats 72-72.9
    melody = [b / 4 for b in range(0, 64)]
    mix_attacks = sorted(set(chugs) | set(kicks) | set(verse_drums) | set(syllables))
    passages = []
    for t in range(0, 48, 2):
        quiet = t < 8
        passages.append({"start_seconds": t, "end_seconds": t + 2, "drum_onset_density": 0 if quiet else 4,
                         "energy_ratio": 0.5 if quiet else 1.0, "support_score": 0.4 if quiet else 0.95})
    contour = [{"seconds": i / 10, "energy": 0.5} for i in range(480)]
    return {"source": {"sha256": "fixture", "duration_seconds": 48}, "created_at": "2026-09-23T00:00:00+00:00",
            "backend": "fixture", "preset": "balanced", "passages": passages,
            "layers": {"mix": {"events": ev("mix", mix_attacks, 0.6) + ev("mix", melody, 0.6, "melody_change"),
                               "energy_contour": contour},
                       "drums": {"events": ev("drums", kicks + verse_drums, 0.6) + ev("drums", crashes, 0.95)},
                       "guitar": {"events": ev("guitar", chugs, 0.9)},
                       "vocals": {"events": ev("vocals", syllables, 0.8), "sustains": sustains}}}


def song_arrangement(tier="band"):
    return {"schema_version": "0.1",
            "song": {"title": "Rules", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 18, "spawn_offset_beats": 0, "target_tier": tier},
            "motifs": {},
            "sections": [{"id": name, "start_beat": a, "length_beats": b - a, "intent": name, "locked": False,
                          "resolved": True, "patterns": [], "notes": []}
                         for name, a, b in (("intro", 0, 16), ("riff", 16, 48), ("verse", 48, 80), ("out", 80, 96))]}


class MusicalRuleTests(unittest.TestCase):
    """The rules SM-036 records from authoring Living a Lie, each drafted for every song."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = song()
        cls.result = propose_rhythm(song_arrangement(), cls.evidence, held=[36.0])
        cls.bars = {b["start_beat"]: b for b in cls.result["bars"]}
        cls.times = {Fraction(str(n["beat"])): n for b in cls.result["bars"] for n in b["notes"]}
        cls.placed = place_arrangement(cls.result["draft"])["arrangement"]

    def test_each_bar_has_one_role(self):
        self.assertEqual([self.bars[b]["role"] for b in (0, 20, 52)], ["soft", "riff", "sung"])

    def test_soft_bars_map_changes_half_a_beat_apart(self):
        soft = sorted(t for t in self.times if t < 16)
        self.assertTrue(soft)
        self.assertTrue(all(b - a >= Fraction(1, 2) for a, b in zip(soft, soft[1:])), soft)

    def test_riff_bars_follow_the_riff_and_keep_its_rests(self):
        riff = [t for t in self.times if 20 <= t < 24]
        for chug in (20, Fraction(41, 2), 21, Fraction(43, 2), 22, Fraction(45, 2)):
            self.assertIn(chug, riff)
        between = [t for t in riff if t % 1 in (Fraction(1, 4),) and t < 23]
        self.assertEqual(between, [], "a kick between two chugs stays unmapped")

    def test_sung_bars_follow_the_syllables_and_the_band_fills_the_gaps(self):
        sung = [t for t in self.times if 48 <= t < 56]
        roles = [self.times[t]["role"] for t in sung]
        self.assertGreaterEqual(roles.count("vocals"), 0.6 * 16)
        band = roles.count("band")
        self.assertLess(band, 0.25 * len(roles) + 1e-9)
        gap = [self.times[t]["role"] for t in self.times if 64 < t < 67]
        self.assertIn("band_gap", gap, "the band carries the voice's gap")

    def test_held_singing_becomes_an_arc_with_the_band_on_the_free_hand(self):
        arcs = {(Fraction(str(a["head"])), Fraction(str(a["tail"]))) for a in self.result["arcs"]}
        self.assertTrue(any(head == 56 and 59 < tail < 60 for head, tail in arcs), arcs)
        self.assertIn(72, {head for head, _ in arcs}, "a hold the user named becomes an arc")
        arc = next(a for s in self.placed["sections"] for a in s.get("arcs", []) if s["id"] == "verse"
                   and Fraction(str(a["beat"])) + 48 == 56)
        tail = 48 + Fraction(str(arc["tail_beat"]))
        inside = [n for n in expanded_notes(self.placed) if 56 < n["beat"] < tail]
        self.assertTrue(inside)
        self.assertTrue(all(n["color"] != arc["color"] for n in inside))

    def test_doubles_mark_the_heaviest_accents_on_one_parity(self):
        from sabermapper.movement import _parity
        doubles = [t for t, n in self.times.items() if n.get("double")]
        self.assertTrue(doubles)
        for beat in doubles:
            self.assertNotIn(beat - Fraction(1, 4), [t for t in self.times if self.times[t]["role"] != "lead"])
            pair = [n for n in expanded_notes(self.placed) if n["beat"] == beat]
            self.assertEqual(sorted(n["color"] for n in pair), [0, 1])
            self.assertEqual(len({_parity(n["direction"], n["color"], 0) for n in pair}), 1, pair)

    def test_the_draft_raises_none_of_the_checked_findings(self):
        warnings = critique_arrangement(self.placed, self.evidence)["warnings"]
        self.assertEqual([w["code"] for w in warnings if w["code"] in TARGET_CODES], [])
        self.assertEqual([d for d in validate_arrangement(self.placed) if d["severity"] == "error"], [])


if __name__ == "__main__":
    unittest.main()
