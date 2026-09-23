"""Small hand-written Vivify fixtures (no EXSII content): arrangement 0.2, evidence, bundle, show."""
import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures") / "vivify"


def note(nid, beat, x, y, color, direction=1):
    return {"id": nid, "beat": beat, "x": x, "y": y, "color": color, "direction": direction}


def arrangement(version="0.2", choreographed=False):
    """Three 8-beat sections at 120 BPM (4 s each); presentation only in 0.2 (bridge optionally choreographed)."""
    sections = [
        {"id": "intro", "start_beat": 0, "length_beats": 8, "intent": "setup", "locked": False, "resolved": True,
         "notes": [note("a", 0, 1, 0, 0), note("b", 2, 2, 0, 1), note("c", 4, 1, 0, 0), note("d", 6, 2, 0, 1)],
         "patterns": []},
        {"id": "drop", "start_beat": 8, "length_beats": 8, "intent": "drop", "locked": False, "resolved": True,
         "notes": [note("a", 0, 1, 0, 0), note("b", 1, 2, 0, 1), note("c", 2, 1, 0, 0), note("d", 3, 2, 0, 1),
                   note("e", 4, 1, 0, 0), note("f", 5, 2, 0, 1)], "patterns": [],
         "bombs": [{"id": "x", "beat": 6, "x": 0, "y": 2}]},
        {"id": "bridge", "start_beat": 16, "length_beats": 8, "intent": "calm", "locked": False, "resolved": True,
         "notes": [note("a", 0, 1, 0, 0), note("b", 4, 2, 0, 1)], "patterns": []},
    ]
    result = {"schema_version": version,
              "song": {"title": "Fixture", "artist": "SaberMapper", "bpm": 120, "audio_offset_seconds": 0},
              "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0},
              "motifs": {}, "sections": sections}
    if version == "0.2":
        result["presentation"] = {"concept": "glass corridor opening with the pad", "palette": ["#1a2b3c", [1, 0.5, 0]],
                                  "possession": "head"}
        sections[0]["presentation"] = {"family": "post_process", "attention": {"notes": 0.6, "scene": 0.4},
                                       "reveal": False, "note_style": "plain", "concept": "grey glass"}
        sections[1]["presentation"] = {"family": "scene", "attention": {"notes": 0.7, "scene": 0.3},
                                       "note_style": "plain"}
        sections[2]["presentation"] = {"family": "none", "note_style": "choreographed" if choreographed else "plain"}
    return alternate_swings(result)


def alternate_swings(arrangement: dict) -> dict:
    """Each hand alternates down and up cuts in beat order, so the chart passes the swing-flow checks."""
    notes = sorted(((section["start_beat"] + n["beat"], n) for section in arrangement["sections"]
                    for n in section["notes"]), key=lambda item: item[0])
    swings = {0: 0, 1: 0}
    for _, item in notes:
        item["direction"] = (1, 0)[swings[item["color"]] % 2]
        swings[item["color"]] += 1
    return arrangement


def report():
    """A fake musical evidence run: drum onsets on beats 0, 2, 4, ... and one rising vocal sustain."""
    drums = [{"id": f"drums:spectral_flux:{i}", "seconds": i * 1.0, "method": "spectral_flux",
              "strength": 0.9 if i % 2 == 0 else 0.5} for i in range(12)]
    return {"source": {"sha256": "fake"}, "created_at": "2026-09-23T00:00:00+00:00", "backend": "fake",
            "preset": "balanced",
            "layers": {"drums": {"kind": "audio_layer", "events": drums, "sustains": []},
                       "vocals": {"kind": "audio_layer", "events": [],
                                  "sustains": [{"id": "vocals:sustain:5", "start_seconds": 9.0, "end_seconds": 10.5,
                                                "strength": 0.8, "pitch_shape": "rise"}]}}}


