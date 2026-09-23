"""Deterministic repair of blocking swing-flow findings.

Handles ``fast_direction_break`` and ``flow_parity_break`` from the movement
model. For each offending same-hand pair, a true 16th pickup (under
``PICKUP_SECONDS``, on a weaker metric position than the cut it runs into) is
removed. Otherwise one cut of the pair is re-angled: the note and direction that
leave the fewest breaks nearby win, then the smallest turn from the authored
direction. Arc anchors may be re-angled; the arc head or tail direction is
updated with the note. Chain anchors, notes in locked sections and
motif-expanded notes are never changed; such pairs are reported as unresolved.

First, ``arc_note_conflict`` and ``chain_note_conflict`` (a note of the held
saber's color inside an arc or chain) are resolved by :func:`repair_held_conflicts`.
"""

from __future__ import annotations

import copy
from fractions import Fraction

from .arrangement import expanded_notes
from .movement import flow_break, turn_degrees, _OPPOSITE
from .validation import _beat, validate_arrangement

BLOCKING_CODES = ("fast_direction_break", "flow_parity_break")
HELD_CODES = ("arc_note_conflict", "chain_note_conflict")
# Only a pickup this close to the next cut is dropped rather than re-angled.
PICKUP_SECONDS = 0.2
# An arc ended early on a conflicting note must still hold at least this long; otherwise it is dropped.
MIN_ARC_BEATS = Fraction(1)


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


def _relative(beat: Fraction):
    return int(beat) if beat.denominator == 1 else str(beat)


def _hold_conflicts(arrangement):
    """{arc or chain object ID: IDs of same-color notes inside it} for blocking held-saber conflicts."""
    holds = {}
    for d in validate_arrangement(arrangement):
        if d["severity"] == "error" and d["code"] in HELD_CODES:
            holds.setdefault(d["object_ids"][0], []).append(d["object_ids"][1])
    return holds


def _blocking(arrangement):
    return {(d["code"], tuple(d["object_ids"])) for d in validate_arrangement(arrangement)
            if d["severity"] == "error" or d["code"] == "reach_proxy"}


def _resolve_hold(trial, sid, kind, item, move, shorten):
    """Reattach ``item`` to ``trial`` and clear its saber; return the change records, or None."""
    from .audio_repair import insert_note
    section = next(s for s in trial["sections"] if s["id"] == sid)
    start = _beat(section["start_beat"])
    head, tail = start + _beat(item["beat"]), start + _beat(item["tail_beat"])
    section[kind].append(item)
    oid = f'{sid}/{kind}/{item["id"]}'
    code = f"{kind[:-1]}_note_conflict"

    def inside():
        return [n for n in expanded_notes(trial) if n["color"] == item["color"] and head < n["beat"] < tail]

    steps = []
    if move:
        for note in inside():
            entry = _literal_notes(trial).get(note["id"])
            if entry is None or entry[0]["locked"]:
                continue
            owner, literal, beat = entry
            owner["notes"].remove(literal)
            moved = insert_note(trial, beat, literal["id"])
            if moved is None:
                owner["notes"].append(literal)
                owner["notes"].sort(key=lambda n: _beat(n["beat"]))
                continue
            steps.append({"object_ids": [oid, note["id"]], "code": code, "beat": float(beat),
                          "action": "moved_to_other_hand", "object_id": moved["object_ids"][0],
                          "color": moved["color"], "x": moved["x"], "y": moved["y"], "direction": moved["direction"],
                          "reason": "the held saber cannot cut it; the other hand is free there"})
    remaining = inside()
    if not remaining:
        return steps
    ids = [oid] + [n["id"] for n in remaining]
    if kind == "arcs":
        first = remaining[0]
        if shorten and first["beat"] - head >= MIN_ARC_BEATS:
            item.update(tail_beat=_relative(first["beat"] - start), tail_x=first["x"], tail_y=first["y"],
                        tail_direction=first["direction"])
            steps.append({"object_ids": ids, "code": code, "beat": float(first["beat"]), "action": "shortened_arc",
                          "object_id": oid, "from_tail_beat": float(tail), "to_tail_beat": float(first["beat"]),
                          "reason": "the arc now ends on the first same-color cut instead of holding through it"})
        else:
            section["arcs"].remove(item)
            steps.append({"object_ids": ids, "code": code, "beat": float(head), "action": "removed_arc",
                          "object_id": oid, "reason": "no hold is left before the same-color cut; its notes stay"})
        return steps
    literal = _literal_notes(trial)
    for note in remaining:
        entry = literal.get(note["id"])
        if entry is None or entry[0]["locked"]:
            return None
        entry[0]["notes"].remove(entry[1])
        steps.append({"object_ids": [oid, note["id"]], "code": code, "beat": float(note["beat"]),
                      "action": "removed", "object_id": note["id"],
                      "reason": "the chain holds this saber; the note cannot be cut inside it"})
    return steps


