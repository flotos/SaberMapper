import json
from pathlib import Path
import tempfile
import unittest

from sabermapper.corpus import CorpusStore
from sabermapper.corpus_analysis import analyze_corpus, chart_records, filter_patterns, pattern_tags, rating_summary
from scripts.expand_player_corpus import select_candidates


class CorpusAnalysisTests(unittest.TestCase):
    def test_rating_denominators_and_boundaries(self):
        records = [{"version_hash": str(i), "stars": value} for i, value in enumerate([None, 0, 6, 6.5, 8, 9])]
        summary = rating_summary(records)
        self.assertEqual(summary["rated_charts"], 4)
        self.assertEqual(summary["unrated_charts"], 2)
        self.assertEqual(summary["mean_stars"], 7.375)
        self.assertEqual(summary["within_target"], 2)
        self.assertEqual(summary["above_target"], 1)

    def test_ratings_join_exact_version_and_characteristic(self):
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            metadata = {"id": "test", "versions": [
                {"hash": "B"*40, "diffs": [{"difficulty": "Expert", "characteristic": "Standard", "stars": 12}]},
                {"hash": "a"*40, "diffs": [
                    {"difficulty": "Expert", "characteristic": "Standard", "stars": 7.2},
                    {"difficulty": "Expert", "characteristic": "OneSaber", "stars": 3}]}]}
            store.db.execute("INSERT INTO maps(version_hash,status,retain_audio,provenance_json,updated_utc) VALUES(?,?,?,?,?)",
                             ("A"*40, "processed", 0, json.dumps({"metadata": metadata}), "test"))
            charts = chart_records(store)
            self.assertEqual(len(charts), 1)
            self.assertEqual(charts[("A"*40, "Expert")]["stars"], 7.2)
            store.close()

    def test_player_filter_excludes_unknown_and_other_difficulty(self):
        patterns = [{"version_hash": "A", "difficulty": label} for label in ("Hard", "Expert", "ExpertPlus")]
        charts = {("A", "Hard"): {"stars": None}, ("A", "Expert"): {"stars": 7.3}, ("A", "ExpertPlus"): {"stars": 11}}
        self.assertEqual(filter_patterns(patterns, charts, min_stars=6.5, max_stars=8), [patterns[1]])
        self.assertEqual(len(filter_patterns(patterns, charts)), 3)

    def test_tags_describe_geometry_not_star_predictions(self):
        p = {"notes": [{"beat": 0, "color": 0, "x": 2, "y": 0, "direction": 4},
                       {"beat": 0, "color": 1, "x": 1, "y": 2, "direction": 8}]}
        self.assertEqual(set(pattern_tags(p)), {"simultaneous_notes", "diagonal_cuts", "dot_notes", "opposite_half_placement"})

    def test_search_selects_target_downmap_not_highest_nps(self):
        item = {"id": "test", "ranked": True, "uploaded": "2024-01-01", "metadata": {"levelAuthorName": "mapper"},
                "versions": [{"state": "Published", "hash": "a"*40, "createdAt": "2024", "diffs": [
                    {"characteristic": "Standard", "difficulty": "ExpertPlus", "stars": 12, "nps": 15},
                    {"characteristic": "Standard", "difficulty": "Hard", "stars": 7.4, "nps": 5}]}]}
        selected = select_candidates([item], set(), {"player_target": 1})
        self.assertEqual(selected["seeds"][0]["difficulty"], "Hard")
        self.assertEqual(select_candidates([item], {"A"*40}, {"player_target": 1})["seeds"], [])

    def test_analysis_writes_reviewable_exact_source_shortlist(self):
        with tempfile.TemporaryDirectory() as root:
            store = CorpusStore(root)
            hash_ = "A"*40
            metadata = {"id": "test", "metadata": {"songName": "Example", "levelAuthorName": "Mapper"},
                        "versions": [{"hash": hash_, "diffs": [{"difficulty": "Expert", "characteristic": "Standard", "stars": 7.2}]}]}
            store.db.execute("INSERT INTO maps(version_hash,status,retain_audio,provenance_json,updated_utc,processing_json) VALUES(?,?,?,?,?,?)",
                             (hash_, "processed", 0, json.dumps({"metadata": metadata}), "test", "{}"))
            p = {"id": hash_+":Expert:0:4", "version_hash": hash_, "difficulty": "Expert", "start_beat": 0,
                 "length_beats": 4, "family_key": "motif", "nps": 1, "bpm": 120,
                 "notes": [{"beat": 0, "color": 0, "x": 0, "y": 0, "direction": 1},
                           {"beat": 1, "color": 1, "x": 3, "y": 0, "direction": 0}]}
            store.catalog_patterns = lambda: [p]
            report = analyze_corpus(store)
            self.assertEqual(report["target_patterns"], 1)
            self.assertEqual(report["shortlist_count"], 1)
            shortlist = json.loads((Path(root)/"player-pattern-shortlist.json").read_text())
            record = shortlist["patterns"][0]
            self.assertEqual(record["chart"]["stars"], 7.2)
            self.assertEqual(record["source_pointer"]["pattern_id"], p["id"])
            self.assertEqual(record["review_status"], "unreviewed")
            self.assertTrue((Path(root)/"player-analysis.md").is_file())
            # Every phrase carries its source chart's player star tier.
            self.assertEqual((record["stars"], record["star_tier"]), (7.2, "band"))
            listed = json.loads((Path(root)/"pattern-list.json").read_text(encoding="utf-8"))["patterns"][0]
            self.assertEqual(listed["star_tier"], "band")
            reference = json.loads((Path(root)/"tier-reference.json").read_text(encoding="utf-8"))
            band = next(t for t in reference["tiers"] if t["id"] == "band")
            self.assertEqual((band["charts"], band["windows"], band["window_nps"]["median"]), (1, 1, 1))
            tiered = json.loads((Path(root)/"tier-pattern-shortlist.json").read_text(encoding="utf-8"))["tiers"]
            self.assertEqual([row["id"] for row in tiered["band"]], [p["id"]])
            self.assertEqual(tiered["challenge"], [])
            store.close()


if __name__ == "__main__":
    unittest.main()
