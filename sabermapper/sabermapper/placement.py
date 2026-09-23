"""Correct-by-construction placement: the agent authors rhythm, the placer chooses hand, cut and cell.

A note needs only ``id`` and ``beat``. ``color`` (hand), ``direction`` (cut) and ``x``/``y`` (cell) are
optional **pins**: a field the agent writes is never changed. The placer fills every missing field so the
blocking movement rules hold by construction:

* swing flow (``movement.flow_break``: ``fast_direction_break``, ``flow_parity_break``);
* held sabers: an arc or chain reserves its color from head to tail (``arc_note_conflict``,
  ``chain_note_conflict``), and its head and tail notes take the arc's hand, cut and cell;
* ``one_hand_burst`` (three fast same-hand swings while the other hand idles);
* ``hidden_note`` (a note arriving too soon behind another in its cell), reach (``movement.REACH_SPEED``)
  and hand crossing.

A saved note lists the fields the placer chose in ``placed``. On the next placement those values are kept
while they stay valid and re-chosen only when a rhythm edit makes them break a rule, so an edit in one bar
leaves the rest of the map alone. Deleting a field asks for a fresh choice; removing it from ``placed``
pins the stored value. Locked sections are fixed context.

Placement is deterministic and searches nothing at random. A beam search over the timeline chooses each
swing's hand and cut; a greedy pass then chooses each note's cell, preferring short hand travel and
placements the recent notes have not used (the SM-034 repetition metrics: distinct placements and strict
cycles). The result is checked with :func:`movement.analyze_movement` itself. A broken rule that involves a
placer-chosen field raises :class:`PlacementError`, which names the beat, the notes, the rule and the
alternatives verified to clear it. A conflict between fully pinned notes is left to validation.
"""

from __future__ import annotations

import copy
from collections import Counter
from fractions import Fraction
from math import hypot

from .movement import (BURST_SECONDS, BURST_SWINGS, CHORD_BEATS, CHORD_SECONDS, FAST_BREAK_SECONDS, REACH_SPEED,
                       _OPPOSITE, _VECTORS, analyze_movement, flow_break, hidden_window, is_rest, next_effective,
                       turn_degrees)
from .validation import _beat

FIELDS = ("x", "y", "color", "direction")
RANGES = {"x": range(4), "y": range(3), "color": range(2), "direction": range(9)}
BEAM_WIDTH = 24
BEAM_PER_TIMING = 4  # beam states kept per hand-timing history, so one hand assignment cannot crowd out the rest
BLOCK = 1e10  # breaking a rule that blocks save (flow, held sabers, hidden notes)
HARD = 1e9  # breaking a review rule the placer also keeps (one_hand_burst, reach)
SOFT = 1e6  # re-choosing a value an earlier placement stored in ``placed``
LANES = {0: (0, 1), 1: (2, 3)}
FIRST_CUTS = (1, 6, 7, 0, 4, 5)  # a hand's first swing: down cuts first
UP_CUTS, DOWN_CUTS = (0, 4, 5), (1, 6, 7)
CYCLE_LOOKBACK = range(2, 17)  # the strict-cycle lags SM-034 measures (critique.CYCLE_RANGE)
VARIETY_WINDOW = 48
TOP_ROW_SHARE = 0.15  # below this recent top-row share, the top row is preferred
# Rules the placer satisfies; each maps to the note fields that can resolve it.
RULE_FIELDS = {"fast_direction_break": ("direction", "color"), "flow_parity_break": ("direction", "color"),
               "one_hand_burst": ("color",), "arc_note_conflict": ("color",), "chain_note_conflict": ("color",),
               "hidden_note": ("x", "y"), "reach_proxy": ("x", "y")}
MAX_ALTERNATIVE_ERRORS = 5


