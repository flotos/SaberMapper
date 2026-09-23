"""Lightshow: generated from the song's evidence, safe, reviewable, and tweakable through cues and overrides."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from sabermapper.__main__ import main
from sabermapper.arrangement import compile_arrangement
from sabermapper.audio import _hash
from sabermapper.critique import critique_arrangement
from sabermapper.lighting import (DENSITY_HIGH, DENSITY_LOW, GENERATOR_FULL_FIELD_PER_SECOND, LIGHT_TYPES,
                                  PULSE_VALUES, TARGET_RATE, _field_times, _moments, _to_seconds, _window_max,
                                  compile_lightshow, generate_lightshow, inspect_lights, lighting_findings,
                                  refresh_lightshow)
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.validation import validate_arrangement

RESOURCE = Path(__file__).resolve().parents[1] / "sabermapper" / "resources" / "lighting-reference.json"


def report(seconds=24.0, *, quiet_until=0.0, sha256="fixture", created="2026-09-23T00:00:00+00:00", dense=False):
    """120 BPM band: kick/snare on every beat, a sung line with rising and falling steps, bass on the bar.

    Near-silent before ``quiet_until``. ``dense`` adds sixteenth-note attacks on every stem.
    """
    beat = 0.5
    contour = [{"seconds": i / 10, "energy": 0.001 if i / 10 < quiet_until else 0.5} for i in range(int(seconds * 10))]
    step = beat / 4 if dense else beat
    drums = [{"id": f"d{i}", "seconds": round(i * step, 4), "method": "spectral_flux",
              "strength": 0.8 if i % 2 == 0 else 0.6} for i in range(int(seconds / step)) if i * step >= quiet_until]
    vocal_step = beat / 4 if dense else 1.0
    vocals = [{"id": f"v{i}", "seconds": round(i * vocal_step + (0 if dense else 0.25), 4), "method": "pitch_change",
               "strength": 0.6, "semitone_delta": 2.0 if i % 2 else -2.0}
              for i in range(int(seconds / vocal_step)) if i * vocal_step >= quiet_until]
    sustains = [{"id": f"s{i}", "start_seconds": i * 4 + 0.25, "end_seconds": i * 4 + 1.75, "strength": 0.7}
                for i in range(int(seconds / 4)) if i * 4 >= quiet_until]
    bass = [{"id": f"b{i}", "seconds": i * 2.0, "method": "spectral_flux", "strength": 0.6}
            for i in range(int(seconds / 2)) if i * 2 >= quiet_until]
    return {"source": {"sha256": sha256, "duration_seconds": seconds}, "created_at": created,
            "backend": "fixture", "preset": "balanced",
            "layers": {"mix": {"events": [], "energy_contour": contour},
                       "drums": {"events": drums}, "bass": {"events": bass},
                       "vocals": {"events": vocals, "sustains": sustains}}}


def arrangement(sections=((0, 48),), notes_from=0):
    """120 BPM, offset 0: beat b sits at b / 2 seconds. One note per beat from ``notes_from``."""
    result = []
    for index, (start, length) in enumerate(sections):
        notes = [{"id": f"n{b}", "beat": b - start, "x": b % 4, "y": 0, "color": b % 2, "direction": 1 - b // 2 % 2}
                 for b in range(max(start, notes_from), start + length)]
        result.append({"id": f"s{index}", "start_beat": start, "length_beats": length, "intent": "fixture",
                       "locked": False, "resolved": True, "notes": notes, "patterns": []})
    return {"schema_version": "0.1",
            "song": {"title": "Fixture", "artist": "Tests", "bpm": 120, "audio_offset_seconds": 0},
            "difficulty": {"name": "ExpertPlus", "rank": 9, "njs": 16, "spawn_offset_beats": 0},
            "motifs": {}, "sections": result}


def lit(arr, evidence=None, **show):
    arr = copy.deepcopy(arr)
    if show:
        arr["lightshow"] = {"environment": "BigMirrorEnvironment", **show}
    arr["lightshow"] = generate_lightshow(arr, evidence or report(), "r" * 32)
    return arr


def pulses(arr):
    events, _ = compile_lightshow(arr)
    return [e for e in events if e[1] in LIGHT_TYPES and e[2] in PULSE_VALUES]


def codes(findings):
    return [f["code"] for f in findings]


def errors(arr):
    return [d for d in validate_arrangement(arr) if d["severity"] == "error"]


class GenerationTests(unittest.TestCase):
    def test_every_generated_pulse_sits_on_a_sound(self):
        arr, evidence = lit(arrangement()), report()
        onsets = sorted(float(e["seconds"]) * 2 for layer in evidence["layers"].values() for e in layer["events"])
        for beat, *_ in pulses(arr):
            self.assertTrue(any(abs(beat - o) <= 0.13 for o in onsets), f"pulse at beat {beat} has no sound")
        _, findings = lighting_findings(arr, evidence)
        self.assertNotIn("light_without_audio", codes(findings))
        self.assertEqual(errors(arr), [])

    def test_silent_section_stays_dark_and_the_band_lights_up(self):
        arr = lit(arrangement(((0, 12), (12, 36)), notes_from=12), report(quiet_until=6.0))
        moods = {s["id"]: s["mood"] for s in arr["lightshow"]["generated"]["sections"]}
        self.assertEqual(moods["s0"], "off")
        self.assertIn(moods["s1"], ("groove", "peak"))
        self.assertFalse([p for p in pulses(arr) if p[0] < 12])
        self.assertTrue([p for p in pulses(arr) if p[0] >= 12])

    def test_drums_pulse_back_center_and_rings_and_the_voice_drives_the_lasers(self):
        arr = lit(arrangement())
        events, _ = compile_lightshow(arr)
        groups = {e[1] for e in pulses(arr)}
        self.assertTrue({0, 1, 2, 3, 4} <= groups)
        speeds = {(e[0], e[1]) for e in events if e[1] in (12, 13)}
        for beat, group, *_ in (p for p in pulses(arr) if p[1] in (2, 3)):
            # Every laser pulse that follows the voice is preceded by its speed event at the same beat.
            if round(beat * 2) % 2:  # vocal onsets sit on half beats
                self.assertIn((beat, 12 if group == 2 else 13), speeds)
        self.assertTrue(any(e[1] == 8 for e in events), "ring spins follow the back beat")

    def test_pitch_direction_picks_the_laser_side(self):
        arr = lit(arrangement(), report(), style={"intensity": 2.0}, sections={"s0": {"mood": "calm"}})
        rising = [p[1] for p in pulses(arr) if p[1] in (2, 3) and abs(p[0] % 4 - 2.5) < 1e-6]
        self.assertTrue(rising and set(rising) <= {3})

    def test_one_event_per_group_and_beat_so_a_section_entry_keeps_its_base(self):
        # A strong hit a hair before the calm section makes the peak bar pulse the center at the same
        # instant the entry accent snaps to; the entry's steady center must win, not the sort order.
        evidence = report()
        evidence["layers"]["drums"]["events"].append({"id": "edge", "seconds": 11.99, "method": "spectral_flux",
                                                      "strength": 0.95})
        arr = lit(arrangement(((0, 24), (24, 24))), evidence, sections={"s0": {"mood": "peak"}, "s1": {"mood": "calm"}})
        events = arr["lightshow"]["generated"]["events"]
        keys = [(e[0], e[1]) for e in events]
        self.assertEqual(len(keys), len(set(keys)))
        center = [e for e in events if e[1] == 4 and 23.9 <= e[0] < 48]
        self.assertEqual(center[0][2], 1)  # blue on: the calm base
        self.assertEqual(len(center), 1)
        _, findings = lighting_findings(arr, evidence)
        self.assertNotIn("light_blackout_notes", codes(findings))

    def test_a_calm_opening_on_beat_zero_keeps_its_base_light(self):
        arr = lit(arrangement(), sections={"s0": {"mood": "calm"}})
        center = [e for e in arr["lightshow"]["generated"]["events"] if e[1] == 4]
        self.assertEqual(center[0][:3], [0.0, 4, 1])
        self.assertNotIn("light_blackout_notes", codes(lighting_findings(arr, report())[1]))

    def test_onsets_inside_the_audio_offset_never_become_events(self):
        arr = arrangement()
        arr["song"]["audio_offset_seconds"] = 0.5
        evidence = report()
        evidence["layers"]["drums"]["events"].insert(0, {"id": "pre", "seconds": 0.45, "method": "spectral_flux",
                                                         "strength": 0.95})
        arr = lit(arr, evidence)
        self.assertGreaterEqual(min(e[0] for e in arr["lightshow"]["generated"]["events"]), 0)
        self.assertEqual(errors(arr), [])

    def test_generation_is_deterministic(self):
        self.assertEqual(lit(arrangement())["lightshow"], lit(arrangement())["lightshow"])

    def test_density_follows_the_mood(self):
        calm = lit(arrangement(), sections={"s0": {"mood": "calm"}})
        peak = lit(arrangement(), sections={"s0": {"mood": "peak"}})
        self.assertLess(len(pulses(calm)), len(pulses(peak)))
        self.assertLessEqual(TARGET_RATE["calm"], TARGET_RATE["groove"])
        boosts = compile_lightshow(peak)[1]
        self.assertEqual(boosts[0][1], True)

    def test_generator_keeps_full_field_pulses_within_its_limit(self):
        arr = lit(arrangement(), report(dense=True), sections={"s0": {"mood": "peak", "intensity": 2.0}})
        events, _ = compile_lightshow(arr)
        count, _ = _window_max(_field_times(_moments(events, _to_seconds(arr)), 4))
        self.assertLessEqual(count, GENERATOR_FULL_FIELD_PER_SECOND)
        self.assertEqual(errors(arr), [])


class CueTests(unittest.TestCase):
    def test_cues_clear_and_add_on_top_of_the_generated_layer(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [
            {"beat": 8, "action": "clear", "end_beat": 16, "targets": ["back", "center"]},
            {"beat": 10, "action": "pulse", "groups": ["center"], "color": "white", "style": "flash", "brightness": 1.5},
            {"beat": 10, "action": "laser_speed", "side": "both", "speed": 9},
            {"beat": 11, "action": "boost", "on": True},
            {"beat": 12, "action": "event", "type": 9, "value": 0, "note": "zoom on the snare fill"}]
        self.assertEqual(errors(arr), [])
        events, boosts = compile_lightshow(arr)
        inside = [e for e in events if 8 <= e[0] < 16 and e[1] in (0, 4)]
        self.assertEqual(inside, [(10.0, 4, 10, 1.5)])
        self.assertIn((10.0, 12, 9, 1.0), events)
        self.assertIn((11.0, True), boosts)
        self.assertIn((12.0, 9, 0, 1.0), events)
        # A cue on a generated event's exact beat and group replaces it rather than racing it.
        generated = next(e for e in arr["lightshow"]["generated"]["events"] if e[1] == 1 and e[0] >= 20)
        arr["lightshow"]["cues"].append({"beat": generated[0], "action": "off", "groups": ["ring"]})
        events, _ = compile_lightshow(arr)
        self.assertEqual([e for e in events if e[0] == generated[0] and e[1] == 1], [(generated[0], 1, 0, 0.0)])

    def test_compiled_beatmap_carries_basic_events_and_boosts(self):
        arr = lit(arrangement(), sections={"s0": {"mood": "peak"}})
        beatmap = compile_arrangement(arr)
        self.assertTrue(beatmap["basicBeatmapEvents"])
        self.assertEqual(set(beatmap["basicBeatmapEvents"][0]), {"b", "et", "i", "f"})
        self.assertEqual(beatmap["colorBoostBeatmapEvents"][0], {"b": 0.0, "o": True})
        order = [(e["b"], e["et"]) for e in beatmap["basicBeatmapEvents"]]
        for beat, kind in order:
            if kind in (2, 3) and (beat, kind + 10) in order:
                self.assertLess(order.index((beat, kind + 10)), order.index((beat, kind)))


class ValidationTests(unittest.TestCase):
    def test_structural_errors_are_reported(self):
        arr = lit(arrangement())
        arr["lightshow"]["environment"] = "WeaveEnvironment"
        arr["lightshow"]["tempo"] = 1
        arr["lightshow"]["style"]["palette"] = "neon"
        arr["lightshow"]["cues"] = [{"beat": 1, "action": "laser_speed", "speed": 99},
                                    {"beat": 2, "action": "pulse", "groups": ["floor"]},
                                    {"beat": 3, "action": "clear", "end_beat": 2}]
        arr["lightshow"]["generated"]["events"].append([1.0, 7, 0, 1.0])
        messages = " | ".join(d["message"] for d in errors(arr))
        for text in ("environment must be one of", "lightshow.tempo is unsupported", "palette must be one of",
                     "speed must be an integer", "groups must list", "end_beat must follow", "event type must be"):
            self.assertIn(text, messages)

    def test_strobing_cues_block(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 20 + i / 8, "action": "pulse", "style": "flash"} for i in range(24)]
        self.assertIn("light_strobe", codes(errors(arr)))

    def test_white_full_field_flashes_block_sooner(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 20 + i / 4, "action": "pulse", "color": "white",
                                     "groups": ["back", "ring", "center"]} for i in range(6)]
        self.assertIn("light_strobe", codes(errors(arr)))

    def test_override_for_an_unknown_section_warns(self):
        arr = lit(arrangement(), sections={"gone": {"mood": "peak"}})
        warnings = [d for d in validate_arrangement(arr) if d["code"] == "lightshow_unknown_section"]
        self.assertEqual(len(warnings), 1)


class CheckTests(unittest.TestCase):
    def test_static_lights_over_active_audio_warn(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 8, "action": "clear", "end_beat": 32}]
        _, findings = lighting_findings(arr, report())
        self.assertIn("light_unmapped", codes(findings))

    def test_darkness_while_notes_are_played_warns(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 8, "action": "clear", "end_beat": 20},
                                    {"beat": 8, "action": "off"}]
        _, findings = lighting_findings(arr, report())
        self.assertIn("light_blackout_notes", codes(findings))

    def test_sustained_heavy_flashing_warns_without_blocking(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 8 + i / 3, "action": "pulse", "groups": ["back", "ring", "left", "right"]}
                                    for i in range(36)]
        self.assertNotIn("light_strobe", codes(errors(arr)))
        _, findings = lighting_findings(arr, report())
        self.assertIn("light_flash_heavy", codes(findings))

    def test_pulses_on_the_grid_without_sound_warn(self):
        arr = lit(arrangement())
        arr["lightshow"]["cues"] = [{"beat": 8, "action": "clear", "end_beat": 20},
                                    *({"beat": 8.3 + i, "action": "pulse", "groups": ["ring"]} for i in range(10))]
        _, findings = lighting_findings(arr, report())
        self.assertIn("light_without_audio", codes(findings))

    def test_sparse_lights_over_a_busy_band_and_excess_density_warn(self):
        sparse = lit(arrangement(), report(dense=True))
        sparse["lightshow"]["cues"] = [{"beat": 0, "action": "clear", "end_beat": 48}]
        _, findings = lighting_findings(sparse, report(dense=True))
        self.assertIn("light_density", codes(findings))
        self.assertLess(DENSITY_LOW, DENSITY_HIGH)

    def test_stale_lights_are_reported_when_auto_is_off(self):
        arr = lit(arrangement(), auto=False)
        self.assertEqual(lighting_findings(arr, report())[0]["state"], "current")
        newer = report(created="2026-09-24T00:00:00+00:00")
        self.assertIn("lightshow_stale", codes(lighting_findings(arr, newer)[1]))
        kept, info = refresh_lightshow(arr, arr, "n" * 32, newer)
        self.assertEqual(info["action"], "kept")
        self.assertIs(kept, arr)

    def test_critique_carries_lighting(self):
        result = critique_arrangement(lit(arrangement()), report())
        self.assertTrue(result["metrics"]["lighting"]["checked"])
        self.assertIn("light_strobe", result["definitions"])

    def test_missing_lights_warn_only_with_evidence(self):
        self.assertEqual(lighting_findings(arrangement(), None)[1], [])
        self.assertEqual(codes(lighting_findings(arrangement(), report())[1]), ["lightshow_missing"])

    def test_inspect_lists_events_with_the_sounds_under_them(self):
        view = inspect_lights(lit(arrangement()), report(), 8, 12)
        self.assertEqual(view["state"], "current")
        self.assertTrue(all(8 <= row["beat"] < 12 for row in view["timeline"]))
        self.assertTrue(any("drums:spectral_flux" in s for row in view["timeline"] for s in row["sounds"]))

    def test_calibration_constants_match_the_reference_study(self):
        summary = json.loads(RESOURCE.read_text(encoding="utf-8"))["summary"]
        tiers = summary["tier_light_events_per_second"]
        self.assertEqual(DENSITY_LOW, tiers["low"]["p10"])
        self.assertEqual(DENSITY_HIGH, tiers["high"]["p90"])
        self.assertLessEqual(TARGET_RATE["peak"], tiers["high"]["p75"])


class ProjectLightingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        created = self.store.create(demo=True)
        self.project_id, self.revision = created["project"]["id"], created["revision"]
        self.directory = self.store.directory(self.project_id)
        run = self.directory / "musical" / ("a" * 32)
        run.mkdir(parents=True)
        (run / "report.json").write_text(json.dumps(report(48.0, sha256=_hash(self.directory / "song.ogg"))),
                                         encoding="utf-8")
        self.arrangement = created["arrangement"]

    def cli(self, *args):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["project", *args, self.project_id, "--workspace", self.temp.name]), 0)
        return json.loads(stream.getvalue())

    def test_save_generates_lights_automatically(self):
        saved = self.store.save(self.project_id, self.arrangement, self.revision)
        show = saved["arrangement"]["lightshow"]
        self.assertEqual(saved["lighting"]["action"], "generated")
        self.assertEqual(show["environment"], "BigMirrorEnvironment")
        self.assertEqual(show["generated"]["evidence_run"], "a" * 32)
        self.assertTrue(show["generated"]["events"])
        self.assertFalse([d for d in saved["diagnostics"] if d["code"].startswith("light")])

    def test_omitted_lights_are_carried_over_with_their_cues(self):
        first = self.store.save(self.project_id, self.arrangement, self.revision)
        tweaked = copy.deepcopy(first["arrangement"])
        tweaked["lightshow"]["cues"] = [{"beat": 20, "action": "zoom", "note": "drop"}]
        second = self.store.save(self.project_id, tweaked, first["revision"])
        self.assertEqual(second["lighting"]["action"], "kept")
        edited = copy.deepcopy(second["arrangement"])
        del edited["lightshow"]
        edited["sections"][0]["notes"][0]["x"] = 3 - edited["sections"][0]["notes"][0]["x"]
        third = self.store.save(self.project_id, edited, second["revision"])
        self.assertEqual(third["arrangement"]["lightshow"]["cues"], tweaked["lightshow"]["cues"])

    def test_input_changes_regenerate_unless_auto_is_off(self):
        first = self.store.save(self.project_id, self.arrangement, self.revision)
        restyled = copy.deepcopy(first["arrangement"])
        restyled["lightshow"]["sections"] = {"section-02": {"mood": "calm", "primary": "red"}}
        second = self.store.save(self.project_id, restyled, first["revision"])
        self.assertEqual(second["lighting"]["action"], "generated")
        moods = {s["id"]: s for s in second["arrangement"]["lightshow"]["generated"]["sections"]}
        self.assertEqual((moods["section-02"]["mood"], moods["section-02"]["primary"]), ("calm", "red"))
        manual = copy.deepcopy(second["arrangement"])
        manual["lightshow"]["auto"] = False
        manual["lightshow"]["sections"] = {}
        third = self.store.save(self.project_id, manual, second["revision"])
        self.assertEqual(third["lighting"]["action"], "kept")
        self.assertIn("lightshow_stale", [d["code"] for d in third["diagnostics"]])

    def test_locked_sections_keep_their_lights(self):
        first = self.store.save(self.project_id, self.arrangement, self.revision)
        locked = self.store.set_lock(self.project_id, "section-02", True, first["revision"])
        before = [e for e in locked["arrangement"]["lightshow"]["generated"]["events"] if 20 <= e[0] < 36]
        restyled = copy.deepcopy(locked["arrangement"])
        restyled["lightshow"]["style"]["palette"] = "red"
        saved = self.store.save(self.project_id, restyled, locked["revision"])
        self.assertEqual(saved["lighting"]["action"], "generated")
        after = [e for e in saved["arrangement"]["lightshow"]["generated"]["events"] if 20 <= e[0] < 36]
        self.assertEqual(before, after)
        cued = copy.deepcopy(saved["arrangement"])
        cued["lightshow"]["cues"] = [{"beat": 24, "action": "spin"}]
        with self.assertRaisesRegex(ConflictError, "section-02"):
            self.store.save(self.project_id, cued, saved["revision"])

    def test_cli_regenerates_inspects_and_export_uses_the_environment(self):
        dry = self.cli("lights", "--revision", self.revision, "--dry-run")
        self.assertFalse(dry["saved"])
        result = self.cli("lights", "--revision", self.revision)
        self.assertTrue(result["saved"])
        self.assertEqual(result["environment"], "BigMirrorEnvironment")
        self.assertEqual([s["id"] for s in result["sections"]], [s["id"] for s in self.arrangement["sections"]])
        view = self.cli("lights-inspect", "--start", "20", "--end", "24")
        self.assertEqual(view["revision"], result["revision"])
        self.assertTrue(view["timeline"])
        exported = self.store.export(self.project_id)
        self.assertEqual(exported["report"]["lighting"]["source"], "lightshow")
        with ZipFile(self.directory / "exports" / exported["filename"]) as archive:
            info = json.loads(archive.read("Info.dat"))
            beatmap = json.loads(archive.read("Expert.dat"))
        self.assertEqual(info["_environmentName"], "BigMirrorEnvironment")
        self.assertEqual(len(beatmap["basicBeatmapEvents"]), exported["report"]["lighting"]["basic_events"])

    def test_each_difficulty_keeps_its_own_lights_and_environment(self):
        first = self.store.save(self.project_id, self.arrangement, self.revision)
        added = self.store.add_difficulty(self.project_id, "ExpertPlus")
        self.assertEqual(added["arrangement"]["lightshow"]["generated"], first["arrangement"]["lightshow"]["generated"])
        other = copy.deepcopy(added["arrangement"])
        other["lightshow"]["environment"] = "NiceEnvironment"
        self.store.save(self.project_id, other, added["revision"], difficulty="ExpertPlus")
        exported = self.store.export(self.project_id)
        with ZipFile(self.directory / "exports" / exported["filename"]) as archive:
            info = json.loads(archive.read("Info.dat"))
        self.assertEqual(info["_environmentNames"], ["BigMirrorEnvironment", "NiceEnvironment"])
        indexes = {d["_difficulty"]: d["_environmentNameIdx"] for d in info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"]}
        self.assertEqual(indexes, {"Expert": 0, "ExpertPlus": 1})

    def test_cli_requires_evidence(self):
        other = self.store.create(demo=True)
        with redirect_stdout(io.StringIO()):
            code = main(["project", "lights", other["project"]["id"], "--workspace", self.temp.name,
                         "--revision", other["revision"]])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
