"""Deterministic arrangement v0 compiler for supported v3 gameplay objects.

Beats in sections and motifs are relative to their containing section/pattern.
Unsupported fields are rejected by validation rather than silently discarded.
"""

from __future__ import annotations

from fractions import Fraction

from .validation import validate_arrangement

_MIRROR_DIRECTION = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}


def beat_fraction(value: int | float | str) -> Fraction:
    """Parse a nonnegative beat, preserving rational subdivisions until export."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("beat must be a number or rational string")
    try:
        beat = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid beat") from exc
    if beat < 0:
        raise ValueError("beat must be nonnegative")
    return beat


def expanded_notes(arrangement: dict) -> list[dict]:
    """Expand literal and referenced notes with stable internal lineage IDs."""
    notes = []
    for section in arrangement["sections"]:
        base = beat_fraction(section["start_beat"])
        for note in section["notes"]:
            notes.append({"id": f'{section["id"]}/note/{note["id"]}',
                          "section_id": section["id"], "beat": base + beat_fraction(note["beat"]),
                          "x": note["x"], "y": note["y"], "color": note["color"],
                          "direction": note["direction"]})
        for pattern in section["patterns"]:
            motif = arrangement["motifs"][pattern["motif"]]
            pattern_start = base + beat_fraction(pattern["start_beat"])
            for note in motif:
                mirror = pattern.get("mirror", False)
                notes.append({"id": f'{section["id"]}/pattern/{pattern["id"]}/{note["id"]}',
                              "section_id": section["id"], "beat": pattern_start + beat_fraction(note["beat"]),
                              "x": 3 - note["x"] if mirror else note["x"], "y": note["y"],
                              "color": 1 - note["color"] if mirror else note["color"],
                              "direction": _MIRROR_DIRECTION[note["direction"]] if mirror else note["direction"]})
    return sorted(notes, key=lambda n: (n["beat"], n["color"], n["x"], n["y"], n["id"]))


def compile_arrangement(arrangement: dict) -> dict:
    """Compile a checked arrangement into a deterministic Beat Saber v3.3 map."""
    errors = [d for d in validate_arrangement(arrangement) if d["severity"] == "error"]
    if errors:
        raise ValueError("Arrangement validation failed: " + "; ".join(
            f'{d["code"]}: {d["message"]}' for d in errors))
    color_notes = [{"b": float(n["beat"]), "x": n["x"], "y": n["y"],
                    "c": n["color"], "d": n["direction"], "a": 0}
                   for n in expanded_notes(arrangement)]
    def section_objects(field, make):
        result = []
        for section in arrangement["sections"]:
            start = beat_fraction(section["start_beat"])
            for item in section.get(field, []):
                result.append(make(item, float(start + beat_fraction(item["beat"]))))
        return sorted(result, key=lambda item: (item["b"], item.get("x", 0), item.get("y", 0)))

    bombs = section_objects("bombs", lambda item, beat: {"b": beat, "x": item["x"], "y": item["y"]})
    obstacles = section_objects("obstacles", lambda item, beat: {
        "b": beat, "d": float(beat_fraction(item["duration_beats"])), "x": item["x"],
        "y": item["y"], "w": item["width"], "h": item["height"]})
    arcs = section_objects("arcs", lambda item, beat: {
        "c": item["color"], "b": beat, "x": item["x"], "y": item["y"],
        "d": item["direction"], "mu": item.get("head_multiplier", 1),
        "tb": beat + float(beat_fraction(item["tail_beat"]) - beat_fraction(item["beat"])),
        "tx": item["tail_x"], "ty": item["tail_y"], "tc": item["tail_direction"],
        "tmu": item.get("tail_multiplier", 1), "m": item.get("mid_anchor", 0)})
    chains = section_objects("chains", lambda item, beat: {
        "c": item["color"], "b": beat, "x": item["x"], "y": item["y"],
        "d": item["direction"],
        "tb": beat + float(beat_fraction(item["tail_beat"]) - beat_fraction(item["beat"])),
        "tx": item["tail_x"], "ty": item["tail_y"], "sc": item["slice_count"],
        "s": item.get("squish", 0.5)})
    tempo = [{"b": float(beat_fraction(item["beat"])), "m": item["bpm"]}
             for item in arrangement.get("tempo_events", [])]
    return {"version": "3.3.0", "bpmEvents": tempo, "rotationEvents": [],
            "colorNotes": color_notes, "bombNotes": bombs, "obstacles": obstacles,
            "sliders": arcs, "burstSliders": chains, "waypoints": [],
            "basicBeatmapEvents": [], "colorBoostBeatmapEvents": [],
            "lightColorEventBoxGroups": [], "lightRotationEventBoxGroups": [],
            "lightTranslationEventBoxGroups": [], "vfxEventBoxGroups": []}