class PlacementError(ValueError):
    """Rhythm the movement rules cannot place; ``errors`` holds one structured record per conflict."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("Placement is infeasible: " + "; ".join(e["message"] for e in errors[:5])
                         + (f"; and {len(errors) - 5} more" if len(errors) > 5 else ""))


class _Slot:
    __slots__ = ("index", "oid", "beat", "seconds", "fixed", "soft", "pinned", "note", "locked", "value",
                 "anchored", "motif", "anchor")

    def __init__(self, oid, beat, fixed, soft, pinned, note, locked, motif=None):
        self.oid, self.beat, self.fixed, self.soft, self.pinned = oid, beat, fixed, soft, pinned
        self.note, self.locked, self.motif = note, locked, motif
        self.value, self.anchored, self.index, self.seconds, self.anchor = {}, set(), 0, 0.0, None

    @property
    def chosen(self):
        """Fields the placer decides (everything the agent did not pin)."""
        return [f for f in FIELDS if f not in self.pinned]


def needs_placement(arrangement: dict) -> bool:
    """True when some note (literal or motif) lacks a field or records placer-chosen fields."""
    def open_note(note):
        return isinstance(note, dict) and ("placed" in note or any(f not in note for f in FIELDS))
    try:
        return (any(open_note(n) for s in arrangement["sections"] for n in s["notes"])
                or any(open_note(n) for motif in arrangement["motifs"].values() for n in motif))
    except (KeyError, TypeError, AttributeError):
        return False


def _clock(arrangement):
    bpm = float(arrangement["song"]["bpm"])
    changes = [(Fraction(0), bpm)] + [(_beat(e["beat"]), float(e["bpm"]))
                                      for e in arrangement.get("tempo_events", [])]

    def seconds(beat):
        total, previous, tempo = 0.0, Fraction(0), bpm
        for change, next_tempo in changes[1:]:
            if change > beat:
                break
            total += float(change - previous) * 60 / tempo
            previous, tempo = change, next_tempo
        return total + float(beat - previous) * 60 / tempo
    return seconds


def _well_formed(note):
    """A note the placer can read: string ID, valid beat, in-range present fields, a valid ``placed`` list."""
    if not isinstance(note, dict) or not isinstance(note.get("id"), str):
        return False
    try:
        _beat(note.get("beat"))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return False
    if any(f in note and (type(note[f]) is not int or note[f] not in RANGES[f]) for f in FIELDS):
        return False
    placed = note.get("placed", [])
    return isinstance(placed, list) and all(f in FIELDS for f in placed) and len(set(placed)) == len(placed)


def _pins(note, locked, unpin):
    """(hard values, soft values, agent-pinned field names) of one authored note."""
    placed = set(note.get("placed", ()))
    fixed, soft, pinned = {}, {}, set()
    for field in FIELDS:
        if field not in note:
            continue
        if locked:
            fixed[field] = note[field]
            pinned.add(field)
        elif unpin:
            continue
        elif field in placed:
            soft[field] = note[field]
        else:
            fixed[field] = note[field]
            pinned.add(field)
    return fixed, soft, pinned


_MIRROR = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}


def _collect(arrangement, unpin):
    """Every expanded note as a slot, time-ordered; None when the input is not readable."""
    seconds = _clock(arrangement)
    slots = []
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        locked = section.get("locked") is True
        for note in section["notes"]:
            if not _well_formed(note):
                return None
            fixed, soft, pinned = _pins(note, locked, unpin)
            slots.append(_Slot(f'{section["id"]}/note/{note["id"]}', start + _beat(note["beat"]),
                               fixed, soft, pinned, note, locked))
        for pattern in section["patterns"]:
            motif = arrangement["motifs"][pattern["motif"]]
            mirror = pattern.get("mirror") is True
            for note in motif:
                if not _well_formed(note) or any(f not in note for f in FIELDS):
                    return None
                values = {f: note[f] for f in FIELDS}
                if mirror:
                    values.update(x=3 - values["x"], color=1 - values["color"], direction=_MIRROR[values["direction"]])
                chosen = set(note.get("placed", ()))
                slots.append(_Slot(f'{section["id"]}/pattern/{pattern["id"]}/{note["id"]}',
                                   start + _beat(pattern["start_beat"]) + _beat(note["beat"]),
                                   values, {}, set(FIELDS) - chosen, None, locked, motif=pattern["motif"]))
    slots.sort(key=lambda s: (s.beat, s.oid))
    for index, slot in enumerate(slots):
        slot.index, slot.seconds = index, seconds(slot.beat)
    return slots


def _holds(arrangement):
    """Arc/chain anchors [(beat, values, oid)] and held spans {color: [(head, tail, oid, kind)]}."""
    anchors, held = [], {0: [], 1: []}
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        for kind in ("arcs", "chains"):
            for item in section.get(kind, []):
                oid = f'{section["id"]}/{kind}/{item["id"]}'
                head, tail = start + _beat(item["beat"]), start + _beat(item["tail_beat"])
                anchors.append((head, {"x": item["x"], "y": item["y"], "color": item["color"],
                                       "direction": item["direction"]}, oid))
                if kind == "arcs":
                    anchors.append((tail, {"x": item["tail_x"], "y": item["tail_y"], "color": item["color"],
                                           "direction": item["tail_direction"]}, oid))
                held[item["color"]].append((head, tail, oid, kind))
    return anchors, held


def _anchor(slots, anchors):
    """Give each arc or chain end's note the end's hand, cut and cell (fields the agent left open)."""
    by_beat = {}
    for slot in slots:
        by_beat.setdefault(slot.beat, []).append(slot)
    taken = set()
    for beat, values, oid in sorted(anchors, key=lambda a: (a[0], a[2])):
        group = [s for s in by_beat.get(beat, []) if s.index not in taken and s.note is not None]
        exact = [s for s in group if all({**s.soft, **s.fixed}.get(f, values[f]) == values[f] for f in FIELDS)
                 and len({**s.soft, **s.fixed}) == 4]
        compatible = [s for s in group if all(s.fixed.get(f, values[f]) == values[f] for f in FIELDS)]
        slot = (exact or sorted(compatible, key=lambda s: -len(s.fixed)) or [None])[0]
        if slot is None:
            continue  # validation reports the arc or chain end without a note
        taken.add(slot.index)
        slot.anchor = oid
        for field in FIELDS:
            if field not in slot.fixed:
                slot.fixed[field] = values[field]
                slot.anchored.add(field)
                slot.soft.pop(field, None)


def _groups(slots):
    groups, current = [], []
    for slot in slots:
        if current and slot.beat != current[0].beat:
            groups.append(current)
            current = []
        current.append(slot)
    return groups + ([current] if current else [])


def _held_colors(held, beat):
    """{color: hold oid} for sabers busy with an arc or chain strictly around ``beat``."""
    busy = {}
    for color, spans in held.items():
        for head, tail, oid, kind in spans:
            if head < beat < tail:
                busy[color] = (oid, kind)
                break
    return busy


# ---------------------------------------------------------------------------------------------------------
# Pass 1: hands and cuts (beam search)
# ---------------------------------------------------------------------------------------------------------

_OPTIONS_CACHE: dict = {}


def _free_cuts(effective, hand, fast, reset, first):
    """(direction, cost) candidates for an unpinned swing, most natural first."""
    key = (effective, hand, fast, reset, first)
    if key in _OPTIONS_CACHE:
        return _OPTIONS_CACHE[key]
    if effective is None:
        order = FIRST_CUTS if first else (1, 0, 6, 7, 4, 5)
        result = [(d, 0.12 * rank) for rank, d in enumerate(order[:4])]
    else:
        reverse = _OPPOSITE[effective]
        gap = 0.1 if fast else 0.5
        # A fast swing reads best as a clean reversal; a slower one may angle off it.
        weight = 0.3 if fast else (0.08 if reset else 0.15)
        found = []
        for direction in range(8):
            if not reset and flow_break(effective, direction, hand, gap, False):
                continue
            cost = weight * turn_degrees(reverse, direction) / 45 + (0.04 if direction in (2, 3) else 0)
            found.append((cost, direction))
        found.sort()
        result = [(d, c) for c, d in found[:5]]
    _OPTIONS_CACHE[key] = result
    return result


def _cut_options(state, notes, hand, beat, seconds, other_last, bpm):
    """(direction, cost, violations, new hand state) for ``hand`` cutting ``notes`` at ``beat``."""
    effective, last_s, last_b, last_dir, run_len, run_start, prev_dir = state
    fixed = sorted({s.fixed["direction"] for s in notes if "direction" in s.fixed})
    soft = sorted({s.soft["direction"] for s in notes if "direction" in s.soft})
    gap = None if last_s is None else seconds - last_s
    beat_gap = None if last_b is None else beat - last_b
    reset = last_s is None or is_rest(gap)
    ids = tuple(s.index for s in notes)
    if fixed:
        candidates = [(fixed[-1], 0.0)]
    else:
        candidates = [(d, c + (SOFT if soft and d != soft[0] else 0))
                      for d, c in _free_cuts(effective, hand, gap is not None and gap < FAST_BREAK_SECONDS,
                                             reset, last_s is None)]
        if soft and all(d != soft[0] for d, _ in candidates):
            candidates.append((soft[0], 0.0))
    options = []
    for direction, cost in candidates:
        if not fixed and direction == prev_dir:
            cost += 0.2  # the same cut as this hand's swing before last: vary the angle
        violations = ()
        if len(fixed) > 1 and any("color" not in s.pinned for s in notes):
            cost += HARD
            violations += (("simultaneous_direction_conflict", ids),)
        if (last_s is not None and 0 <= beat_gap <= CHORD_BEATS and 0 <= gap <= CHORD_SECONDS
                and direction == last_dir):
            options.append((direction, cost, violations, state))  # one swing with the note just before
            continue
        if effective is not None and gap and not reset:
            found = flow_break(effective, direction, hand, gap, False)
            if found:
                cost += BLOCK
                violations += ((found[0], ids),)
        if gap is not None and 0 < gap < 1 / REACH_SPEED:
            # Two separate swings this close need two cells (a note right behind another is hidden),
            # and even the nearest cell is out of reach.
            cost += HARD
            violations += (("reach_proxy", ids),)
        if gap is not None and gap < BURST_SECONDS:
            length, begun = run_len + 1, run_start
        else:
            length, begun = 1, seconds
        if length >= BURST_SWINGS and not (other_last is not None and begun < other_last < seconds):
            cost += HARD
            violations += (("one_hand_burst", ids),)
        options.append((direction, cost, violations,
                        (next_effective(effective, direction, reset), seconds, beat, direction, length, begun,
                         last_dir)))
    return options


def _assignments(group, busy):
    """(colors per slot, cost, violations) hand assignments for one time group."""
    choices = []
    for slot in group:
        if "color" in slot.fixed:
            choices.append([(slot.fixed["color"], 0.0)])
        elif "color" in slot.soft:
            choices.append([(slot.soft["color"], 0.0), (1 - slot.soft["color"], SOFT)])
        else:
            choices.append([(0, 0.0), (1, 0.0)])
    combos = [((), 0.0)]
    for options in choices:
        combos = [(colors + (c,), cost + extra) for colors, cost in combos for c, extra in options][:64]
    result = []
    for colors, cost in combos:
        violations = ()
        for slot, color in zip(group, colors):
            if color in busy:
                cost += BLOCK
                violations += ((f"{busy[color][1][:-1]}_note_conflict", (slot.index,)),)
        if len(group) > 1 and len(set(colors)) == 1 and any("color" not in s.fixed for s in group):
            cost += 2.0  # a same-hand chord where a double would do
        result.append((colors, cost, violations))
    return result


def _plan_cuts(groups, held, bpm):
    """Beam search for every swing's hand and cut; returns ({slot index: (color, direction)}, violations)."""
    empty = (None, None, None, None, 0, None, None)
    beam = [(0.0, (empty, empty), None, None, None)]  # cost, hand states, last single hand, last beat, node
    for group in groups:
        beat, seconds = group[0].beat, group[0].seconds
        busy = _held_colors(held, beat)
        candidates = {}
        for cost, hands, last_hand, last_beat, node in beam:
            for colors, assign_cost, assign_violations in _assignments(group, busy):
                by_hand = {0: [], 1: []}
                for slot, color in zip(group, colors):
                    by_hand[color].append(slot)
                used = [h for h in (0, 1) if by_hand[h]]
                extra = assign_cost
                if len(used) == 1 and last_hand == used[0]:
                    close = last_beat is not None and beat - last_beat < 1
                    extra += 0.8 if close else 0.15
                per_hand = []
                for hand in used:
                    other = hands[1 - hand][1]
                    per_hand.append([(hand, *option) for option in
                                     _cut_options(hands[hand], by_hand[hand], hand, beat, seconds, other, bpm)])
                combos = per_hand[0] if len(per_hand) == 1 else [
                    (a, b) for a in per_hand[0] for b in per_hand[1]]
                for combo in combos:
                    parts = (combo,) if len(per_hand) == 1 else combo
                    total = cost + extra
                    new_hands = list(hands)
                    decisions, violations = [], assign_violations
                    for hand, direction, option_cost, option_violations, state in parts:
                        total += option_cost
                        violations += option_violations
                        new_hands[hand] = state
                        decisions += [(s.index, hand, direction) for s in by_hand[hand]]
                    if len(parts) == 2 and (parts[0][1] in UP_CUTS) != (parts[1][1] in UP_CUTS):
                        total += 0.4  # a double reads best as a parallel cut
                    new_hands = tuple(new_hands)
                    single = used[0] if len(used) == 1 else None
                    signature = (new_hands, single)
                    if signature not in candidates or candidates[signature][0] > total:
                        candidates[signature] = (total, new_hands, single, beat,
                                                 (node, tuple(decisions), violations))
        beam, per_timing = [], Counter()
        for candidate in sorted(candidates.values(), key=lambda c: c[0]):
            timing = tuple((h[1], h[4]) for h in candidate[1])
            if per_timing[timing] < BEAM_PER_TIMING:
                per_timing[timing] += 1
                beam.append(candidate)
                if len(beam) == BEAM_WIDTH:
                    break
    best = beam[0]
    plan, node = {}, best[4]
    while node is not None:
        node, decisions, _ = node
        for index, hand, direction in decisions:
            plan[index] = (hand, direction)
    return plan


