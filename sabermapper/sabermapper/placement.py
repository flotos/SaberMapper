"""Correct-by-construction placement: the agent authors rhythm, the placer chooses hand, cut and cell.

A note needs only ``id`` and ``beat``. ``color`` (hand), ``direction`` (cut) and ``x``/``y`` (cell) are
optional **pins**: a field the agent writes is never changed. The placer fills every missing field so the
blocking movement rules hold by construction:

* swing flow (``movement.flow_break``: ``fast_direction_break``, ``flow_parity_break``);
* wrist roll (``movement.next_roll``: ``wrist_roll``): angled cuts that keep turning the same way off each
  reversal faster than the wrist unwinds; a cut that turns back towards the reversal is cheaper
  (``ROLL_COST``), and repeating the cut of the swing before last costs nothing when it unwinds the wrist, so
  an angular style plays as a zig-zag about the reversal, never a spin round the clock;
* held sabers: an arc or chain reserves its color from head to tail (``arc_note_conflict``,
  ``chain_note_conflict``), and its head and tail notes take the arc's hand, cut and cell;
* ``one_hand_burst`` (three fast same-hand swings while the other hand idles);
* ``hidden_note`` (a note arriving too soon behind another in its cell), reach (``movement.REACH_SPEED``)
  and hand crossing;
* ``cut_path_blocked``: no cut sweeps through a note of the other color at the same instant
  (``movement.cut_path``).

Notes marked ``"stack": true`` at one beat form a stack: one hand cuts all of them in one direction, and
their cells run in an unbroken line along that cut (``movement.stack_line``, ``stack_shape``), so the stack reads
as one longer note; a stack of three runs vertically or diagonally, never sideways. A diagonal cut is preferred
when the flow allows it. The other hand's note at that instant keeps a free cell away from the stack
(``stack_touch``); a later note stays out of the stack's cells for ``movement.STACK_HIDDEN_SECONDS``; and when
notes follow within STACK_SIDE_SECONDS the stack keeps to the outer lanes.

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

A recurring part of the song is played as a recurring pattern. The arrangement's ``themes`` pair a statement
span with echo spans (:mod:`recurrence`); after a first placement, an open echo note whose time matches a
statement note (a single on a single, a double on a double, a stack on a stack) prefers that note's hand, cut and cell (mirrored
when the echo is), and the statement keeps its own. The preference (``ECHO``) outweighs comfort and novelty
but yields to every movement rule and to stored values, so an echo deviates only where the flow into or out
of it, or its own audio, differs.

The map's ``style`` (:mod:`style`) tunes the comfort costs, never a rule: ``flow`` weighs how far a cut may turn
from a clean reversal, how much a repeated angle costs and how much hand travel costs; ``diagonals`` makes diagonal
cuts cheaper or dearer; ``top_row`` sets the top-row share the placer lifts the hands towards. Without a style
(every setting at its middle value) the costs are the defaults.
"""

from __future__ import annotations

import copy
from collections import Counter
from fractions import Fraction
from math import hypot
from typing import NamedTuple

from .movement import (BURST_SECONDS, BURST_SWINGS, CHORD_BEATS, CHORD_SECONDS, FAST_BREAK_SECONDS, REACH_SPEED,
                       STACK_HIDDEN_SECONDS, STACK_MAX_NOTES, _OPPOSITE, _VECTORS, _parity, analyze_movement,
                       ROLL_LIMIT_DEGREES, cut_path, flow_break, hidden_window, is_rest, next_effective, next_roll,
                       turn_degrees)
from .validation import _beat

