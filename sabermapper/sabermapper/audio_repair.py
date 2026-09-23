"""Deterministic repair of audio-grounding and salience findings.

Two passes, both judged against one musical evidence run:

1. **Ground notes on sounds.** Every note time with no supporting onset (the
   ``note_support`` rule of :mod:`audio_grounding`) moves to the nearest
   supporting onset within ``SNAP_BEATS``, snapped to the coarsest grid that
   stays on the sound, without crossing a neighbouring note time. A note time
   with no onset in reach is removed. Arc anchors move with their arc when the
   arc stays valid and are never removed.
2. **Map unmapped sounds.** Critique findings that name audible, unmapped
   onsets get a note on those onsets: ``vocal_line_unmapped`` (vocal onsets of
   the flagged bars), ``drum_rhythm_unmapped`` (strongest drum hit per
   half-beat), ``boundary_accent_unmapped`` (the accent) and
   ``density_collapse`` (strong stem onsets inside the sparse window). A new
   note takes the hand and cut direction that add no flow break with either
   neighbouring swing of that hand, in a cell where it neither hides behind
   nor hides another note (``hidden_note``); otherwise the onset is reported
   unresolved.
   ``lead_rhythm_unmapped`` adds notes on the declared lead's strongest attack
   per half-beat, and ``melody_unmapped`` on the strongest melody change per
   half-beat of a melodic bar.
3. **Follow the lead.** Each bar flagged ``lead_rhythm_diluted`` (notes filling
   the space between the lead's attacks) or ``lead_rhythm_unmapped`` (an even
   stream leaving no room for the lead's attacks) is rebuilt: its free notes are cleared,
   then flow-safe notes go on the lead's strongest attack per half-beat (and
   on sixteenth attacks of strength 0.6 or more), and
   another stem's strongest attack fills each beat where the lead is silent. A
   rebuilt bar that adds a blocking diagnostic, a ``reach_proxy`` warning,
   keeps fewer than min(4, old count) notes, or puts no more notes on the lead's
   attacks than before (for ``lead_rhythm_unmapped``) is restored.
4. **Settle density.** The quiet-passage thinning runs once more, so notes the
   lead rebuild or the fills added never leave a ``density_exceeds_audio``
   window behind.

Between the two, ``density_exceeds_audio`` windows (thin, quiet audio mapped as
densely as the full band) are thinned: note times with the weakest audio under
them and the least room around them go first, off-beat before on-beat, until the window fits the density its
audio support allows. Notes on vocal, drum or melody onsets that the salience checks
count are exempt from that density and kept, as are arc anchors and doubles.

Locked sections, chain anchors and motif-expanded notes are never changed.
Every change is re-validated; one that introduces a blocking diagnostic or a
``reach_proxy`` warning is reverted. The input arrangement is not mutated.
"""

from __future__ import annotations

import copy
from bisect import bisect_left
from fractions import Fraction

from .arrangement import expanded_notes
from .audio_grounding import SUPPORT_BEATS, SUPPORT_STRENGTH, ONSET_METHODS, ONSET_STRENGTH, _stem_onsets
from .critique import (ACCENT_STRENGTH, DRUM_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT, LEAD_ONSET_STRENGTH,
                       LEAD_SUPPORT_STRENGTH, MELODY_LAYER, MELODY_MATCH_BEATS, MELODY_ONSET_STRENGTH, QUIET_WINDOW_SECONDS,
                       SALIENCE_BAR_BEATS, SALIENCE_MATCH_BEATS, VOCAL_ONSET_STRENGTH, _sections, beat_to_seconds,
                       critique_arrangement, focus_lead, lead_onsets, on_onset, quiet_bar, quiet_windows,
                       salient_onsets, strongest_per_slot)
from .movement import hidden_window, turn_degrees, _OPPOSITE
from .swing_repair import _count_breaks, _hand_swings
from .validation import _beat, validate_arrangement

SNAP_BEATS = 0.5
SNAP_TOLERANCE = 0.07
GRIDS = (1, 2, 4, 3, 8, 6, 16, 12)
# A new note keeps at least this distance from every other note time; a moved
# one keeps this much (or its original distance, if smaller) from its neighbours.
MIN_GAP_BEATS = Fraction(1, 4)
# A new note keeps at least this distance from the same hand's neighbouring swings.
HAND_GAP_BEATS = Fraction(1, 2)
REACH_SPEED = 12  # grid cells per second; above this the movement model reports reach_proxy
MAX_ROUNDS = 12
THIN_STRENGTH_FLOOR = 0.25
THIN_OFFBEAT_FACTOR = 0.8
FILL_CODES = ("vocal_line_unmapped", "drum_rhythm_unmapped", "lead_rhythm_unmapped", "melody_unmapped",
              "boundary_accent_unmapped", "density_collapse")