# ---------------------------------------------------------------------------------------------------------
# Pass 2: cuts and cells together (greedy, in time order)
# ---------------------------------------------------------------------------------------------------------

def _entry_exit(x, y, direction):
    if direction == 8:
        return (x, y), (x, y)
    vx, vy = _VECTORS[direction]
    return (x - 0.5 * vx, y - 0.5 * vy), (x + 0.5 * vx, y + 0.5 * vy)


def _cell_fixed(slot):
    return "x" in slot.fixed and "y" in slot.fixed


def _place_cells(groups, slots, bpm, joint=True):
    """Choose every open cell (and, when ``joint``, every open cut) in time order.

    Hands come from pass 1. With ``joint`` a free cut is re-chosen together with its cell among the cuts
    that keep the flow from the hand's actual previous swing and into its next pinned one, so the cut
    follows the hand's path across the grid. Without it, pass 1's cuts stay.
    """
    fixed_cells = {}  # cell -> seconds of notes whose cell is fixed
    for slot in slots:
        if _cell_fixed(slot):
            fixed_cells.setdefault((slot.fixed["x"], slot.fixed["y"]), []).append(slot.seconds)
    next_fixed, next_swing = {}, {}
    upcoming, following = {0: None, 1: None}, {0: None, 1: None}
    for group in reversed(groups):
        for slot in group:
            hand = slot.value["color"]
            next_fixed[slot.index] = upcoming[hand]
            next_swing[slot.index] = following[hand]
        for slot in group:
            if _cell_fixed(slot):
                upcoming[slot.value["color"]] = slot
            following[slot.value["color"]] = slot
    hands = {0: _HandState(), 1: _HandState()}
    front = {}  # cell -> (seconds, slot index) of the latest note there
    sequence, used = [], set()
    for group in groups:
        beat, seconds = group[0].beat, group[0].seconds
        occupied = {(s.fixed["x"], s.fixed["y"]) for s in group if _cell_fixed(s)}
        open_slots = sorted((s for s in group if not _cell_fixed(s) or (joint and "direction" not in s.fixed)),
                            key=lambda s: (s.value["color"], s.oid))
        context = {"recent": Counter(sequence[-VARIETY_WINDOW:]), "sequence": sequence, "used": used,
                   "top_share": sum(1 for p in sequence[-VARIETY_WINDOW:] if p[1] == 2)
                   / max(1, min(len(sequence), VARIETY_WINDOW))}
        options = [_cell_options(slot, occupied, hands, front, fixed_cells, next_fixed[slot.index],
                                 next_swing[slot.index], context, beat, seconds, bpm, joint)
                   for slot in open_slots]
        for slot, (_, x, y, direction, _) in zip(open_slots, _combine(open_slots, options, group)):
            slot.value.update(x=x, y=y, direction=direction)
        for slot in group:
            if _cell_fixed(slot) and slot not in open_slots:
                slot.value["x"], slot.value["y"] = slot.fixed["x"], slot.fixed["y"]
        swung = {}
        for slot in sorted(group, key=lambda s: (s.value["color"], s.value["x"], s.value["y"], s.oid)):
            x, y = slot.value["x"], slot.value["y"]
            sequence.append((x, y, slot.value["color"], slot.value["direction"]))
            used.add(sequence[-1])
            front[(x, y)] = (seconds, slot.index)
            swung.setdefault(slot.value["color"], slot)
        for hand, slot in swung.items():
            hands[hand].swing(slot, beat, seconds, bpm)


