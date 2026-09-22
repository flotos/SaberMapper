"""Audio grounding: playing audio must be mapped, and notes must sit on sounds."""
import copy
import io
import json
from contextlib import redirect_stdout
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.audio import _hash
from sabermapper.audio_grounding import audio_findings, note_support, underfilled_spans
from sabermapper.critique import critique_arrangement
from sabermapper.projects import ProjectStore


def arrangement(beats, *, length=48):
    # 120 BPM, offset 0: beat b sits at b / 2 seconds.
    notes = [{"id": f"n{i}", "beat": b, "x": i % 4, "y": 0, "color": i % 2, "direction": 1}
             for i, b in enumerate(beats)]
    return {"schema_version": 1,
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0.0},
            "difficulty": {"name": "ExpertPlus", "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": [{"id": "s", "start_beat": 0, "length_beats": length, "intent": "fixture",
                                        "locked": False, "resolved": True, "notes": notes, "patterns": []}]}


def report(seconds=24.0, *, quiet_until=0.0, sha256="fixture"):
    """A loud drum groove on every half second, optionally near-silent before quiet_until."""
    contour = [{"seconds": i / 10, "energy": 0.001 if i / 10 < quiet_until else 0.5}
               for i in range(int(seconds * 10))]
    drums = [{"id": f"drums:{i}", "seconds": i / 2, "method": "spectral_flux", "strength": 0.8}
             for i in range(int(seconds * 2)) if i / 2 >= quiet_until]
    return {"source": {"sha256": sha256, "duration_seconds": seconds}, "created_at": "2026-09-22T00:00:00+00:00",
            "backend": "fixture", "preset": "balanced",
            "layers": {"mix": {"events": [], "energy_contour": contour}, "drums": {"events": drums}}}


class UnderfilledAudioTests(unittest.TestCase):
    def test_a_long_unmapped_groove_is_blocking(self):
        # The groove plays from 0 s; notes only start at 14 s (beat 28), like an intro left empty.
        spans = underfilled_spans(arrangement([28 + i for i in range(20)]), report())
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["start_seconds"], 0.0)
        self.assertGreaterEqual(spans[0]["end_seconds"], 13.0)
        self.assertTrue(spans[0]["blocking"])
        self.assertEqual(spans[0]["strong_onsets"]["drums"], spans[0]["seconds"] * 2)
        _, findings = audio_findings(arrangement([28 + i for i in range(20)]), report())
        self.assertEqual([f["severity"] for f in findings if f["code"] == "audio_unmapped"], ["error"])

    def test_one_note_every_few_seconds_does_not_count_as_mapped(self):
        # A lone note every 5 s must not break the stretch into short, harmless gaps.
        spans = underfilled_spans(arrangement([0, 10, 20, 30, 40]), report())
        self.assertTrue(any(s["blocking"] for s in spans))

    def test_a_mapped_groove_passes(self):
        self.assertEqual(underfilled_spans(arrangement([i for i in range(48)]), report()), [])

    def test_a_genuinely_quiet_intro_may_stay_empty(self):
        spans = underfilled_spans(arrangement([24 + i for i in range(24)]), report(quiet_until=12.0))
        self.assertEqual(spans, [])

    def test_a_short_gap_is_only_a_warning(self):
        beats = [b for b in range(48) if not 10 <= b < 20]  # 5 s hole
        _, findings = audio_findings(arrangement(beats), report())
        self.assertEqual({f["severity"] for f in findings if f["code"] == "audio_unmapped"}, {"warning"})


class NoteSupportTests(unittest.TestCase):
    def test_notes_off_every_sound_are_flagged_as_a_run(self):
        # Drum hits sit on whole beats; beats 10.5..13.5 fall between them.
        beats = list(range(10)) + [10.5, 11.5, 12.5, 13.5] + list(range(14, 40))
        support = note_support(arrangement(beats), report())
        self.assertEqual(support["supported"], len(beats) - 4)
        self.assertEqual(support["unsupported_runs"][0]["start_beat"], 10.5)
        self.assertEqual(support["unsupported_runs"][0]["note_times"], 4)
        result = critique_arrangement(arrangement(beats), report())
        self.assertIn("note_without_audio", {w["code"] for w in result["warnings"]})
        self.assertTrue(all(w["severity"] == "warning" for w in result["warnings"]))

    def test_mostly_grid_filler_lowers_support(self):
        beats = [b + 0.25 for b in range(40)]
        _, findings = audio_findings(arrangement(beats), report())
        self.assertIn("low_audio_support", {f["code"] for f in findings})

    def test_without_evidence_nothing_is_checked(self):
        self.assertEqual(audio_findings(arrangement([0, 1]), None), ({"checked": False}, []))


class ProjectAudioGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        created = self.store.create(demo=True)
        self.project_id, self.revision = created["project"]["id"], created["revision"]
        directory = self.store.directory(self.project_id)
        run = directory / "musical" / ("a" * 32)
        run.mkdir(parents=True)
        seconds = created["project"]["duration_seconds"]
        (run / "report.json").write_text(json.dumps(report(seconds, sha256=_hash(directory / "song.ogg"))),
                                         encoding="utf-8")
        self.arrangement = created["arrangement"]

    def emptied(self):
        edited = copy.deepcopy(self.arrangement)
        for section in edited["sections"][:3]:
            section["notes"], section["patterns"] = [], []
        return edited

    def test_save_refuses_long_unmapped_audio_and_names_the_stretch(self):
        with self.assertRaisesRegex(ValueError, r"Audio left unmapped .*song is playing"):
            self.store.save(self.project_id, self.emptied(), self.revision)

    def test_get_reports_the_audio_check(self):
        record = self.store.get(self.project_id)
        self.assertEqual(record["audio_check"]["run_id"], "a" * 32)
        self.assertTrue(record["audio_check"]["checked"])

    def test_project_critique_uses_the_newest_matching_run_by_default(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["project", "critique", self.project_id, "--workspace", self.temp.name]), 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["run_id"], "a" * 32)
        self.assertTrue(result["metrics"]["audio"]["checked"])

    def test_critique_without_evidence_says_so(self):
        other = self.store.create(demo=True)["project"]["id"]
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["project", "critique", other, "--workspace", self.temp.name]), 0)
        result = json.loads(stream.getvalue())
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["warnings"][0]["code"], "audio_evidence_missing")


if __name__ == "__main__":
    unittest.main()