REBUILD_MIN_NOTES = 4
LEAD_RUN_STRENGTH = 0.6
LANES = {0: (0, 1), 1: (2, 3)}
UP_CUTS, DOWN_CUTS = (0, 4, 5), (1, 6, 7)


def _grid_beat(beat: float) -> Fraction:
    """The coarsest grid position within SNAP_TOLERANCE of ``beat``."""
    for denominator in GRIDS:
        candidate = Fraction(round(beat * denominator), denominator)
        if abs(float(candidate) - beat) <= SNAP_TOLERANCE:
            return candidate
    return Fraction(round(beat * 16), 16)


def _relative(beat: Fraction):
    return int(beat) if beat.denominator == 1 else str(beat)


# Warnings a repair must not introduce either: a move that shortens a gap can make the hand's travel too fast.
AVOIDED_WARNINGS = ("reach_proxy",)


def _errors(arrangement):
    """Blocking diagnostics plus avoided warnings, keyed by (code, object IDs)."""
    return {(d["code"], tuple(d["object_ids"])) for d in validate_arrangement(arrangement)
            if d["severity"] == "error" or d["code"] in AVOIDED_WARNINGS}


def _culprits(arrangement, baseline, changes):
    """Changes responsible for blocking diagnostics absent from ``baseline``.

    A diagnostic naming a changed note or arc blames that change. One naming only
    untouched notes (a removal can join two neighbours into a flow break) blames the
    change nearest in beat to those notes.
    """
    new = _errors(arrangement) - baseline
    if not new:
        return [], set()
    beats = {n["id"]: float(n["beat"]) for n in expanded_notes(arrangement)}
    blamed, orphans = [], set()
    for _, ids in new:
        named = [c for c in changes if set(ids) & set(c["object_ids"] + c.get("arc_ids", []))]
        if not named:
            spots = [beats[i] for i in ids if i in beats]
            if spots and changes:
                named = [min(changes, key=lambda c: min(abs(c.get("to_beat", c["beat"]) - b) for b in spots))]
        if named:
            blamed.extend(c for c in named if c not in blamed)
        else:
            orphans.update(ids)
    return blamed, orphans


class _Map:
    """Mutable view of an arrangement's literal notes by absolute beat."""

    def __init__(self, arrangement):
        self.arrangement = arrangement
        self.bpm = float(arrangement["song"]["bpm"])

    def sections(self):
        for section in self.arrangement["sections"]:
            start = _beat(section["start_beat"])
            yield section, start, start + _beat(section["length_beats"])

    def section_at(self, beat):
        return next(((s, start) for s, start, end in self.sections() if start <= beat < end), (None, None))

    def entries(self):
        """(section, note, absolute beat) for every literal note."""
        return [(section, note, start + _beat(note["beat"]))
                for section, start, _ in self.sections() for note in section["notes"]]

    def times(self):
        return sorted({n["beat"] for n in expanded_notes(self.arrangement)})

    def arcs_at(self, section, start, note, beat):
        """(arc, role) pairs anchored on ``note``."""
        found = []
        for arc in section.get("arcs", []):
            if arc["color"] != note["color"]:
                continue
            if (start + _beat(arc["beat"]), arc["x"], arc["y"]) == (beat, note["x"], note["y"]):
                found.append((arc, "head"))
            if (start + _beat(arc["tail_beat"]), arc["tail_x"], arc["tail_y"]) == (beat, note["x"], note["y"]):
                found.append((arc, "tail"))
        return found

    def chain_anchored(self, section, start, note, beat):
        return any((start + _beat(c["beat"]), c["x"], c["y"], c["color"]) == (beat, note["x"], note["y"], note["color"])
                   for c in section.get("chains", []))

    def held(self, hand, beat):
        """True when an arc or chain of ``hand`` spans ``beat`` (the saber is already occupied)."""
        for section, start, _ in self.sections():
            for kind in ("arcs", "chains"):
                for item in section.get(kind, []):
                    if item["color"] == hand and start + _beat(item["beat"]) <= beat <= start + _beat(item["tail_beat"]):
                        return True
        return False


def _support(arrangement, report):
    """Sorted supporting onset seconds and a predicate for a beat."""
    onsets = sorted(t for values in _stem_onsets(report, SUPPORT_STRENGTH, include_mix=True).values() for t in values)
    tolerance = SUPPORT_BEATS * 60 / float(arrangement["song"]["bpm"])

    def supported(beat):
        seconds = beat_to_seconds(beat, arrangement)
        index = bisect_left(onsets, seconds - tolerance)
        return index < len(onsets) and onsets[index] <= seconds + tolerance
    return onsets, supported


