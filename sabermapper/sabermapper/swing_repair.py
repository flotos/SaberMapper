"""Deterministic repair of blocking swing-flow findings.

Handles ``fast_direction_break`` and ``flow_parity_break`` from the movement
model. For each offending same-hand pair, a true 16th pickup (under
``PICKUP_SECONDS``, on a weaker metric position than the cut it runs into) is
removed. Otherwise one cut of the pair is re-angled: the note and direction that
leave the fewest breaks nearby win, then the smallest turn from the authored
direction. Arc anchors may be re-angled; the arc head or tail direction is
updated with the note. Chain anchors, notes in locked sections and
motif-expanded notes are never changed; such pairs are reported as unresolved.
"""

from __future__ import annotations

import copy
from fractions import Fraction

from .arrangement import expanded_notes
from .movement import flow_break, turn_degrees, _OPPOSITE
from .validation import _beat, validate_arrangement

BLOCKING_CODES = ("fast_direction_break", "flow_parity_break")
# Only a pickup this close to the next cut is dropped rather than re-angled.
PICKUP_SECONDS = 0.2


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


def _chain_anchors(arrangement):
    keys = set()
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        for chain in section.get("chains", []):
            keys.add((start + _beat(chain["beat"]), chain["x"], chain["y"], chain["color"]))
    return keys


def _arc_anchors(arrangement):
    keys = set()
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        for arc in section.get("arcs", []):
            keys.add((start + _beat(arc["beat"]), arc["x"], arc["y"], arc["color"]))
            keys.add((start + _beat(arc["tail_beat"]), arc["tail_x"], arc["tail_y"], arc["color"]))
    return keys


def _materialize(arrangement, object_ids):
    """Inline the unlocked patterns behind motif-expanded IDs as literal notes.

    Returns the pattern object IDs inlined. The compiled notes are unchanged; only
    those pattern instances stop sharing their motif, so one cut can be re-angled.
    """
    wanted = {tuple(oid.split("/")[:3]) for oid in object_ids if "/pattern/" in oid}
    expanded = {n["id"]: n for n in expanded_notes(arrangement)}
    done = []
    for section in arrangement["sections"]:
        if section["locked"]:
            continue
        start = _beat(section["start_beat"])
        for pattern in list(section["patterns"]):
            if (section["id"], "pattern", pattern["id"]) not in wanted:
                continue
            prefix = f'{section["id"]}/pattern/{pattern["id"]}/'
            taken = {note["id"] for note in section["notes"]}
            for oid, note in expanded.items():
                if not oid.startswith(prefix):
                    continue
                nid = f'{pattern["id"]}-{oid[len(prefix):]}'
                while nid in taken:
                    nid += "x"
                taken.add(nid)
                beat = note["beat"] - start
                section["notes"].append({"id": nid, "beat": str(beat) if beat.denominator != 1 else int(beat),
                                         "x": note["x"], "y": note["y"], "color": note["color"],
                                         "direction": note["direction"]})
            section["patterns"].remove(pattern)
            done.append(prefix.rstrip("/"))
    return done


def _hand_swings(arrangement, hand):
    """Same-hand swings grouped exactly as the movement model groups chords."""
    swings = []
    for note in expanded_notes(arrangement):
        if note["color"] != hand:
            continue
        seconds = _seconds(arrangement, note["beat"])
        prior = swings[-1] if swings else None
        if (prior and note["beat"] - prior["beat"] <= Fraction(1, 16) and seconds - prior["seconds"] <= 0.06
                and note["direction"] == prior["direction"]):
            prior["ids"].append(note["id"])
            continue
        swings.append({"beat": note["beat"], "seconds": seconds, "direction": note["direction"], "ids": [note["id"]]})
    return swings


def _count_breaks(swings, hand, bpm, lo, hi):
    """Count blocking flow breaks whose later swing index lies in [lo, hi]."""
    count, effective = 0, None
    for index, swing in enumerate(swings[:hi + 1]):
        prior = swings[index - 1] if index else None
        gap = swing["seconds"] - prior["seconds"] if prior else 0
        reset = bool(prior and (swing["beat"] - prior["beat"] >= 1 or gap >= 60 / bpm))
        if index >= lo and gap and effective is not None and flow_break(effective, swing["direction"], hand, gap, reset):
            count += 1
        if swing["direction"] != 8:
            effective = swing["direction"]
        else:
            effective = _OPPOSITE[effective] if effective is not None and not reset else None
    return count


