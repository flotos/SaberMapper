import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.game.logs import diagnose, parse_records

LOG = """\
[DEBUG @ 10:39:00 | IPA] Game version set early to 1.40.8_7379
[CRITICAL @ 10:39:00 | IPA/LibraryLoader] No library BeatSaber.VisualTests.PlayTests found
[INFO @ 10:39:06 | IPA] Game version 1.40.8
[INFO @ 10:39:05 | ScoreSaber] Failed to get hmd from OpenXR System.Exception: openxr_loader not found
[INFO @ 10:39:05 | ScoreSaber]   at ScoreSaber.Core.Utils.OpenXRManager.AttemptGetHmd () [0x00037] in OpenXRManager.cs:85
[WARNING @ 10:39:11 | SongCore] Folder: 'C:\\Beat Saber\\Beat Saber_Data\\CustomWIPLevels\\Cache' is missing Info.dat file!
[INFO @ 10:40:00 | SaberMapperBridge] level_start C:\\Beat Saber\\Beat Saber_Data\\CustomWIPLevels\\sm-old
[ERROR @ 10:40:01 | Vivify] Could not find UnityEngine.Material [assets/old.mat]
[INFO @ 10:40:30 | SaberMapperBridge] level_end
[INFO @ 10:41:00 | SaberMapperBridge] level_start C:\\Beat Saber\\Beat Saber_Data\\CustomWIPLevels\\sm-demo
[ERROR @ 10:41:01 | UnityEngine] CRC Mismatch. Provided 11, calculated 22 from data. Will not load AssetBundle 'C:\\x\\bundleWindows2021.vivify'
[ERROR @ 10:41:01 | Vivify] Failed to load [C:\\x\\bundleWindows2021.vivify]
[ERROR @ 10:41:02 | Vivify] Could not find UnityEngine.Material [assets/foo.mat]
[ERROR @ 10:41:02 | Vivify] Checksum not defined
[ERROR @ 10:41:03 | Heck] Could not parse custom data for custom event [AnimateTrack] at [12.5]
[ERROR @ 10:41:03 | Heck] System.NullReferenceException: Object reference not set to an instance of an object
[ERROR @ 10:41:03 | Heck]   at Heck.Animation.Foo.Bar () [0x00000] in <abc>:0
[ERROR @ 10:41:03 | Heck]   at Heck.Animation.Foo.Baz () [0x00000] in <abc>:0
[WARNING @ 10:41:04 | UnityEngine] WARNING: Shader Unsupported: 'Custom/Glow' - All subshaders removed
[ERROR @ 10:41:05 | BeatLeader] System.InvalidOperationException: boom
[ERROR @ 10:41:05 | BeatLeader]   at BeatLeader.Replayer.Tick ()
[WARNING @ 10:41:06 | BeatLeader] OpenXR session is not running, info won't be available!
[ERROR @ 10:41:07 | Chroma] Something odd happened
    raw continuation line without a prefix
[INFO @ 10:41:08 | SaberMapperBridge] level_end
"""