def ground_notes(arrangement: dict, report: dict) -> dict:
    """Pass 1: move or remove note times that no audio event supports."""
    from .musical import seconds_to_beat
    result = copy.deepcopy(arrangement)
    view = _Map(result)
    onsets, supported = _support(result, report)
    strongest = {}
    for layer in (report.get("layers") or {}).values():
        for event in layer.get("events", []):
            if event.get("method") in ONSET_METHODS and event.get("strength", 0) >= SUPPORT_STRENGTH:
                seconds = float(event["seconds"])
                strongest[seconds] = max(strongest.get(seconds, 0), event["strength"])
    onset_beats = [seconds_to_beat(t, result) for t in onsets]
    onset_strength = [strongest.get(t, 0) for t in onsets]
    baseline = _errors(result)
    changes, unresolved = [], []
    times = view.times()
    by_time = {}
    for section, note, beat in view.entries():
        by_time.setdefault(beat, []).append((section, note))
    literal_count = {beat: len(items) for beat, items in by_time.items()}
    expanded_count = {}
    for note in expanded_notes(result):
        expanded_count[note["beat"]] = expanded_count.get(note["beat"], 0) + 1
    for position, beat in enumerate(times):
        if supported(beat):
            continue
        group = by_time.get(beat, [])
        ids = [f'{s["id"]}/note/{n["id"]}' for s, n in group]
        record = {"beat": float(beat), "object_ids": ids}
        if literal_count.get(beat, 0) != expanded_count.get(beat, 0) or any(s["locked"] for s, _ in group):
            unresolved.append({**record, "code": "note_without_audio",
                               "reason": "locked or motif-expanded notes; unlock the section or edit the motif"})
            continue
        section, start = view.section_at(beat)
        end = start + _beat(section["length_beats"])
        if any(view.chain_anchored(s, start, n, beat) for s, n in group):
            unresolved.append({**record, "code": "note_without_audio", "reason": "chain anchor"})
            continue
        previous = times[position - 1] if position else None
        following = times[position + 1] if position + 1 < len(times) else None
        low = max(start, start if previous is None else previous + min(MIN_GAP_BEATS, beat - previous))
        high = min(end - Fraction(1, 16),
                   end if following is None else following - min(MIN_GAP_BEATS, following - beat))
        anchors = [(s, n, arc, role) for s, n in group for arc, role in view.arcs_at(s, start, n, beat)]
        options = []
        lo = bisect_left(onset_beats, float(beat) - SNAP_BEATS)
        hi = bisect_left(onset_beats, float(beat) + SNAP_BEATS)
        for onset, strength in zip(onset_beats[lo:hi], onset_strength[lo:hi]):
            target = _grid_beat(onset)
            if not low <= target <= high or target == beat or not supported(target):
                continue
            if not all(_arc_ok(arc, role, start, target) for _, _, arc, role in anchors):
                continue
            if not _reach_after_move(result, group, beat, target):
                continue
            options.append((abs(target - beat), -strength, target))  # nearest, then strongest
        if options:
            target = min(options)[2]
            for s, n in group:
                n["beat"] = _relative(target - start)
            for _, _, arc, role in anchors:
                arc["beat" if role == "head" else "tail_beat"] = _relative(target - start)
            changes.append({**record, "action": "moved", "to_beat": float(target),
                            "arc_ids": sorted({f'{section["id"]}/arcs/{arc["id"]}' for _, _, arc, _ in anchors}),
                            "reason": "moved onto the nearest audio onset"})
            times[position] = target
        elif anchors:
            unresolved.append({**record, "code": "note_without_audio",
                               "reason": f"arc anchor with no audio onset within {SNAP_BEATS} beat"})
        else:
            for s, n in group:
                s["notes"].remove(n)
            changes.append({**record, "action": "removed",
                            "reason": f"no audio onset within {SNAP_BEATS} beat that the hand can reach in time"})
    _revert_breaking(result, arrangement, changes, unresolved, baseline)
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}


def _strength_near(report, threshold):
    """Sorted (seconds, strength) onsets of every layer at or above ``threshold``."""
    found = []
    for layer in (report.get("layers") or {}).values():
        found.extend((float(e["seconds"]), e["strength"]) for e in layer.get("events", [])
                     if e.get("method") in ONSET_METHODS and e.get("strength", 0) >= threshold)
    return sorted(found)


