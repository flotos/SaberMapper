"""Concept artifact: validation, references to listen evidence, revision-aware saving, template and CLI."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.concept import (ConceptError, concept_template, evidence_index, get_concept, save_concept,
                                 validate_concept)
from sabermapper.listen import latest_listen, listen_project
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.storage import read_json, write_json
from tests.test_moments import build_run


def rubric(score=4):
    return {name: {"score": score, "why": f"{name} reason"} for name in
            ("grounded", "one_idea", "develops", "readable", "buildable")}


def candidate(cid, moments, sections, score=4):
    return {"id": cid, "title": f"Treatment {cid}", "central_idea": f"Idea {cid}: a ring of light tightens.",
            "grounding": {"moments": [moments[0]], "mood": [sections[0]], "lyrics": [],
                          "notes": "The drop is where the ring closes."},
            "palette": ["#101020", "#f0c040"],
            "motifs": [{"name": "ring", "description": "floor ring",
                        "development": {sections[0]: "faint", sections[-1]: "closed"}},
                       {"name": "sparks", "description": "sparks on hits",
                        "development": {sections[0]: "few", sections[-1]: "many"}}],
            "key_moments": [{"moment_id": moments[0], "treatment": "ring appears", "held_for_end": False},
                            {"moment_id": moments[-1], "treatment": "ring closes", "held_for_end": True}],
            "possession": "none", "buildability": {"tiers": [1, 2], "notes": "procedural ring shader, particle preset"},
            "rubric": rubric(score)}


class ConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = ProjectStore(cls.temp.name)
        cls.project = cls.store.create(demo=True)["project"]["id"]
        cls.directory = cls.store.directory(cls.project)
        build_run(cls.directory)
        listen_project(cls.store, cls.project)
        cls.listen = latest_listen(cls.directory)
        cls.moments = [m["id"] for m in cls.listen["moments"]]
        cls.sections = [s["id"] for s in cls.listen["sections"]]
        cls.evidence = evidence_index(cls.listen, read_json(cls.directory / "arrangement.json"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        (self.directory / "concept.json").unlink(missing_ok=True)
        shutil.rmtree(self.directory / "concept-history", ignore_errors=True)

    def document(self, selected="a"):
        return {"schema_version": "1.0", "listen_run": self.listen["run_id"],
                "steering": [{"text": "warmer colours", "source": "user", "applied": "palettes shifted to amber"}],
                "candidates": [candidate("a", self.moments, self.sections, 5),
                               {**candidate("b", self.moments, self.sections, 3), "central_idea": "Idea b: smoke."},
                               {**candidate("c", self.moments, self.sections, 2), "central_idea": "Idea c: mirrors."}],
                "selected": selected}

    def codes(self, result, candidate_id=None):
        return {d["code"] for d in result["diagnostics"] if candidate_id is None or d["candidate"] == candidate_id}

    def test_valid_document_computes_totals_and_ranking(self):
        result = validate_concept(self.document(), self.evidence)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual({k: v["total"] for k, v in result["candidates"].items()}, {"a": 25, "b": 15, "c": 10})
        self.assertEqual(result["ranking"], ["a", "b", "c"])

    def test_reference_and_structure_errors(self):
        document = self.document(selected=None)
        broken = document["candidates"][1]
        broken["grounding"]["moments"] = ["drop-99"]
        broken["grounding"]["lyrics"] = ["lyr-001"]
        broken["palette"] = ["#12345", "red", "#000000"]
        broken["motifs"] = broken["motifs"][:1]
        broken["key_moments"][0]["held_for_end"] = True
        broken["possession"] = "feet"
        broken["buildability"]["tiers"] = [4]
        broken["rubric"]["readable"] = {"score": 6, "why": "two\nlines"}
        document["candidates"][2]["motifs"][0]["development"] = {"nowhere": "x", self.sections[0]: "y"}
        result = validate_concept(document, self.evidence)
        self.assertEqual(self.codes(result, "b"),
                         {"grounding_unknown_moment", "lyrics_unavailable", "palette_hex", "motif_count",
                          "held_for_end_count", "possession_value", "buildability_tiers", "rubric_score", "rubric_why"})
        self.assertEqual(self.codes(result, "c"), {"motif_unknown_section"})
        self.assertTrue(result["candidates"]["a"]["valid"])
        self.assertFalse(result["candidates"]["b"]["valid"])
        self.assertIsNone(result["candidates"]["b"]["total"])
        self.assertTrue(result["saveable"])  # drafts may keep invalid candidates while none of them is selected

    def test_document_level_rules(self):
        document = self.document()
        document["candidates"] = document["candidates"][:2]
        self.assertIn("candidate_count", self.codes(validate_concept(document, self.evidence)))
        document = self.document()
        document["candidates"][1]["id"] = "a"
        self.assertIn("candidate_id", self.codes(validate_concept(document, self.evidence)))
        document = self.document(selected="b")
        result = validate_concept(document, self.evidence)
        self.assertIn("selected_not_top", self.codes(result))
        self.assertFalse(result["saveable"])
        document["selection_reason"] = "The user asked for smoke."
        self.assertTrue(validate_concept(document, self.evidence)["saveable"])
        document = self.document()
        first, last = document["candidates"][0]["key_moments"]
        first["held_for_end"], last["held_for_end"] = True, False
        self.assertIn("held_for_end_not_last", self.codes(validate_concept(document, self.evidence)))
        document["listen_run"] = "0" * 32
        self.assertIn("listen_run_mismatch", self.codes(validate_concept(document, self.evidence)))

    def test_selecting_an_invalid_candidate_is_refused(self):
        document = self.document()
        document["candidates"][0]["palette"] = ["#zzzzzz", "#000000"]
        with self.assertRaises(ConceptError) as raised:
            save_concept(self.store, self.project, document, "none")
        self.assertEqual(raised.exception.code, "concept_invalid")
        self.assertIn("selected_invalid", {d["code"] for d in raised.exception.details["diagnostics"]})
        self.assertFalse((self.directory / "concept.json").exists())

    def test_save_is_revision_aware_with_history(self):
        first = save_concept(self.store, self.project, self.document(), "none")
        self.assertIsNone(first["previous_revision"])
        self.assertEqual(first["totals"], {"a": 25, "b": 15, "c": 10})
        with self.assertRaises(ConflictError):
            save_concept(self.store, self.project, self.document(), "none")
        changed = self.document()
        changed["steering"].append({"text": "less smoke", "source": "user"})
        with self.assertRaises(ConflictError):
            save_concept(self.store, self.project, changed, "0" * 64)
        second = save_concept(self.store, self.project, changed, first["revision"])
        self.assertEqual(second["previous_revision"], first["revision"])
        stored = get_concept(self.store, self.project)
        self.assertEqual(stored["revision"], second["revision"])
        self.assertEqual(stored["concept"], changed)
        self.assertTrue(stored["current_validation"]["valid"])
        self.assertEqual([h["revision"] for h in stored["history"]], [second["revision"], first["revision"]])
        self.assertTrue((self.directory / "concept-history" / f"{first['revision']}.json").exists())

    def test_template_prefills_evidence_and_is_not_valid_until_filled(self):
        template = concept_template(self.store, self.project)
        self.assertEqual(template["run_id"], self.listen["run_id"])
        self.assertEqual([m["id"] for m in template["evidence"]["moments"]], self.moments)
        self.assertIn("valence", template["evidence"]["sections"][0])
        self.assertIsNone(template["evidence"]["lyrics"])
        self.assertTrue(template["evidence"]["lyrics_hint"])
        self.assertEqual(len(template["concept"]["candidates"]), 3)
        result = validate_concept(template["concept"], self.evidence)
        self.assertFalse(result["valid"])
        self.assertIn("rubric_score", self.codes(result))

    def test_listen_missing_is_structured(self):
        store = ProjectStore(Path(self.temp.name) / "other")
        project = store.create(demo=True)["project"]["id"]
        with self.assertRaises(ConceptError) as raised:
            concept_template(store, project)
        self.assertEqual(raised.exception.code, "listen_missing")

    def test_cli_round_trip(self):
        path = Path(self.temp.name) / "concept.json"
        write_json(path, {"concept": self.document()})  # template-shaped wrapper is accepted
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["concept", "validate", "--project", self.project, "--workspace", self.temp.name,
                                   "--file", str(path)]), 0)
        self.assertTrue(json.loads(out.getvalue())["valid"])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["concept", "save", self.project, "--workspace", self.temp.name, "--file", str(path),
                                   "--revision", "none"]), 0)
        revision = json.loads(out.getvalue())["revision"]
        out = io.StringIO()
        with redirect_stdout(out):
            main(["concept", "get", self.project, "--workspace", self.temp.name])
        self.assertEqual(json.loads(out.getvalue())["revision"], revision)
        bad = copy.deepcopy(self.document())
        bad["candidates"][0]["possession"] = "tail"
        write_json(path, bad)
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as exited:
            main(["concept", "validate", "--project", self.project, "--workspace", self.temp.name, "--file", str(path)])
        self.assertEqual(exited.exception.code, 1)
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as exited:
            main(["concept", "save", self.project, "--workspace", self.temp.name, "--file", str(path),
                  "--revision", revision])
        self.assertEqual(exited.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "concept_invalid")


if __name__ == "__main__":
    unittest.main()
