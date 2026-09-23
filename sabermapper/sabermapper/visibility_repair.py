"""Deterministic repair of blocking ``hidden_note`` findings.

A note that arrives in the same cell as the note just in front of it, sooner
than ``movement.hidden_window``, stays hidden until that note is cut. The repair
moves one note of each pair to a nearby free cell. Timing and cut direction never
change, so audio grounding and swing flow are unaffected.

A candidate cell must be empty at that beat and keep the hands uncrossed against
the other hand's simultaneous notes. The moved note must be visible in its new
cell and must not hide the next note there. The hand's travel must stay under the
reach limit. The cheapest cell wins: fewest hidden pairs left nearby, then fewest
cells moved, then staying on the hand's side of the grid and off the centre line
of sight, then nearest where the hand's previous cut left the saber. The later note
of a pair is preferred. When neither note can move, the note on the weaker metric
position is removed, unless it anchors an arc or chain. Arc heads and tails move
with their note. Pattern instances are inlined first, which leaves the compiled
output the same. Locked sections, chain anchors and same-hand chord notes never move.
"""

from __future__ import annotations

import copy
from math import hypot

from .arrangement import expanded_notes
from .movement import _VECTORS, hidden_note, hidden_window
from .swing_repair import (BLOCKING_CODES as FLOW_CODES, _arc_anchors, _chain_anchors, _literal_notes,
                           _materialize, _seconds, _strength)
from .validation import _beat, validate_arrangement

CODE = "hidden_note"
REACH_SPEED = 12  # grid cells per second; above this the movement model reports reach_proxy
MAX_MOVE = 2  # Manhattan cells a note may travel
SIDES = {0: (0, 1), 1: (2, 3)}
TOLERATED = (CODE, "unresolved_section") + FLOW_CODES


def _timeline(arrangement):
    notes = expanded_notes(arrangement)
    for note in notes:
        note["seconds"] = _seconds(arrangement, note["beat"])
    return sorted(notes, key=lambda n: (n["seconds"], n["color"], n["id"]))


def hidden_pairs(notes):
    """(front ID, hidden ID) pairs under the movement model's ``hidden_note`` rule."""
    front, pairs = {}, []
    for note in sorted(notes, key=lambda n: (n["seconds"], n["color"], n["id"])):
        cell = (note["x"], note["y"])
        ahead = front.get(cell)
        if ahead and hidden_note(note["seconds"] - ahead["seconds"], *cell):
            pairs.append((ahead["id"], note["id"]))
        front[cell] = note
    return pairs


def _blocking(arrangement):
    return {(d["code"], tuple(d["object_ids"])) for d in validate_arrangement(arrangement)
            if d["severity"] == "error" and d["code"] != CODE or d["code"] == "reach_proxy"}


def _speed(a, b):
    gap = abs(a["seconds"] - b["seconds"])
    return hypot(a["x"] - b["x"], a["y"] - b["y"]) / gap if gap else 0


def _cells(timeline, note):
    """Candidate (cost, exit distance, x, y) cells for ``note``, cheapest first."""
    others = [n for n in timeline if n["id"] != note["id"]]
    together = [n for n in others if n["beat"] == note["beat"]]
    rivals = [n["x"] for n in together if n["color"] != note["color"]]
    crossed = any((note["x"] > o) if note["color"] == 0 else (note["x"] < o) for o in rivals)
    hand = [n for n in others if n["color"] == note["color"]]
    before = [n for n in hand if n["seconds"] < note["seconds"]]
    after = [n for n in hand if n["seconds"] > note["seconds"]]
    neighbours = [n for n in (before[-1] if before else None, after[0] if after else None) if n]
    exit_point = None
    if before and before[-1]["direction"] != 8:
        vx, vy = _VECTORS[before[-1]["direction"]]
        exit_point = (before[-1]["x"] + vx, before[-1]["y"] + vy)
    cells = []
    for x in range(4):
        for y in range(3):
            moved = abs(x - note["x"]) + abs(y - note["y"])
            if not 0 < moved <= MAX_MOVE or any((n["x"], n["y"]) == (x, y) for n in together):
                continue
            if not crossed and any((x > o) if note["color"] == 0 else (x < o) for o in rivals):
                continue
            trial = {**note, "x": x, "y": y}
            window = hidden_window(x, y)
            same = [n for n in others if (n["x"], n["y"]) == (x, y)]
            ahead = [n for n in same if n["seconds"] < note["seconds"]]
            behind = [n for n in same if n["seconds"] > note["seconds"]]
            if ahead and note["seconds"] - ahead[-1]["seconds"] < window:
                continue
            if behind and behind[0]["seconds"] - note["seconds"] < window:
                continue
            if any(_speed(trial, n) > max(REACH_SPEED, _speed(note, n)) for n in neighbours):
                continue
            cost = moved + (x not in SIDES[note["color"]] and note["x"] in SIDES[note["color"]])
            cost += 0.5 * (hidden_window(x, y) > hidden_window(note["x"], note["y"]) or x in (1, 2) and y >= 1)
            cells.append((cost, hypot(x - exit_point[0], y - exit_point[1]) if exit_point else 0, x, y))
    return sorted(cells)