def thin_quiet(arrangement: dict, report: dict) -> dict:
    """Remove the weakest-supported note times from density_exceeds_audio windows."""
    result = copy.deepcopy(arrangement)
    view = _Map(result)
    baseline = _errors(result)
    tolerance = SUPPORT_BEATS * 60 / view.bpm
    support = _strength_near(report, SUPPORT_STRENGTH)
    support_seconds = [t for t, _ in support]
    # Onsets the salience checks count: removing their notes would open a vocal or drum finding.
    keep, match = salient_onsets(result, report)

    def strength(seconds):
        lo, hi = bisect_left(support_seconds, seconds - tolerance), bisect_left(support_seconds, seconds + tolerance)
        return max((s for _, s in support[lo:hi]), default=0.0)

    def kept(seconds):
        return on_onset(keep, match, seconds)

    changes, unresolved, tried, blocked = [], [], set(), set()
    progress = True
    while progress:
        progress = False
        times = sorted(beat_to_seconds(n["beat"], result) for n in expanded_notes(result))
        by_time, expanded = {}, {}
        for section, note, beat in view.entries():
            by_time.setdefault(beat, []).append((section, note))
        for note in expanded_notes(result):
            expanded[note["beat"]] = expanded.get(note["beat"], 0) + 1
        for window in quiet_windows(result, times, report)[1]:
            if not window.get("excess") or window["start_seconds"] in blocked:
                continue
            candidates = []
            for beat, group in by_time.items():
                seconds = beat_to_seconds(beat, result)
                if not window["start_seconds"] <= seconds < window["end_seconds"] or beat in tried:
                    continue
                section, start = view.section_at(beat)
                if (len(group) != 1 or expanded.get(beat, 0) != 1 or section["locked"] or kept(seconds)
                        or view.arcs_at(section, start, group[0][1], beat)
                        or view.chain_anchored(section, start, group[0][1], beat)):
                    continue
                # Thin evenly: the cheapest removal is a weak, off-beat note in a crowded spot, so no
                # phrase empties while a run beside it stays dense.
                index = bisect_left(times, seconds)
                previous = times[index - 1] if index else seconds - QUIET_WINDOW_SECONDS
                following = times[index + 1] if index + 1 < len(times) else seconds + QUIET_WINDOW_SECONDS
                cost = (strength(seconds) + THIN_STRENGTH_FLOOR) * (following - previous)
                cost *= 1.0 if beat.denominator == 1 else THIN_OFFBEAT_FACTOR
                candidates.append((cost, beat, group[0]))
            if not candidates:
                blocked.add(window["start_seconds"])
                unresolved.append({"beat": round(window["start_beat"], 4), "code": "density_exceeds_audio",
                                   "object_ids": [],
                                   "reason": f'{window["free_notes"]} notes off the vocal and drum onsets in '
                                             f'{window["start_seconds"]:g}-{window["end_seconds"]:g} s remain above '
                                             f'{window["allowed_nps"]:.2f} nps; they are arc anchors, doubles or in '
                                             "locked sections, or their removal would break flow"})
                continue
            _, beat, (section, note) = min(candidates, key=lambda c: (c[0], c[1]))
            tried.add(beat)
            progress = True
            section["notes"].remove(note)
            if _errors(result) - baseline:
                section["notes"].append(note)
                section["notes"].sort(key=lambda n: _beat(n["beat"]))
                break
            changes.append({"beat": float(beat), "object_ids": [f'{section["id"]}/note/{note["id"]}'],
                            "action": "removed", "code": "density_exceeds_audio",
                            "reason": f'thins a quiet passage ({window["nps"]:.2f} nps against '
                                      f'{window["allowed_nps"]:.2f} allowed): weakest audio support in the window'})
            break
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}


def _reach_after_move(arrangement, group, beat, target):
    """True when moving ``group`` from ``beat`` to ``target`` keeps each hand's travel under REACH_SPEED."""
    moving = {f'{s["id"]}/note/{n["id"]}' for s, n in group}
    seconds = beat_to_seconds(target, arrangement)
    for _, note in group:
        others = [n for n in expanded_notes(arrangement) if n["color"] == note["color"] and n["id"] not in moving]
        before = [n for n in others if n["beat"] < target]
        after = [n for n in others if n["beat"] > target]
        for neighbour in (before[-1] if before else None, after[0] if after else None):
            if neighbour is None:
                continue
            gap = abs(seconds - beat_to_seconds(neighbour["beat"], arrangement))
            distance = ((neighbour["x"] - note["x"]) ** 2 + (neighbour["y"] - note["y"]) ** 2) ** 0.5
            if gap and distance / gap > REACH_SPEED:
                return False
    return True


def _arc_ok(arc, role, start, target):
    head = start + _beat(arc["beat"]) if role == "tail" else target
    tail = start + _beat(arc["tail_beat"]) if role == "head" else target
    return head < tail