def repair_fast_breaks(arrangement: dict, max_steps: int = 5000) -> dict:
    """Return ``{"arrangement", "changes", "unresolved"}`` without mutating the input."""
    result = copy.deepcopy(arrangement)
    bpm = float(result["song"]["bpm"])
    changes, unresolved, skipped = [], [], set()
    for _ in range(max_steps):
        diagnostics = validate_arrangement(result)
        findings = [d for d in diagnostics
                    if d["severity"] == "error" and d["code"] in BLOCKING_CODES
                    and tuple(d["object_ids"]) not in skipped]
        if not findings:
            break
        blocking = [d for d in diagnostics
                    if d["severity"] == "error" and d["code"] not in BLOCKING_CODES + ("unresolved_section", "hidden_note")]
        if blocking:
            raise ValueError("Fix structural errors before repairing swings: "
                             + "; ".join(d["message"] for d in blocking[:5]))
        finding = findings[0]
        pair = tuple(finding["object_ids"])
        if any("/pattern/" in oid for oid in pair):
            inlined = _materialize(result, pair)
            if inlined:
                changes.append({"object_ids": list(pair), "code": finding["code"], "action": "inlined_pattern",
                                "object_id": inlined[0], "patterns": inlined,
                                "reason": "pattern converted to literal notes (same output) so one cut can be re-angled"})
                continue
            unresolved.append({"object_ids": list(pair), "code": finding["code"],
                               "reason": "motif-expanded notes in a locked section; unlock it or edit the motif"})
            skipped.add(pair)
            continue
        literal, chains, arcs = _literal_notes(result), _chain_anchors(result), _arc_anchors(result)
        hand = literal[pair[0]][1]["color"]
        swings = _hand_swings(result, hand)
        index_of = {oid: i for i, swing in enumerate(swings) for oid in swing["ids"]}
        first_index, second_index = index_of[pair[0]], index_of[pair[1]]

        def entries(index):
            return [literal.get(oid) for oid in swings[index]["ids"]]

        def key(entry):
            return (entry[2], entry[1]["x"], entry[1]["y"], entry[1]["color"])

        def can_turn(index):
            group = entries(index)
            return all(e is not None and not e[0]["locked"] and key(e) not in chains for e in group)

        def can_remove(index):
            return can_turn(index) and all(key(e) not in arcs for e in entries(index))

        def evaluate(index, direction):
            """(pair still breaks, breaks from this swing through the next three)."""
            original = swings[index]["direction"]
            swings[index]["direction"] = direction
            try:
                return (_count_breaks(swings, hand, bpm, second_index, second_index) > 0,
                        _count_breaks(swings, hand, bpm, index, index + 3))
            finally:
                swings[index]["direction"] = original

        record = {"object_ids": list(pair), "code": finding["code"],
                  "beat": float(swings[second_index]["beat"]), "color": hand}
        gap = swings[second_index]["seconds"] - swings[first_index]["seconds"]
        if (finding["code"] == "fast_direction_break" and gap < PICKUP_SECONDS
                and _strength(swings[first_index]["beat"]) < _strength(swings[second_index]["beat"])
                and can_remove(first_index)):
            for section, note, _ in entries(first_index):
                section["notes"].remove(note)
            changes.append({**record, "action": "removed", "object_id": pair[0],
                            "reason": "weaker-position pickup cannot reset before the following cut"})
            continue
        options = []
        for preference, index in enumerate((second_index, first_index)):
            if not can_turn(index) or swings[index]["direction"] == 8:
                continue
            for direction in range(8):
                if direction == swings[index]["direction"]:
                    continue
                pair_breaks, nearby = evaluate(index, direction)
                if not pair_breaks:  # the chosen cut must clear the reported pair itself
                    options.append((nearby, turn_degrees(swings[index]["direction"], direction),
                                    preference, direction, index))
        if options:
            _, _, _, direction, index = min(options)
            old = swings[index]["direction"]
            for section, note, beat in entries(index):
                note["direction"] = direction
                start = _beat(section["start_beat"])
                for arc in section.get("arcs", []):
                    if arc["color"] != note["color"]:
                        continue
                    if (start + _beat(arc["beat"]), arc["x"], arc["y"]) == (beat, note["x"], note["y"]):
                        arc["direction"] = direction
                    if (start + _beat(arc["tail_beat"]), arc["tail_x"], arc["tail_y"]) == (beat, note["x"], note["y"]):
                        arc["tail_direction"] = direction
            changes.append({**record, "action": "reangled", "object_id": swings[index]["ids"][0],
                            "object_ids_changed": list(swings[index]["ids"]),
                            "from_direction": old, "to_direction": direction,
                            "reason": "turned so the same-hand swings alternate and reverse in time"})
            continue
        removable = next((i for i in (second_index, first_index) if can_remove(i)), None)
        if removable is not None:
            for section, note, _ in entries(removable):
                section["notes"].remove(note)
            changes.append({**record, "action": "removed", "object_id": swings[removable]["ids"][0],
                            "reason": "no direction resolves the pair; removed the unanchored note"})
            continue
        unresolved.append({"object_ids": list(pair), "code": finding["code"],
                           "reason": "both notes are locked, chain anchors or motif notes"})
        skipped.add(pair)
    else:
        raise ValueError("Swing repair did not converge; inspect the reported findings")
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}