FIELDS = ("x", "y", "color", "direction")
RANGES = {"x": range(4), "y": range(3), "color": range(2), "direction": range(9)}
# (beam width, states kept per hand-timing history): one hand assignment cannot crowd out the rest. The wider
# beam runs only when the first leaves a rule broken, for example a long phrase whose cuts must meet a pinned arc.
BEAMS = ((24, 4), (160, 32))
BLOCK = 1e10  # breaking a rule that blocks save (flow, held sabers, hidden notes)
HARD = 1e9  # breaking a review rule the placer also keeps (one_hand_burst, reach)
SOFT = 1e6  # re-choosing a value an earlier placement stored in ``placed``
LANES = {0: (0, 1), 1: (2, 3)}
FIRST_CUTS = (1, 6, 7, 0, 4, 5)  # a hand's first swing: down cuts first
CYCLE_LOOKBACK = range(2, 17)  # the strict-cycle lags SM-034 measures (critique.CYCLE_RANGE)
VARIETY_WINDOW = 48
TOP_ROW_SHARE = 0.15  # below this recent top-row share, the top row is preferred
# A double reads as one accent only when both hands cut it on the same forehand/backhand: the beam then hands
# the last single note before it to whichever hand leaves both hands on that parity.
DOUBLE_PARITY_COST = 3.0
# An echo note leaving its statement note's hand, cut or cell (half per coordinate): above every comfort cost,
# far below the rules.
ECHO = 4.0
# One hand taking a double (unmarked notes at one instant): above every comfort and echo cost, below a stored value.
DOUBLE_SPLIT = 100.0
ECHO_RETRIES = 4  # echoed placements tried, each releasing the echoes around the rules the last one broke
ECHO_RELEASE_SECONDS = 2.0  # a hand's flow resets after a 2 s rest, so a broken rule reaches no further
# Rules the placer satisfies; each maps to the note fields that can resolve it.
RULE_FIELDS = {"fast_direction_break": ("direction", "color"), "flow_parity_break": ("direction", "color"),
               "wrist_roll": ("direction", "color"),
               "one_hand_burst": ("color",), "arc_note_conflict": ("color",), "chain_note_conflict": ("color",),
               "hidden_note": ("x", "y"), "reach_proxy": ("x", "y"),
               "stack_shape": ("x", "y", "direction"), "stack_touch": ("x", "y"),
               "simultaneous_direction_conflict": ("direction", "color"),
               "cut_path_blocked": ("x", "y", "direction")}
MAX_ALTERNATIVE_ERRORS = 5
STACK_OPTIONS = 36  # cell and cut choices kept per stack note, so a full line along the cut stays reachable
STACK_DIAGONAL_PREFERENCE = 0.3  # stacks lie on a diagonal cut when the flow allows one
SIDEWAYS = (2, 3, 8)  # cuts a stack of three never takes: it runs vertically or diagonally
# When the next notes follow a stack this soon, the stack keeps to the outer lanes, off the centre where they
# would sit behind it.
STACK_SIDE_SECONDS = 0.5
STACK_CENTRE_COST = 2.0  # above the travel cost of reaching the outer lane
# Comfort cost of a hand's wrist roll after a cut, per ROLL_LIMIT_DEGREES: of two equally angled cuts, the one
# turning back towards the reversal wins.
ROLL_COST = 0.3


class PlacementStyle(NamedTuple):
    """The comfort costs a map's ``style`` tunes (see the module docstring)."""
    turn_scale: float = 1.0  # weight of a cut's turn away from its preferred turn
    turn_target: float = 0.0  # the preferred turn from a clean reversal, in degrees
    repeat_angle: float = 0.2  # a hand repeating the cut of its swing before last
    travel_scale: float = 1.0  # weight of hand travel between swings
    diagonal_cost: float = 0.0  # added to each diagonal cut
    top_row_share: float = TOP_ROW_SHARE  # below this recent top-row share, the top row is preferred
    top_row_lift: float = -0.1  # a top-row cell while the recent share is below the target
    top_row_rest: float = 0.08  # a top-row cell while the recent share has reached it


DEFAULT_STYLE = PlacementStyle()
FLOW_COSTS = {"round": {"turn_scale": 1.8, "repeat_angle": 0.1, "travel_scale": 1.4},
              "balanced": {},
              "angular": {"turn_target": 45.0, "repeat_angle": 0.4, "travel_scale": 0.7}}
DIAGONAL_COSTS = {"few": 0.15, "some": 0.0, "many": -0.12}
TOP_ROW_COSTS = {"low": {"top_row_share": 0.08, "top_row_rest": 0.3},
                 "normal": {},
                 "high": {"top_row_share": 0.25, "top_row_lift": -0.2}}


def placement_style(arrangement: dict) -> PlacementStyle:
    """The placement costs for ``arrangement["style"]["settings"]``; unknown or missing settings stay default."""
    style = arrangement.get("style") if isinstance(arrangement, dict) else None
    settings = style.get("settings") if isinstance(style, dict) else None
    if not isinstance(settings, dict):
        return DEFAULT_STYLE
    values = dict(FLOW_COSTS.get(settings.get("flow"), {}))
    if settings.get("diagonals") in DIAGONAL_COSTS:
        values["diagonal_cost"] = DIAGONAL_COSTS[settings["diagonals"]]
    values.update(TOP_ROW_COSTS.get(settings.get("top_row"), {}))
    return PlacementStyle(**values)