def _revert_breaking(result, original, changes, unresolved, baseline):
    """Undo changes whose notes appear in new blocking diagnostics, until none remain."""
    source = {f'{s["id"]}/note/{n["id"]}': copy.deepcopy(n) for s in original["sections"] for n in s["notes"]}
    source_arcs = {(s["id"], a["id"]): copy.deepcopy(a) for s in original["sections"] for a in s.get("arcs", [])}
    for _ in range(len(changes) + 1):
        culprits, orphans = _culprits(result, baseline, changes)
        if orphans:
            raise ValueError("Audio repair introduced blocking diagnostics it cannot attribute: "
                             + ", ".join(sorted(orphans)))
        if not culprits:
            return
        for change in culprits:
            for oid in change["object_ids"]:
                sid, _, nid = oid.split("/")
                section = next(s for s in result["sections"] if s["id"] == sid)
                if change["action"] == "added":
                    section["notes"] = [n for n in section["notes"] if n["id"] != nid]
                    continue
                current = next((n for n in section["notes"] if n["id"] == nid), None)
                if current is None:
                    section["notes"].append(copy.deepcopy(source[oid]))
                else:
                    current.update(copy.deepcopy(source[oid]))
            for arc_oid in change.get("arc_ids", []):
                sid, _, aid = arc_oid.split("/")
                section = next(s for s in result["sections"] if s["id"] == sid)
                arc = next(a for a in section["arcs"] if a["id"] == aid)
                arc.update(copy.deepcopy(source_arcs[(sid, aid)]))
            changes.remove(change)
            unresolved.append({"beat": change["beat"], "object_ids": change["object_ids"],
                               "code": change.get("code", "note_without_audio"),
                               "reason": f'{change["action"]} note would add a blocking diagnostic or reach_proxy; reverted'})
    raise ValueError("Audio repair did not converge; inspect the reported findings")


def _cells(view, hand, direction, beat, anchor):
    """Candidate (cost, x, y) cells for a new note, nearest the hand's previous position first.

    A cell whose note would hide behind, or hide, a nearby note in that cell (``hidden_note``) is skipped.
    """
    notes = expanded_notes(view.arrangement)
    occupied = {(n["x"], n["y"]) for n in notes if n["beat"] == beat}
    other = [n["x"] for n in notes if n["beat"] == beat and n["color"] != hand]
    seconds = beat_to_seconds(beat, view.arrangement)
    near = [(n["x"], n["y"], abs(beat_to_seconds(n["beat"], view.arrangement) - seconds))
            for n in notes if n["beat"] != beat and abs(n["beat"] - beat) <= 4]
    cells = []
    for x in LANES[hand]:
        for y in range(3):
            if (x, y) in occupied or any((x > o) if hand == 0 else (x < o) for o in other):
                continue
            if any((nx, ny) == (x, y) and gap < hidden_window(x, y) for nx, ny, gap in near):
                continue
            cost = abs(x - anchor[0]) + abs(y - anchor[1])
            cost += 1.5 if (direction in UP_CUTS and y == 2) or (direction in DOWN_CUTS and y == 0 and anchor[1] == 0) else 0
            cost += 0.5 if direction in (2, 3) and y != 1 else 0
            cells.append((cost, x, y))
    return sorted(cells)


def insert_note(arrangement: dict, beat: Fraction, note_id: str) -> dict | None:
    """Add a flow-safe note at ``beat`` in place; return the change or None."""
    view = _Map(arrangement)
    section, start = view.section_at(beat)
    if section is None or section["locked"]:
        return None
    times = view.times()
    index = bisect_left(times, beat)
    near = [t for t in times[max(0, index - 1):index + 1] if abs(t - beat) < MIN_GAP_BEATS]
    if near:
        return None
    seconds = beat_to_seconds(beat, arrangement)
    options = []
    for hand in (0, 1):
        if view.held(hand, beat):
            continue
        swings = _hand_swings(arrangement, hand)
        at = bisect_left([s["beat"] for s in swings], beat)
        before = swings[at - 1] if at else None
        after = swings[at] if at < len(swings) else None
        if (before and beat - before["beat"] < HAND_GAP_BEATS) or (after and after["beat"] - beat < HAND_GAP_BEATS):
            continue
        anchor = _position(arrangement, before or after, hand)
        effective = _effective(swings[:at])
        prefer = _OPPOSITE[effective] if effective is not None else 1
        for direction in sorted(range(8), key=lambda d: turn_degrees(prefer, d)):
            trial = swings[:at] + [{"beat": beat, "seconds": seconds, "direction": direction, "ids": ["new"]}] + swings[at:]
            if _count_breaks(trial, hand, view.bpm, at, at + 1):
                continue
            for cost, x, y in _cells(view, hand, direction, beat, anchor):
                if not _reach_ok(arrangement, hand, before, after, seconds, x, y):
                    continue
                spare = min(beat - before["beat"] if before else Fraction(8), after["beat"] - beat if after else Fraction(8))
                options.append((-min(spare, 4), turn_degrees(prefer, direction), cost, hand, direction, x, y))
                break
            else:
                continue
            break
    if not options:
        return None
    _, _, _, hand, direction, x, y = min(options)
    taken = {n["id"] for n in section["notes"]}
    while note_id in taken:
        note_id += "x"
    section["notes"].append({"id": note_id, "beat": _relative(beat - start), "x": x, "y": y,
                             "color": hand, "direction": direction})
    section["notes"].sort(key=lambda n: _beat(n["beat"]))
    return {"beat": float(beat), "object_ids": [f'{section["id"]}/note/{note_id}'], "action": "added",
            "color": hand, "direction": direction, "x": x, "y": y}


