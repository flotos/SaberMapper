"""Lyrics: Whisper output parsing (faked subprocess), lyric-sheet import and alignment, beats."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sabermapper.__main__ import main
from sabermapper.listen import latest_listen
from sabermapper.lyrics import (ListenError, align_lines, import_lyric_sheet, lyrics_document, lyrics_project,
                                normalize_segments, parse_lyric_sheet, rebeat_lyrics, syllables, transcribe)
from sabermapper.projects import ProjectStore
from sabermapper.storage import read_json, write_json
from tests.test_moments import build_run

ARRANGEMENT = {"song": {"bpm": 120.0, "audio_offset_seconds": .5}, "tempo_events": [], "sections": []}
FAKE_WHISPER = {"backend": "faster_whisper", "model": "large-v3", "language": "en", "language_probability": .98,
                "device": "cuda", "compute_type": "float16", "version": "1.1.0",
                "segments": [{"start": 22.0, "end": 24.1, "text": " Light the way ",
                              "words": [{"word": " Light", "start": 22.0, "end": 22.4, "probability": .91},
                                        {"word": " the", "start": 22.4, "end": 22.6, "probability": .88},
                                        {"word": " way", "start": 22.6, "end": 24.1, "probability": .95},
                                        {"word": " ", "start": 24.1, "end": 24.1, "probability": .1}]},
                             {"start": 30.0, "end": 31.0, "text": "   ", "words": []}]}


class WhisperParsingTests(unittest.TestCase):
    def test_normalize_cleans_words_and_converts_beats(self):
        segments = normalize_segments(FAKE_WHISPER["segments"], ARRANGEMENT)
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual(segment["id"], "lyr-001")
        self.assertEqual(segment["text"], "Light the way")
        self.assertEqual([w["word"] for w in segment["words"]], ["Light", "the", "way"])
        self.assertEqual(segment["words"][0]["beat"], 43.0)  # (22.0 - 0.5) s at 120 BPM
        self.assertEqual(segment["start_beat"], 43.0)
        self.assertEqual(segment["words"][2]["probability"], .95)

    def test_document_records_provenance_and_precision(self):
        document = lyrics_document(FAKE_WHISPER, {"source": {"sha256": "f" * 64}}, "ab" * 16, ARRANGEMENT)
        self.assertEqual(document["backend"], "faster_whisper")
        self.assertEqual(document["word_count"], 3)
        self.assertEqual(document["precision"], "whisper")
        self.assertTrue(document["provenance"]["word_timestamps"])

    def test_rebeat(self):
        segments = normalize_segments(FAKE_WHISPER["segments"], ARRANGEMENT)
        lyrics = rebeat_lyrics({"segments": segments}, {"song": {"bpm": 60.0, "audio_offset_seconds": 0.0}})
        self.assertEqual(lyrics["segments"][0]["words"][0]["beat"], 22.0)


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        self.project = self.store.create(demo=True)["project"]["id"]
        self.directory = self.store.directory(self.project)
        self.run_id, self.report = build_run(self.directory)

    def fake_runner(self, command, **kwargs):
        config = json.loads(Path(command[2]).read_text(encoding="utf-8"))
        self.config = config
        Path(config["output"]).write_text(json.dumps({**FAKE_WHISPER, "model": config["model"]}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def test_whisper_missing_is_structured_with_install_command(self):
        with patch("sabermapper.lyrics.whisper_backend", return_value=None):
            with self.assertRaises(ListenError) as raised:
                transcribe(self.directory, self.run_id, self.report, python=Path("venv/python"))
        self.assertEqual(raised.exception.code, "whisper_missing")
        self.assertIn("pip install faster-whisper", raised.exception.details["install_command"])
        out = io.StringIO()
        with patch("sabermapper.lyrics.whisper_backend", return_value=None), redirect_stdout(out), \
                self.assertRaises(SystemExit) as exited:
            main(["music", "lyrics", self.project, "--workspace", self.temp.name])
        self.assertEqual(exited.exception.code, 2)
        error = json.loads(out.getvalue())["error"]
        self.assertEqual(error["code"], "whisper_missing")
        self.assertIn("pip install", error["fix"])

    def test_fake_whisper_run_writes_lyrics_json(self):
        with patch("sabermapper.lyrics.whisper_backend", return_value="faster_whisper"):
            result = lyrics_project(self.store, self.project, python=Path("venv/python"), model="medium",
                                    language="en", runner=self.fake_runner)
        self.assertEqual(self.config["backend"], "faster_whisper")
        self.assertEqual(self.config["language"], "en")
        self.assertEqual(result["words"], 3)
        stored = read_json(self.directory / "musical" / self.run_id / "lyrics.json")
        self.assertEqual(stored["model"], "medium")
        self.assertEqual(stored["input"], "vocals")
        self.assertEqual(stored["source_sha256"], self.report["source"]["sha256"])
        self.assertEqual(latest_listen(self.directory)["lyrics"]["segments"][0]["text"], "Light the way")

    def test_runner_failure_points_to_the_log(self):
        with patch("sabermapper.lyrics.whisper_backend", return_value="whisper"):
            with self.assertRaises(ListenError) as raised:
                transcribe(self.directory, self.run_id, self.report, python=Path("p"),
                           runner=lambda command, **kw: subprocess.CompletedProcess(command, 3))
        self.assertEqual(raised.exception.code, "whisper_failed")
        self.assertTrue(raised.exception.details["log"].endswith("lyrics.log"))

    def test_missing_vocal_stem(self):
        report = {**self.report, "layers": {k: v for k, v in self.report["layers"].items() if k != "vocals"}}
        with patch("sabermapper.lyrics.whisper_backend", return_value="whisper"):
            with self.assertRaises(ListenError) as raised:
                transcribe(self.directory, self.run_id, report, python=Path("p"), runner=self.fake_runner)
        self.assertEqual(raised.exception.code, "vocal_stem_missing")

    def test_cli_from_file(self):
        sheet = Path(self.temp.name) / "lyrics.lrc"
        sheet.write_text("[ti:Test]\n[00:22.00]Light the way\n[00:40.50]Carry on home\n", encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["music", "lyrics", self.project, "--workspace", self.temp.name,
                                   "--from-file", str(sheet)]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["precision"], "lrc_line")
        self.assertEqual([line["start"] for line in result["lines"]], [22.0, 40.5])


class LyricSheetTests(unittest.TestCase):
    def test_parse_lrc_plain_and_enhanced(self):
        kind, lines = parse_lyric_sheet("[ar:Someone]\n[00:12.50][01:02.00]Echo line\n"
                                        "[00:05.00]<00:05.00>first <00:05.40>words\n")
        self.assertEqual(kind, "lrc")
        self.assertEqual([l["time"] for l in lines], [5.0, 12.5, 62.0])
        self.assertEqual(lines[0]["words"], [{"word": "first", "start": 5.0}, {"word": "words", "start": 5.4}])
        kind, lines = parse_lyric_sheet("[Verse 1]\nOne line here\n\n(x2)\nAnother one\n")
        self.assertEqual(kind, "text")
        self.assertEqual([l["text"] for l in lines], ["One line here", "Another one"])

    def test_syllables(self):
        self.assertEqual(syllables("hello"), 2)
        self.assertEqual(syllables("rhythm"), 1)
        self.assertEqual(syllables("étoile"), 3)

    def test_alignment_is_monotone_and_groups_phrases(self):
        lines = [{"text": "short one"}, {"text": "a much longer line with many many syllables in it"},
                 {"text": "end"}]
        phrases = [[1.0, 2.0], [3.0, 3.3], [5.0, 9.0], [10.0, 10.8]]
        spans, _ = align_lines(lines, phrases)
        starts = [span[0][0] for span in spans]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(spans[1][-1], [5.0, 9.0])
        self.assertEqual(spans[2], [[10.0, 10.8]])

    def test_more_lines_than_phrases_splits_phrases(self):
        spans, _ = align_lines([{"text": "a b"}, {"text": "c d"}, {"text": "e f"}], [[0.0, 6.0]])
        self.assertTrue(all(spans))

    def test_text_import_is_labelled_rough(self):
        report = {"source": {"sha256": "0" * 64, "duration_seconds": 20.0},
                  "layers": {"vocals": {"energy_contour": [{"seconds": i / 10, "energy": .1 if 20 <= i < 60 or 100 <= i < 140 else 1e-6}
                                                            for i in range(200)],
                                        "events": [{"seconds": 2.05, "method": "spectral_flux", "strength": .8}]}}}
        document = import_lyric_sheet("first line sung here\nsecond line\n", report, "ab" * 16, ARRANGEMENT)
        self.assertEqual(document["precision"], "rough")
        self.assertIn("rough", document["precision_note"])
        first, second = document["segments"]
        self.assertAlmostEqual(first["start"], 2.0, delta=.15)
        self.assertEqual(first["words"][0]["start"], 2.05)  # snapped to the vocal onset
        self.assertAlmostEqual(second["start"], 10.0, delta=.15)
        with self.assertRaises(ListenError) as raised:
            import_lyric_sheet("[Chorus]\n", report, "ab" * 16)
        self.assertEqual(raised.exception.code, "lyrics_empty")


if __name__ == "__main__":
    unittest.main()
