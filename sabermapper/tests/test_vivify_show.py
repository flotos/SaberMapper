"""Vivify Phase A: arrangement 0.2 presentation, show.json 0.1, compiler merge, checks and vivified export."""
import copy
import hashlib
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from sabermapper import vivify
from sabermapper.arrangement import compile_arrangement
from sabermapper.export import ExportError, export_arrangement, export_arrangements
from sabermapper.mapio import parse_map
from sabermapper.projects import ConflictError, ProjectStore
from sabermapper.show import ShowError, save_show, validate_show
from sabermapper.show_compile import compile_show
from sabermapper.show_validation import check_compiled, compile_difficulty
from sabermapper.storage import read_json, write_json
from sabermapper.validation import validate_arrangement

try:
    import vivify_fixtures as fx
except ImportError:  # run as tests.test_vivify_show
    from tests import vivify_fixtures as fx

AUDIO, COVER = fx.FIXTURES / "silence.ogg", fx.FIXTURES / "cover.png"
EVIDENCE = {"report": fx.report(), "run_id": "r1"}
# The EXSII maps are local user data (never committed); SABERMAPPER_EXSII points at another checkout's copy.
EXSII = Path(os.environ.get("SABERMAPPER_EXSII") or
             Path(__file__).resolve().parents[1] / "workspace" / "corpus" / "extrasensory" / "extracted")
EXSII_INDEX = Path(__file__).resolve().parents[1] / "docs" / "references" / "extrasensory" / "map-index.json"


def errors(findings, code=None):
    return [d for d in findings if d["severity"] == "error" and (code is None or d["code"] == code)]


def codes(findings):
    return {d["code"] for d in findings}


class BundleCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle_dir = fx.write_bundle(self.root / "assets")
        self.bundle = vivify.read_bundle(self.bundle_dir)

    def compile(self, primitives, arrangement=None, bundle="default", evidence=EVIDENCE):
        show = {"schema_version": "0.1", "primitives": primitives}
        arrangement = arrangement or fx.arrangement()
        return compile_difficulty(show, arrangement, bundle=self.bundle if bundle == "default" else bundle,
                                  evidence=evidence)

    def primitive(self, pid):
        return copy.deepcopy(next(p for p in fx.show()["primitives"] if p.get("id") == pid))


class PresentationTests(unittest.TestCase):
    def test_0_2_accepts_presentation_and_compiles_like_0_1(self):
        presented, plain = fx.arrangement("0.2"), fx.arrangement("0.1")
        self.assertEqual(errors(validate_arrangement(presented)), [])
        self.assertEqual(errors(validate_arrangement(plain)), [])
        self.assertEqual(compile_arrangement(presented), compile_arrangement(plain))

    def test_0_1_still_rejects_presentation_fields(self):
        plain = fx.arrangement("0.1")
        plain["presentation"] = {"concept": "x"}
        plain["sections"][0]["presentation"] = {"family": "scene"}
        found = errors(validate_arrangement(plain), "unsupported_field")
        self.assertEqual(len(found), 2)

    def test_0_2_rejects_unknown_and_invalid_presentation(self):
        cases = [
            (lambda a: a["presentation"].update(mood="x"), "unsupported_field"),
            (lambda a: a["presentation"].update(possession="feet"), "invalid_presentation"),
            (lambda a: a["presentation"].update(palette=["red"]), "invalid_presentation"),
            (lambda a: a["sections"][0]["presentation"].update(family="both"), "invalid_presentation"),
            (lambda a: a["sections"][0]["presentation"].update(attention={"notes": 0.8, "scene": 0.5}),
             "invalid_presentation"),
            (lambda a: a["sections"][0]["presentation"].pop("family"), "invalid_presentation"),
            (lambda a: a["sections"][0]["presentation"].update(note_style="wild"), "invalid_presentation"),
            (lambda a: a["sections"][0]["presentation"].update(sparkle=True), "unsupported_field"),
            (lambda a: a.update(extra=1), "unsupported_field"),
        ]
        for change, code in cases:
            arrangement = fx.arrangement()
            change(arrangement)
            self.assertTrue(errors(validate_arrangement(arrangement), code), code)

    def test_unknown_schema_version_rejected(self):
        arrangement = fx.arrangement()
        arrangement["schema_version"] = "0.3"
        self.assertTrue(errors(validate_arrangement(arrangement), "schema_version"))


