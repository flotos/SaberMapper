"""Shared, versioned swing candidates and descriptive difficulty proxies."""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, isfinite, radians, sin

MODEL_VERSION = "1.1"
_VECTORS = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0),
            4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}


def _finite(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value)) and (value > 0 if positive else True)
    except OverflowError:
        return False


def _vector(direction, angle):
    if direction == 8:
        return None
    x, y = _VECTORS[direction]
    theta = radians(angle)
    return x * cos(theta) - y * sin(theta), x * sin(theta) + y * cos(theta)


def _parity(direction, hand, angle):
    if direction == 8 or angle:
        return "ambiguous"
    if direction in (1, 6, 7):
        return "forehand"
    if direction in (0, 4, 5):
        return "backhand"
    return ("forehand" if direction == 3 else "backhand") if hand == 0 else ("forehand" if direction == 2 else "backhand")


def _reaction_proxy(bpm, njs, spawn_offset_beats):
    if njs is None:
        return None
    half = 4.0
    while half > 0.25 and njs * half * 60 / bpm > 18:
        half /= 2
    return max(0.25, half + spawn_offset_beats) * 60 / bpm


def analyze_movement(notes: list, bpm: float = 120, *, njs=None,
                     spawn_offset_beats=0) -> dict:
    """Infer reviewable swing candidates from notes and optional native seconds.

    This is not a biomechanics, playability, or ranked-difficulty model.
    Without a ``seconds`` field on every note, constant BPM is assumed.
    """
    if not _finite(bpm, True) or (njs is not None and not _finite(njs, True)) or not _finite(spawn_offset_beats):
        raise ValueError("invalid BPM, NJS, or spawn offset")
    if not isinstance(notes, list):
        raise ValueError("notes must be an array")
    supplied_seconds = bool(notes) and all(isinstance(n, dict) and "seconds" in n for n in notes)
    clean = []
    for index, note in enumerate(notes):
        if not isinstance(note, dict) or not _finite(note.get("beat")) or note["beat"] < 0:
            raise ValueError(f"notes[{index}].beat invalid")
        for key, high in (("x", 3), ("y", 2), ("color", 1), ("direction", 8)):
            if type(note.get(key)) is not int or not 0 <= note[key] <= high:
                raise ValueError(f"notes[{index}].{key} invalid")
        angle = note.get("angle", 0)
        seconds = note.get("seconds") if supplied_seconds else float(note["beat"]) * 60 / bpm
        if not _finite(angle) or not _finite(seconds):
            raise ValueError(f"notes[{index}] angle or seconds invalid")
        clean.append({"id": str(note.get("id", f"note:{index}")), "beat": float(note["beat"]),
                      "seconds": float(seconds), "x": note["x"], "y": note["y"],
                      "color": note["color"], "direction": note["direction"], "angle": float(angle)})
    beat_sorted = sorted(clean, key=lambda n: (n["beat"], n["seconds"]))
    if any(b["seconds"] < a["seconds"] for a, b in zip(beat_sorted, beat_sorted[1:])):
        raise ValueError("note seconds must increase with beat")
    clean.sort(key=lambda n: (n["seconds"], n["color"], n["id"]))
    swings, warnings, previous = [], [], {0: None, 1: None}
    distances, speed_pairs, recovery, angular_changes = [], [], [], []
    crossover_count = 0
    for note in clean:
        prior = previous[note["color"]]
        beat_gap = note["beat"] - prior["beat"] if prior else None
        gap = note["seconds"] - prior["seconds"] if prior else None
        compatible = (prior and 0 <= beat_gap <= 1 / 16 and 0 <= gap <= 0.06
                      and note["direction"] == prior["direction"] and note["angle"] == prior["angle"])
        if compatible:
            count = len(prior["note_ids"])
            prior["note_ids"].append(note["id"])
            prior["x"] = (prior["x"] * count + note["x"]) / (count + 1)
            prior["y"] = (prior["y"] * count + note["y"]) / (count + 1)
            prior["simultaneous"] = True
            prior["reason"] = "same-hand chord with matching cut direction"
            continue
        if prior and beat_gap == 0 and gap == 0:
            warnings.append({"code": "simultaneous_direction_conflict", "note_ids": [prior["note_ids"][-1], note["id"]],
                             "beat": note["beat"], "confidence": "high",
                             "reason": "same-hand simultaneous notes have incompatible cut directions"})
        parity = _parity(note["direction"], note["color"], note["angle"])
        reset = bool(prior and (beat_gap >= 1 or gap >= 60 / bpm))
        swing = {"id": f"swing:{len(swings)}", "note_ids": [note["id"]],
                 "beat": note["beat"], "seconds": note["seconds"], "hand": note["color"],
                 "x": float(note["x"]), "y": float(note["y"]), "direction": note["direction"],
                 "angle": note["angle"], "parity": parity,
                 "confidence": "low" if parity == "ambiguous" else "medium",
                 "entry_state": "unconstrained" if not prior or reset else prior["exit_state"],
                 "exit_state": parity, "reset": reset, "simultaneous": False,
                 "reason": "dot or angle offset permits multiple paths" if parity == "ambiguous" else
                           "direction and hand suggest posture; review context"}
        crossover_count += (note["color"] == 0 and note["x"] >= 2) or (note["color"] == 1 and note["x"] <= 1)
        if prior:
            distance = hypot(swing["x"] - prior["x"], swing["y"] - prior["y"])
            distances.append(distance)
            if gap > 0:
                recovery.append(gap)
                speed_pairs.append(distance / gap)
            prev_vec, vec = _vector(prior["direction"], prior["angle"]), _vector(note["direction"], note["angle"])
            if prev_vec and vec:
                angle_a, angle_b = degrees(atan2(prev_vec[1], prev_vec[0])), degrees(atan2(vec[1], vec[0]))
                change = abs((angle_b - angle_a + 180) % 360 - 180)
                angular_changes.append(change)
                if gap and gap <= 0.25 and change < 60:
                    warnings.append({"code": "rapid_repeat_cut", "note_ids": [prior["note_ids"][-1], note["id"]],
                                     "beat": note["beat"], "confidence": "medium",
                                     "reason": "rapid same-hand cuts point in broadly similar directions; review swing reset"})
            if gap and distance / gap > 12:
                warnings.append({"code": "reach_proxy", "note_ids": [prior["note_ids"][-1], note["id"]],
                                 "beat": note["beat"], "confidence": "low", "reason": "large grid displacement in short time"})
        swings.append(swing)
        previous[note["color"]] = swing
    span = swings[-1]["seconds"] - swings[0]["seconds"] if len(swings) > 1 else 0
    longest, run = (1, 1) if swings else (0, 0)
    for left, right in zip(swings, swings[1:]):
        run = run + 1 if 0 < right["seconds"] - left["seconds"] <= 0.25 else 1
        longest = max(longest, run)
    peak = max((sum(0 <= other["seconds"] - swing["seconds"] < 1 for other in swings[i:])
                for i, swing in enumerate(swings)), default=0)
    metrics = {"swing_count": len(swings), "swing_rate_per_second": (len(swings) - 1) / span if span else 0,
               "peak_one_second_swing_count": peak, "longest_quarter_second_burst": longest,
               "mean_grid_distance": sum(distances) / len(distances) if distances else 0,
               "mean_angular_change_degrees": sum(angular_changes) / len(angular_changes) if angular_changes else None,
               "minimum_recovery_seconds": min(recovery) if recovery else None,
               "maximum_grid_speed_proxy": max(speed_pairs, default=0),
               "crossover_demand_count": int(crossover_count),
               "reaction_time_proxy_seconds": _reaction_proxy(bpm, njs, spawn_offset_beats)}
    return {"model_version": MODEL_VERSION, "swings": swings, "metrics": metrics, "warnings": warnings,
            "timing_source": "note_seconds" if supplied_seconds else "constant_bpm_assumption",
            "unsupported_motion": ["bombs", "walls", "arcs", "chains", "complex rotations"]}