class PlacementError(ValueError):
    """Rhythm the movement rules cannot place; ``errors`` holds one structured record per conflict."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("Placement is infeasible: " + "; ".join(e["message"] for e in errors[:5])
                         + (f"; and {len(errors) - 5} more" if len(errors) > 5 else ""))


class _Slot:
    __slots__ = ("index", "oid", "beat", "seconds", "fixed", "soft", "pinned", "note", "locked", "value",
                 "anchored", "motif", "anchor", "held_cut", "stack", "echo", "themed")

    def __init__(self, oid, beat, fixed, soft, pinned, note, locked, motif=None, stack=False):
        self.oid, self.beat, self.fixed, self.soft, self.pinned = oid, beat, fixed, soft, pinned
        self.note, self.locked, self.motif, self.stack = note, locked, motif, stack
        self.value, self.anchored, self.index, self.seconds, self.anchor = {}, set(), 0, 0.0, None
        self.held_cut = None  # a cut pass 1 settled that pass 2 keeps (a double's parity)
        self.echo = None  # the statement note's values a theme echo prefers
        self.themed = False  # inside a theme echo span

    def echoes(self, field, hand=None):
        """The theme value this slot prefers for an open ``field`` (None when it has none).

        A cut or cell is only echoed on the statement note's hand: on the other hand it would mean nothing.
        """
        if self.echo is None or field in self.fixed or field in self.soft:
            return None
        if hand is not None and self.echo["color"] != hand:
            return None
        return self.echo[field]

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
                               fixed, soft, pinned, note, locked, stack=note.get("stack") is True))
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
                                   values, {}, set(FIELDS) - chosen, None, locked, motif=pattern["motif"],
                                   stack=note.get("stack") is True))
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


def _free_cuts(effective, hand, fast, reset, first, style=None):
    """(direction, cost) candidates for an unpinned swing, most natural first."""
    style = style or DEFAULT_STYLE
    key = (effective, hand, fast, reset, first, style)
    if key in _OPTIONS_CACHE:
        return _OPTIONS_CACHE[key]
    diagonal = lambda direction: style.diagonal_cost if direction in (4, 5, 6, 7) else 0.0
    if effective is None:
        order = FIRST_CUTS if first else (1, 0, 6, 7, 4, 5)
        result = sorted(((d, 0.12 * rank + diagonal(d)) for rank, d in enumerate(order[:4])), key=lambda c: c[1])
    else:
        reverse = _OPPOSITE[effective]
        gap = 0.1 if fast else 0.5
        # A fast swing reads best as a clean reversal; a slower one may angle off it.
        weight = (0.3 if fast else (0.08 if reset else 0.15)) * style.turn_scale
        found = []
        for direction in range(8):
            if not reset and flow_break(effective, direction, hand, gap, False):
                continue
            turn = abs(turn_degrees(reverse, direction) - style.turn_target)
            cost = weight * turn / 45 + (0.04 if direction in (2, 3) else 0) + diagonal(direction)
            found.append((cost, direction))
        found.sort()
        result = [(d, c) for c, d in found[:5]]
    _OPTIONS_CACHE[key] = result
    return result


def _roll_cost(style, repeated, roll_before, roll_after):
    """Comfort cost of a cut leaving the wrist at ``roll_after``; a repeat of the swing before last costs
    ``repeat_angle`` unless it unwinds the wrist (a zig-zag about the reversal returns to it)."""
    cost = ROLL_COST * abs(roll_after) / ROLL_LIMIT_DEGREES
    if repeated and abs(roll_after) >= abs(roll_before or 0.0):
        cost += (style or DEFAULT_STYLE).repeat_angle  # the same cut as this hand's swing before last
    return cost


def _cut_options(state, notes, hand, beat, seconds, other_last, bpm, style=None, quick=False):
    """(direction, cost, violations, new hand state) for ``hand`` cutting ``notes`` at ``beat``."""
    effective, last_s, last_b, last_dir, run_len, run_start, prev_dir, roll = state
    fixed = sorted({s.fixed["direction"] for s in notes if "direction" in s.fixed})
    soft = sorted({s.soft["direction"] for s in notes if "direction" in s.soft})
    gap = None if last_s is None else seconds - last_s
    beat_gap = None if last_b is None else beat - last_b
    reset = last_s is None or is_rest(gap)
    ids = tuple(s.index for s in notes)
    echo = next((e for e in (s.echoes("direction", hand) for s in notes) if e is not None), None)
    if fixed:
        candidates = [(fixed[-1], 0.0)]
    else:
        candidates = [(d, c + (SOFT if soft and d != soft[0] else 0) + (ECHO if echo is not None and d != echo else 0))
                      for d, c in _free_cuts(effective, hand, gap is not None and gap < FAST_BREAK_SECONDS,
                                             reset, last_s is None, style)]
        if soft and all(d != soft[0] for d, _ in candidates):
            candidates.append((soft[0], 0.0))
        if not soft and echo is not None and all(d != echo for d, _ in candidates):
            candidates.append((echo, 0.0))
    options = []
    for direction, cost in candidates:
        merges = (last_s is not None and 0 <= beat_gap <= CHORD_BEATS and 0 <= gap <= CHORD_SECONDS
                  and direction == last_dir)
        roll_after, rolled = next_roll(roll, effective, direction, gap or 0.0, reset or not gap)
        if not fixed and not merges:
            cost += _roll_cost(style, direction == prev_dir, roll, roll_after)
        violations = ()
        if len(fixed) > 1 and any("color" not in s.pinned for s in notes):
            cost += HARD
            violations += (("simultaneous_direction_conflict", ids),)
        stacked = sum(1 for s in notes if s.stack)
        if direction in SIDEWAYS and stacked >= STACK_MAX_NOTES:
            cost += HARD  # a stack of three runs vertically or diagonally, never across a row
        if quick and stacked >= 2 and direction not in (0, 1, 8):
            # Notes follow fast: a stack spanning columns would reach the centre, where they sit behind it.
            # A vertical cut keeps it in the outer lane (pass 2 prices the cells the same way).
            cost += STACK_CENTRE_COST * (stacked - 1)
        if merges:
            options.append((direction, cost, violations, state))  # one swing with the note just before
            continue
        if effective is not None and gap and not reset:
            found = flow_break(effective, direction, hand, gap, False) or rolled
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
                         last_dir, round(roll_after, 1))))
    return options


def _assignments(group, busy):
    """(colors per slot, cost, violations) hand assignments for one time group."""
    choices = []
    for slot in group:
        if "color" in slot.fixed:
            choices.append([(slot.fixed["color"], 0.0)])
        elif "color" in slot.soft:
            choices.append([(slot.soft["color"], 0.0), (1 - slot.soft["color"], SOFT)])
        elif slot.echo is not None:
            choices.append([(slot.echo["color"], 0.0), (1 - slot.echo["color"], ECHO)])
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
        if len({c for slot, c in zip(group, colors) if slot.stack}) > 1:
            cost += BLOCK  # a stack split across both hands (validation names pinned ones)
        if (len(group) > 1 and len(set(colors)) == 1 and any("color" not in s.fixed for s in group)
                and not all(s.stack for s in group)):
            # A same-hand chord where a double would do; inside an echo the neighbours' echoed hands never
            # outweigh this occurrence's own two-hand accent. Unmarked notes at one instant are a double the
            # draft chose for both hands: one hand takes them only when the other cannot (a stack is marked).
            instant = len({s.beat for s in group}) == 1
            cost += DOUBLE_SPLIT if instant else 2.0 + (ECHO if any(s.themed for s in group) else 0.0)
        result.append((colors, cost, violations))
    return result


def _plan_cuts(groups, held, bpm, width=BEAMS[0][0], per_timing_limit=BEAMS[0][1], style=None):
    """Beam search for every swing's hand and cut; returns ({slot index: (color, direction)}, violations)."""
    empty = (None, None, None, None, 0, None, None, None)
    beam = [(0.0, (empty, empty), None, None, None)]  # cost, hand states, last single hand, last beat, node
    for number, group in enumerate(groups):
        beat, seconds = float(group[0].beat), group[0].seconds
        busy = _held_colors(held, group[0].beat)
        quick = number + 1 < len(groups) and groups[number + 1][0].seconds - seconds < STACK_SIDE_SECONDS
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
                                     _cut_options(hands[hand], by_hand[hand], hand, beat, seconds, other, bpm,
                                                  style, quick)])
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
                    if len(parts) == 2 and _parity(parts[0][1], parts[0][0], 0) != _parity(parts[1][1], parts[1][0], 0):
                        total += DOUBLE_PARITY_COST
                    new_hands = tuple(new_hands)
                    single = used[0] if len(used) == 1 else None
                    signature = (new_hands, single)
                    if signature not in candidates or candidates[signature][0] > total:
                        candidates[signature] = (total, new_hands, single, beat,
                                                 (node, tuple(decisions), violations))
        beam, per_timing = [], Counter()
        for candidate in sorted(candidates.values(), key=lambda c: c[0]):
            timing = tuple((h[1], h[4]) for h in candidate[1])
            if per_timing[timing] < per_timing_limit:
                per_timing[timing] += 1
                beam.append(candidate)
                if len(beam) == width:
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