class PlainExportRegressionTests(unittest.TestCase):
    def test_0_1_export_is_byte_identical_to_the_golden(self):
        # Digests of a plain 0.1 export; the Vivify layer must never change it. (Re-recorded on 2026-09-23 when
        # the swing-flow parity rule made the old example chart invalid; the Vivify code is unchanged.)
        golden = read_json(fx.FIXTURES / "plain-0.1-export-golden.json")
        arrangement = fx.arrangement("0.1")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "map.zip"
            export_arrangement(arrangement, AUDIO, COVER, output)
            with ZipFile(output) as archive:
                digests = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
            self.assertEqual(digests, golden)
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["map.zip"])

    def test_plain_project_export_has_no_twin_or_custom_data(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(temp)
            project = store.create(demo=True)["project"]["id"]
            result = store.export(project)
            self.assertNotIn("vanilla_twin", result)
            self.assertNotIn("vivify", result["report"])
            exports = store.root / "projects" / project / "exports"
            self.assertEqual(sorted(p.suffix for p in exports.iterdir()), [".json", ".zip"])
            with ZipFile(exports / result["filename"]) as archive:
                self.assertNotIn("_customData", json.loads(archive.read("Info.dat")))
                self.assertNotIn("customData", json.loads(archive.read("Expert.dat")))


class PrimitiveCompileTests(BundleCase):
    def test_setup(self):
        beatmap, result = self.compile([self.primitive("setup")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 0, "t": "CreateScreenTexture", "d": {"id": "_Half", "xRatio": 2, "yRatio": 2}},
            {"b": 0, "t": "CreateCamera", "d": {"id": "depthcam", "texture": "_Depth",
                                                "properties": {"clearFlags": "Depth"}}},
            {"b": 0, "t": "SetCameraProperty", "d": {"properties": {"depthTextureMode": ["Depth"]}}},
            {"b": 0, "t": "SetRenderingSettings", "d": {"renderSettings": {"fog": 0}}}])
        self.assertEqual({row["evidence"]["source"] for row in result["provenance"]}, {"setup"})
        setup = {"kind": "setup", "player_tracks": {"Head": "sm_head"}}
        beatmap, _ = self.compile([setup])
        self.assertEqual(beatmap["customData"]["customEvents"],
                         [{"b": 0, "t": "AssignPlayerToTrack", "d": {"track": "sm_head", "target": "Head"}}])

    def test_look(self):
        beatmap, result = self.compile([self.primitive("grey")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 0, "t": "Blit", "d": {"asset": "assets/sm/post/glow.mat", "duration": 8, "priority": 1,
                                        "properties": [{"id": "_Amount", "type": "Float", "value": 0.2}]}},
            {"b": 4, "t": "SetMaterialProperty", "d": {
                "asset": "assets/sm/post/glow.mat", "duration": 2,
                "properties": [{"id": "_Amount", "type": "Float", "value": [[0.2, 0], [0.6, 1, "easeOutQuad"]]}]}}])
        self.assertEqual(result["provenance"][1]["evidence"]["id"], "drums:spectral_flux:2")
        self.assertEqual(result["requirements"], ["Vivify"])

    def test_keyframe_after_points_starts_where_the_points_end(self):
        # Ko Phangan: an animal ran in with points [-40 -> 0]; its exit keyframe restarted from -40.
        look = dict(self.primitive("grey"), keyframes=[
            {"beat": 1, "property": "_Amount", "points": [[0.9, 0], [0.4, 1, "easeOutQuad"]], "duration_beats": 1},
            {"beat": 4, "property": "_Amount", "value": 0.6, "duration_beats": 2}])
        beatmap, _ = self.compile([look])
        events = [e for e in beatmap["customData"]["customEvents"] if e["t"] == "SetMaterialProperty"]
        self.assertEqual(events[1]["d"]["properties"][0]["value"], [[0.4, 0], [0.6, 1]])

    def test_scene_pairs_spawn_with_destroy(self):
        beatmap, result = self.compile([self.primitive("ring")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 8, "t": "InstantiatePrefab", "d": {"asset": "assets/sm/scene/ring.prefab", "id": "sm_scene_ring",
                                                     "track": "sm_scene_ring", "position": [0, 2, 20]}},
            {"b": 8, "t": "AnimateTrack", "d": {"track": "sm_scene_ring", "duration": 4,
                                                "scale": [[1, 1, 1, 0], [2, 2, 2, 1]]}},
            {"b": 12, "t": "SetMaterialProperty", "d": {"asset": "assets/sm/scene/ring.mat", "properties": [
                {"id": "_Glow", "type": "Float", "value": 1}]}},
            {"b": 16, "t": "DestroyObject", "d": {"id": "sm_scene_ring"}}])
        self.assertEqual(result["provenance"][3]["evidence"], {"source": "lifetime", "of_event": 0})
        self.assertEqual(result["requirements"], ["Vivify", "Noodle Extensions"])
        persistent = dict(self.primitive("ring"), persist=True)
        beatmap, result = self.compile([persistent])
        self.assertNotIn("DestroyObject", [e["t"] for e in beatmap["customData"]["customEvents"]])
        self.assertEqual(errors(result["diagnostics"]), [])

    def test_skin_assigns_prefab_and_note_tracks(self):
        beatmap, _ = self.compile([self.primitive("glass")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 8, "t": "AssignObjectPrefab", "d": {"colorNotes": {"track": "sm_skin_glass",
                                                                     "asset": "assets/sm/skins/glassnote.prefab"}}}])
        tracks = [n.get("customData") for n in beatmap["colorNotes"]]
        self.assertEqual(tracks, [None] * 4 + [{"track": "sm_skin_glass"}] * 6 + [None] * 2)
        self.assertNotIn("customData", beatmap["bombNotes"][0])

    def test_pulse_binds_onsets_and_sustains(self):
        beatmap, result = self.compile([self.primitive("kick")])
        value = [[0.95, 0], [0.5, 1, "easeOutQuad"]]
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": b, "t": "SetMaterialProperty", "d": {"asset": "assets/sm/scene/ring.mat", "duration": 0.5,
                                                       "properties": [{"id": "_Glow", "type": "Float", "value": value}]}}
            for b in (8, 12)])
        self.assertEqual([row["evidence"]["id"] for row in result["provenance"]],
                         ["drums:spectral_flux:4", "drums:spectral_flux:6"])
        swell = {"kind": "pulse", "section": "bridge", "global": True, "type": "Float", "property": "_Swell",
                 "driver": {"source": "sustains", "layer": "vocals"}, "envelope": {"peak": 1, "scale_by_strength": False}}
        beatmap, result = self.compile([swell])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 18, "t": "SetGlobalProperty", "d": {"duration": 3, "properties": [
                {"id": "_Swell", "type": "Float", "value": [[1.0, 0], [1.0, 0.833333], [0.0, 1, "easeOutQuad"]]}]}}])
        self.assertEqual(result["provenance"][0]["evidence"]["source"], "sustains")
        track = {"kind": "pulse", "section": "drop", "track": "sm_scene_ring", "property": "scale",
                 "driver": {"source": "onsets", "layer": "drums", "min_strength": 0.8},
                 "envelope": {"peak": 1.5, "base": 1, "scale_by_strength": False}, "max_events": 1}
        beatmap, _ = self.compile([track])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 8, "t": "AnimateTrack", "d": {"track": "sm_scene_ring", "duration": 0.5,
                                                "scale": [[1.5, 1.5, 1.5, 0], [1.0, 1.0, 1.0, 1, "easeOutQuad"]]}}])

    def test_possess(self):
        beatmap, _ = self.compile([self.primitive("head")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 0, "t": "AssignPlayerToTrack", "d": {"track": "sm_head", "target": "Head"}},
            {"b": 16, "t": "AnimateTrack", "d": {"track": "sm_head", "duration": 8,
                                                 "position": [[0, 0, 0, 0], [0, 0.5, 0, 1]]}}])

    def test_env(self):
        beatmap, result = self.compile([self.primitive("fog")])
        self.assertEqual(beatmap["customData"]["environment"],
                         [{"id": "Environment", "lookupMethod": "Contains", "track": "sm_env"}])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 16, "t": "AnimateComponent", "d": {"track": "sm_env", "duration": 4, "BloomFogEnvironment": {
                "attenuation": [[0.1, 0], [0.01, 1]]}}}])
        self.assertEqual(result["requirements"], ["Chroma"])
        materials = {"kind": "env", "materials": {"glass": {"shader": "Standard", "color": [1, 1, 1, 1]}}}
        beatmap, result = self.compile([materials])
        self.assertEqual(beatmap["customData"], {"materials": {"glass": {"shader": "Standard", "color": [1, 1, 1, 1]}}})

    def test_path_sets_per_note_jump_only_where_declared(self):
        path = dict(self.primitive("float"), animation={"dissolve": [[0, 0], [1, 0.2]]}, world_rotation=[0, 15, 0],
                    colors=[1])
        beatmap, result = self.compile([path], fx.arrangement(choreographed=True))
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 16, "t": "AssignPathAnimation", "d": {"track": "sm_path_float", "offsetPosition": [
                [0, 0, 10, 0], [0, 0, 0, 0.5, "easeOutSine"]]}}])
        notes = [n.get("customData") for n in beatmap["colorNotes"]]
        self.assertEqual(notes[:11], [None] * 11)
        self.assertEqual(notes[11], {"track": "sm_path_float", "noteJumpMovementSpeed": 10,
                                     "noteJumpStartBeatOffset": 1, "animation": {"dissolve": [[0, 0], [1, 0.2]]},
                                     "worldRotation": [0, 15, 0]})
        self.assertEqual(result["requirements"], ["Noodle Extensions"])
        # colors=[1] leaves the red bridge note without per-note NJS: a choreographed-section error.
        self.assertEqual(len(errors(result["diagnostics"], "choreographed_note_jump_missing")), 1)

    def test_raw(self):
        beatmap, result = self.compile([self.primitive("anim")])
        self.assertEqual(beatmap["customData"]["customEvents"], [
            {"b": 20, "t": "AnimateTrack", "d": {"track": "sm_env", "duration": 1, "dissolve": [[1, 0], [0, 1]]}}])
        self.assertEqual(result["requirements"], ["Noodle Extensions"])

    def test_full_show_is_clean_and_ordered(self):
        beatmap, result = compile_difficulty(fx.show(), fx.arrangement(choreographed=True), bundle=self.bundle, evidence=EVIDENCE)
        self.assertEqual(errors(result["diagnostics"]), [])
        beats = [e["b"] for e in beatmap["customData"]["customEvents"]]
        self.assertEqual(beats, sorted(beats))
        self.assertEqual(len(result["provenance"]), len(beats))
        self.assertTrue(all(row["evidence"] for row in result["provenance"]))
        self.assertEqual(result["requirements"], ["Vivify", "Noodle Extensions", "Chroma"])