class _HandState:
    """One hand's position and flow while pass 2 walks the timeline."""
    __slots__ = ("effective", "seconds", "beat", "direction", "previous", "x", "y", "index")

    def __init__(self):
        self.effective = self.seconds = self.beat = self.direction = self.previous = None
        self.x = self.y = self.index = None

    def reset(self, beat, seconds, bpm):
        return self.seconds is None or is_rest(seconds - self.seconds)

    def merges(self, beat, seconds, direction):
        """True when a cut at ``beat`` joins this hand's last swing (a same-cut chord across a 16th)."""
        return (self.seconds is not None and 0 <= beat - self.beat <= CHORD_BEATS
                and 0 <= seconds - self.seconds <= CHORD_SECONDS and direction == self.direction)

    def swing(self, slot, beat, seconds, bpm):
        direction = slot.value["direction"]
        if not self.merges(beat, seconds, direction):
            self.effective = next_effective(self.effective, direction, self.reset(beat, seconds, bpm))
            self.previous, self.direction = self.direction, direction
            self.seconds, self.beat = seconds, beat
        self.x, self.y, self.index = slot.value["x"], slot.value["y"], slot.index


def _cut_choices(slot, state, ahead, beat, seconds, bpm, joint):
    """(direction, cost) cuts pass 2 may give ``slot``."""
    hand = slot.value["color"]
    if "direction" in slot.fixed or not joint:
        return [(slot.value["direction"], 0.0)]
    gap = None if state.seconds is None else seconds - state.seconds
    reset = state.reset(beat, seconds, bpm)
    choices = dict(_free_cuts(state.effective, hand, gap is not None and gap < FAST_BREAK_SECONDS, reset,
                              state.seconds is None))
    choices.setdefault(slot.value["direction"], 0.3)  # pass 1's cut stays available
    soft = slot.soft.get("direction")
    if soft is not None:
        choices.setdefault(soft, 0.0)
    result = []
    for direction, cost in choices.items():
        if soft is not None and direction != soft:
            cost += SOFT
        if direction == state.previous and not state.merges(beat, seconds, direction):
            cost += 0.2  # the same cut as this hand's swing before last: vary the angle
        if state.effective is not None and gap and not reset and not state.merges(beat, seconds, direction):
            if flow_break(state.effective, direction, hand, gap, False):
                cost += BLOCK
        if ahead is not None and "direction" in ahead.fixed and direction != 8:
            later_gap = ahead.seconds - seconds
            if later_gap > 0 and not is_rest(later_gap) and flow_break(
                    direction, ahead.fixed["direction"], hand, later_gap, False):
                cost += BLOCK  # would break the flow into the hand's next pinned cut
        result.append((direction, cost))
    return result