def _cut_fixed(slot):
    """The cut pass 2 may not change: pinned, anchored, or settled by pass 1 for a double."""
    return slot.fixed.get("direction", slot.held_cut)


def _place_cells(groups, slots, bpm, joint=True, style=None):
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
    front = {}  # cell -> (seconds, slot index, part of a stack) of the latest note there
    sequence, used = [], set()
    for number, group in enumerate(groups):
        beat, seconds = group[0].beat, group[0].seconds
        occupied = {(s.fixed["x"], s.fixed["y"]) for s in group if _cell_fixed(s)}
        open_slots = sorted((s for s in group if not _cell_fixed(s) or (joint and _cut_fixed(s) is None)),
                            key=lambda s: (s.value["color"], s.oid))
        context = {"recent": Counter(sequence[-VARIETY_WINDOW:]), "sequence": sequence, "used": used,
                   "style": style or DEFAULT_STYLE,
                   "top_share": sum(1 for p in sequence[-VARIETY_WINDOW:] if p[1] == 2)
                   / max(1, min(len(sequence), VARIETY_WINDOW)),
                   "tall": Counter(s.value["color"] for s in group if s.stack),
                   "next_gap": groups[number + 1][0].seconds - seconds if number + 1 < len(groups) else None}
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
            front[(x, y)] = (seconds, slot.index, slot.stack)
            swung.setdefault(slot.value["color"], slot)
        for hand, slot in swung.items():
            hands[hand].swing(slot, beat, seconds, bpm)