class RequirementTests(unittest.TestCase):
    def test_requirements_follow_the_events_used(self):
        self.assertEqual(vivify.requirements({}), [])
        self.assertEqual(vivify.requirements({"customEvents": [{"b": 0, "t": "Blit", "d": {}}]}), ["Vivify"])
        self.assertEqual(vivify.requirements({"customEvents": [{"b": 0, "t": "AnimateTrack",
                                                                "d": {"track": "t", "color": [[1, 1, 1, 1, 0]]}}]}),
                         ["Chroma"])
        self.assertEqual(vivify.requirements({}, [{"track": "t"}]), [])
        self.assertEqual(vivify.requirements({}, [{"noteJumpMovementSpeed": 10}]), ["Noodle Extensions"])
        self.assertEqual(vivify.requirements({"environment": [{"id": "x"}]}), ["Chroma"])


class ValidationRuleTests(BundleCase):
    def test_bundle_paths_properties_and_types(self):
        look = {"kind": "look", "section": "intro", "material": "assets/sm/post/missing.mat"}
        _, result = self.compile([look])
        self.assertTrue(errors(result["diagnostics"], "unknown_material"))
        raw = {"kind": "raw", "event": {"b": 1, "t": "SetMaterialProperty", "d": {
            "asset": "Assets/SM/Post/Glow.mat", "properties": [{"id": "_Amount", "type": "Float", "value": 1}]}}}
        self.assertTrue(errors(self.compile([raw])[1]["diagnostics"], "asset_path_case"))
        raw["event"]["d"]["asset"] = "assets/sm/post/glow.mat"
        raw["event"]["d"]["properties"] = [{"id": "_Nope", "type": "Float", "value": 1}]
        self.assertTrue(errors(self.compile([raw])[1]["diagnostics"], "unknown_material_property"))
        raw["event"]["d"]["properties"] = [{"id": "_Tint", "type": "Float", "value": 1}]
        self.assertTrue(errors(self.compile([raw])[1]["diagnostics"], "property_type_mismatch"))
        raw["event"]["d"]["properties"] = [{"id": "_Tint", "type": "Color", "value": [1, 0]}]
        self.assertTrue(errors(self.compile([raw])[1]["diagnostics"], "property_value_shape"))
        raw["event"]["d"]["properties"] = [{"id": "_Tint", "type": "Color", "value": [1, 0, 0, 1]}]
        self.assertEqual(errors(self.compile([raw])[1]["diagnostics"]), [])
        spawn = {"kind": "raw", "event": {"b": 1, "t": "InstantiatePrefab", "d": {"asset": "assets/sm/scene/nope.prefab",
                                                                                  "id": "n"}}, "persist": True}
        self.assertTrue(errors(self.compile([spawn])[1]["diagnostics"], "unknown_prefab"))
        keyframe = {"kind": "look", "section": "intro", "material": "assets/sm/post/glow.mat",
                    "keyframes": [{"beat": 2, "property": "_Amount", "value": 1, "type": "Color"}]}
        self.assertTrue(errors(self.compile([keyframe])[1]["diagnostics"], "property_type_mismatch"))

    def test_missing_bundle_is_an_export_error_not_a_save_error(self):
        _, result = self.compile([self.primitive("grey")], bundle=None)
        self.assertTrue(errors(result["diagnostics"], "bundle_missing"))
        self.assertTrue(errors(result["diagnostics"], "property_type_unknown"))
        self.assertEqual(errors(validate_show(fx.show(), {"Expert": fx.arrangement()})), [])

    def test_spawn_needs_destroy_or_persist(self):
        spawn = {"kind": "raw", "event": {"b": 1, "t": "InstantiatePrefab",
                                          "d": {"asset": "assets/sm/scene/ring.prefab", "id": "r"}}}
        self.assertTrue(errors(self.compile([spawn])[1]["diagnostics"], "prefab_not_destroyed"))
        destroy = {"kind": "raw", "event": {"b": 4, "t": "DestroyObject", "d": {"id": ["r"]}}}
        self.assertEqual(errors(self.compile([spawn, destroy])[1]["diagnostics"]), [])
        self.assertEqual(errors(self.compile([dict(spawn, persist=True)])[1]["diagnostics"]), [])
        anonymous = {"kind": "raw", "event": {"b": 1, "t": "InstantiatePrefab", "d": {"asset": "assets/sm/scene/ring.prefab"}}}
        self.assertTrue(errors(self.compile([anonymous])[1]["diagnostics"], "prefab_without_id"))
        twice = [spawn, dict(spawn, event={**spawn["event"], "b": 2}), destroy]
        self.assertTrue(errors(self.compile(twice)[1]["diagnostics"], "duplicate_object_id"))

    def test_one_setup_and_possession_follows_the_map_decision(self):
        _, result = self.compile([{"kind": "setup"}, {"kind": "setup"}])
        self.assertTrue(errors(result["diagnostics"], "multiple_setup"))
        hands = {"kind": "possess", "target": "LeftHand", "track": "l"}
        self.assertTrue(errors(self.compile([hands])[1]["diagnostics"], "possession_not_allowed"))
        arrangement = fx.arrangement()
        arrangement["presentation"]["possession"] = "hands"
        self.assertEqual(errors(self.compile([hands], arrangement)[1]["diagnostics"]), [])
        arrangement["presentation"]["possession"] = "none"
        self.assertTrue(errors(self.compile([self.primitive("head")], arrangement)[1]["diagnostics"],
                               "possession_not_allowed"))
        plain = fx.arrangement("0.1")
        self.assertTrue(errors(self.compile([{"kind": "setup", "player_tracks": {"Root": "p"}}], plain)[1]["diagnostics"],
                               "possession_not_allowed"))
        _, result = self.compile([self.primitive("grey")])
        self.assertIn("possession_unused", codes(result["diagnostics"]))

    def test_flash_rate_ceiling(self):
        def blits(count, spacing):
            return [{"kind": "raw", "event": {"b": i * spacing, "t": "Blit",
                                              "d": {"asset": "assets/sm/post/glow.mat", "duration": spacing / 4}}}
                    for i in range(count)]
        # 120 BPM: a beat is 0.5 s; a blit every half beat flashes 4 times a second.
        self.assertTrue(errors(self.compile(blits(8, 0.5))[1]["diagnostics"], "flash_rate_exceeded"))
        found = self.compile(blits(8, 0.8))[1]["diagnostics"]
        self.assertIn("flash_rate_high", codes(found))
        self.assertFalse(errors(found, "flash_rate_exceeded"))
        self.assertFalse({"flash_rate_high", "flash_rate_exceeded"} & codes(self.compile(blits(4, 4))[1]["diagnostics"]))
        stacked = blits(1, 4) + [{"kind": "raw", "event": {"b": 0, "t": "Blit", "d": {"asset": "assets/sm/post/glow.mat",
                                                                                      "duration": 1, "pass": 1}}}]
        self.assertFalse({"flash_rate_high", "flash_rate_exceeded"} & codes(self.compile(stacked)[1]["diagnostics"]))

    @staticmethod
    def stream():
        """Sixteen alternating down/up notes in eight beats: 4 notes per second at 120 BPM."""
        return [fx.note(f"n{i}", i / 2, 1 + i % 2, 0 if (i // 2) % 2 else 1, i % 2, 1 if (i // 2) % 2 == 0 else 0)
                for i in range(16)]

    def test_attention_budget_and_choreography(self):
        arrangement = fx.arrangement(choreographed=True)
        drop = arrangement["sections"][1]
        drop["presentation"]["attention"] = {"notes": 0.3, "scene": 0.7}
        drop["notes"] = self.stream()
        _, result = self.compile([], fx.alternate_swings(arrangement))
        self.assertIn("attention_over_budget", codes(result["diagnostics"]))
        self.assertTrue(errors(result["diagnostics"], "choreographed_note_jump_missing"))
        _, result = self.compile([self.primitive("float")], fx.arrangement(choreographed=True))
        self.assertFalse(errors(result["diagnostics"]))
        fast = dict(self.primitive("float"), njs=16)
        self.assertIn("choreographed_njs_high", codes(self.compile([fast], fx.arrangement(choreographed=True))[1]["diagnostics"]))
        arrangement = fx.arrangement(choreographed=True)
        arrangement["sections"][2]["notes"] = self.stream()
        self.assertIn("choreographed_density",
                      codes(self.compile([self.primitive("float")], fx.alternate_swings(arrangement))[1]["diagnostics"]))
        wrong = dict(self.primitive("float"), section="drop")
        self.assertTrue(errors(self.compile([wrong])[1]["diagnostics"], "path_requires_choreographed"))
        blended = dict(self.primitive("grey"), section="drop", keyframes=[])
        self.assertIn("family_mismatch", codes(self.compile([blended])[1]["diagnostics"]))

    def test_envelope_and_evidence_warnings(self):
        envelope = {"max": {"custom_events": 1, "events_per_second": 0, "spawns_per_second": 1}}
        show = {"schema_version": "0.1", "primitives": [self.primitive("grey")]}
        arrangement = fx.arrangement()
        beatmap = compile_arrangement(arrangement)
        result = compile_show(show, arrangement, beatmap, bundle=self.bundle, evidence=EVIDENCE)
        found = check_compiled(show, arrangement, beatmap, result, self.bundle, envelope)
        self.assertEqual({d["metric"] for d in found if d["code"] == "outside_exsii_envelope"},
                         {"custom_events", "events_per_second"})
        offbeat = {"kind": "raw", "event": {"b": 5.3, "t": "SetGlobalProperty",
                                            "d": {"properties": [{"id": "_X", "type": "Float", "value": 1}]}}}
        _, result = self.compile([offbeat])
        self.assertIn("visual_without_evidence", codes(result["diagnostics"]))
        anchored = dict(offbeat, anchor={"source": "onsets", "id": "drums:spectral_flux:3"})
        _, result = self.compile([anchored])
        self.assertNotIn("visual_without_evidence", codes(result["diagnostics"]))
        self.assertTrue(result["provenance"][0]["evidence"]["explicit"])

    def test_drivers_for_missing_sources_fail_gracefully(self):
        lyric = {"kind": "pulse", "section": "drop", "material": "assets/sm/scene/ring.mat", "property": "_Glow",
                 "driver": {"source": "lyrics", "words": ["light"]}}
        _, result = self.compile([lyric])
        self.assertTrue(errors(result["diagnostics"], "driver_source_unavailable"))
        _, result = self.compile([self.primitive("kick")], evidence={})
        self.assertTrue(errors(result["diagnostics"], "evidence_missing"))
        bad_layer = dict(self.primitive("kick"), driver={"source": "onsets", "layer": "cowbell"})
        self.assertTrue(errors(self.compile([bad_layer])[1]["diagnostics"], "unknown_layer"))

    def test_moments_and_lyrics_from_project_files(self):
        project = self.root / "project"
        project.mkdir()
        write_json(project / "moments.json", {"items": [{"id": "drop-1", "seconds": 4.0, "kind": "drop"},
                                                        {"id": "riser", "start_seconds": 5.0, "end_seconds": 6.0,
                                                         "kind": "riser"}]})
        write_json(project / "lyrics.json", [{"word": "Light,", "start_seconds": 6.0, "end_seconds": 6.4}])
        evidence = {**EVIDENCE, "project_dir": project}
        drop = {"kind": "pulse", "section": "drop", "material": "assets/sm/scene/ring.mat", "property": "_Glow",
                "driver": {"source": "moments", "kinds": ["drop"]}}
        word = dict(drop, driver={"source": "lyrics", "words": ["light"]})
        beatmap, result = self.compile([drop, word], evidence=evidence)
        self.assertEqual([(e["b"], row["evidence"]["source"]) for e, row in
                          zip(beatmap["customData"]["customEvents"], result["provenance"])],
                         [(8, "moments"), (12, "lyrics")])
        self.assertEqual(result["provenance"][1]["evidence"]["label"], "Light,")


class StructuralValidationTests(unittest.TestCase):
    def check(self, primitive, code):
        show = {"schema_version": "0.1", "primitives": [primitive]}
        found = errors(validate_show(show, {"Expert": fx.arrangement()}), code)
        self.assertTrue(found, f"{code} not raised for {primitive}")

    def test_structure_errors(self):
        self.check({"kind": "sparkle"}, "unknown_primitive")
        self.check({"kind": "look", "section": "intro"}, "missing_field")
        self.check({"kind": "look", "section": "intro", "material": "m.mat", "glow": 1}, "unsupported_field")
        self.check({"kind": "look", "section": "outro", "material": "m.mat"}, "unknown_section")
        self.check({"kind": "look", "section": "intro", "material": "m.mat", "end_beat": 12}, "outside_section")
        self.check({"kind": "look", "section": "intro", "material": "m.mat",
                    "keyframes": [{"beat": 9, "property": "_A", "value": 1}]}, "keyframe_outside_span")
        self.check({"kind": "look", "section": "intro", "material": "m.mat",
                    "keyframes": [{"beat": 2, "property": "_A", "points": [[1, 0], [0, 2]]}]}, "invalid_points")
        self.check({"kind": "pulse", "section": "drop", "material": "m.mat", "property": "_A",
                    "driver": {"source": "vibes"}}, "invalid_driver")
        self.check({"kind": "raw", "event": {"b": 0, "t": "SpawnDragon", "d": {}}}, "raw_unknown_event")
        self.check({"kind": "raw", "event": {"b": 0, "t": "Blit", "d": {"shader": "x"}}}, "raw_invalid_field")
        self.check({"kind": "setup", "beat": 4}, "invalid_value")
        self.check({"kind": "look", "section": "intro", "material": "m.mat", "anchor": {"source": "vibes", "id": "x"}},
                   "invalid_anchor")
        show = {"schema_version": "0.2", "primitives": []}
        self.assertTrue(errors(validate_show(show, {}), "schema_version"))
        duplicate = {"schema_version": "0.1", "primitives": [{"kind": "setup", "id": "a"}, {"kind": "setup", "id": "a"}]}
        self.assertTrue(errors(validate_show(duplicate, {}), "duplicate_id"))

    def test_fixture_show_is_structurally_valid(self):
        self.assertEqual(validate_show(fx.show(), {"Expert": fx.arrangement(choreographed=True)}), [])


class VivifiedExportTests(BundleCase):
    def export(self, arrangement=None, **options):
        output = self.root / "out" / "map.zip"
        report = export_arrangements([arrangement or fx.arrangement(choreographed=True)], AUDIO, COVER, output, **options)
        return output, report

    def test_bundle_copied_asset_bundle_filled_twin_stripped(self):
        output, report = self.export(show=fx.show(), bundle_dir=self.bundle_dir, evidence=EVIDENCE)
        with ZipFile(output) as archive:
            self.assertIn("bundleWindows2021.vivify", archive.namelist())
            self.assertEqual(archive.read("bundleWindows2021.vivify"), b"UnityFS\x00fake bundle")
            info = json.loads(archive.read("Info.dat"))
            self.assertEqual(info["_customData"], {"_assetBundle": {"_windows2021": 1234567890}})
            entry = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0]
            self.assertEqual(entry["_customData"], {"_requirements": ["Vivify", "Noodle Extensions", "Chroma"]})
            beatmap = json.loads(archive.read("Expert.dat"))
            self.assertTrue(beatmap["customData"]["customEvents"])
        twin = output.with_name("map-vanilla.zip")
        self.assertEqual(report["vivify"]["vanilla_twin"], str(twin))
        with ZipFile(twin) as archive:
            self.assertNotIn("bundleWindows2021.vivify", archive.namelist())
            info = json.loads(archive.read("Info.dat"))
            self.assertNotIn("_customData", info)
            self.assertNotIn("_customData", info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0])
            text = archive.read("Expert.dat").decode()
            self.assertNotIn("customData", text)
            self.assertEqual(json.loads(text)["colorNotes"], [{k: v for k, v in n.items() if k != "customData"}
                                                              for n in beatmap["colorNotes"]])
        sidecar = read_json(Path(report["vivify"]["provenance_file"]))
        rows = sidecar["difficulties"]["Expert"]
        self.assertEqual(len(rows), len(beatmap["customData"]["customEvents"]))
        self.assertEqual([r["event_index"] for r in rows], list(range(len(rows))))
        self.assertNotIn("_provenance", json.dumps(report))
        self.assertIn("bundle_platform_missing", codes(report["vivify"]["warnings"]))

    def test_note_colors_become_the_map_colour_scheme(self):
        arrangement = fx.arrangement(choreographed=True)
        arrangement["presentation"]["note_colors"] = {"left": "#4dff59", "right": [0.95, 1, 0.95]}
        self.assertFalse(errors(validate_arrangement(arrangement), "invalid_presentation"))
        output, _ = self.export(arrangement, show=fx.show(), bundle_dir=self.bundle_dir, evidence=EVIDENCE)
        with ZipFile(output) as archive:
            info = json.loads(archive.read("Info.dat"))
        scheme = info["_colorSchemes"][0]
        self.assertTrue(scheme["useOverride"])
        # Info 2.1.0 keys only: SongCore refuses the map on anything else (environmentColorW broke loading).
        self.assertEqual(set(scheme["colorScheme"]), {
            "colorSchemeId", "saberAColor", "saberBColor", "environmentColor0", "environmentColor1", "obstaclesColor",
            "environmentColor0Boost", "environmentColor1Boost"})
        self.assertEqual(scheme["colorScheme"]["saberAColor"], {"r": 0.302, "g": 1.0, "b": 0.349, "a": 1.0})
        self.assertEqual(scheme["colorScheme"]["saberBColor"], {"r": 0.95, "g": 1.0, "b": 0.95, "a": 1.0})
        entry = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0]
        self.assertEqual(entry["_beatmapColorSchemeIdx"], 0)
        self.assertEqual(entry["_customData"]["_colorLeft"], {"r": 0.302, "g": 1.0, "b": 0.349})
        self.assertEqual(entry["_customData"]["_requirements"], ["Vivify", "Noodle Extensions", "Chroma"])
        with ZipFile(output.with_name("map-vanilla.zip")) as archive:
            twin = json.loads(archive.read("Info.dat"))
        self.assertEqual(twin["_colorSchemes"], info["_colorSchemes"])
        self.assertNotIn("_customData", twin["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"][0])
        for bad in ({"left": "#4dff59"}, {"left": "green", "right": "#ffffff"}):
            arrangement["presentation"]["note_colors"] = bad
            self.assertTrue(errors(validate_arrangement(arrangement), "invalid_presentation"))

    def test_exporter_never_computes_crcs_and_fails_on_errors(self):
        (self.bundle_dir / "bundleAndroid2021.vivify").write_bytes(b"x")
        with self.assertRaisesRegex(ExportError, "bundle_crc_missing"):
            self.export(show=fx.show(), bundle_dir=self.bundle_dir, evidence=EVIDENCE)
        (self.bundle_dir / "bundleAndroid2021.vivify").unlink()
        with self.assertRaisesRegex(ExportError, "bundle_missing"):
            self.export(show=fx.show(), bundle_dir=self.root / "nowhere", evidence=EVIDENCE)
        bad = fx.show()
        bad["primitives"].append({"kind": "setup"})
        with self.assertRaisesRegex(ExportError, "multiple_setup"):
            self.export(show=bad, bundle_dir=self.bundle_dir, evidence=EVIDENCE)
        self.assertFalse((self.root / "out" / "map.zip").exists())

    def test_audio_offset_shifts_custom_events(self):
        arrangement = fx.arrangement()
        arrangement["song"]["audio_offset_seconds"] = 0.5
        output = self.root / "shift.zip"
        show = {"schema_version": "0.1", "primitives": [self.primitive("head")]}
        export_arrangements([arrangement], AUDIO, COVER, output, show=show, bundle_dir=self.bundle_dir,
                            evidence=EVIDENCE)
        with ZipFile(output) as archive:
            beatmap = json.loads(archive.read("Expert.dat"))
        self.assertEqual([e["b"] for e in beatmap["customData"]["customEvents"]], [1.0, 17.0])
        self.assertEqual(beatmap["colorNotes"][0]["b"], 1.0)

    def test_presentation_only_export_still_gets_a_twin(self):
        output, report = self.export(fx.arrangement())
        self.assertEqual(report["vivify"]["requirements"], {"Expert": []})
        self.assertTrue(output.with_name("map-vanilla.zip").exists())


class ShowStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(self.temp.name)
        self.project = self.store.create(demo=True)["project"]["id"]
        self.path = self.store.directory(self.project)
        record = self.store.get(self.project)
        arrangement = fx.arrangement()
        arrangement["song"] = record["arrangement"]["song"]
        arrangement["sections"] = [dict(s, notes=[]) if s["id"] != "intro" else s for s in arrangement["sections"]]
        write_json(self.path / "arrangement.json", arrangement)
        fx.write_bundle(self.path / "assets")
        self.show = {"schema_version": "0.1", "primitives": [
            {"kind": "look", "id": "grey", "section": "intro", "material": "assets/sm/post/glow.mat"},
            {"kind": "look", "id": "late", "section": "drop", "material": "assets/sm/post/glow.mat"}]}

    def test_first_save_conflicts_and_written_against(self):
        record = self.store.get(self.project)
        self.assertEqual(record["show"]["revision"], "none")
        self.assertIsNone(record["show"]["document"])
        self.assertEqual(record["show"]["bundle"]["crcs"]["_windows2021"], 1234567890)
        with self.assertRaises(ConflictError):
            save_show(self.store, self.project, self.show, "abc")
        saved = save_show(self.store, self.project, self.show, "none")
        self.assertEqual(saved["written_against"], {"Expert": record["revision"]})
        self.assertEqual(self.store.get(self.project)["show"]["revision"], saved["revision"])
        with self.assertRaises(ConflictError):
            save_show(self.store, self.project, self.show, "none")
        changed = copy.deepcopy(self.show)
        changed["description"] = "v2"
        second = save_show(self.store, self.project, changed, saved["revision"])
        self.assertTrue((self.path / "show-history" / (saved["revision"] + ".json")).exists())
        self.assertTrue((self.path / "show-history" / (second["revision"] + ".json")).exists())
        operations = [read_json(p).get("operation") for p in (self.path / "revisions").glob("*.json")]
        self.assertEqual(operations.count("save_show"), 2)

    def test_structural_errors_block_save_but_bundle_gaps_do_not(self):
        broken = {"schema_version": "0.1", "primitives": [{"kind": "look", "section": "nowhere", "material": "x.mat"}]}
        with self.assertRaises(ShowError) as caught:
            save_show(self.store, self.project, broken, "none")
        self.assertEqual(caught.exception.code, "show_invalid")
        missing = {"schema_version": "0.1", "primitives": [{"kind": "look", "section": "intro",
                                                            "material": "assets/sm/post/unknown.mat"}]}
        save_show(self.store, self.project, missing, "none")

    def test_edits_over_locked_sections_are_refused(self):
        saved = save_show(self.store, self.project, self.show, "none")
        record = self.store.get(self.project)
        self.store.set_lock(self.project, "intro", True, record["revision"])
        touching = copy.deepcopy(self.show)
        touching["primitives"][0]["priority"] = 3
        with self.assertRaisesRegex(ConflictError, "intro"):
            save_show(self.store, self.project, touching, saved["revision"])
        elsewhere = copy.deepcopy(self.show)
        elsewhere["primitives"][1]["priority"] = 3
        save_show(self.store, self.project, elsewhere, saved["revision"])
        stale = self.store.get(self.project)["show"]
        self.assertEqual(stale["stale_difficulties"], [])

    def test_project_export_is_vivified_and_reports_both_paths(self):
        save_show(self.store, self.project, self.show, "none")
        result = self.store.export(self.project)
        exports = self.path / "exports"
        self.assertTrue((exports / result["vanilla_twin"]).exists())
        self.assertTrue((exports / result["provenance_file"]).exists())
        self.assertTrue(result["vanilla_twin"].endswith("-vanilla.zip"))
        self.assertTrue(result["vanilla_twin_url"].endswith("/exports/" + result["vanilla_twin"]))

    def test_cli_round_trip(self):
        from sabermapper.__main__ import main

        def run(*argv):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(list(argv))
            return code, json.loads(out.getvalue()) if out.getvalue() else None
        file = Path(self.temp.name) / "show.json"
        file.write_text(json.dumps(self.show), encoding="utf-8")
        code, got = run("show", "get", self.project, "--workspace", self.temp.name)
        self.assertEqual((code, got["revision"]), (0, "none"))
        code, saved = run("show", "save", self.project, "--workspace", self.temp.name, "--show", str(file),
                          "--revision", "none")
        self.assertTrue(saved["saved"])
        code, checked = run("show", "validate", self.project, "--workspace", self.temp.name)
        self.assertEqual(code, 0)
        self.assertIn("Expert", checked["difficulties"])
        code, compiled = run("show", "compile", self.project, "--workspace", self.temp.name)
        self.assertEqual(compiled["requirements"], ["Vivify"])
        self.assertEqual(len(compiled["provenance"]), len(compiled["customData"]["customEvents"]))
        code, bundle = run("show", "bundle", self.project, "--workspace", self.temp.name)
        self.assertIn("assets/sm/post/glow.mat", bundle["bundle"]["materials"])
        code, envelope = run("show", "envelope")
        self.assertIn("max", envelope)
        code, _ = run("show", "save", self.project, "--workspace", self.temp.name, "--show", str(file),
                      "--revision", "none")
        self.assertEqual(code, 1)


