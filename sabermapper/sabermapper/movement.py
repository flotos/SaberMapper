"""Shared, versioned swing candidates and descriptive difficulty proxies."""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, isfinite, radians, sin

MODEL_VERSION = "1.5"
# A same-hand swing arriving sooner than this must nearly reverse the previous
# cut; a sideways (90-degree) or repeated cut this fast forces a wrist reset.
FAST_BREAK_SECONDS = 0.3
REVERSAL_DEGREES = 135
# Without a reset (a full beat), consecutive same-hand swings must alternate
# forehand/backhand and turn at least this much.
MIN_TURN_DEGREES = 90
# Three or more same-hand swings each less than this after the previous, while the other hand has
# nothing to cut, stream on one hand: alternating hands or fewer notes carry the same sound.
BURST_SECONDS = 0.2
BURST_SWINGS = 3
# A note arriving in the same cell as the note just before it (either hand) is
# hidden behind that note for most of its approach, and its arrow reads only
# once the front note is cut. The four centre cells of the middle and top rows
# sit on the player's line of sight, where the hidden stretch lasts longest.
HIDDEN_SECONDS = 0.2
SIGHTLINE_HIDDEN_SECONDS = 0.35
# Grid cells per second a hand may travel between consecutive cuts before reach_proxy reports it.
REACH_SPEED = 12
# Same-hand notes this close (in beats and seconds) with one cut direction are cut in one swing.
CHORD_BEATS = 1 / 16
CHORD_SECONDS = 0.06
_VECTORS = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0),
            4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}
_OPPOSITE = {0: 1, 1: 0, 2: 3, 3: 2, 4: 7, 7: 4, 5: 6, 6: 5}


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


def is_reset(beat_gap, gap_seconds, bpm):
    """True when a hand rests long enough (a full beat) to start its next swing unconstrained."""
    return beat_gap >= 1 or gap_seconds >= 60 / bpm


def next_effective(effective, direction, reset):
    """The direction a hand's next swing must flow from: a dot is cut as the reverse of the swing before it."""
    if direction != 8:
        return direction
    return _OPPOSITE[effective] if effective is not None and effective != 8 and not reset else None


def turn_degrees(previous, direction, previous_angle=0.0, angle=0.0):
    """Angle in degrees between two cut directions (0 = same, 180 = reversal)."""
    a, b = _vector(previous, previous_angle), _vector(direction, angle)
    return abs((degrees(atan2(b[1], b[0])) - degrees(atan2(a[1], a[0])) + 180) % 360 - 180)


def flow_break(previous, direction, hand, gap_seconds, reset, previous_angle=0.0, angle=0.0):
    """Return the blocking flow finding for a consecutive same-hand swing pair, or None.

    ``previous`` is the effective direction of the earlier swing (a dot takes the
    reverse of the swing before it). Returns ``(code, reason)``.
    """
    if previous is None or previous == 8 or direction == 8 or reset:
        return None
    change = turn_degrees(previous, direction, previous_angle, angle)
    if gap_seconds < FAST_BREAK_SECONDS and change < REVERSAL_DEGREES:
        return ("fast_direction_break",
                f"same-hand cut {gap_seconds:.3f}s after the previous one turns only {change:.0f} degrees; "
                f"within {FAST_BREAK_SECONDS}s it must reverse by at least {REVERSAL_DEGREES} degrees. "
                "Re-angle one cut, give it to the other hand or remove the weaker note; unpin the cut to let the "
                "placer choose (project check lists edits that clear it)")
    same_parity = (not previous_angle and not angle
                   and _parity(previous, hand, 0) == _parity(direction, hand, 0))
    if change < MIN_TURN_DEGREES or (same_parity and change < REVERSAL_DEGREES):
        return ("flow_parity_break",
                f"same-hand cut {gap_seconds:.3f}s after the previous one turns {change:.0f} degrees"
                f"{' on the same forehand/backhand' if same_parity else ''} without a full-beat reset; "
                f"alternate parity and turn at least {MIN_TURN_DEGREES} degrees "
                "(project check lists edits that clear it)")
    return None