class _HandState:
    """One hand's position and flow while pass 2 walks the timeline."""
    __slots__ = ("effective", "seconds", "beat", "direction", "previous", "x", "y", "index", "roll")

    def __init__(self):
        self.effective = self.seconds = self.beat = self.direction = self.previous = self.roll = None
        self.x = self.y = self.index = None

    def reset(self, beat, seconds, bpm):
        return self.seconds is None or is_rest(seconds - self.seconds)

    def merges(self, beat, seconds, direction):
        """True when a cut at ``beat`` joins this hand's last swing (a same-cut chord across a 16th)."""
        return (self.seconds is not None and 0 <= beat - self.beat <= CHORD_BEATS
                and 0 <= seconds - self.seconds <= CHORD_SECONDS and direction == self.direction)

    def roll_after(self, beat, seconds, bpm, direction):
        """(roll, finding) of ``movement.next_roll`` for a new swing cutting ``direction``."""
        gap = None if self.seconds is None else seconds - self.seconds
        return next_roll(self.roll, self.effective, direction, gap or 0.0, self.reset(beat, seconds, bpm) or not gap)

    def swing(self, slot, beat, seconds, bpm):
        direction = slot.value["direction"]
        if not self.merges(beat, seconds, direction):
            self.roll = self.roll_after(beat, seconds, bpm, direction)[0]
            self.effective = next_effective(self.effective, direction, self.reset(beat, seconds, bpm))
            self.previous, self.direction = self.direction, direction
            self.seconds, self.beat = seconds, beat
        self.x, self.y, self.index = slot.value["x"], slot.value["y"], slot.index


def _cut_choices(slot, state, ahead, beat, seconds, bpm, joint, style=None):
    """(direction, cost) cuts pass 2 may give ``slot``."""
    hand = slot.value["color"]
    if _cut_fixed(slot) is not None or not joint:
        return [(slot.value["direction"], 0.0)]
    gap = None if state.seconds is None else seconds - state.seconds
    reset = state.reset(beat, seconds, bpm)
    choices = dict(_free_cuts(state.effective, hand, gap is not None and gap < FAST_BREAK_SECONDS, reset,
                              state.seconds is None, style))
    choices.setdefault(slot.value["direction"], 0.3)  # pass 1's cut stays available
    soft = slot.soft.get("direction")
    if soft is not None:
        choices.setdefault(soft, 0.0)
    echo = slot.echoes("direction", hand)
    if echo is not None:
        choices.setdefault(echo, 0.0)
    result = []
    for direction, cost in choices.items():
        if soft is not None and direction != soft:
            cost += SOFT
        if echo is not None and direction != echo:
            cost += ECHO
        merged = state.merges(beat, seconds, direction)
        if not merged:
            roll_after, rolled = state.roll_after(beat, seconds, bpm, direction)
            cost += _roll_cost(style, direction == state.previous, state.roll, roll_after)
        if state.effective is not None and gap and not reset and not merged:
            if flow_break(state.effective, direction, hand, gap, False) or rolled:
                cost += BLOCK
        if ahead is not None and _cut_fixed(ahead) is not None and direction != 8:
            later_gap = ahead.seconds - seconds
            if later_gap > 0 and not is_rest(later_gap) and flow_break(
                    direction, _cut_fixed(ahead), hand, later_gap, False):
                cost += BLOCK  # would break the flow into the hand's next pinned cut
        result.append((direction, cost))
    return result