def _cell_options(slot, occupied, hands, front, fixed_cells, ahead_cell, ahead_swing, context, beat, seconds, bpm,
                  joint):
    """Up to eight (cost, x, y, direction, violations) choices for one open note, cheapest first."""
    hand = slot.value["color"]
    state, other = hands[hand], hands[1 - hand]
    sequence, recent = context["sequence"], context["recent"]
    cuts = _cut_choices(slot, state, ahead_swing, beat, seconds, bpm, joint)
    cells = []
    for x in ([slot.fixed["x"]] if "x" in slot.fixed else range(4)):
        for y in ([slot.fixed["y"]] if "y" in slot.fixed else range(3)):
            if (x, y) in occupied and not _cell_fixed(slot):
                continue
            base, found = 0.0, []
            for field, value in (("x", x), ("y", y)):
                if field in slot.soft and slot.soft[field] != value:
                    base += SOFT
            window = hidden_window(x, y)
            before = front.get((x, y))
            if before is not None and 0 < seconds - before[0] < window:
                base += BLOCK
                found.append(("hidden_note", before[1]))
            later = [t for t in fixed_cells.get((x, y), ()) if t > seconds]
            if later and min(later) - seconds < window and not _cell_fixed(slot):
                base += BLOCK
                found.append(("hidden_note", None))
            gap = None if state.seconds is None else seconds - state.seconds
            if gap is not None and gap > 0 and hypot(x - state.x, y - state.y) / gap > REACH_SPEED:
                base += HARD
                found.append(("reach_proxy", state.index))
            if ahead_cell is not None:
                later_gap = ahead_cell.seconds - seconds
                if later_gap > 0 and hypot(ahead_cell.fixed["x"] - x, ahead_cell.fixed["y"] - y) / later_gap > REACH_SPEED:
                    base += HARD
                    found.append(("reach_proxy", None))
            base += (0.0, 0.8, 2.0)[max(0, x - 1) if hand == 0 else max(0, 2 - x)]  # lanes off the hand's side
            if other.seconds is not None and seconds - other.seconds < 0.6 and (
                    x > other.x if hand == 0 else x < other.x):
                base += 1.5  # crossing the other hand's position
            if x in (1, 2) and y >= 1:
                base += 0.05 if y == 1 else 0.0  # the centre of the middle row sits on the line of sight
            if y == 2:
                # Lift the hands now and then (SM-034 flags maps that almost never use the top row).
                base += -0.1 if context["top_share"] < TOP_ROW_SHARE else 0.08
            if gap is not None and (x, y) == (state.x, state.y) and gap >= FAST_BREAK_SECONDS:
                base += 0.2  # a hand parked on one cell: move it with the music
            for direction, cut_cost in cuts:
                cost = base + cut_cost
                if direction in (2, 3) and y != 1:
                    cost += 0.4
                if gap is not None and gap > 0 and state.direction is not None:
                    _, exit_point = _entry_exit(state.x, state.y, state.direction)
                    entry, _ = _entry_exit(x, y, direction)
                    travel = hypot(entry[0] - exit_point[0], entry[1] - exit_point[1])
                    # Moving a cell or two between swings is easy; longer or faster reaches cost more.
                    effort = (0.05 * min(travel, 1.0) + 0.3 * max(0.0, min(travel, 2.0) - 1.0)
                              + 0.9 * max(0.0, travel - 2.0))
                    cost += effort * min(3.0, max(0.3, 0.35 / gap))
                placement = (x, y, hand, direction)
                repeats = sum(1 for k in CYCLE_LOOKBACK if len(sequence) >= k and sequence[-k] == placement)
                cost += 0.3 * repeats + 0.05 * recent.get(placement, 0)
                cost -= 0.12 if placement not in context["used"] else 0  # a placement the map has not used yet
                cells.append((cost, x, y, direction, found))
    cells.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    return cells[:8]


