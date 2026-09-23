"""Several difficulties per project, player star tiers and the target-tier comparison."""

import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from zipfile import ZipFile

from sabermapper.corpus_analysis import filter_patterns
from sabermapper.critique import critique_arrangement
from sabermapper.export import ExportError, export_arrangements
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.server import make_server
from sabermapper.star_tiers import TIER_IDS, default_tiers, player_tiers, tier_for
from sabermapper.tier_fit import missing_reference_warning
from sabermapper.validation import validate_arrangement


class ProjectDifficultyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ProjectStore(self.temporary.name)
        self.project_id = self.store.create(demo=True)["project"]["id"]

    def tearDown(self):
        self.temporary.cleanup()

    def add_harder(self):
        first = self.store.get(self.project_id)
        self.store.set_lock(self.project_id, first["arrangement"]["sections"][0]["id"], True, first["revision"])
        return self.store.add_difficulty(self.project_id, "ExpertPlus", njs=19, target_tier="challenge")

    def test_added_difficulty_is_an_unlocked_copy_beside_an_untouched_primary(self):
        primary_before = self.store.get(self.project_id)
        harder = self.add_harder()
        self.assertEqual(harder["difficulty"], "ExpertPlus")
        self.assertEqual(harder["arrangement"]["difficulty"],
                         {**primary_before["arrangement"]["difficulty"], "name": "ExpertPlus", "rank": 9, "njs": 19,
                          "target_tier": "challenge"})
        self.assertFalse(any(s["locked"] for s in harder["arrangement"]["sections"]))
        self.assertEqual([(r["name"], r["primary"]) for r in harder["difficulties"]],
                         [("Expert", True), ("ExpertPlus", False)])
        primary = self.store.get(self.project_id)
        self.assertTrue(primary["arrangement"]["sections"][0]["locked"])
        self.assertEqual(primary["difficulty"], "Expert")
        self.assertEqual(self.store.list()[0]["difficulties"], ["Expert", "ExpertPlus"])
        with self.assertRaises(ConflictError):
            self.store.add_difficulty(self.project_id, "ExpertPlus")
        with self.assertRaisesRegex(FileNotFoundError, "add-difficulty"):
            self.store.get(self.project_id, "Hard")
        with self.assertRaisesRegex(ValueError, "Unknown difficulty"):
            self.store.get(self.project_id, "Extreme")

    def test_saves_feedback_and_history_stay_inside_one_difficulty(self):
        harder = self.add_harder()
        primary_revision = self.store.get(self.project_id)["revision"]
        changed = copy.deepcopy(harder["arrangement"])
        changed["sections"][0]["notes"][0]["direction"] = 6
        request = self.store.add_feedback(self.project_id, {"revision": harder["revision"], "start_beat": 0,
                                                            "end_beat": 8, "text": "Harder here", "difficulty": "ExpertPlus"})
        self.assertEqual(request["difficulty"], "ExpertPlus")
        saved = self.store.save(self.project_id, changed, harder["revision"], request_id=request["id"],
                                difficulty="ExpertPlus")
        self.assertEqual(saved["difficulty"], "ExpertPlus")
        self.assertEqual(self.store.get(self.project_id)["revision"], primary_revision)
        self.assertIn(saved["revision"], saved["history"])
        self.assertNotIn(saved["revision"], self.store.get(self.project_id)["history"])
        with self.assertRaises(ConflictError):  # the primary's revision is not the ExpertPlus revision
            self.store.save(self.project_id, changed, primary_revision, difficulty="ExpertPlus")

    def test_renaming_through_save_refuses_an_existing_name(self):
        harder = self.add_harder()
        clash = copy.deepcopy(harder["arrangement"])
        clash["difficulty"].update(name="Expert", rank=7)
        with self.assertRaisesRegex(ConflictError, "already has a Expert"):
            self.store.save(self.project_id, clash, harder["revision"], difficulty="ExpertPlus")
        primary = self.store.get(self.project_id)
        renamed = copy.deepcopy(primary["arrangement"])
        renamed["difficulty"].update(name="Hard", rank=5)
        result = self.store.save(self.project_id, renamed, primary["revision"])
        self.assertEqual([r["name"] for r in result["difficulties"]], ["Hard", "ExpertPlus"])
        moved = copy.deepcopy(harder["arrangement"])
        moved["difficulty"].update(name="Expert", rank=7)
        result = self.store.save(self.project_id, moved, harder["revision"], difficulty="ExpertPlus")
        self.assertEqual(result["difficulty"], "Expert")
        self.assertEqual(sorted(p.name for p in (self.store.directory(self.project_id) / "difficulties").iterdir()),
                         ["Expert.json"])

    def test_export_bundles_every_difficulty_and_requires_shared_timing(self):
        harder = self.add_harder()
        exported = self.store.export(self.project_id)
        with ZipFile(self.store.directory(self.project_id) / "exports" / exported["filename"]) as archive:
            info = json.loads(archive.read("Info.dat"))
            beatmaps = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"]
            self.assertEqual([(b["_difficulty"], b["_difficultyRank"], b["_noteJumpMovementSpeed"]) for b in beatmaps],
                             [("Expert", 7, 14), ("ExpertPlus", 9, 19)])
            self.assertIn("ExpertPlus.dat", archive.namelist())
            self.assertIn("Expert.dat", archive.namelist())
        self.assertEqual([row["difficulty"] for row in exported["report"]["difficulties"]], ["Expert", "ExpertPlus"])
        self.assertEqual(exported["report"]["difficulties"][1]["target_tier"], "challenge")
        retimed = copy.deepcopy(harder["arrangement"])
        retimed["song"]["bpm"] = 121
        saved = self.store.save(self.project_id, retimed, harder["revision"], difficulty="ExpertPlus")
        self.assertIn("difficulty_timing_mismatch", [d["code"] for d in saved["diagnostics"]])
        with self.assertRaisesRegex(ExportError, "song timing differs"):
            self.store.export(self.project_id)

    def test_only_non_primary_difficulties_can_be_removed(self):
        harder = self.add_harder()
        primary = self.store.get(self.project_id)
        with self.assertRaisesRegex(ValueError, "primary"):
            self.store.remove_difficulty(self.project_id, "Expert", primary["revision"])
        with self.assertRaises(ConflictError):
            self.store.remove_difficulty(self.project_id, "ExpertPlus", primary["revision"])
        result = self.store.remove_difficulty(self.project_id, "ExpertPlus", harder["revision"])
        self.assertEqual([r["name"] for r in result["difficulties"]], ["Expert"])
        # Its content stays restorable from history.
        self.assertTrue((self.store.directory(self.project_id) / "history" / (harder["revision"] + ".json")).is_file())

    def test_studio_reads_and_writes_the_selected_difficulty(self):
        self.add_harder()
        server = make_server(self.temporary.name, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            host = f"127.0.0.1:{port}"

            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request(method, path, body=body, headers={"Host": host, **(headers or {})})
                response = conn.getresponse()
                data = response.read()
                conn.close()
                return response.status, data

            token = json.loads(request("GET", "/api/status")[1])["token"]
            status, body = request("GET", f"/api/projects/{self.project_id}?difficulty=ExpertPlus")
            self.assertEqual(status, 200)
            current = json.loads(body)
            self.assertEqual(current["difficulty"], "ExpertPlus")
            status, body = request("POST", f"/api/projects/{self.project_id}/feedback", json.dumps(
                {"revision": current["revision"], "start_beat": 0, "end_beat": 4, "text": "More",
                 "difficulty": "ExpertPlus"}).encode(),
                {"Content-Type": "application/json", "X-SaberMapper-Token": token})
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body)["difficulty"], "ExpertPlus")
            self.assertEqual(request("GET", f"/api/projects/{self.project_id}?difficulty=Hard")[0], 404)
        finally:
            server.shutdown()
            server.server_close()


