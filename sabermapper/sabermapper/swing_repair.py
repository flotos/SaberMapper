"""Deterministic repair of blocking ``fast_direction_break`` findings.

For each offending same-hand pair the weaker note is removed when the earlier
note sits on a weaker metric position (typically a 16th pickup into a beat);
otherwise the later note is re-angled to the nearest direction that reverses the
earlier cut and still reverses into the next fast same-hand cut. Notes that
anchor arcs or chains, notes in locked sections and motif-expanded notes are
never changed; such pairs are reported as unresolved for the agent to rework.
"""

from __future__ import annotations

import copy
from fractions import Fraction

from .movement import FAST_BREAK_SECONDS, REVERSAL_DEGREES, _VECTORS
from .validation import _beat, validate_arrangement

_ANGLES = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315}


def _turn(a, b):
    return abs((_ANGLES[b] - _ANGLES[a] + 180) % 360 - 180)


def _strength(beat: Fraction) -> int:
    """Higher is metrically stronger: beat > half > quarter > finer subdivisions."""
    frac = beat - (beat.numerator // beat.denominator)
    return {1: 3, 2: 2, 4: 1}.get(frac.denominator, 0)


def _seconds(arrangement, beat: Fraction) -> float:
    bpm = float(arrangement["song"]["bpm"])
    seconds, previous, tempo = 0.0, Fraction(0), bpm
    for event in arrangement.get("tempo_events", []):
        change = _beat(event["beat"])
        if change > beat:
            break
        seconds += float(change - previous) * 60 / tempo
        previous, tempo = change, float(event["bpm"])
    return seconds + float(beat - previous) * 60 / tempo


def _literal_notes(arrangement):
    """Map ``section/note/id`` to (section, note, absolute beat)."""
    out = {}
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        for note in section["notes"]:
            out[f'{section["id"]}/note/{note["id"]}'] = (section, note, start + _beat(note["beat"]))
    return out


def _anchors(arrangement):
    keys = set()
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        for arc in section.get("arcs", []):
            keys.add((start + _beat(arc["beat"]), arc["x"], arc["y"], arc["color"]))
            keys.add((start + _beat(arc["tail_beat"]), arc["tail_x"], arc["tail_y"], arc["color"]))
        for chain in section.get("chains", []):
            keys.add((start + _beat(chain["beat"]), chain["x"], chain["y"], chain["color"]))
    return keys


def repair_fast_breaks(arrangement: dict, max_steps: int = 500) -> dict:
    """Return ``{"arrangement", "changes", "unresolved"}`` without mutating the input."""
    result = copy.deepcopy(arrangement)
    changes, unresolved, skipped = [], [], set()
    for _ in range(max_steps):
        diagnostics = validate_arrangement(result)
        findings = [d for d in diagnostics
                    if d["code"] == "fast_direction_break" and tuple(d["object_ids"]) not in skipped]
        if not findings:
            break
        blocking = [d for d in diagnostics
                    if d["severity"] == "error" and d["code"] not in ("fast_direction_break", "unresolved_section")]
        if blocking:
            raise ValueError("Fix structural errors before repairing swings: "
                             + "; ".join(d["message"] for d in blocking[:5]))
        finding = findings[0]
        pair = tuple(finding["object_ids"])
        notes, anchors = _literal_notes(result), _anchors(result)
        entries = [notes.get(oid) for oid in pair]

        def movable(entry):
            section, note, beat = entry
            return not section["locked"] and (beat, note["x"], note["y"], note["color"]) not in anchors

        if None in entries:
            unresolved.append({"object_ids": list(pair), "reason": "motif-expanded note; edit the motif or pattern"})
            skipped.add(pair)
            continue
        (first_section, first, first_beat), (second_section, second, second_beat) = entries
        record = {"object_ids": list(pair), "beat": float(second_beat), "color": second["color"]}
        if _strength(first_beat) < _strength(second_beat) and movable(entries[0]):
            first_section["notes"].remove(first)
            changes.append({**record, "action": "removed", "object_id": pair[0],
                            "reason": "weaker-position pickup cannot reset before the following cut"})
            continue
        if movable(entries[1]):
            later = sorted(((beat, note) for _, note, beat in notes.values()
                            if note["color"] == second["color"] and beat > second_beat and note["direction"] != 8),
                           key=lambda item: item[0])
            constraint = None
            if later and _seconds(result, later[0][0]) - _seconds(result, second_beat) < FAST_BREAK_SECONDS:
                constraint = later[0][1]["direction"]
            options = [d for d in _VECTORS
                       if _turn(first["direction"], d) >= REVERSAL_DEGREES
                       and (constraint is None or _turn(d, constraint) >= REVERSAL_DEGREES)]
            if options:
                choice = min(options, key=lambda d: (_turn(second["direction"], d), d))
                changes.append({**record, "action": "reangled", "object_id": pair[1],
                                "from_direction": second["direction"], "to_direction": choice,
                                "reason": "turned to reverse the previous fast cut"})
                second["direction"] = choice
                continue
            second_section["notes"].remove(second)
            changes.append({**record, "action": "removed", "object_id": pair[1],
                            "reason": "no direction reverses both neighbouring fast cuts"})
            continue
        if movable(entries[0]):
            first_section["notes"].remove(first)
            changes.append({**record, "action": "removed", "object_id": pair[0],
                            "reason": "later note is anchored; removed the earlier note"})
            continue
        unresolved.append({"object_ids": list(pair), "reason": "both notes are locked or anchor arcs/chains"})
        skipped.add(pair)
    else:
        raise ValueError("Swing repair did not converge; inspect the reported findings")
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}