def _combine(open_slots, options, group):
    """The cheapest joint choice of cell and cut for one time group's open notes."""
    if not open_slots:
        return []
    if len(open_slots) > 4:
        options = [o[:2] for o in options]
    fixed = [s for s in group if _cell_fixed(s) and s not in open_slots]
    best = [None, None]

    def pair_cost(a_slot, a, b_slot, b):
        (ax, ay, ad), (bx, by, bd) = a, b
        if (ax, ay) == (bx, by):
            return BLOCK
        ca, cb = a_slot.value["color"], b_slot.value["color"]
        if ca != cb:
            red, blue = (ax, bx) if ca == 0 else (bx, ax)
            crossed = 0.0 if red < blue else 50.0  # hands crossed on a double
            return crossed + (0.4 if (ad in UP_CUTS) != (bd in UP_CUTS) else 0.0)  # doubles read best parallel
        if ad != bd:
            return 50.0  # one saber cuts a chord in one direction
        if ad == 8:
            return 0.0 if max(abs(ax - bx), abs(ay - by)) == 1 else 5.0
        vx, vy = _VECTORS[ad]
        return 0.0 if (bx - ax, by - ay) in ((vx, vy), (-vx, -vy)) else 5.0  # a chord lies along its cut

    def search(index, chosen, total):
        if best[0] is not None and total >= best[0]:
            return
        if index == len(open_slots):
            best[0], best[1] = total, list(chosen)
            return
        slot = open_slots[index]
        for option in options[index]:
            here = (option[1], option[2], option[3])
            extra = option[0]
            for other_slot, other in zip(open_slots[:index], chosen):
                extra += pair_cost(other_slot, (other[1], other[2], other[3]), slot, here)
            for other_slot in fixed:
                extra += pair_cost(other_slot, (other_slot.fixed["x"], other_slot.fixed["y"],
                                                other_slot.value["direction"]), slot, here)
            search(index + 1, chosen + [option], total + extra)

    search(0, [], 0.0)
    if best[1] is None:  # every cell is taken at this beat
        return [(HARD, s.value.get("x", 0), s.value.get("y", 0), s.value["direction"], [("overlapping_cell", None)])
                for s in open_slots]
    return best[1]


# ---------------------------------------------------------------------------------------------------------
# Rule check, attribution and alternatives
# ---------------------------------------------------------------------------------------------------------

def rule_violations(arrangement: dict) -> list[dict]:
    """The placer's rules broken by a complete arrangement, from the movement model and the held sabers.

    Each entry is ``{"code", "object_ids", "beat", "reason"}`` (the later note last).
    """
    from .arrangement import expanded_notes
    notes = expanded_notes(arrangement)
    if not notes:
        return []
    seconds = _clock(arrangement)
    difficulty = arrangement["difficulty"]
    movement = analyze_movement([{"id": n["id"], "beat": float(n["beat"]), "x": n["x"], "y": n["y"],
                                  "color": n["color"], "direction": n["direction"], "seconds": seconds(n["beat"])}
                                 for n in notes], bpm=float(arrangement["song"]["bpm"]), njs=difficulty["njs"],
                                spawn_offset_beats=difficulty["spawn_offset_beats"])
    found = [{"code": w["code"], "object_ids": list(w["note_ids"]), "beat": w["beat"], "reason": w["reason"]}
             for w in movement["warnings"] if w["code"] in RULE_FIELDS]
    _, held = _holds(arrangement)
    for color, spans in held.items():
        for head, tail, oid, kind in spans:
            for note in notes:
                if note["color"] == color and head < note["beat"] < tail:
                    found.append({"code": f"{kind[:-1]}_note_conflict", "object_ids": [oid, note["id"]],
                                  "beat": float(note["beat"]),
                                  "reason": f"{oid} holds color {color} from beat {float(head):g} to {float(tail):g}"})
    return found


def _attributable(violation, slots_by_id):
    """True when an involved note is being placed (it has a placer-chosen field).

    A rule broken only by fully pinned or locked notes is the agent's explicit choice; validation reports it.
    """
    for oid in violation["object_ids"]:
        slot = slots_by_id.get(oid)
        if slot is not None and not slot.locked and len(slot.pinned) < len(FIELDS):
            return True
    return False


def _free(slot):
    return [f for f in FIELDS if f not in slot.fixed and f not in slot.soft]