def _effective(swings):
    """Direction the hand last cut, a dot taking the reverse of its predecessor."""
    effective = None
    for swing in swings:
        effective = swing["direction"] if swing["direction"] != 8 else (
            _OPPOSITE[effective] if effective is not None else None)
    return effective


def _position(arrangement, swing, hand):
    if swing is None:
        return (LANES[hand][0] if hand else LANES[hand][1], 1)
    notes = [n for n in expanded_notes(arrangement) if n["id"] in swing["ids"]]
    return (notes[0]["x"], notes[0]["y"]) if notes else (1 + hand, 1)


def _reach_ok(arrangement, hand, before, after, seconds, x, y):
    for swing in (before, after):
        if swing is None:
            continue
        px, py = _position(arrangement, swing, hand)
        gap = abs(seconds - swing["seconds"])
        if gap and ((px - x) ** 2 + (py - y) ** 2) ** 0.5 / gap > REACH_SPEED:
            return False
    return True


def _fill_targets(arrangement, report, warning):
    """(strength, beat) onsets a fill finding asks to map."""
    from .musical import seconds_to_beat
    layers = report.get("layers") or {}
    start, end = warning["beats"]
    code = warning["code"]

    def events(names, threshold, methods=("spectral_flux",)):
        return [(e["strength"], seconds_to_beat(e["seconds"], arrangement)) for name in names
                for e in (layers.get(name) or {}).get("events", [])
                if e.get("method") in methods and e.get("strength", 0) >= threshold]

    if code == "vocal_line_unmapped":
        found = events(["vocals"], VOCAL_ONSET_STRENGTH)
    elif code == "drum_rhythm_unmapped":
        strongest = {}
        for strength, beat in events(["drums"], DRUM_ONSET_STRENGTH):
            slot = int(beat * DRUM_SLOTS_PER_BEAT + 0.5)
            if slot not in strongest or strongest[slot][0] < strength:
                strongest[slot] = (strength, beat)
        found = list(strongest.values())
    elif code == "lead_rhythm_unmapped":
        lead = focus_lead(_sections(arrangement), start + SALIENCE_BAR_BEATS / 2, layers)
        found = [(strength, beat) for beat, strength in
                 strongest_per_slot(lead_onsets(layers, lead, arrangement, LEAD_ONSET_STRENGTH))] if lead else []
    elif code == "melody_unmapped":
        found = [(strength, beat) for beat, strength in
                 strongest_per_slot([(b, s) for s, b in events([MELODY_LAYER], MELODY_ONSET_STRENGTH, ("melody_change",))])]
    elif code == "boundary_accent_unmapped":
        return [(1.0, start)]
    else:
        names = [n for n in layers if n != "mix"] or list(layers)
        found = events(names, ONSET_STRENGTH, ONSET_METHODS)
    return sorted(((s, b) for s, b in found if start - 1e-6 <= b < end + 1e-6), reverse=True)


def fill_findings(arrangement: dict, report: dict) -> dict:
    """Pass 2: add flow-safe notes on the unmapped onsets named by salience and density findings."""
    result = copy.deepcopy(arrangement)
    baseline = _errors(result)
    changes, unresolved, tried, counter = [], [], set(), 0
    for _ in range(MAX_ROUNDS):
        warnings = [w for w in critique_arrangement(result, report)["warnings"]
                    if w["code"] in FILL_CODES and "beats" in w]
        added = 0
        for warning in warnings:
            beats = sorted(float(n["beat"]) for n in expanded_notes(result))
            melody = warning["code"] == "melody_unmapped"
            reach = MELODY_MATCH_BEATS if melody else SALIENCE_MATCH_BEATS
            for strength, onset in _fill_targets(result, report, warning):
                index = bisect_left(beats, onset - reach)
                if index < len(beats) and beats[index] <= onset + reach:
                    continue  # already mapped
                # A legato pitch change lands just after the beat; melodic bars keep the half-beat grid.
                half = Fraction(round(onset * 2), 2)
                target = half if melody and abs(float(half) - onset) <= MELODY_MATCH_BEATS else _grid_beat(onset)
                key = (warning["code"], target)
                if key in tried:
                    continue
                tried.add(key)
                counter += 1
                change = insert_note(result, target, f"aud-{counter:03d}")
                if change is None:
                    unresolved.append({"beat": float(target), "code": warning["code"], "object_ids": [],
                                       "reason": "no hand can take this onset without a flow break, crowding "
                                                 "or an occupied saber"})
                    continue
                change.update(code=warning["code"], onset_beat=round(onset, 4), strength=strength,
                              reason=f'maps an unmapped {warning["code"].split("_")[0]} onset')
                changes.append(change)
                beats = sorted(beats + [float(target)])
                added += 1
        if not added:
            break
        _revert_breaking(result, arrangement, changes, unresolved, baseline)
    resolved_beats = {c["beat"] for c in changes}
    unresolved = [u for u in unresolved if u["beat"] not in resolved_beats]
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}