def _cell_options(slot, occupied, hands, front, fixed_cells, ahead_cell, ahead_swing, context, beat, seconds, bpm,
                  joint):
    """Up to eight (cost, x, y, direction, violations) choices for one open note, cheapest first."""
    hand = slot.value["color"]
    state, other = hands[hand], hands[1 - hand]
    sequence, recent = context["sequence"], context["recent"]
    style = context.get("style") or DEFAULT_STYLE
    cuts = _cut_choices(slot, state, ahead_swing, beat, seconds, bpm, joint, style)
    cells = []
    for x in ([slot.fixed["x"]] if "x" in slot.fixed else range(4)):
        for y in ([slot.fixed["y"]] if "y" in slot.fixed else range(3)):
            if (x, y) in occupied and not _cell_fixed(slot):
                continue
            base, found = 0.0, []
            for field, value in (("x", x), ("y", y)):
                if field in slot.soft and slot.soft[field] != value:
                    base += SOFT
                if slot.echoes(field, hand) not in (None, value):
                    base += ECHO / 2
            before = front.get((x, y))
            if before is not None and 0 < seconds - before[0] < hidden_window(x, y, before[2]):
                base += BLOCK
                found.append(("hidden_note", before[1]))
            later = [t for t in fixed_cells.get((x, y), ()) if t > seconds]
            if later and min(later) - seconds < hidden_window(x, y, slot.stack) and not _cell_fixed(slot):
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
            if (slot.stack and x in (1, 2) and context["next_gap"] is not None
                    and context["next_gap"] < STACK_SIDE_SECONDS):
                base += STACK_CENTRE_COST  # quick notes follow: the stack keeps to the side, out of their way
            if other.seconds is not None and seconds - other.seconds < 0.6 and (
                    x > other.x if hand == 0 else x < other.x):
                base += 1.5  # crossing the other hand's position
            if x in (1, 2) and y >= 1:
                base += 0.05 if y == 1 else 0.0  # the centre of the middle row sits on the line of sight
            if y == 2:
                # Lift the hands now and then (SM-034 flags maps that almost never use the top row).
                base += style.top_row_lift if context["top_share"] < style.top_row_share else style.top_row_rest
            if gap is not None and (x, y) == (state.x, state.y) and gap >= FAST_BREAK_SECONDS:
                base += 0.2  # a hand parked on one cell: move it with the music
            for direction, cut_cost in cuts:
                cost = base + cut_cost
                if direction in (2, 3) and y != 1:
                    cost += 0.4
                if slot.stack and direction in (4, 5, 6, 7):
                    cost -= STACK_DIAGONAL_PREFERENCE
                if slot.stack and direction in SIDEWAYS and context["tall"][hand] >= STACK_MAX_NOTES:
                    cost += HARD
                if gap is not None and gap > 0 and state.direction is not None:
                    _, exit_point = _entry_exit(state.x, state.y, state.direction)
                    entry, _ = _entry_exit(x, y, direction)
                    travel = hypot(entry[0] - exit_point[0], entry[1] - exit_point[1])
                    # Moving a cell or two between swings is easy; longer or faster reaches cost more.
                    effort = (0.05 * min(travel, 1.0) + 0.3 * max(0.0, min(travel, 2.0) - 1.0)
                              + 0.9 * max(0.0, travel - 2.0))
                    cost += effort * min(3.0, max(0.3, 0.35 / gap)) * style.travel_scale
                placement = (x, y, hand, direction)
                repeats = sum(1 for k in CYCLE_LOOKBACK if len(sequence) >= k and sequence[-k] == placement)
                cost += 0.3 * repeats + 0.05 * recent.get(placement, 0)
                if slot.echo is None and placement not in context["used"]:
                    cost -= 0.12  # a placement the map has not used yet (an echo repeats one on purpose)
                cells.append((cost, x, y, direction, found))
    cells.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    return cells[:STACK_OPTIONS if slot.stack else 8]