def _place(arrangement, *, unpin=False):
    """Place a copy of ``arrangement``; returns (placed copy, report, violations, slots by ID) or None.

    None means the notes are not readable (validation reports why).
    """
    result = copy.deepcopy(arrangement)
    try:
        motifs = _place_motifs(result)
        slots = _collect(result, unpin)
        if slots is None:
            return None
        anchors, held = _holds(result)
        bpm = float(result["song"]["bpm"])
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError):
        return None
    _anchor(slots, anchors)
    by_id = {s.oid: s for s in slots}
    if not any(_free(s) for s in slots):
        # Every value is stored: keep them all unless a stored placer choice now breaks a rule.
        for slot in slots:
            slot.value = {**slot.soft, **slot.fixed}
        trial = copy.deepcopy(result)
        _write(trial, _collect_for(trial, slots))
        violations = rule_violations(trial)
        if not any(_attributable(v, by_id) for v in violations):
            return trial, _report(slots, motifs), violations, by_id
    groups = _groups(slots)
    plan = _plan_cuts(groups, held, bpm)
    outcome = None
    for joint in (True, False):
        # Cuts chosen with their cells follow the hand's path; pass 1's cuts are the verified fallback.
        for slot in slots:
            hand, direction = plan[slot.index]
            slot.value = {"color": slot.fixed.get("color", hand), "direction": slot.fixed.get("direction", direction)}
        _place_cells(groups, slots, bpm, joint)
        trial = copy.deepcopy(result)
        _write(trial, _collect_for(trial, slots))
        violations = rule_violations(trial)
        failures = sum(1 for v in violations if _attributable(v, by_id))
        if outcome is None or failures < outcome[0]:
            outcome = (failures, trial, violations, _report(slots, motifs))
        if not failures:
            break
    return outcome[1], outcome[3], outcome[2], by_id


def _collect_for(copied, slots):
    """``slots`` re-pointed at the matching literal notes of a deep copy of their arrangement."""
    notes = {f'{s["id"]}/note/{n["id"]}': n for s in copied["sections"] for n in s["notes"]}
    moved = []
    for slot in slots:
        clone = copy.copy(slot)
        clone.note = notes.get(slot.oid) if slot.note is not None else None
        moved.append(clone)
    return moved


def _write(arrangement, slots):
    """Store the values on literal notes and list the placer-chosen fields in ``placed``."""
    for slot in slots:
        note = slot.note
        chosen = [f for f in FIELDS if f not in slot.pinned]
        if note is None or not chosen:
            continue  # motif notes are written by _place_motifs; fully pinned notes stay byte for byte
        rest = {k: v for k, v in note.items() if k not in ("id", "beat", "placed", *FIELDS)}
        values = {"id": note["id"], "beat": note["beat"], **{f: slot.value[f] for f in FIELDS},
                  "placed": chosen, **rest}
        note.clear()
        note.update(values)


def _report(slots, motifs):
    literal = [s for s in slots if s.note is not None]
    rechosen = [s.oid for s in literal if any(s.value.get(f) != v for f, v in s.soft.items())]
    return {"notes": len(slots), "placed_notes": sum(1 for s in literal if len(s.pinned) < 4),
            "fully_pinned_notes": sum(1 for s in literal if len(s.pinned) == 4),
            "chosen_fields": sum(4 - len(s.pinned) for s in literal),
            "anchored_fields": sum(len(s.anchored) for s in literal),
            "rechosen": rechosen, "motifs": motifs}


def _place_motifs(arrangement):
    """Place each motif with open fields once, on its own, before its patterns expand; returns motif IDs."""
    placed = []
    for motif_id, notes in sorted(arrangement["motifs"].items()):
        if not isinstance(notes, list) or not any(
                isinstance(n, dict) and ("placed" in n or any(f not in n for f in FIELDS)) for n in notes):
            continue
        beats = [_beat(n["beat"]) for n in notes]
        alone = {"song": arrangement["song"], "difficulty": arrangement["difficulty"], "motifs": {},
                 "sections": [{"id": "motif", "start_beat": 0, "length_beats": max(beats) + 1,
                               "locked": False, "notes": copy.deepcopy(notes), "patterns": []}]}
        done = _place(alone)
        if done is None:
            continue
        notes[:] = done[0]["sections"][0]["notes"]
        placed.append(motif_id)
    return placed


def place_arrangement(arrangement: dict, *, unpin: bool = False, strict: bool = True,
                      alternatives: bool = True) -> dict:
    """Fill every open note field so the movement rules hold; the input is not modified.

    Returns ``{"arrangement", "report", "errors"}``. A fully specified arrangement with no ``placed`` record
    is returned unchanged (the same object). ``unpin`` re-places every unlocked literal note from scratch,
    ignoring its stored values (for comparing a stored map with a fresh placement). When a rule cannot hold,
    ``strict`` raises :class:`PlacementError`; otherwise the best placement comes back with the errors.
    ``alternatives=False`` skips verifying alternatives for the errors (a draft generator's inner loop).
    """
    empty = {"placed_notes": 0, "rechosen": [], "motifs": []}
    if not unpin and not needs_placement(arrangement):
        return {"arrangement": arrangement, "report": empty, "errors": []}
    done = _place(arrangement, unpin=unpin)
    if done is None:
        return {"arrangement": arrangement, "report": {**empty, "skipped": "unreadable notes; see validation"},
                "errors": []}
    result, report, violations, by_id = done
    errors = [v for v in violations if _attributable(v, by_id)]
    errors = _describe(arrangement, errors, by_id, unpin, alternatives) if errors else []
    if errors and strict:
        raise PlacementError(errors)
    return {"arrangement": result, "report": report, "errors": errors}