def one_hand_bursts(swings: list) -> list:
    """Review warnings for runs of fast same-hand swings while the other hand idles."""
    found = []
    for hand in (0, 1):
        own = [s for s in swings if s["hand"] == hand]
        other = [s["seconds"] for s in swings if s["hand"] != hand]
        run = own[:1]
        for swing in own[1:] + [None]:
            if swing is not None and swing["seconds"] - run[-1]["seconds"] < BURST_SECONDS:
                run.append(swing)
                continue
            if len(run) >= BURST_SWINGS and not any(run[0]["seconds"] < t < run[-1]["seconds"] for t in other):
                span = run[-1]["seconds"] - run[0]["seconds"]
                found.append({"code": "one_hand_burst", "note_ids": [i for s in run for i in s["note_ids"]],
                              "beat": run[0]["beat"], "confidence": "medium",
                              "reason": f"{'right' if hand else 'left'} hand swings {len(run)} times in {span:.3f}s, "
                                        f"each under {BURST_SECONDS}s after the last, while the other hand has "
                                        "nothing to cut; alternate hands or keep only the notes on the lead's "
                                        "strongest sounds (project check lists edits)"})
            run = [swing] if swing is not None else []
    return sorted(found, key=lambda w: w["beat"])


def hidden_window(x, y):
    """Seconds a later note must trail the note in front of it in cell (x, y)."""
    return SIGHTLINE_HIDDEN_SECONDS if x in (1, 2) and y >= 1 else HIDDEN_SECONDS


def hidden_note(gap_seconds, x, y):
    """Return the blocking finding for a note ``gap_seconds`` behind another in its cell, or None."""
    window = hidden_window(x, y)
    if not 0 < gap_seconds < window:
        return None
    where = "a centre line-of-sight cell" if window == SIGHTLINE_HIDDEN_SECONDS else "the same cell"
    return ("hidden_note",
            f"note at ({x},{y}) arrives {gap_seconds:.3f}s behind the note in front of it in {where}, "
            f"which hides it until that note is cut; same-cell notes need {window}s here. "
            "Move one to a free neighbouring cell, or unpin its cell to let the placer choose (project check "
            "lists the free cells)")


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
    swings, warnings, previous, flow = [], [], {0: None, 1: None}, {0: None, 1: None}
    front = {}  # (x, y) -> latest note in that cell
    distances, speed_pairs, recovery, angular_changes = [], [], [], []
    crossover_count = 0
    for note in clean:
        cell = (note["x"], note["y"])
        ahead = front.get(cell)
        found = ahead and hidden_note(note["seconds"] - ahead["seconds"], *cell)
        if found:
            warnings.append({"code": found[0], "note_ids": [ahead["id"], note["id"]], "beat": note["beat"],
                             "confidence": "high", "severity": "error", "reason": found[1]})
        front[cell] = note
        prior = previous[note["color"]]
        beat_gap = note["beat"] - prior["beat"] if prior else None
        gap = note["seconds"] - prior["seconds"] if prior else None
        compatible = (prior and 0 <= beat_gap <= CHORD_BEATS and 0 <= gap <= CHORD_SECONDS
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
        reset = bool(prior and is_reset(beat_gap, gap, bpm))
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
            if prior["direction"] != 8 and note["direction"] != 8:
                angular_changes.append(turn_degrees(prior["direction"], note["direction"], prior["angle"], note["angle"]))
            effective = flow[note["color"]]
            found = gap and effective and flow_break(effective[0], note["direction"], note["color"], gap, reset,
                                                     effective[1], note["angle"])
            if found:
                warnings.append({"code": found[0], "note_ids": [prior["note_ids"][-1], note["id"]],
                                 "beat": note["beat"], "confidence": "high", "severity": "error", "reason": found[1]})
            if gap and distance / gap > REACH_SPEED:
                warnings.append({"code": "reach_proxy", "note_ids": [prior["note_ids"][-1], note["id"]],
                                 "beat": note["beat"], "confidence": "low", "reason": "large grid displacement in short time"})
        swings.append(swing)
        previous[note["color"]] = swing
        if note["direction"] != 8:
            flow[note["color"]] = (note["direction"], note["angle"])
        else:  # a dot is cut as the reversal of the swing before it
            effective = flow[note["color"]]
            flow[note["color"]] = ((_OPPOSITE[effective[0]], effective[1])
                                   if effective and not reset else None)
    warnings.extend(one_hand_bursts(swings))
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
