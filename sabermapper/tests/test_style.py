"""A map's style: brainstormed per song, stored, and followed by the draft, the placer and project check."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.critique import critique_arrangement
from sabermapper.placement import DEFAULT_STYLE, place_arrangement, placement_style
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.storage import read_json, write_json
from sabermapper.style import (DEFAULTS, RUBRIC, SETTINGS, StyleError, arrangement_style, get_style, save_style,
                               style_metrics, style_template, validate_document)
from sabermapper.validation import validate_arrangement


def stream(length=64, bpm=150):
    """A steady eighth-note stream of rhythm-only notes with a few doubles: the placer chooses everything."""
    notes = [{"id": f"n{i:03d}", "beat": i / 2} for i in range(length * 2)]
    notes += [{"id": f"d{b:03d}", "beat": b} for b in range(8, length, 8)]
    return {"schema_version": "0.1", "song": {"title": "F", "artist": "T", "bpm": bpm, "audio_offset_seconds": 0},
            "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0}, "motifs": {},
            "sections": [{"id": "a", "start_beat": 0, "length_beats": length, "intent": "fixture", "locked": False,
                          "resolved": True, "notes": notes, "patterns": []}]}


def styled(settings, arrangement=None):
    result = copy.deepcopy(arrangement or stream())
    result["style"] = {"idea": "One idea.", "grounding": ["the fixture"], "settings": settings}
    return result


def measured(settings):
    return style_metrics(place_arrangement(styled(settings))["arrangement"])


def candidate(cid, **settings):
    return {"id": cid, "idea": f"Idea {cid}.", "grounding": ["the gallop riff in the overview"],
            "settings": {**DEFAULTS, **settings}, "signatures": [],
            "rubric": {name: {"score": 4, "why": "because"} for name in RUBRIC}}


def document(selected="a"):
    return {"schema_version": "1.0", "selected": selected,
            "candidates": [candidate("a", flow="angular"), candidate("b", flow="round"),
                           candidate("c", diagonals="many")]}


class PlacementStyleTests(unittest.TestCase):
    def test_a_map_without_a_style_places_as_one_with_every_middle_setting(self):
        self.assertEqual(placement_style(stream()), DEFAULT_STYLE)
        self.assertEqual(placement_style(styled(dict(DEFAULTS))), DEFAULT_STYLE)
        self.assertEqual(place_arrangement(stream())["arrangement"]["sections"],
                         place_arrangement(styled(dict(DEFAULTS)))["arrangement"]["sections"])

    def test_flow_moves_the_turn_away_from_clean_reversals(self):
        round_, balanced, angular = (measured({"flow": f})["turn_degrees"] for f in SETTINGS["flow"])
        self.assertLess(round_, balanced)
        self.assertLess(balanced, angular)
        self.assertLessEqual(round_, 14)
        self.assertGreaterEqual(angular, 34)

    def test_diagonals_and_top_row_follow_their_settings(self):
        few, many = (measured({"diagonals": d})["diagonal_share"] for d in ("few", "many"))
        self.assertLess(few, many)
        low, high = (measured({"top_row": t})["top_row_share"] for t in ("low", "high"))
        self.assertLess(low, high)

    def test_every_style_places_without_breaking_a_rule(self):
        for name, values in SETTINGS.items():
            for value in values:
                result = place_arrangement(styled({name: value}), strict=False)
                self.assertEqual(result["errors"], [], (name, value))


class ArrangementStyleTests(unittest.TestCase):
    def test_validation_rejects_a_malformed_style(self):
        self.assertNotIn("invalid_style", {d["code"] for d in validate_arrangement(styled({"flow": "round"}))})
        for broken in ({"idea": "", "grounding": ["x"], "settings": {}},
                       {"idea": "x", "grounding": [], "settings": {}},
                       {"idea": "x", "grounding": ["x"], "settings": {"flow": "wobbly"}},
                       {"idea": "x", "grounding": ["x"], "settings": {"speed": "fast"}},
                       {"idea": "x", "grounding": ["x"], "settings": {}, "signatures": [{"theme": "none", "move": "x"}]}):
            draft = stream()
            draft["style"] = broken
            self.assertIn("invalid_style", {d["code"] for d in validate_arrangement(draft)}, broken)

    def test_project_check_reports_a_missing_style_and_a_style_the_notes_contradict(self):
        placed = place_arrangement(stream())["arrangement"]
        self.assertIn("style_missing", [w["code"] for w in critique_arrangement(placed, None)["warnings"]])
        placed["style"] = styled({"flow": "angular"})["style"]  # the notes stay placed with the balanced costs
        warnings = [w for w in critique_arrangement(placed, None)["warnings"] if w["code"] == "style_drift"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("flow angular", warnings[0]["message"])
        replaced = place_arrangement(styled({"flow": "angular"}))["arrangement"]
        self.assertNotIn("style_drift", [w["code"] for w in critique_arrangement(replaced, None)["warnings"]])


class DraftStyleTests(unittest.TestCase):
    def test_accents_and_arcs_tune_the_rhythm_draft(self):
        from sabermapper.rhythm_proposal import propose_rhythm
        from tests.test_rhythm_proposal import song, song_arrangement
        evidence = song()

        def draft(**settings):
            result = propose_rhythm(styled(settings, song_arrangement()), evidence, held=[36.0])
            doubles = sum(1 for bar in result["bars"] for n in bar["notes"] if n.get("double"))
            return doubles, len(result["arcs"])
        sparse, heavy = draft(accents="sparse"), draft(accents="heavy")
        self.assertLess(sparse[0], heavy[0])
        self.assertLessEqual(draft(arcs="sparse")[1], draft(arcs="lavish")[1])

    def test_theme_variation_sets_how_echoes_mirror(self):
        from sabermapper.recurrence import propose_themes
        from tests.test_recurrence import arrangement, listen_sections
        sections = listen_sections()
        sections[3]["repeats"] = [{"section_id": "sec-01", "similarity": 0.8, "transposed_semitones": 0}]
        mirrors = {}
        for variation in SETTINGS["theme_variation"]:
            theme, = propose_themes(styled({"theme_variation": variation}, arrangement()), None, sections)
            mirrors[variation] = [bool(span.get("mirror")) for span in theme["spans"][1:]]
        self.assertEqual(mirrors, {"repeat": [False, False], "alternate": [False, True], "mirror": [True, True]})


class BrainstormTests(unittest.TestCase):
    def test_three_distinct_scored_candidates_and_a_selection(self):
        result = validate_document(document())
        self.assertTrue(result["saveable"], result["diagnostics"])
        self.assertEqual(arrangement_style(document())["settings"]["flow"], "angular")
        alike = document()
        alike["candidates"][2]["settings"] = dict(alike["candidates"][0]["settings"])
        self.assertIn("candidates_alike", {d["code"] for d in validate_document(alike)["diagnostics"]})
        two = document()
        two["candidates"].pop()
        self.assertIn("candidate_count", {d["code"] for d in validate_document(two)["diagnostics"]})
        unscored = document()
        unscored["candidates"][0]["rubric"]["grounded"]["score"] = 7
        self.assertIn("selected_invalid", {d["code"] for d in validate_document(unscored)["diagnostics"]})
        self.assertFalse(validate_document(document(selected=None))["saveable"])

    def test_save_template_get_and_cli_on_a_project(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(temp)
            project = store.create(demo=True)["project"]["id"]
            template = style_template(store, project)
            self.assertEqual(len(template["style"]["candidates"]), 3)
            self.assertIn("measured_style", template["evidence"])
            saved = save_style(store, project, document(), "none")
            self.assertEqual(saved["arrangement_style"]["source"]["candidate"], "a")
            with self.assertRaises(ConflictError):
                save_style(store, project, document("b"), "none")
            with self.assertRaises(StyleError):
                save_style(store, project, document(selected=None), saved["revision"])
            self.assertEqual(get_style(store, project)["selected"]["settings"]["flow"], "angular")
            path = Path(temp) / "doc.json"
            write_json(path, document("b"))
            out = io.StringIO()
            with redirect_stdout(out):
                main(["style", "save", project, "--workspace", temp, "--file", str(path),
                      "--revision", saved["revision"]])
            self.assertEqual(json.loads(out.getvalue())["arrangement_style"]["settings"]["flow"], "round")
            self.assertEqual(template["current_revision"], None)


if __name__ == "__main__":
    unittest.main()