def _combine(open_slots, options, group):
    """The cheapest joint choice of cell and cut for one time group's open notes."""
    if not open_slots:
        return []
    if len(open_slots) > 4:
        options = [o[:2] for o in options]
    fixed = [s for s in group if _cell_fixed(s) and s not in open_slots]
    tall = Counter(s.value["color"] for s in group if s.stack)  # notes in each hand's stack
    at_once = Counter((s.value["color"], s.beat) for s in group)  # each hand's notes at one instant
    best = [None, None]

    def pair_cost(a_slot, a, b_slot, b):
        (ax, ay, ad), (bx, by, bd) = a, b
        if (ax, ay) == (bx, by):
            return BLOCK
        ca, cb = a_slot.value["color"], b_slot.value["color"]
        if ca != cb:
            if (bx, by) in cut_path(ax, ay, ad) or (ax, ay) in cut_path(bx, by, bd):
                return BLOCK  # one hand's cut would sweep through the other color's note
            stacked = a_slot.stack and tall[ca] >= 2 or b_slot.stack and tall[cb] >= 2
            if stacked and max(abs(ax - bx), abs(ay - by)) <= 1:
                return HARD  # the other hand's note touches a stack: keep a free cell between them
            red, blue = (ax, bx) if ca == 0 else (bx, ax)
            crossed = 0.0 if red < blue else 50.0  # hands crossed on a double
            return crossed + (DOUBLE_PARITY_COST if _parity(ad, ca, 0) != _parity(bd, cb, 0) else 0.0)
        stack = a_slot.stack and b_slot.stack
        # Same-hand notes at one instant are cut as one stack whether or not the draft marked them: they keep
        # the movement model's stack rules (one cut, one unbroken line), even when a stored cell or cut moves.
        together = a_slot.beat == b_slot.beat
        if ad != bd:
            return BLOCK if stack else HARD if together else 50.0  # one saber cuts a chord in one direction
        # A chord lies along its cut, its notes next to each other; a stack must, even if a stored cell or cut
        # moves for it (the third note of a stack of three fills the gap two cells apart).
        off = HARD if stack or together else 5.0
        size = tall[ca] if stack else at_once[(ca, a_slot.beat)] if together else 3
        gap = 1.0 if size >= 3 else off  # two cells apart: only a third note fills the gap
        dx, dy = bx - ax, by - ay
        if ad == 8:
            return 0.0 if max(abs(dx), abs(dy)) == 1 else (gap if max(abs(dx), abs(dy)) == 2
                                                         and dx % 2 == 0 and dy % 2 == 0 else off)
        vx, vy = _VECTORS[ad]
        if (dx, dy) in ((vx, vy), (-vx, -vy)):
            return 0.0
        return gap if (dx, dy) in ((2 * vx, 2 * vy), (-2 * vx, -2 * vy)) else off

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

def _movement_warnings(arrangement, notes):
    seconds = _clock(arrangement)
    difficulty = arrangement["difficulty"]
    return analyze_movement([{"id": n["id"], "beat": float(n["beat"]), "x": n["x"], "y": n["y"],
                              "color": n["color"], "direction": n["direction"], "seconds": seconds(n["beat"])}
                             for n in notes], bpm=float(arrangement["song"]["bpm"]), njs=difficulty["njs"],
                            spawn_offset_beats=difficulty["spawn_offset_beats"])["warnings"]


def _stack_breaks(arrangement):
    """Stacks that do not read as one longer note (``stack_shape``), which the placer lines up but does not block."""
    from .arrangement import expanded_notes
    notes = expanded_notes(arrangement)
    return sum(1 for w in _movement_warnings(arrangement, notes) if w["code"] == "stack_shape") if notes else 0


def rule_violations(arrangement: dict) -> list[dict]:
    """The placer's rules broken by a complete arrangement, from the movement model and the held sabers.

    Each entry is ``{"code", "object_ids", "beat", "reason"}`` (the later note last).
    """
    from .arrangement import expanded_notes
    notes = expanded_notes(arrangement)
    if not notes:
        return []
    found = [{"code": w["code"], "object_ids": list(w["note_ids"]), "beat": w["beat"], "reason": w["reason"]}
             for w in _movement_warnings(arrangement, notes) if w["code"] in RULE_FIELDS]
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


def _place(arrangement, *, unpin=False, beams=BEAMS):
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
    style = placement_style(result)
    outcome = _search(result, slots, groups, held, bpm, beams, by_id, motifs, style=style)
    links = _echo_links(result, slots)
    if links:
        # Place again with every echo preferring its statement's first placement; a theme never costs a rule.
        # Where the echoed placement breaks one, the notes around it give up their echo and the rest keep it.
        _set_echoes(links, outcome[1])
        for _ in range(ECHO_RETRIES):
            echoed = _search(result, slots, groups, held, bpm, beams, by_id, motifs, prefer=_echo_agreement,
                             style=style)
            if echoed[0] <= outcome[0]:
                outcome = echoed
                break
            broken = [by_id[oid].seconds for v in echoed[2] if _attributable(v, by_id)
                      for oid in v["object_ids"] if oid in by_id]
            near = [s for s in slots if s.echo is not None and any(abs(s.seconds - t) <= ECHO_RELEASE_SECONDS
                                                                  for t in broken)]
            if not near:
                break
            for slot in near:
                slot.echo = None
        outcome[3]["themes"] = _theme_report(outcome[1])
    return outcome[1], outcome[3], outcome[2], by_id


