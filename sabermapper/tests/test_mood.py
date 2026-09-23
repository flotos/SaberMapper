"""Heuristic mood descriptors and the external model hook."""
import json
import subprocess
import unittest
from unittest.mock import patch

from sabermapper.mood import MoodBackendError, external_mood, heuristic_mood, section_moods


def features(**overrides):
    base = {"loudness_dbfs": -12.0, "centroid_hz": 2000.0, "flatness": .1, "harmonic_ratio": .6, "low_share": .3,
            "high_share": .05, "air_share": .01, "onset_density": 3.0, "tempo_bpm": 120, "tempo_source": "arrangement",
            "audio_tempo": None, "mode": "major", "major_minus_minor": 0.0, "song_major_minus_minor": 0.0}
    base.update(overrides)
    return base


def tags(result):
    return {t["tag"]: t["confidence"] for t in result["tags"]}


class HeuristicMoodTests(unittest.TestCase):
    def test_arousal_follows_tempo_loudness_density_and_brightness(self):
        calm = heuristic_mood(features(tempo_bpm=70, loudness_dbfs=-26, onset_density=.5, centroid_hz=900,
                                       harmonic_ratio=.85))
        driving = heuristic_mood(features(tempo_bpm=175, loudness_dbfs=-8, onset_density=6, centroid_hz=3500,
                                          harmonic_ratio=.3))
        self.assertLess(calm["arousal"], .3)
        self.assertGreater(driving["arousal"], .8)
        for result in (calm, driving):
            self.assertTrue(0 <= result["valence"] <= 1 and 0 <= result["arousal"] <= 1)
            self.assertEqual(set(result["components"]), {"arousal", "valence"})

    def test_valence_follows_mode_and_brightness(self):
        bright_major = heuristic_mood(features(major_minus_minor=.15, song_major_minus_minor=.15, centroid_hz=3000))
        dark_minor = heuristic_mood(features(major_minus_minor=-.15, song_major_minus_minor=-.15, centroid_hz=900,
                                             flatness=.3))
        self.assertGreater(bright_major["valence"], .6)
        self.assertLess(dark_minor["valence"], .4)

    def test_stem_tags(self):
        vocal = heuristic_mood(features(stem_share={"vocals": .4, "drums": .1, "bass": .1, "guitar": .1, "other": .3},
                                        stem_active={"vocals": .9, "drums": .3, "bass": .3, "guitar": .2, "other": .8},
                                        stem_timbre={"other": {"flatness": .01, "centroid_hz": 900, "level_jitter_db": .3}}))
        self.assertGreater(tags(vocal)["vocal_led"], .8)
        self.assertIn("sustained_pad", tags(vocal))
        self.assertNotIn("drum_heavy", tags(vocal))
        metal = heuristic_mood(features(stem_share={"vocals": .1, "drums": .35, "bass": .15, "guitar": .4},
                                        stem_active={"vocals": .5, "drums": 1, "bass": 1, "guitar": 1},
                                        stem_timbre={"guitar": {"flatness": .15, "centroid_hz": 2200, "level_jitter_db": .5}}))
        self.assertGreater(tags(metal)["distorted_guitar"], .8)
        self.assertNotIn("clean_guitar", tags(metal))
        self.assertIn("drum_heavy", tags(metal))
        self.assertTrue(all(t["because"] for t in metal["tags"]))

    def test_without_stems_only_mix_tags(self):
        result = heuristic_mood(features(centroid_hz=800, harmonic_ratio=.2))
        names = set(tags(result))
        self.assertTrue(names <= {"drum_heavy", "sparse", "bright", "dark", "airy", "noisy"}, names)
        self.assertIn("dark", names)


class ExternalMoodTests(unittest.TestCase):
    sections = [{"id": "sec-01", "start": 0.0, "end": 10.0}]

    def test_unconfigured_and_missing_module_are_structured(self):
        with self.assertRaises(MoodBackendError) as raised:
            external_mood(self.sections, {}, {})
        self.assertEqual(raised.exception.code, "mood_model_unconfigured")
        with patch("sabermapper.mood.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            with self.assertRaises(MoodBackendError) as raised:
                external_mood(self.sections, {}, {"python": "py", "module": "moodnet"})
        self.assertEqual(raised.exception.code, "mood_model_missing")
        self.assertIn("pip install", raised.exception.fix)

    def test_model_output_is_parsed(self):
        output = {"model": {"name": "fake"}, "sections": {"sec-01": {"valence": .2, "arousal": .9,
                                                                     "tags": [{"tag": "tense", "confidence": .7}]}}}
        calls = [subprocess.CompletedProcess([], 0, "", ""), subprocess.CompletedProcess([], 0, json.dumps(output), "")]
        with patch("sabermapper.mood.subprocess.run", side_effect=calls) as run:
            model, predictions = external_mood(self.sections, {"sec-01": {}}, {"python": "py", "module": "moodnet"})
        self.assertEqual(model, {"name": "fake"})
        self.assertEqual(predictions["sec-01"]["arousal"], .9)
        sent = json.loads(run.call_args_list[1].kwargs["input"])
        self.assertEqual(sent["sections"][0]["id"], "sec-01")

    def test_unknown_backend(self):
        with self.assertRaises(MoodBackendError) as raised:
            section_moods({}, [], {}, backend="oracle")
        self.assertEqual(raised.exception.code, "mood_backend_unknown")


if __name__ == "__main__":
    unittest.main()