def repair_held_conflicts(arrangement: dict) -> dict:
    """Resolve ``arc_note_conflict``/``chain_note_conflict`` without mutating the input.

    An arc or chain occupies its saber from head to tail, so a note of that color inside
    it is impossible to play. Per hold, the first strategy that adds no blocking
    diagnostic or ``reach_proxy`` warning wins:

    1. move each inner note to the other hand when that hand is free (a flow-safe cut
       and reachable cell, at least half a beat from its own swings), then end an arc on
       the first note still inside it if MIN_ARC_BEATS of hold remain, else drop the arc;
    2. the same without moving notes;
    3. drop the arc (its head and tail notes stay).

    A chain's remaining inner notes are removed instead. Motif notes are inlined first;
    locked sections are never changed (their conflicts are warnings, not errors).
    Returns ``{"arrangement", "changes", "unresolved"}``.
    """
    result = copy.deepcopy(arrangement)
    changes, unresolved = [], []
    holds = _hold_conflicts(result)
    patterned = [nid for ids in holds.values() for nid in ids if "/pattern/" in nid]
    if patterned:
        inlined = _materialize(result, patterned)
        if inlined:
            changes.append({"object_ids": patterned, "code": "arc_note_conflict", "action": "inlined_pattern",
                            "object_id": inlined[0], "patterns": inlined,
                            "reason": "pattern converted to literal notes (same output) so one note can move"})
            holds = _hold_conflicts(result)
    # Detach every conflicting hold: while one remains, validation skips the movement
    # model and could not judge a fix for flow breaks.
    detached = []
    for oid in holds:
        sid, kind, hid = oid.split("/")
        section = next(s for s in result["sections"] if s["id"] == sid)
        item = next(i for i in section[kind] if i["id"] == hid)
        section[kind].remove(item)
        detached.append((oid, sid, kind, item))
    baseline = _blocking(result)
    pending = []
    for oid, sid, kind, item in detached:
        for move, shorten in ((True, True), (False, True), (False, False)):
            if kind == "chains" and not shorten:
                continue
            trial = copy.deepcopy(result)
            steps = _resolve_hold(trial, sid, kind, copy.deepcopy(item), move, shorten)
            if steps is not None and not _blocking(trial) - baseline:
                result = trial
                changes += steps
                break
        else:
            unresolved.append({"object_ids": [oid, *holds[oid]], "code": f"{kind[:-1]}_note_conflict",
                               "reason": "no inner note could move or be removed without a new blocking finding; "
                                         "motif notes in a locked section or chain anchors need a manual edit"})
            pending.append((sid, kind, item))
    for sid, kind, item in pending:
        next(s for s in result["sections"] if s["id"] == sid)[kind].append(item)
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}


def repair_fast_breaks(arrangement: dict, max_steps: int = 5000) -> dict:
    """Return ``{"arrangement", "changes", "unresolved"}`` without mutating the input.

    Held-saber conflicts are resolved first (:func:`repair_held_conflicts`); until they
    are, validation does not run the movement model that reports swing breaks.
    """
    held = repair_held_conflicts(arrangement)
    result = held["arrangement"]
    bpm = float(result["song"]["bpm"])
    changes, unresolved, skipped = list(held["changes"]), list(held["unresolved"]), set()
    for _ in range(max_steps):
        diagnostics = validate_arrangement(result)
        findings = [d for d in diagnostics
                    if d["severity"] == "error" and d["code"] in BLOCKING_CODES
                    and tuple(d["object_ids"]) not in skipped]
        if not findings:
            break
        blocking = [d for d in diagnostics
                    if d["severity"] == "error" and d["code"] not in BLOCKING_CODES + ("unresolved_section",)]
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