def _free_notes(view, first, last):
    """Literal notes in [first, last) the rebuild may clear, or None when motif notes are there."""
    expanded = {}
    for note in expanded_notes(view.arrangement):
        expanded[note["beat"]] = expanded.get(note["beat"], 0) + 1
    free, literal = [], {}
    for section, note, beat in view.entries():
        if not first <= beat < last:
            continue
        literal[beat] = literal.get(beat, 0) + 1
        start = view.section_at(beat)[1]
        if section["locked"] or view.arcs_at(section, start, note, beat) or view.chain_anchored(section, start, note, beat):
            continue  # arcs, chains and locked notes stay; the rebuilt rhythm fits around them
        free.append((section, note, beat))
    inside = {beat: count for beat, count in expanded.items() if first <= beat < last}
    if any(literal.get(beat, 0) != count for beat, count in inside.items()):
        return None  # motif-expanded notes: edit the motif instead
    return free


def _lead_targets(arrangement, report, lead, first, last):
    """Beats for a rebuilt bar: the lead's strongest attack per half-beat, then fills where it is silent.

    A thin, soft bar (``quiet_bar``) takes only the strongest attack per beat and no sixteenth runs, so the
    rebuild never maps a quiet passage as densely as the full band.
    """
    layers = report.get("layers") or {}
    found = lead_onsets(layers, lead, arrangement, LEAD_SUPPORT_STRENGTH)
    quiet = quiet_bar(report, arrangement, first, last)
    targets = [(beat, strength) for beat, strength in strongest_per_slot(found, 1 if quiet else DRUM_SLOTS_PER_BEAT)
               if strength >= LEAD_ONSET_STRENGTH and first <= beat < last]
    # A strong sixteenth run in the lead is part of its rhythm: keep those attacks too.
    targets += [] if quiet else [(beat, strength) for beat, strength in strongest_per_slot(found, 4)
                                 if strength >= LEAD_RUN_STRENGTH and first <= beat < last
                                 and all(abs(beat - other) > 1e-6 for other, _ in targets)]
    heard = [beat for beat, _ in found]
    fills = []
    for beat in range(int(first), int(last)):
        if any(beat - 0.25 <= b < beat + 1.25 for b in heard):
            continue
        others = [(s, b) for name in layers if name not in ("mix", lead)
                  for b, s in lead_onsets(layers, name, arrangement, LEAD_ONSET_STRENGTH) if beat <= b < beat + 1]
        if others:
            strength, onset = max(others)
            fills.append((onset, strength))
    return targets, fills


def _lead_mapped(arrangement, report, lead, first, last):
    """How many of the lead's strongest attacks per half-beat in [first, last) carry a note."""
    found = lead_onsets(report.get("layers") or {}, lead, arrangement, LEAD_SUPPORT_STRENGTH)
    strong = [beat for beat, strength in strongest_per_slot(found)
              if strength >= LEAD_ONSET_STRENGTH and first <= beat < last]
    times = sorted(float(n["beat"]) for n in expanded_notes(arrangement))
    return sum(1 for beat in strong
               if bisect_left(times, beat - SALIENCE_MATCH_BEATS) < len(times)
               and times[bisect_left(times, beat - SALIENCE_MATCH_BEATS)] <= beat + SALIENCE_MATCH_BEATS)


REBUILD_CODES = ("lead_rhythm_diluted", "lead_rhythm_unmapped")


def follow_lead(arrangement: dict, report: dict) -> dict:
    """Pass 3: rebuild bars whose notes bury the lead's rhythm in filler or in an even stream."""
    result = copy.deepcopy(arrangement)
    changes, unresolved, counter = [], [], 0
    critique = critique_arrangement(result, report)
    leads = {bar["start_beat"]: bar["lead"] for bar in critique["metrics"]["lead_rhythm"]["bars"]}
    flagged = {}
    for warning in critique["warnings"]:
        if warning["code"] in REBUILD_CODES:
            for bar in range(int(warning["beats"][0]), int(warning["beats"][1]), SALIENCE_BAR_BEATS):
                flagged.setdefault(bar, warning["code"])
    baseline = _errors(result)
    for bar, code in sorted(flagged.items()):
        first, last = Fraction(bar), Fraction(bar + SALIENCE_BAR_BEATS)
        snapshot = copy.deepcopy(result)
        before = _lead_mapped(result, report, leads[bar], float(first), float(last))
        view = _Map(result)
        free = _free_notes(view, first, last)
        record = {"beat": float(first), "code": code, "object_ids": []}
        if free is None:
            unresolved.append({**record, "reason": "motif-expanded notes in the bar; edit the motif"})
            continue
        old = len({beat for _, _, beat in free})
        removed = [f'{section["id"]}/note/{note["id"]}' for section, note, _ in free]
        for section, note, _ in free:
            section["notes"].remove(note)
        targets, fills = _lead_targets(result, report, leads[bar], float(first), float(last))
        added = []
        for onset, _ in targets + fills:
            counter += 1
            change = insert_note(result, _grid_beat(onset), f"lead-{counter:03d}")
            if change is not None:
                added.append(change)
        times = {n["beat"] for n in expanded_notes(result) if first <= n["beat"] < last}
        worse = code == "lead_rhythm_unmapped" and _lead_mapped(
            result, report, leads[bar], float(first), float(last)) <= before
        if len(times) < min(REBUILD_MIN_NOTES, old) or worse or _errors(result) - baseline:
            result.clear()
            result.update(snapshot)
            unresolved.append({**record, "reason": "no flow-safe rebuild on the lead's attacks; re-author by hand"})
            continue
        changes.append({**record, "action": "rebuilt", "lead": leads[bar], "removed_ids": removed,
                        "object_ids": [i for c in added for i in c["object_ids"]],
                        "reason": f'notes follow the {leads[bar]} attacks instead of an even stream'})
    return {"arrangement": result, "changes": changes, "unresolved": unresolved}