class StarTierTests(unittest.TestCase):
    def test_boundaries_are_half_open_and_unrated_is_unknown(self):
        tiers = default_tiers()
        self.assertEqual([tier_for(value, tiers) for value in (5, 6.5, 7.99, 8, 9, 9.49, 9.5, 13)],
                         ["below_band", "band", "band", "challenge", "stretch", "stretch", "beyond", "beyond"])
        self.assertIsNone(tier_for(None, tiers))
        self.assertIsNone(tier_for(0, tiers))

    def test_stretch_ends_at_the_hardest_recorded_pass(self):
        def profile(hardest):
            return {"score_evidence": {"ranked_standard_unmodified": {"max_stars": hardest}}}
        self.assertEqual(player_tiers(profile(9.47))[3]["max_stars"], 9.5)
        self.assertEqual(player_tiers(profile(10.2))[3]["max_stars"], 10.5)
        self.assertEqual(player_tiers(None)[3]["max_stars"], 9.5)
        with self.assertRaisesRegex(ValueError, "contiguous"):
            broken = default_tiers()
            broken[1]["max_stars"] = 7.5
            player_tiers({"overrides": {"star_tiers": {"tiers": broken}}})

    def test_patterns_filter_by_the_source_chart_tier(self):
        patterns = [{"version_hash": "A", "difficulty": label} for label in ("Hard", "Expert", "ExpertPlus")]
        charts = {("A", "Hard"): {"stars": 6, "star_tier": "below_band"},
                  ("A", "Expert"): {"stars": 8.4, "star_tier": "challenge"},
                  ("A", "ExpertPlus"): {"stars": 8.6, "star_tier": "challenge", "requires_gameplay_mods": True}}
        self.assertEqual(filter_patterns(patterns, charts, tier="challenge"), [patterns[1]])

    def test_target_tier_must_be_a_known_tier(self):
        arrangement = {"schema_version": "0.1", "song": {"title": "t", "artist": "a", "bpm": 120, "audio_offset_seconds": 0},
                       "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0, "target_tier": "hard"},
                       "motifs": {}, "sections": []}
        self.assertIn("invalid_target_tier", [d["code"] for d in validate_arrangement(arrangement)])
        arrangement["difficulty"]["target_tier"] = "challenge"
        self.assertNotIn("invalid_target_tier", [d["code"] for d in validate_arrangement(arrangement)])