def _move(arrangement, oid, x, y, beat):
    """Move literal note ``oid`` to (x, y); arcs anchored on it follow. Returns moved arc IDs."""
    section, note, _ = _literal_notes(arrangement)[oid]
    start = _beat(section["start_beat"])
    old = (note["x"], note["y"])
    arcs = []
    for arc in section.get("arcs", []):
        if arc["color"] != note["color"]:
            continue
        if (start + _beat(arc["beat"]), arc["x"], arc["y"]) == (beat, *old):
            arc["x"], arc["y"] = x, y
            arcs.append(f'{section["id"]}/arcs/{arc["id"]}')
        if (start + _beat(arc["tail_beat"]), arc["tail_x"], arc["tail_y"]) == (beat, *old):
            arc["tail_x"], arc["tail_y"] = x, y
            arcs.append(f'{section["id"]}/arcs/{arc["id"]}')
    note["x"], note["y"] = x, y
    return arcs


def repair_hidden_notes(arrangement: dict, max_steps: int = 5000) -> dict:
    """Return ``{"arrangement", "changes", "unresolved"}`` without mutating the input."""
    result = copy.deepcopy(arrangement)
    changes, unresolved, skipped = [], [], set()
    for _ in range(max_steps):
        diagnostics = validate_arrangement(result)
        blocking = [d for d in diagnostics if d["severity"] == "error" and d["code"] not in TOLERATED]
        if blocking:
            raise ValueError("Fix structural errors before repairing hidden notes: "
                             + "; ".join(d["message"] for d in blocking[:5]))
        findings = [d for d in diagnostics if d["severity"] == "error" and d["code"] == CODE
                    and tuple(d["object_ids"]) not in skipped]
        if not findings:
            break
        pair = tuple(findings[0]["object_ids"])
        if any("/pattern/" in oid for oid in pair):
            inlined = _materialize(result, pair)
            if inlined:
                changes.append({"object_ids": list(pair), "code": CODE, "action": "inlined_pattern",
                                "object_id": inlined[0], "patterns": inlined,
                                "reason": "pattern converted to literal notes (same output) so one note can move"})
                continue
        timeline = _timeline(result)
        by_id = {n["id"]: n for n in timeline}
        literal, chains, arcs = _literal_notes(result), _chain_anchors(result), _arc_anchors(result)

        def key(oid):
            n = by_id[oid]
            return (n["beat"], n["x"], n["y"], n["color"])

        def movable(oid):
            entry, n = literal.get(oid), by_id[oid]
            chord = any(m["id"] != oid and m["color"] == n["color"] and abs(m["seconds"] - n["seconds"]) <= 0.06
                        for m in timeline)
            return entry is not None and not entry[0]["locked"] and key(oid) not in chains and not chord

        record = {"object_ids": list(pair), "code": CODE, "beat": float(by_id[pair[1]]["beat"])}
        baseline, remaining = _blocking(result), len(hidden_pairs(timeline))
        options = []
        for preference, oid in enumerate((pair[1], pair[0])):
            if not movable(oid):
                continue
            note = by_id[oid]
            for cost, exit_distance, x, y in _cells(timeline, note):
                trial = [{**n, "x": x, "y": y} if n["id"] == oid else n for n in timeline]
                options.append((len(hidden_pairs(trial)) - remaining, cost + 0.5 * preference, exit_distance,
                                preference, x, y, oid))
        moved = False
        for *_, x, y, oid in sorted(options):
            note = by_id[oid]
            trial = copy.deepcopy(result)
            arc_ids = _move(trial, oid, x, y, note["beat"])
            if _blocking(trial) - baseline:
                continue  # the move would add a flow, structural or reach finding
            result = trial
            changes.append({**record, "action": "moved", "object_id": oid, "arc_ids": arc_ids,
                            "from": [note["x"], note["y"]], "to": [x, y],
                            "reason": "moved to a free cell so neither note hides the other"})
            moved = True
            break
        if moved:
            continue
        removable = sorted((_strength(by_id[oid]["beat"]), -preference, oid)
                           for preference, oid in enumerate((pair[1], pair[0]))
                           if movable(oid) and key(oid) not in arcs)
        for *_, oid in removable:
            trial = copy.deepcopy(result)
            section, note, _ = _literal_notes(trial)[oid]
            section["notes"].remove(note)
            if _blocking(trial) - baseline:
                continue
            result = trial
            changes.append({**record, "action": "removed", "object_id": oid,
                            "reason": "no free cell nearby; removed the note on the weaker metric position"})
            moved = True
            break
        if not moved:
            unresolved.append({"object_ids": list(pair), "code": CODE,
                               "reason": "no free visible cell and neither note can be removed "
                                         "(locked, chain or arc anchor, chord, or removal breaks flow)"})
            skipped.add(pair)
    else:
        raise ValueError("Hidden-note repair did not converge; inspect the reported findings")
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}