class ParserTests(unittest.TestCase):
    def test_hand_written_custom_events_are_normalized(self):
        beatmap = {"version": "3.3.0", "colorNotes": [{"b": 1, "x": 1, "y": 0, "c": 0, "d": 1,
                                                        "customData": {"track": "t", "noteJumpMovementSpeed": 10}}],
                   "customData": {"customEvents": [
                       {"t": "InstantiatePrefab", "d": {"asset": "assets/a.prefab", "id": "a", "track": "a"}},
                       {"b": 2, "t": "AnimateTrack", "d": {"track": ["a", "b"], "duration": 1}},
                       {"b": 4, "t": "DestroyObject", "d": {"id": "a"}},
                       {"b": 5, "t": "MysteryEvent", "d": {"x": 1}},
                       {"b": None, "t": "Blit", "d": {}}],
                       "environment": [{"id": "Ring", "lookupMethod": "Contains", "active": False}],
                       "materials": {"m": {"shader": "Standard"}}}}
        parsed = parse_map(beatmap, bpm=120)
        custom = parsed["custom"]
        self.assertEqual([e["type"] for e in custom["custom_events"]],
                         ["InstantiatePrefab", "AnimateTrack", "DestroyObject", "MysteryEvent"])
        self.assertEqual(custom["custom_events"][0]["beat"], 0.0)
        self.assertEqual(custom["custom_events"][1]["seconds"], 1.0)
        self.assertEqual(custom["event_counts"], {"vivify": {"InstantiatePrefab": 1, "DestroyObject": 1},
                                                  "heck": {"AnimateTrack": 1}, "unknown": {"MysteryEvent": 1}})
        self.assertEqual(custom["tracks"], ["a", "b"])
        self.assertEqual(custom["assets"], ["assets/a.prefab"])
        self.assertEqual(len(custom["unknown"]), 1)
        self.assertEqual(custom["object_custom_fields"], {"colorNotes": {"track": 1, "noteJumpMovementSpeed": 1}})
        self.assertTrue(any(u["path"] == "customData" for u in parsed["unsupported"]))
        self.assertNotIn("custom", parse_map({"version": "3.3.0", "colorNotes": []}, bpm=120))

    @unittest.skipUnless(EXSII.is_dir() and EXSII_INDEX.is_file(), "EXSII corpus not present (local user data)")
    def test_every_extracted_exsii_difficulty_parses(self):
        index = read_json(EXSII_INDEX)
        checked = 0
        for entry in index["maps"]:
            folder = EXSII / Path(entry["extracted"]).name
            info = read_json(folder / "Info.dat")
            files = {(d["characteristic"], d["difficulty"]): d for d in entry["difficulties"]}
            for group in info["_difficultyBeatmapSets"]:
                for item in group["_difficultyBeatmaps"]:
                    beatmap = read_json(folder / item["_beatmapFilename"])
                    try:
                        custom = parse_map(beatmap, bpm=float(info["_beatsPerMinute"]))["custom"]
                    except ValueError:  # off-grid gameplay objects in one file; the custom events still parse
                        custom = vivify.parse_custom(beatmap["customData"], lambda b: b)
                    total = len(custom["custom_events"]) + len(custom["unknown"])
                    expected = files.get((group["_beatmapCharacteristicName"], item["_difficulty"]))
                    if expected:
                        self.assertEqual(total, expected["customEvents"]["total"], item["_beatmapFilename"])
                    self.assertFalse(custom["event_counts"].get("unknown"), item["_beatmapFilename"])
                    checked += 1
        self.assertGreaterEqual(checked, 10)


if __name__ == "__main__":
    unittest.main()