class LogParseTest(unittest.TestCase):
    def test_records_group_exception_traces(self):
        records = parse_records(LOG)
        heck = [r for r in records if r["mod"] == "Heck"]
        self.assertEqual(len(heck), 1)
        self.assertEqual(len(heck[0]["trace"]), 3)
        self.assertTrue(heck[0]["exception"].startswith("System.NullReferenceException"))
        chroma = next(r for r in records if r["mod"] == "Chroma")
        self.assertEqual(chroma["trace"], ["    raw continuation line without a prefix"])
        scoresaber = [r for r in records if r["mod"] == "ScoreSaber"]
        self.assertEqual(len(scoresaber), 1)

    def test_since_level_classifies_known_failures(self):
        result = diagnose(LOG, since_level=True)
        self.assertEqual(result["game_version"], "1.40.8_7379")
        self.assertTrue(result["level"].endswith("sm-demo"))
        self.assertEqual(result["scope"]["mode"], "since_level")
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, ["bundle_checksum_mismatch", "bundle_load_failed", "asset_not_found",
                                 "bundle_checksum_missing", "custom_data_parse_error", "shader_error", "exception",
                                 "log_error"])
        self.assertTrue(all(d["level_scope"] for d in result["diagnostics"]))
        heck = next(d for d in result["diagnostics"] if d["source"] == "Heck")
        self.assertIn("12.5", heck["message"])
        self.assertTrue(heck["fix"])
        for key in ("severity", "source", "code", "time", "line", "message", "trace", "level_scope"):
            self.assertIn(key, heck)
        self.assertNotIn("BeatLeader", [d["source"] for d in result["diagnostics"] if d["severity"] == "warning"])
        self.assertEqual(result["counts"], {"error": 7, "warning": 1})

    def test_whole_log_filters_to_relevant_mods_and_all_disables_filter(self):
        filtered = diagnose(LOG)
        sources = {d["source"] for d in filtered["diagnostics"]}
        self.assertNotIn("IPA", sources)
        self.assertNotIn("ScoreSaber", sources)  # info-level exception from an unrelated mod
        self.assertIn("SongCore", sources)
        old = [d for d in filtered["diagnostics"] if "old.mat" in d["message"]]
        self.assertEqual(len(old), 1)
        self.assertFalse(old[0]["level_scope"])
        everything = diagnose(LOG, all_mods=True)
        sources = {d["source"] for d in everything["diagnostics"]}
        self.assertIn("IPA", sources)
        self.assertIn("BeatLeader", sources)
        self.assertGreater(everything["counts"]["warning"], filtered["counts"]["warning"])

    def test_level_scopes_to_that_levels_last_run(self):
        result = diagnose(LOG, level="sm-old")
        self.assertTrue(result["scope"]["found"])
        self.assertEqual([d["message"] for d in result["diagnostics"]], ["Could not find UnityEngine.Material [assets/old.mat]"])
        missing = diagnose(LOG, level="C:/elsewhere/nope")
        self.assertFalse(missing["scope"]["found"])
        self.assertEqual(missing["diagnostics"], [])

    def test_heck_trace_marker_is_fallback_level_start(self):
        text = ("[ERROR @ 10:00:00 | Vivify] Could not find UnityEngine.Material [assets/a.mat]\n"
                "[TRACE @ 10:01:00 | Heck] Deserializing BeatmapData\n"
                "[ERROR @ 10:01:01 | Vivify] [bundleWindows2021.vivify] not found\n")
        result = diagnose(text, since_level=True)
        self.assertEqual([d["code"] for d in result["diagnostics"]], ["bundle_missing"])
        self.assertEqual(result["scope"]["marker"]["source"], "Heck")
        none = diagnose("[ERROR @ 10:00:00 | Vivify] Checksum not defined\n", since_level=True)
        self.assertFalse(none["scope"]["found"])
        self.assertEqual(none["diagnostics"], [])

    def test_limit_keeps_newest(self):
        result = diagnose(LOG, since_level=True, limit=2)
        self.assertTrue(result["truncated"])
        self.assertEqual([d["code"] for d in result["diagnostics"]], ["exception", "log_error"])
        self.assertEqual(result["total"], 8)

    def test_json_and_harmony_patterns(self):
        text = ("[ERROR @ 10:00:00 | CustomJSONData] Newtonsoft.Json.JsonReaderException: Unexpected character "
                "encountered while parsing value: }. Path '_notes', line 1\n"
                "[ERROR @ 10:00:01 | SiraUtil] HarmonyLib.HarmonyException: Patching exception in method X\n"
                "[ERROR @ 10:00:02 | SongCore] Failed to load song: C:\\x\\sm-demo\n")
        codes = [d["code"] for d in diagnose(text)["diagnostics"]]
        self.assertEqual(codes, ["json_parse_error", "harmony_patch_failed", "level_load_failed"])


class LogCliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["game", "logs", *argv])
        return code, json.loads(out.getvalue())

    def test_cli_reads_log_and_reports_missing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "_latest.log"
            log.write_text(LOG, encoding="utf-8")
            code, body = self.run_cli("--log", str(log), "--since-level")
            self.assertEqual(code, 0)
            self.assertEqual(body["log"], str(log))
            self.assertEqual(body["counts"]["error"], 7)
            code, body = self.run_cli("--game-dir", str(Path(tmp) / "missing"))
            self.assertEqual((code, body["error"]["code"]), (2, "game_not_found"))
            self.assertIn("--log", body["error"]["fix"])


if __name__ == "__main__":
    unittest.main()