def reweight_focus(arrangement: dict, report: dict) -> dict:
    """Drop stems that are absent from a focus phrase (focus_on_quiet_stem) from its weights.

    A stem at least QUIET_STEM_DB below its own usual level only contributes separator bleed. When the
    declared lead is absent, the most active stem takes its weight and becomes the lead; when every
    stem is absent the phrase follows the mix.
    """
    from .critique import QUIET_STEM_DB
    result = copy.deepcopy(arrangement)
    measured = critique_arrangement(result, report)["metrics"]["focus_stems"]
    levels = {(p["section_id"], p["focus_id"]): p for p in measured.get("phrases", [])}
    changes = []
    for section in result["sections"]:
        if section.get("locked"):
            continue
        for phrase in section.get("musical_focus") or []:
            found = levels.get((section["id"], phrase["id"]))
            if not found:
                continue
            db, active = found["db_vs_own_level"], found["most_active"]
            quiet = {name for name in phrase["weights"] if name in db and db[name] <= -QUIET_STEM_DB}
            if not quiet:
                continue
            before = {"lead": phrase["lead"], "weights": dict(phrase["weights"])}
            weights = {name: w for name, w in phrase["weights"].items() if name not in quiet and w > 0}
            lead = phrase["lead"]
            if lead in quiet or not weights:
                lead = active if db[active] > -QUIET_STEM_DB else "mix"
                weights[lead] = weights.get(lead, 0) + before["weights"].get(phrase["lead"], 0) or 1.0
            total = sum(weights.values())
            weights = {name: round(w / total, 4) for name, w in weights.items()}
            weights[lead] = round(weights[lead] + 1 - sum(weights.values()), 4)
            phrase["weights"], phrase["lead"] = weights, lead
            phrase["intent"] = phrase["intent"].rstrip() + f" Reweighted: {', '.join(sorted(quiet))} absent here."
            changes.append({"action": "reweight_focus", "section_id": section["id"], "focus_id": phrase["id"],
                            "absent": sorted(quiet), "from": before, "to": {"lead": lead, "weights": weights}})
    return {"arrangement": result, "changes": changes, "unresolved": []}


def repair_audio(arrangement: dict, report: dict | None) -> dict:
    """Return ``{"arrangement", "changes", "unresolved", "remaining"}`` without mutating the input."""
    if not report:
        raise ValueError("No musical evidence run for the current audio; run `music analyze` first")
    blocking = [d for d in validate_arrangement(arrangement) if d["severity"] == "error"]
    if blocking:
        raise ValueError("Fix blocking diagnostics before repairing audio findings: "
                         + "; ".join(d["message"] for d in blocking[:5]))
    focus = reweight_focus(arrangement, report)
    grounded = ground_notes(focus["arrangement"], report)
    grounded["changes"] = focus["changes"] + grounded["changes"]
    thinned = thin_quiet(grounded["arrangement"], report)
    grounded = {"arrangement": thinned["arrangement"], "changes": grounded["changes"] + thinned["changes"],
                "unresolved": grounded["unresolved"] + thinned["unresolved"]}
    led = follow_lead(grounded["arrangement"], report)
    filled = fill_findings(led["arrangement"], report)
    # Notes added for the lead or for unmapped onsets can push a thin window (or the map's full-band
    # reference) past its allowance again; intensity keeps the last word on density.
    settled = thin_quiet(filled["arrangement"], report)
    remaining = [{k: w[k] for k in ("code", "message", "section_id")}
                 for w in critique_arrangement(settled["arrangement"], report)["warnings"]]
    return {"arrangement": settled["arrangement"],
            "changes": grounded["changes"] + led["changes"] + filled["changes"] + settled["changes"],
            "unresolved": grounded["unresolved"] + led["unresolved"] + filled["unresolved"] + settled["unresolved"],
            "remaining": remaining}