def _reference():
    def tier(tier_id, nps, swings, peak):
        return {"id": tier_id, "label": tier_id, "windows": 100, "window_nps": {"median": nps, "p90": nps * 1.2},
                "window_movement": {"swing_rate_per_second": {"median": swings},
                                    "peak_one_second_swing_count": {"median": peak}}}
    return {"tiers": [tier("below_band", 4, 4.2, 5), tier("band", 6.75, 6.9, 8), tier("challenge", 7.7, 7.7, 9),
                      tier("stretch", 9, 8.7, 10), tier("beyond", 9.75, 9.7, 10)]}


def _arrangement(step, target, bpm=120):
    notes = [{"id": f"n{i}", "beat": i * step, "x": 1 + i % 2, "y": 0, "color": i % 2,
              "direction": 1 if (i // 2) % 2 == 0 else 0} for i in range(int(64 / step))]
    return {"schema_version": "0.1", "song": {"title": "t", "artist": "a", "bpm": bpm, "audio_offset_seconds": 0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 18, "spawn_offset_beats": 0, "target_tier": target},
            "motifs": {}, "sections": [{"id": "body", "start_beat": 0, "length_beats": 64, "intent": "test", "locked": False,
                                        "resolved": True, "notes": notes, "patterns": []}]}


class TierFitTests(unittest.TestCase):
    def test_a_sparse_map_reads_below_its_challenge_target(self):
        result = critique_arrangement(_arrangement(0.5, "challenge"), None, _reference())
        fit = result["metrics"]["tier_fit"]
        self.assertTrue(fit["checked"])
        self.assertEqual(fit["closest_tier"], "below_band")
        self.assertEqual(fit["sections"][0]["below_target"], True)
        self.assertIn("tier_below_target", [w["code"] for w in result["warnings"]])

    def test_a_dense_stream_meets_the_challenge_target(self):
        result = critique_arrangement(_arrangement(0.25, "challenge", bpm=130), None, _reference())
        self.assertEqual(result["metrics"]["tier_fit"]["closest_tier"], "challenge")
        self.assertFalse({"tier_below_target", "tier_above_target"} & {w["code"] for w in result["warnings"]})

    def test_missing_reference_or_target_is_reported_not_guessed(self):
        # Repairs call critique without a reference: no tier warning leaks into their remaining warnings.
        result = critique_arrangement(_arrangement(0.5, "challenge"), None, None)
        self.assertEqual(result["metrics"]["tier_fit"], {"checked": False, "target_tier": "challenge",
                                                          "reason": "no tier reference"})
        self.assertFalse([w for w in result["warnings"] if w["code"].startswith("tier_")])
        self.assertEqual(missing_reference_warning(_arrangement(0.5, "challenge"))["code"], "tier_reference_missing")
        arrangement = _arrangement(0.5, "challenge")
        del arrangement["difficulty"]["target_tier"]
        self.assertFalse(critique_arrangement(arrangement, None, _reference())["metrics"]["tier_fit"]["checked"])
        self.assertEqual(TIER_IDS, ("below_band", "band", "challenge", "stretch", "beyond"))


if __name__ == "__main__":
    unittest.main()
