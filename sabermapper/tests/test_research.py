import io
import json
import argparse
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from sabermapper.corpus import (CorpusStore, _vanilla_exclusion_reasons, beat_saber_map_hash, beat_saber_map_hashes, corpus_report, coverage_report,
                                discover_maps, ingest_seeds, safe_zip_members,
                                seeds_from_candidate_snapshot, select_corpus_seeds, process_all)
from sabermapper.evaluation import SplitRegistry, evaluation_report
from sabermapper.learning import LabelStore, evaluate_ranker, label_report, train_and_record, train_pairwise
from sabermapper.patterns import (_family_key, extract_patterns, group_patterns,
                                  near_matches, pattern_distance, retrieve_patterns)
from sabermapper.profile import summarize_scores
from sabermapper.research_cli import dispatch, register_subcommands


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return out.getvalue()


class ResearchTests(unittest.TestCase):
    def test_archive_safety_and_resume(self):
        with self.assertRaises(ValueError):
            safe_zip_members(archive({"../escape.dat": "{}"}))
        with self.assertRaises(ValueError):
            safe_zip_members(archive({"big.dat": "x" * 100}), max_expanded_bytes=50)
        modern = archive({"Info.dat": json.dumps({"version": "4.0.0", "audio": {"bpm": 140},
            "difficultyBeatmaps": [{"characteristic": "Standard", "difficulty": "Expert",
                                    "beatmapDataFilename": "Expert.dat", "lightshowDataFilename": "Lights.dat"}]}),
            "Expert.dat": '{"version":"4.0.0"}', "Lights.dat": "{}"})
        self.assertTrue(beat_saber_map_hashes(modern))
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            data = archive({"Info.dat": json.dumps({"_beatsPerMinute": 120,
                "_difficultyBeatmapSets": [{"_beatmapCharacteristicName": "Standard",
                 "_difficultyBeatmaps": [{"_difficulty": "Expert", "_beatmapFilename": "Expert.dat"}]}]}),
                "Expert.dat": json.dumps({
                "version": "3.3.0", "colorNotes": [
                    {"b": 0, "x": 0, "y": 1, "c": 0, "d": 1},
                    {"b": 0.5, "x": 1, "y": 1, "c": 1, "d": 0}]})})
            hash_ = "A" * 40
            self.assertEqual(len(beat_saber_map_hash(data)), 40)
            row = store.import_archive(data, version_hash=hash_, provenance={"kind": "test"})
            self.assertEqual(store.read_map_files(hash_)["Expert.dat"]["version"], "3.3.0")
            self.assertEqual(store.process_maps(hash_)["status"], "processed")
            self.assertEqual(len(store.process_maps(hash_)["patterns"]), 1)
            self.assertEqual(corpus_report(store.rows())["status"], {"processed": 1})
            self.assertNotIn("processing_json", store.rows()[0])
            self.assertIn("processing_json", store.rows(include_processing=True)[0])
            self.assertEqual(row["archive_sha256"], store.import_archive(data, version_hash=hash_)["archive_sha256"])
            store.process_maps(hash_)
            self.assertTrue(store.processed(hash_)["patterns"])
            self.assertTrue(store.discard_archive_after_processing(hash_)["archive_deleted"])
            self.assertFalse((Path(root) / "archives" / f"{row['archive_sha256']}.zip").exists())
            store.close()

    def test_process_all_and_persistent_labels(self):
        info = {"_beatsPerMinute": 120, "_difficultyBeatmapSets": [{
            "_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": [
                {"_difficulty": "Expert", "_beatmapFilename": "Expert.dat"}]}]}
        diff = {"version": "3.3.0", "colorNotes": [
            {"b": 0, "x": 0, "y": 1, "c": 0, "d": 1},
            {"b": .5, "x": 1, "y": 1, "c": 1, "d": 0}]}
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            store.import_archive(archive({"Info.dat": json.dumps(info), "Expert.dat": json.dumps(diff)}),
                                 version_hash="C" * 40)
            first = process_all(store)
            self.assertEqual(first["pattern_count"], 1)
            self.assertEqual(process_all(store)["processed_now"], [])
            self.assertEqual(len(json.loads((Path(root) / "patterns.json").read_text())["patterns"]), 1)
            self.assertEqual(store.library_summary(limit=1)["pattern_count"], 1)
            self.assertFalse(store.library_summary(limit=1)["stale"])
            self.assertEqual(len(store.library_summary(limit=0)["patterns"]), 0)
            hash_ = "C" * 40
            saved = store.processed(hash_)
            saved["parser_fingerprint"] = "old-parser"
            store.db.execute("UPDATE maps SET processing_json=? WHERE version_hash=?", (json.dumps(saved), hash_))
            store.db.commit()
            self.assertIsNone(store.valid_processed(hash_))
            self.assertEqual(store.process_all()["processed_now"], [hash_])
            self.assertIsNotNone(store.valid_processed(hash_))
            store.discard_archive_after_processing(hash_)
            saved = store.processed(hash_)
            saved["parser_fingerprint"] = "old-parser"
            store.db.execute("UPDATE maps SET processing_json=? WHERE version_hash=?", (json.dumps(saved), hash_))
            store.db.commit()
            self.assertIsNone(store.valid_processed(hash_))
            self.assertEqual(store.process_all()["processed_now"], [hash_])
            labels = LabelStore(Path(root) / "labels.json")
            label = {"left_id": "a", "right_id": "b", "winner": "left", "dimension": "flow",
                     "rater": "user", "origin": "human", "family_id": "song", "seconds_spent": 30}
            labels.append(label)
            self.assertEqual(len(LabelStore(Path(root) / "labels.json").labels()), 1)
            with self.assertRaises(ValueError):
                labels.append(label)
            artifact = train_and_record({}, [], train_families=set(), heldout_families=set(),
                                        output=Path(root) / "model.json")
            self.assertEqual(artifact["evaluation"]["decision"], "no_go")
            self.assertFalse(artifact["active"])
            self.assertEqual(len(artifact["labels_sha256"]), 64)
            store.close()

    def test_mod_required_difficulty_keeps_ir_but_no_vanilla_patterns(self):
        info = {"_beatsPerMinute": 120, "_difficultyBeatmapSets": [{
            "_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": [{
                "_difficulty": "Expert", "_beatmapFilename": "Expert.dat",
                "_customData": {"_requirements": ["Noodle Extensions"]}}]}]}
        chart = {"version": "3.3.0", "colorNotes": [
            {"b": 0, "x": 0, "y": 1, "c": 0, "d": 1},
            {"b": .5, "x": 1, "y": 1, "c": 1, "d": 0}]}
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            store.import_archive(archive({"Info.dat": json.dumps(info), "Expert.dat": json.dumps(chart)}),
                                 version_hash="D" * 40)
            result = store.process_maps("D" * 40)
            self.assertEqual(result["status"], "processed")
            self.assertIn("Expert.dat", result["normalized"])
            self.assertEqual(result["patterns"], [])
            self.assertIn("required mods", result["excluded_difficulties"]["Expert.dat"][0])
            store.close()

    def test_pattern_grouping_retrieval_and_leakage_filter(self):
        upright = [{"beat": 0, "x": 0, "y": 1, "color": 0, "direction": 0},
                   {"beat": 1, "x": 1, "y": 1, "color": 1, "direction": 2}]
        mirrored = [{"beat": 0, "x": 3, "y": 1, "color": 1, "direction": 0},
                    {"beat": 1, "x": 2, "y": 1, "color": 0, "direction": 3}]
        self.assertEqual(_family_key(upright), _family_key(mirrored))
        self.assertEqual(pattern_distance({"notes": upright}, {"notes": mirrored})["total"], 0)
        self.assertEqual(near_matches([], max_pairs=0), [])
        notes = [{"id": str(i), "beat": beat, "x": i % 4, "y": 1,
                  "color": i % 2, "direction": 1} for i, beat in enumerate([0, 0.5, 4, 4.5, 8, 8.5])]
        patterns = extract_patterns({"notes": notes, "bpm": 120}, version_hash="A" * 40,
                                    difficulty="Expert", min_notes=2)
        self.assertEqual(len(patterns), 3)
        self.assertTrue(group_patterns(patterns))
        self.assertEqual(retrieve_patterns(patterns, forbidden_versions={"A" * 40}), [])
        self.assertEqual(retrieve_patterns(patterns, forbidden_song_families={"version:" + "A" * 40}), [])
        self.assertEqual(len(retrieve_patterns(patterns, bpm=120)), len(group_patterns(patterns)))
        with_wall = extract_patterns({"notes": notes, "bpm": 120, "obstacles": [
            {"beat": 0, "duration_beats": 1}]}, version_hash="A" * 40,
            difficulty="Expert", min_notes=2)
        self.assertTrue(with_wall[0]["unsupported_motion"])
        self.assertEqual(with_wall[0]["motion_context"]["obstacles"], 1)
        self.assertEqual(_vanilla_exclusion_reasons({}, {"unsupported": [
            {"path": "basicBeatmapEvents", "value": []}]}), [])
        self.assertTrue(_vanilla_exclusion_reasons({"_customData": {"_requirements": ["Noodle Extensions"]}},
                                                  {"unsupported": []}))
        self.assertTrue(_vanilla_exclusion_reasons({}, {"unsupported": [
            {"path": "colorNotes[0].customData", "value": {"animation": {}}}]}))

    def test_discovery_pages_and_quota(self):
        pages = [json.dumps({"docs": [{"id": "one"}, {"id": "two"}]}).encode(),
                 json.dumps({"docs": [{"id": "two"}, {"id": "three"}]}).encode()]
        with patch("sabermapper.corpus._read_url", side_effect=pages) as fetch:
            self.assertEqual([x["id"] for x in discover_maps("tech", pages=2)], ["one", "two", "three"])
            self.assertEqual(fetch.call_count, 2)
        candidates = [{"hash": "A" * 40, "cohort": "style"}, {"hash": "B" * 40, "cohort": "style"},
                      {"hash": "C" * 40, "cohort": "contrast", "ne": True}]
        selected = select_corpus_seeds(candidates, quotas={"style": 1, "contrast": 1})
        self.assertEqual(len(selected["selected"]), 1)
        self.assertEqual(selected["gaps"], {"style": 0, "contrast": 1})
        snapshot = {"retrievedAtUtc": "2026-01-01", "candidates": [
            {"hash": "A" * 40, "difficulty": "Expert", "ne": False},
            {"hash": "B" * 40, "difficulty": "Hard", "ne": True}]}
        seeds = seeds_from_candidate_snapshot(snapshot)
        self.assertEqual(seeds[1]["cohort"], "unsupported_modded")
        self.assertEqual(coverage_report(seeds, []) ["unresolved_count"], 2)
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            self.assertEqual(ingest_seeds(store, seeds, max_items=2, max_new_archive_bytes=0)["results"][0]["status"], "budget_exhausted")
            store.close()

    def test_split_alias_quarantine_and_leakage(self):
        with tempfile.TemporaryDirectory() as root:
            registry = SplitRegistry(Path(root) / "splits.json")
            first = registry.resolve(version_hash="A" * 40, audio_sha256="audio", family_id="song-a")
            self.assertEqual(registry.resolve(version_hash="B" * 40, audio_sha256="audio")["family_id"], "song-a")
            self.assertEqual(registry.resolve(version_hash="A" * 40, family_id="song-b")["split"], "quarantine")
            marked = registry.mark_development(["A" * 40, "B" * 40], reason="pilot inspection")
            self.assertEqual(marked["marked_families"], 1)
            self.assertEqual(registry.resolve(version_hash="B" * 40)["split"], "development")
            frozen = registry.freeze([{"version_hash": "B" * 40, "audio_sha256": "audio"}], Path(root) / "release.json")
            self.assertEqual(frozen["records"][0]["split"], "development")
            self.assertIn("retired_evaluation_memberships", frozen)
        with self.assertRaises(ValueError):
            evaluation_report(predicted=[.7, .6], expected=[1, 1], family_ids=["same", "same"], split=["train", "test"])
        with self.assertRaises(ValueError):
            evaluation_report(predicted=[.7, .6], expected=[1, 1], family_ids=["same", "same"], split=["validation", "test"])

    def test_profile_snapshot_and_no_go_learning(self):
        path = Path(__file__).parents[1] / "planning" / "research" / "scoresaber-snapshot.json"
        snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
        summary = summarize_scores(snapshot)
        self.assertEqual(summary["since_2024"]["count"], 9)
        self.assertAlmostEqual(summary["since_2024"]["mean_stars"], 7.43, places=2)
        self.assertAlmostEqual(summary["since_2024"]["mean_accuracy_percent"], 80.50, places=2)
        self.assertEqual(train_pairwise({}, [], allowed_families=set())["status"], "no_go")
        self.assertEqual(label_report([])["count"], 0)

    def test_training_filters_song_families_and_dimensions(self):
        patterns = {
            "left": {"song_family_id": "train-song", "family_key": "motif-1", "nps": 6,
                     "active_nps": 7, "note_count": 12, "length_beats": 4},
            "right": {"song_family_id": "train-song", "family_key": "motif-2", "nps": 3,
                      "active_nps": 4, "note_count": 6, "length_beats": 4},
            "held": {"song_family_id": "held-song", "family_key": "motif-1", "nps": 5,
                     "active_nps": 5, "note_count": 10, "length_beats": 4}}
        labels = [{"left_id": "left", "right_id": "right", "winner": "left" if i % 2 else "right",
                   "dimension": "flow", "rater": "user", "origin": "human", "family_id": "train-song",
                   "seconds_spent": 20} for i in range(20)]
        labels.append({"left_id": "held", "right_id": "right", "winner": "left", "dimension": "flow",
                       "rater": "user", "origin": "human", "family_id": "held-song", "seconds_spent": 20})
        labels.append({"left_id": "left", "right_id": "right", "winner": "left", "dimension": "enjoyment",
                       "rater": "user", "origin": "human", "family_id": "train-song",
                       "seconds_spent": 20, "feedback_reference": "session:1"})
        model = train_pairwise(patterns, labels, allowed_families={"train-song"}, dimension="flow")
        self.assertEqual(model["training_count"], 20)
        self.assertEqual(model["dimension"], "flow")
        self.assertEqual(evaluate_ranker(model, patterns, labels, heldout_families={"held-song"})["decision"], "no_go")

    def test_research_cli_local_import_and_profile(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)
        register_subcommands(subparsers)
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            zip_path = folder / "test.zip"
            zip_path.write_bytes(archive({"Info.dat": "{}"}))
            args = parser.parse_args(["corpus", "import", str(zip_path), "--hash", "A" * 40,
                                      "--workspace", root])
            with patch("builtins.print"):
                self.assertTrue(dispatch(args))
                self.assertTrue(dispatch(parser.parse_args(["corpus", "status", "--workspace", root])))
            snapshot = folder / "snapshot.json"
            snapshot.write_text(json.dumps({"player": {"id": "user"}, "scores": []}), encoding="utf-8")
            with patch("builtins.print"):
                dispatch(parser.parse_args(["profile", "calibrate", str(snapshot), "--workspace", root]))
            self.assertEqual(json.loads((folder / "player-profile.json").read_text())["player_id"], "user")


if __name__ == "__main__":
    unittest.main()