def _search(result, slots, groups, held, bpm, beams, by_id, motifs, prefer=None, style=None):
    """(attributable failures, placed copy, violations, report) of the best pass over ``beams``.

    With ``prefer`` (a score of the placed copy) both cut passes of a beam are compared: among equal failures
    the one with fewer broken stack lines, then the higher score, wins. Pass 2 re-chooses cuts greedily, which
    can flip the parity a hand enters an echo with, while the beam planned the whole timeline.
    """
    outcome = None
    for width, per_timing in beams:
        plan = _plan_cuts(groups, held, bpm, width, per_timing, style)
        for joint in (True, False):
            # Cuts chosen with their cells follow the hand's path; pass 1's cuts are the verified fallback.
            for slot in slots:
                hand, direction = plan[slot.index]
                slot.value = {"color": slot.fixed.get("color", hand),
                              "direction": slot.fixed.get("direction", direction)}
                slot.held_cut = None
            for group in groups:  # a double keeps the parity pass 1 found for both hands
                if len({s.value["color"] for s in group}) == 2:
                    for slot in group:
                        slot.held_cut = slot.value["direction"]
            _place_cells(groups, slots, bpm, joint, style)
            trial = copy.deepcopy(result)
            _write(trial, _collect_for(trial, slots))
            violations = rule_violations(trial)
            failures = sum(1 for v in violations if _attributable(v, by_id))
            # A preferred placement never buys its score with a broken stack line.
            score = (-_stack_breaks(trial), prefer(trial)) if prefer else (0, 0.0)
            if outcome is None or failures < outcome[0] or failures == outcome[0] and score > outcome[4]:
                outcome = (failures, trial, violations, _report(slots, motifs), score)
            if not failures and not prefer:
                return outcome
        if not outcome[0] and not outcome[4][0]:
            return outcome  # no rule broken and every stack in line (the wider beam may still line one up)
    return outcome


def _echo_links(arrangement, slots):
    """[(statement slots, echo slots, offset, mirror)] for declared themes whose echo has an open note."""
    from .recurrence import theme_links
    links = []
    for link in theme_links(arrangement):
        (a0, a1), (b0, b1) = link["statement"], link["echo"]
        echo = [s for s in slots if b0 <= s.beat < b1]
        if any(_free(s) for s in echo):
            links.append(([s for s in slots if a0 <= s.beat < a1], echo, b0 - a0, link["mirror"]))
    return links


def _set_echoes(links, placed):
    """Give each echo slot its matched statement note's placed values; the statement keeps its own."""
    from .arrangement import expanded_notes
    from .recurrence import mirrored, pair_by_time
    values = {n["id"]: {f: n[f] for f in FIELDS} for n in expanded_notes(placed)}
    for statement, echo, offset, mirror in links:
        for slot in echo:
            slot.themed = True
        for slot in statement:
            if _free(slot) and slot.oid in values:
                slot.echo = values[slot.oid]
        # A statement double pairs by its placed hands and cells, an echo double by note ID.
        sources = [s for s in statement if s.oid in values]
        placed_order = lambda s: (values[s.oid]["color"], values[s.oid]["x"], values[s.oid]["y"], s.oid)
        for source, target in pair_by_time(sources, echo, offset, beat=lambda s: s.beat, same_size=True,
                                           order=lambda s: placed_order(s) if s in sources else (0, 0, 0, s.oid)):
            if source.stack != target.stack:
                continue  # a stack (one hand, one line) and a double or single are different figures
            chosen = values[source.oid]
            target.echo = mirrored(chosen) if mirror else chosen


def _echo_agreement(placed):
    """Matched echo notes that repeat their statement note's placement, over every declared echo."""
    return sum(round(t["placement"] * t["matched"]) for t in _theme_report(placed))


def _theme_report(placed):
    """Per declared echo: how many of its notes matched a statement note and share its placement."""
    from .arrangement import expanded_notes
    from .recurrence import echo_score, theme_links
    notes = expanded_notes(placed)
    return [{"theme": link["theme"], "echo": [float(link["echo"][0]), float(link["echo"][1])],
             **echo_score(notes, link["statement"], link["echo"], link["mirror"])} for link in theme_links(placed)]


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
                      alternatives: bool = True, thorough: bool = True) -> dict:
    """Fill every open note field so the movement rules hold; the input is not modified.

    Returns ``{"arrangement", "report", "errors"}``. A fully specified arrangement with no ``placed`` record
    is returned unchanged (the same object). ``unpin`` re-places every unlocked literal note from scratch,
    ignoring its stored values (for comparing a stored map with a fresh placement). When a rule cannot hold,
    ``strict`` raises :class:`PlacementError`; otherwise the best placement comes back with the errors.
    ``alternatives=False`` skips verifying alternatives for the errors, and ``thorough=False`` the wider beam
    retried after a broken rule (both for a draft generator's inner loop).
    """
    empty = {"placed_notes": 0, "rechosen": [], "motifs": []}
    if not unpin and not needs_placement(arrangement):
        return {"arrangement": arrangement, "report": empty, "errors": []}
    done = _place(arrangement, unpin=unpin, beams=BEAMS if thorough else BEAMS[:1])
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
        if violation["code"] in ("hidden_note", "reach_proxy", "stack_shape", "stack_touch", "cut_path_blocked"):
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