def bundleinfo():
    """Shaped like VivifyTemplate's bundleinfo.json (BundleInfoProcessor.cs)."""
    return {"materials": {"glow": {"path": "assets/sm/post/glow.mat", "properties": {
                "_Amount": {"value": 0.0, "type": {"Float": None}},
                "_Tint": {"value": [1, 1, 1, 1], "type": {"Color": None}}}},
            "ring": {"path": "assets/sm/scene/ring.mat", "properties": {
                "_Glow": {"value": 0.5, "type": {"Float": None}}}}},
            "prefabs": {"ring": "assets/sm/scene/ring.prefab", "glassnote": "assets/sm/skins/glassnote.prefab"},
            "bundleFiles": ["C:/build/bundleWindows2021.vivify"],
            "bundleCRCs": {"_windows2021": 1234567890, "_windows2019": 42}, "isCompressed": False}


def write_bundle(directory: Path, info=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundleinfo.json").write_text(json.dumps(info or bundleinfo()), encoding="utf-8")
    (directory / "bundleWindows2021.vivify").write_bytes(b"UnityFS\x00fake bundle")
    return directory


def show():
    """One of every primitive; valid against arrangement(choreographed=True) with the fixture bundle."""
    return {"schema_version": "0.1", "description": "fixture show", "primitives": [
        {"kind": "setup", "id": "setup", "screen_textures": [{"id": "_Half", "xRatio": 2, "yRatio": 2}],
         "cameras": [{"id": "depthcam", "texture": "_Depth", "properties": {"clearFlags": "Depth"}}],
         "camera_properties": {"depthTextureMode": ["Depth"]}, "rendering": {"renderSettings": {"fog": 0}}},
        {"kind": "look", "id": "grey", "section": "intro", "material": "assets/sm/post/glow.mat", "priority": 1,
         "properties": [{"id": "_Amount", "value": 0.2}],
         "keyframes": [{"beat": 4, "property": "_Amount", "value": 0.6, "duration_beats": 2, "easing": "easeOutQuad"}]},
        {"kind": "scene", "id": "ring", "section": "drop", "prefab": "assets/sm/scene/ring.prefab",
         "position": [0, 2, 20], "animate": [{"beat": 8, "duration_beats": 4, "scale": [[1, 1, 1, 0], [2, 2, 2, 1]]}],
         "keyframes": [{"beat": 12, "material": "assets/sm/scene/ring.mat", "property": "_Glow", "value": 1}]},
        {"kind": "skin", "id": "glass", "section": "drop", "colorNotes": {"asset": "assets/sm/skins/glassnote.prefab"}},
        {"kind": "pulse", "id": "kick", "section": "drop", "material": "assets/sm/scene/ring.mat", "property": "_Glow",
         "driver": {"source": "onsets", "layer": "drums", "detector": "spectral_flux", "min_strength": 0.8},
         "envelope": {"peak": 1, "base": 0.5, "decay_beats": "1/2"}},
        {"kind": "possess", "id": "head", "target": "Head", "track": "sm_head", "beat": 0,
         "animate": [{"beat": 16, "duration_beats": 8, "position": [[0, 0, 0, 0], [0, 0.5, 0, 1]]}]},
        {"kind": "env", "id": "fog", "environment": [{"id": "Environment", "lookupMethod": "Contains",
                                                      "track": "sm_env"}],
         "animate": [{"beat": 16, "track": "sm_env", "component": "BloomFogEnvironment",
                      "fields": {"attenuation": [[0.1, 0], [0.01, 1]]}, "duration_beats": 4}]},
        {"kind": "path", "id": "float", "section": "bridge", "njs": 10, "offset": 1,
         "keyframes": [{"beat": 16, "offsetPosition": [[0, 0, 10, 0], [0, 0, 0, 0.5, "easeOutSine"]]}]},
        {"kind": "raw", "id": "anim", "section": "bridge",
         "event": {"b": 20, "t": "AnimateTrack", "d": {"track": "sm_env", "duration": 1, "dissolve": [[1, 0], [0, 1]]}}},
    ]}


def clone(value):
    return copy.deepcopy(value)
