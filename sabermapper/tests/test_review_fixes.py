"""Regressions for the code-review fixes: ranker crash, mapper credit, Info 2.1 fields,
legacy v2 tempo events, catalog-backed retrieval, and pre-analysis save checks."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from sabermapper import compile_arrangement, validate_arrangement
from sabermapper.corpus import CorpusStore, _vanilla_exclusion_reasons, process_all
from sabermapper.export import export_arrangement
from sabermapper.learning import evaluate_ranker, train_and_record, train_pairwise
from sabermapper.mapio import parse_map
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.server import corpus_action

from test_arrangement import arrangement
from test_export import ogg, png
from test_research import archive


HUMAN_LABEL = {"left_id": "A:Expert:0:4", "right_id": "B:Expert:0:4", "winner": "left",
               "dimension": "enjoyment", "rater": "me", "origin": "human", "family_id": "f1",
               "seconds_spent": 10, "feedback_reference": "fb-1"}


class RankerLabelResolutionTests(unittest.TestCase):
    def test_unresolved_pattern_ids_yield_no_go_not_crash(self):
        result = train_pairwise({}, [HUMAN_LABEL], allowed_families={"f1"})
        self.assertEqual(result["status"], "no_go")
        self.assertEqual(result["unresolved_pattern_labels"], 1)
        self.assertEqual(result["count"], 0)
        model = {"status": "trained_not_promoted", "dimension": "enjoyment",
                 "weights": [0, 0, 0, 0], "scale": [1, 1, 1, 1]}
        self.assertEqual(evaluate_ranker(model, {}, [HUMAN_LABEL], heldout_families={"f1"})["decision"], "no_go")
        with tempfile.TemporaryDirectory() as root:
            artifact = train_and_record({}, [HUMAN_LABEL], train_families={"f1"}, heldout_families={"f2"},
                                        output=Path(root) / "ranker.json")
        self.assertEqual(artifact["model"]["status"], "no_go")
        self.assertFalse(artifact["active"])


class MapperCreditAndInfoTests(unittest.TestCase):
    def test_optional_mapper_is_validated(self):
        source = arrangement()
        source["mapper"] = "Someone"
        self.assertEqual([d for d in validate_arrangement(source) if d["severity"] == "error"], [])
        compile_arrangement(source)
        for bad in ("", "   ", 3):
            source["mapper"] = bad
            codes = {d["code"] for d in validate_arrangement(source) if d["severity"] == "error"}
            self.assertIn("invalid_metadata", codes, bad)

    def test_export_writes_mapper_and_info_2_1_collections(self):
        source = arrangement()
        source["mapper"] = "Someone"
        source["sections"][0]["start_beat"] = 0
        with tempfile.TemporaryDirectory() as root:
            audio, cover, output = Path(root, "song.ogg"), Path(root, "cover.png"), Path(root, "map.zip")
            audio.write_bytes(ogg())
            cover.write_bytes(png())
            export_arrangement(source, audio, cover, output)
            with ZipFile(output) as bundle:
                info = json.loads(bundle.read("Info.dat"))
        self.assertEqual(info["_version"], "2.1.0")
        self.assertEqual(info["_levelAuthorName"], "Someone")
        self.assertEqual(info["_environmentNames"], ["DefaultEnvironment"])
        self.assertEqual(info["_colorSchemes"], [])
        difficulty = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0]
        self.assertEqual((difficulty["_beatmapColorSchemeIdx"], difficulty["_environmentNameIdx"]), (0, 0))


class LegacyTempoEventTests(unittest.TestCase):
    def test_v2_type_100_without_float_value_is_recorded_and_excluded(self):
        data = {"_version": "2.0.0",
                "_notes": [{"_time": 1, "_lineIndex": 1, "_lineLayer": 0, "_type": 0, "_cutDirection": 1}],
                "_events": [{"_time": 0, "_type": 100, "_value": 8}]}
        parsed = parse_map(data, bpm=120)
        self.assertEqual(len(parsed["notes"]), 1)
        self.assertEqual(parsed["tempo_events"][0]["bpm"], 120)
        legacy = [u for u in parsed["unsupported"] if u["path"] == "_events[0]"]
        self.assertTrue(legacy and legacy[0]["reason"].startswith("legacy BPM event"))
        self.assertTrue(any(reason.startswith("uninterpreted tempo event") for reason in _vanilla_exclusion_reasons({}, parsed)))


class CatalogRetrievalTests(unittest.TestCase):
    def test_catalog_patterns_track_processing_state(self):
        info = {"_beatsPerMinute": 120, "_difficultyBeatmapSets": [{
            "_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": [
                {"_difficulty": "Expert", "_beatmapFilename": "Expert.dat"}]}]}
        diff = {"version": "3.3.0", "colorNotes": [
            {"b": 0, "x": 0, "y": 1, "c": 0, "d": 1},
            {"b": .5, "x": 1, "y": 1, "c": 1, "d": 0}]}
        hash_ = "D" * 40
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            self.assertEqual(store.catalog_patterns(), [])
            store.import_archive(archive({"Info.dat": json.dumps(info), "Expert.dat": json.dumps(diff)}), version_hash=hash_)
            process_all(store)
            patterns = store.catalog_patterns()
            self.assertEqual([p["version_hash"] for p in patterns], [hash_])
            index_path = Path(root) / "library-index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["parser_fingerprint"] = "old-parser"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            self.assertEqual(store.catalog_patterns(), [], "stale catalog must not be served")
            process_all(store)
            self.assertEqual(len(store.catalog_patterns()), 1)
            (Path(root) / "splits.json").write_text(json.dumps({
                "schema_version": "1.0", "families": {}, "aliases": {},
                "quarantine": [{"version_hash": hash_}], "retired_evaluation_memberships": []}), encoding="utf-8")
            self.assertEqual(store.catalog_patterns(), [], "quarantined versions are excluded")
            store.close()

    def test_server_retrieve_and_pattern_use_catalog(self):
        info = {"_beatsPerMinute": 120, "_difficultyBeatmapSets": [{
            "_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": [
                {"_difficulty": "Expert", "_beatmapFilename": "Expert.dat"}]}]}
        diff = {"version": "3.3.0", "colorNotes": [
            {"b": 0, "x": 0, "y": 1, "c": 0, "d": 1},
            {"b": .5, "x": 1, "y": 1, "c": 1, "d": 0}]}
        with tempfile.TemporaryDirectory() as workspace:
            store = CorpusStore(Path(workspace) / "corpus")
            store.import_archive(archive({"Info.dat": json.dumps(info), "Expert.dat": json.dumps(diff)}), version_hash="E" * 40)
            process_all(store)
            store.close()
            found = corpus_action(Path(workspace), "retrieve", {"bpm": 120, "limit": 5})
            self.assertEqual(len(found), 1)
            pattern_id = found[0]["pattern"]["id"]
            self.assertEqual(corpus_action(Path(workspace), "pattern", {"id": pattern_id})["id"], pattern_id)
            with self.assertRaises(ValueError):
                corpus_action(Path(workspace), "pattern", {"id": "F" * 40 + ":Expert:0:4"})


class PreAnalysisCheckTests(unittest.TestCase):
    def test_check_save_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as root:
            store = ProjectStore(root)
            created = store.create(demo=True)
            pid, revision = created["project"]["id"], created["revision"]
            path = store.directory(pid) / "arrangement.json"
            before = path.read_bytes()
            changed = copy.deepcopy(created["arrangement"])
            changed["song"]["bpm"] += 1
            self.assertEqual(store.check_save(pid, changed, revision), created["arrangement"])
            with self.assertRaises(ConflictError):
                store.check_save(pid, changed, "0" * 64)
            locked = store.set_lock(pid, changed["sections"][0]["id"], True, revision)
            retimed = copy.deepcopy(locked["arrangement"])
            retimed["song"]["bpm"] += 1
            with self.assertRaises(ConflictError):
                store.check_save(pid, retimed, locked["revision"])
            self.assertEqual(store.get(pid)["revision"], locked["revision"])
            self.assertNotEqual(path.read_bytes(), before)  # only the lock write changed the file
            self.assertEqual(len(list((store.directory(pid) / "history").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
