"""Frame review: capture loading, contact sheets and frame metrics on synthetic frame sequences."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from sabermapper.__main__ import main
from sabermapper.frame_metrics import (analyze_frames, delta_e00, frame_findings, section_summary)
from sabermapper.frames import contact_sheets, load_capture
from sabermapper.revisions import arrangement_revision

W, H = 320, 180
FINDING_KEYS = {"severity", "code", "section_id", "object_ids", "value", "threshold", "message"}


def solid(color):
    return np.full((H, W, 3), color, dtype=np.uint8)


def write_capture(root, images, times, *, sections=None, reasons=None, camera="player", manifest=True,
                  revision="r" * 40):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, (image, t) in enumerate(zip(images, times)):
        name = f"t{t:08.3f}.png"
        Image.fromarray(image).save(root / name)
        frames.append({"file": name, "requested_time": t, "song_time": t, "beat": t * 2,
                       "section_id": sections[i] if sections else None,
                       "reason": reasons[i] if reasons else "grid"})
    if manifest:
        (root / "capture.json").write_text(json.dumps({
            "schema_version": 1, "project": "p1", "revision": revision, "difficulty": "ExpertPlus",
            "camera": camera, "width": W, "height": H, "game_version": "1.40.8", "level_path": "x",
            "created_at": "2026-09-23T00:00:00Z", "frames": frames, "log_diagnostics": []}))
    return root


def dense(root, color_at, seconds=2.0, fps=30, start=10.0, section="a"):
    count = int(seconds * fps)
    times = [round(start + i / fps, 3) for i in range(count)]
    return write_capture(root, [color_at(i) for i in range(count)], times, sections=[section] * count,
                         reasons=["probe"] * count)


def codes(findings):
    return [f["code"] for f in findings]


def arrangement(sections):
    return {"song": {"bpm": 120, "audio_offset_seconds": 0}, "tempo_events": [],
            "sections": [{"id": sid, "start_beat": start, "length_beats": length} for sid, start, length in sections]}


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_steady_frames_have_no_flash(self):
        result = analyze_frames(dense(self.root / "c", lambda i: solid((60, 60, 70))))
        self.assertTrue(result["metrics"]["flash"]["checked"])
        self.assertFalse([c for c in codes(result["findings"]) if "flash" in c])
        self.assertFalse(result["summary"]["blocking"])

    def test_five_hertz_full_frame_alternation_blocks(self):
        result = analyze_frames(dense(self.root / "c", lambda i: solid((255,) * 3 if (i // 3) % 2 else (0,) * 3)))
        finding = next(f for f in result["findings"] if f["code"] == "flash_rate_exceeded")
        self.assertEqual(finding["severity"], "error")
        self.assertEqual(finding["value"], 5.0)
        self.assertEqual(finding["threshold"], 3.0)
        self.assertTrue(finding["frames"])
        self.assertTrue(result["summary"]["blocking"])

    def test_two_and_a_half_hertz_warns(self):
        result = analyze_frames(dense(self.root / "c", lambda i: solid((230,) * 3 if (i // 6) % 2 else (10,) * 3)))
        self.assertIn("flash_rate_high", codes(result["findings"]))
        self.assertNotIn("flash_rate_exceeded", codes(result["findings"]))

    def test_small_area_flicker_is_not_a_general_flash(self):
        def frame(i):
            image = solid((0, 0, 0))
            if (i // 3) % 2:
                image[60:120, 120:200] = 255  # about 8% of the frame
            return image
        result = analyze_frames(dense(self.root / "c", frame))
        self.assertFalse([c for c in codes(result["findings"]) if "flash" in c])

    def test_saturated_red_flash(self):
        result = analyze_frames(dense(self.root / "c", lambda i: solid((255, 0, 0) if (i // 3) % 2 else (0, 0, 0))))
        self.assertIn("red_flash_rate_exceeded", codes(result["findings"]))

    def test_sparse_sampling_reports_insufficient(self):
        times = [float(t) for t in range(10)]
        root = write_capture(self.root / "c", [solid((255,) * 3 if t % 2 else (0,) * 3) for t in range(10)], times)
        result = analyze_frames(root)
        finding = next(f for f in result["findings"] if f["code"] == "flash_check_insufficient_sampling")
        self.assertEqual(finding["severity"], "info")
        self.assertEqual(finding["threshold"], 20.0)
        self.assertFalse(result["metrics"]["flash"]["checked"])


class CorridorAndPaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def grid(self, name, images, sections=None, camera="player"):
        times = [float(i) for i in range(len(images))]
        return write_capture(self.root / name, images, times, sections=sections or ["a"] * len(images), camera=camera)

    def test_dark_corridor_reads_well(self):
        findings = frame_findings(self.grid("c", [solid((8, 10, 14))] * 3))
        self.assertNotIn("note_contrast_low", codes(findings))

    def test_background_matching_blue_notes_warns(self):
        findings = frame_findings(self.grid("c", [solid((44, 140, 205))] * 3))
        finding = next(f for f in findings if f["code"] == "note_contrast_low")
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("right note colour", finding["message"])
        self.assertEqual(len(finding["frames"]), 3)
        self.assertTrue(FINDING_KEYS <= finding.keys())

    def test_bright_corridor_washes_out_arrows_and_concept_colours_apply(self):
        findings = frame_findings(self.grid("c", [solid((235, 235, 235))] * 2))
        self.assertIn("washes out the white arrows", next(f for f in findings if f["code"] == "note_contrast_low")["message"])
        concept = {"note_colors": {"left": "#f0f0f0", "right": "#ffffff"}}
        findings = frame_findings(self.grid("d", [solid((20, 20, 20))] * 2), concept=concept)
        self.assertNotIn("note_contrast_low", codes(findings))

    def test_busy_background_warns_and_wide_camera_skips(self):
        rng = np.random.default_rng(1)
        noise = [rng.integers(0, 60, (H, W, 3), dtype=np.uint8) * 4 for _ in range(2)]
        self.assertIn("busy background", next(f for f in frame_findings(self.grid("c", noise))
                                              if f["code"] == "note_contrast_low")["message"])
        self.assertNotIn("note_contrast_low", codes(frame_findings(self.grid("w", noise, camera="wide"))))

    def test_palette_drift(self):
        concept = {"palette": ["#ff00ff", "#00c8ff"]}
        drifting = frame_findings(self.grid("g", [solid((20, 200, 40))] * 3), concept=concept)
        finding = next(f for f in drifting if f["code"] == "palette_drift")
        self.assertGreater(finding["value"], finding["threshold"])
        on_palette = frame_findings(self.grid("m", [solid((230, 10, 230)), solid((180, 0, 190)),
                                                    solid((0, 190, 245))]), concept=concept)
        self.assertNotIn("palette_drift", codes(on_palette))

    def test_observed_palette_without_concept_and_dark_frames_do_not_drift(self):
        findings = frame_findings(self.grid("n", [solid((20, 200, 40))] * 2))
        self.assertIn("#", next(f for f in findings if f["code"] == "palette_observed")["message"])
        dark = frame_findings(self.grid("k", [solid((3, 3, 5))] * 2), concept={"palette": ["#ff00ff"]})
        self.assertNotIn("palette_drift", codes(dark))

    def test_palette_from_arrangement_presentation(self):
        arr = arrangement([("a", 0, 64)]) | {"presentation": {"palette": ["#ff00ff"]}}
        findings = frame_findings(self.grid("p", [solid((20, 200, 40))] * 2), arrangement=arr)
        self.assertIn("palette_drift", codes(findings))


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.arr = arrangement([("verse", 0, 16), ("chorus", 16, 16)])  # chorus at 8 s

    def tearDown(self):
        self.tmp.cleanup()

    def capture(self, change_at):
        times = [float(t) for t in range(14)]
        images = [solid((10, 10, 60) if t < change_at else (200, 40, 40)) for t in times]
        return write_capture(self.root / f"c{change_at}", images, times,
                             sections=["verse" if t < 8 else "chorus" for t in times])

    def test_change_on_the_boundary_is_aligned(self):
        result = analyze_frames(self.capture(8), self.arr)
        self.assertFalse({"visual_change_unaligned", "section_boundary_static"} & set(codes(result["findings"])))
        self.assertTrue(result["metrics"]["changes"]["boundaries"][0]["sampled"])

    def test_change_off_the_boundary_and_static_boundary(self):
        findings = frame_findings(self.capture(5), self.arr)
        self.assertIn("visual_change_unaligned", codes(findings))
        static = next(f for f in findings if f["code"] == "section_boundary_static")
        self.assertEqual(static["section_id"], "chorus")
        self.assertEqual(static["time"], 8.0)

    def test_boundaries_from_manifest_without_arrangement(self):
        self.assertIn("section_boundary_static", codes(frame_findings(self.capture(5))))

    def test_stale_revision_is_reported(self):
        findings = frame_findings(self.capture(8), self.arr)
        self.assertIn("capture_revision_stale", codes(findings))
        root = write_capture(self.root / "fresh", [solid((0, 0, 0))] * 2, [0.0, 1.0],
                             revision=arrangement_revision(self.arr))
        self.assertNotIn("capture_revision_stale", codes(frame_findings(root, self.arr)))


class SheetAndLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sheets_group_by_section_and_stay_readable(self):
        sections = ["intro"] * 5 + ["drop"] * 20 + ["outro"] * 2
        images = [solid((i * 9 % 255, 40, 90)) for i in range(len(sections))]
        root = write_capture(self.root / "c", images, [i * 0.5 for i in range(len(sections))], sections=sections)
        result = contact_sheets(root, columns=10, thumb_width=420)
        self.assertEqual(result["columns"], 4)
        self.assertEqual([(s["section_id"], s["part"], len(s["frames"])) for s in result["sheets"]],
                         [("intro", 1, 5), ("drop", 1, 16), ("drop", 2, 4), ("outro", 1, 2)])
        for sheet in result["sheets"]:
            with Image.open(sheet["path"]) as image:
                self.assertLessEqual(image.width, 2000)
                self.assertLessEqual(image.height, 1400)
                self.assertEqual(image.size, (sheet["width"], sheet["height"]))
        self.assertTrue((root / "sheets" / "sheets.json").is_file())
        chunked = contact_sheets(root, self.root / "out", per_section=False, columns=3, thumb_width=300)
        self.assertEqual([len(s["frames"]) for s in chunked["sheets"]], [12, 12, 3])

    def test_probe_frames_are_left_out_of_sheets_by_default(self):
        root = write_capture(self.root / "c", [solid((0, 0, 0))] * 4, [0.0, 1.0, 1.05, 1.1],
                             reasons=["grid", "probe", "probe", "probe"])
        self.assertEqual(contact_sheets(root)["probe_frames_omitted"], 3)
        self.assertEqual(contact_sheets(root, include_probe=True)["frame_count"], 4)

    def test_manifest_less_directory(self):
        root = write_capture(self.root / "plain", [solid((0, 0, 0))] * 3, [12.5, 1.25, 3.0], manifest=False)
        Image.fromarray(solid((0, 0, 0))).save(root / "cover.png")
        capture = load_capture(root)
        self.assertFalse(capture["manifest"])
        self.assertEqual([f["song_time"] for f in capture["frames"]], [1.25, 3.0, 12.5])
        self.assertEqual(capture["warnings"][0]["code"], "frame_name_unparsed")
        annotated = load_capture(root, arrangement([("a", 0, 4), ("b", 4, 60)]))
        self.assertEqual([(f["beat"], f["section_id"]) for f in annotated["frames"]],
                         [(2.5, "a"), (6.0, "b"), (25.0, "b")])
        self.assertEqual(contact_sheets(root)["sheets"][0]["section_id"], None)

    def test_errors_are_actionable(self):
        with self.assertRaisesRegex(ValueError, "game capture"):
            load_capture(self.root / "missing")
        (self.root / "empty").mkdir()
        with self.assertRaisesRegex(ValueError, "tSSSS.mmm.png"):
            load_capture(self.root / "empty")
        (self.root / "bad").mkdir()
        (self.root / "bad" / "capture.json").write_text(json.dumps({"schema_version": 9, "frames": []}))
        with self.assertRaisesRegex(ValueError, "schema_version"):
            load_capture(self.root / "bad")

    def test_ciede2000_reference_pair(self):
        self.assertAlmostEqual(float(delta_e00([50, 2.6772, -79.7751], [50, 0, -82.7485])), 2.0425, places=3)
        self.assertAlmostEqual(float(delta_e00([50, 2.5, 0], [73, 25, -18])), 27.1492, places=3)

    def test_cli_metrics_sheet_and_summary(self):
        root = write_capture(self.root / "c", [solid((10, 10, 40)), solid((10, 10, 40)), solid((200, 50, 50))],
                             [0.0, 1.0, 2.0], sections=["a", "a", "b"])
        for command in (["frames", "metrics", str(root)], ["frames", "summary", str(root), "--corridor",
                                                            "0.2,0.3,0.8,0.9"],
                        ["frames", "sheet", str(root), "--columns", "2"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(command), 0)
            data = json.loads(out.getvalue())
            self.assertIn("sheets" if command[1] == "sheet" else "summary", data)
        summary = section_summary(root)
        self.assertEqual([s["section_id"] for s in summary["sections"]], ["a", "b"])
        self.assertIsNotNone(summary["sections"][0]["corridor_min_contrast"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["frames", "metrics", str(root), "--corridor", "0.9,0,0.1,1"]), 1)
        self.assertIn("--corridor", err.getvalue())


if __name__ == "__main__":
    unittest.main()