def pin_edits(stored: dict, edited: dict) -> dict:
    """A copy of ``edited`` where every placer-chosen value the agent changed since ``stored`` is pinned.

    A field the stored note listed in ``placed`` whose value now differs leaves ``placed``: the agent chose it,
    so placement keeps it. A field that was pinned before and is now listed in ``placed`` stays open: the
    agent handed it to the placer.
    """
    result = copy.deepcopy(edited)
    try:
        before = {(s["id"], n["id"]): n for s in stored["sections"] for n in s["notes"]}
        before.update({("motif", m, n["id"]): n for m, notes in stored["motifs"].items() for n in notes})
        current = [((s["id"], n["id"]), n) for s in result["sections"] for n in s["notes"]]
        current += [(("motif", m, n["id"]), n) for m, notes in result["motifs"].items() for n in notes]
    except (KeyError, TypeError, AttributeError):
        return result
    for key, note in current:
        old = before.get(key)
        if not isinstance(note, dict) or not isinstance(old, dict) or not isinstance(note.get("placed"), list):
            continue
        changed = [f for f in note["placed"] if f in note and f in old and note[f] != old[f]
                   and f in (old.get("placed") or ())]
        if changed:
            note["placed"] = [f for f in note["placed"] if f not in changed]
            if not note["placed"]:
                del note["placed"]
    return result


def _describe(arrangement, violations, by_id, unpin, alternatives=True):
    """Structured infeasibility errors; the first few carry alternatives verified by placing them."""
    errors = []
    for number, violation in enumerate(violations):
        slots = [by_id[oid] for oid in violation["object_ids"] if oid in by_id]
        later = slots[-1] if slots else None
        record = {"code": "placement_infeasible", "rule": violation["code"], "severity": "error",
                  "beat": round(float(later.beat if later else violation["beat"]), 4),
                  "seconds": round(later.seconds, 3) if later else None,
                  "object_ids": violation["object_ids"],
                  "pinned": {s.oid: sorted(s.pinned, key=FIELDS.index) for s in slots},
                  "reason": violation["reason"]}
        record["alternatives"] = (_alternatives(arrangement, violation, slots, unpin)
                                  if alternatives and number < MAX_ALTERNATIVE_ERRORS else [])
        options = "; ".join(_say(a) for a in record["alternatives"]) or "none verified; see project check"
        record["message"] = (f'beat {record["beat"]:g}: {", ".join(violation["object_ids"])} cannot be placed '
                             f'without {violation["code"]} ({violation["reason"]}). Feasible alternatives: {options}')
        errors.append(record)
    return errors


def _say(alternative):
    if alternative["op"] == "remove":
        return f'remove {alternative["object_id"]}'
    chosen = ", ".join(f"{k} {v}" for k, v in alternative["placer_choice"].items())
    return f'unpin {"/".join(alternative["fields"])} of {alternative["object_id"]} (placer picks {chosen})'


def _edit(arrangement, oid, fields=None):
    """A copy with ``fields`` removed from literal note ``oid`` (the note itself when ``fields`` is None)."""
    trial = copy.deepcopy(arrangement)
    sid, _, nid = oid.split("/", 2)
    section = next(s for s in trial["sections"] if s["id"] == sid)
    note = next(n for n in section["notes"] if n["id"] == nid)
    if fields is None:
        section["notes"].remove(note)
    else:
        for field in fields:
            note.pop(field, None)
        if "placed" in note:
            note["placed"] = [f for f in note["placed"] if f not in fields]
    return trial


def _alternatives(arrangement, violation, slots, unpin):
    """Edits verified to let placement clear ``violation``: unpin a field of an involved note, or drop a note."""
    trials = []
    literal = [s for s in reversed(slots) if s.note is not None and not s.locked]
    for slot in literal:
        pins = sorted(slot.pinned, key=FIELDS.index)
        relevant = [f for f in FIELDS if f in slot.pinned and f in RULE_FIELDS.get(violation["code"], FIELDS)]
        sets = [[f] for f in relevant] + [relevant, pins]
        if violation["code"] in ("hidden_note", "reach_proxy"):
            sets = [relevant] + sets  # a cell moves as a pair of coordinates
        for fields in sets:
            if fields and fields not in [t[0].get("fields") for t in trials if t[0]["object_id"] == slot.oid]:
                trials.append(({"op": "unpin", "object_id": slot.oid, "fields": fields},
                               _edit(arrangement, slot.oid, fields)))
    for slot in literal:
        if slot.anchor is None:  # an arc or chain end keeps its note
            trials.append(({"op": "remove", "object_id": slot.oid}, _edit(arrangement, slot.oid)))
    found = []
    involved = set(violation["object_ids"])
    for alternative, trial in trials:
        done = _place(trial, unpin=unpin)
        if done is None:
            continue
        result, _, violations, by_id = done
        if any(_attributable(v, by_id) and involved & set(v["object_ids"]) for v in violations):
            continue
        if alternative["op"] == "unpin":
            sid, _, nid = alternative["object_id"].split("/", 2)
            note = next(n for s in result["sections"] if s["id"] == sid for n in s["notes"] if n["id"] == nid)
            alternative["placer_choice"] = {f: note[f] for f in alternative["fields"]}
        found.append(alternative)
    return found
