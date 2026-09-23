"""Rhythm drafts that follow the critique's own rules (SM-036).

``music rhythm --propose`` suggests note times, bar by bar, with the evidence behind each one. It uses the
functions the critique judges a map with, scaled to the difficulty's ``target_tier``:

* the declared lead's strongest attack per half-beat (per beat in a thin, soft bar; a strong sixteenth run
  where the tier allows it), and the singing's onsets while the voice leads;
* fills where the lead rests for a beat or more, on another stem's strongest attack away from the lead;
* the drum pattern or the melody's pitch changes where no voice or declared lead carries the bar, else the
  strongest attack per beat, so playing audio is never left unmapped;
* the bar's heaviest ensemble accent;
* every time snapped to the coarsest grid that stays on its sound.

The draft is then placed and critiqued, and adjusted until none of the critique's rhythm findings remain:
unsupported notes and one-hand bursts lose a time, a quiet passage or a soft bar sheds its weakest times, a
bar that buries its lead loses its stray times, and a lead left unmapped or a heavy run played easier than the
soft passages gains attacks. What cannot be resolved is reported, never hidden. The draft is a starting
point: the agent edits it, and ``project save`` places it like any other rhythm.
"""

from __future__ import annotations

import copy
import math
from bisect import bisect_left
from fractions import Fraction

from .audio_grounding import ONSET_METHODS, SUPPORT_BEATS, SUPPORT_STRENGTH
from .movement import BURST_SECONDS, BURST_SWINGS
from .critique import (DRUM_ONSET_STRENGTH, DRUM_PATTERN_MIN_ONSETS, DRUM_SLOTS_PER_BEAT, INTENSITY_BAR_BEATS,
                       INTENSITY_LOUD_PERCENTILE, LEAD_GAP_BEATS, LEAD_MAPPED_THRESHOLD, LEAD_MIN_ONSETS,
                       LEAD_ONSET_STRENGTH, LEAD_SUPPORT_STRENGTH,
                       MELODY_MIN_CHANGES, SALIENCE_BAR_BEATS, SALIENCE_MATCH_BEATS, SOFT_RATIO, VOCAL_ONSET_STRENGTH,
                       _percentile, _sections, beat_to_seconds, critique_arrangement, ensemble_accents, focus_lead,
                       lead_onsets, melody_onsets, on_onset, quiet_bar, salient_onsets, strongest_per_slot)
from .placement import place_arrangement
from .validation import _beat

TARGET_CODES = ("note_without_audio", "density_exceeds_audio", "lead_rhythm_diluted", "lead_rhythm_unmapped",
                "intensity_underplayed", "difficulty_exceeds_intensity", "one_hand_burst")
GRIDS = (1, 2, 4, 3, 8, 6, 16, 12)
SNAP_TOLERANCE = 0.07  # beats: a snapped time stays within the audio support window of its sound
MIN_GAP_BEATS = Fraction(1, 4)
# Sixteenth runs of the lead join the draft at this attack strength; None keeps the tier to half-beats.
RUN_STRENGTH = {"below_band": None, "band": 0.6, "challenge": 0.5, "stretch": 0.45, "beyond": 0.4}
ONSET_STRENGTH = 0.3
MAX_ROUNDS = 16
ROLE_RANK = {"anchor": 0, "lead": 1, "vocals": 1, "drums": 2, "melody": 2, "run": 3, "ensemble": 4, "onset": 4,
             "fill": 5, "intensity": 6}


def grid_beat(beat: float) -> Fraction:
    """The coarsest grid position within SNAP_TOLERANCE of ``beat`` (a sixteenth when none is)."""
    for denominator in GRIDS:
        candidate = Fraction(round(beat * denominator), denominator)
        if abs(float(candidate) - beat) <= SNAP_TOLERANCE:
            return candidate
    return Fraction(round(beat * 16), 16)


def melody_beat(beat: float) -> Fraction:
    """A whole or half beat within SNAP_TOLERANCE of a melody change, else the nearest quarter."""
    for denominator in (1, 2):
        candidate = Fraction(round(beat * denominator), denominator)
        if abs(float(candidate) - beat) <= SNAP_TOLERANCE:
            return candidate
    return Fraction(round(beat * 4), 4)


def _relative(beat: Fraction):
    return int(beat) if beat.denominator == 1 else str(beat)


class _Evidence:
    """The evidence run seen from the arrangement's beat grid."""

    def __init__(self, arrangement, report):
        from .musical import seconds_to_beat
        self.arrangement, self.report = arrangement, report
        self.layers = report.get("layers") or {}
        self.to_beat = lambda seconds: seconds_to_beat(seconds, arrangement)
        support = sorted((float(e["seconds"]), e.get("strength", 0))
                         for layer in self.layers.values() for e in layer.get("events", [])
                         if e.get("method") in ONSET_METHODS and e.get("strength", 0) >= SUPPORT_STRENGTH)
        self.support = [t for t, _ in support]
        self.support_strength = [s for _, s in support]
        self.tolerance = SUPPORT_BEATS * 60 / float(arrangement["song"]["bpm"])
        self.spans = _sections(arrangement)
        self.cache = {}

    def strength_at(self, beat) -> float:
        """Strongest supporting onset under ``beat`` (0.0 when the note would sit on no sound)."""
        seconds = beat_to_seconds(beat, self.arrangement)
        lo = bisect_left(self.support, seconds - self.tolerance)
        hi = bisect_left(self.support, seconds + self.tolerance + 1e-12)
        return max(self.support_strength[lo:hi], default=0.0)

    def events(self, name, methods, threshold):
        """(beat, strength, method, seconds) of one layer's events."""
        key = (name, methods, threshold)
        if key not in self.cache:
            self.cache[key] = sorted((self.to_beat(float(e["seconds"])), e["strength"], e["method"], float(e["seconds"]))
                                     for e in (self.layers.get(name) or {}).get("events", [])
                                     if e.get("method") in methods and e.get("strength", 0) >= threshold)
        return self.cache[key]

    def stems(self):
        return [n for n in self.layers if n != "mix"] or list(self.layers)


def _loudness(evidence, first, last):
    """{bar start: loudness relative to the song's heavy bars}, as the intensity check measures it."""
    passages = evidence.report.get("passages") or []
    values = {}
    for start in range(first, last, INTENSITY_BAR_BEATS):
        a = beat_to_seconds(start, evidence.arrangement)
        b = beat_to_seconds(start + INTENSITY_BAR_BEATS, evidence.arrangement)
        weighted = [(min(b, p["end_seconds"]) - max(a, p["start_seconds"]), p["energy_ratio"])
                    for p in passages if p["end_seconds"] > a and p["start_seconds"] < b]
        weight = sum(w for w, _ in weighted)
        if weight > 0:
            values[start] = sum(w * e for w, e in weighted) / weight
    loud = _percentile(list(values.values()), INTENSITY_LOUD_PERCENTILE) if values else 0.0
    return {start: value / loud for start, value in values.items()} if loud > 1e-9 else {}


def _candidate(beat, strength, role, layer, method, onset, seconds, melodic=False):
    return {"beat": (melody_beat if melodic else grid_beat)(onset), "strength": round(strength, 4), "role": role,
            "evidence": {"layer": layer, "method": method, "strength": round(strength, 4),
                         "onset_beat": round(onset, 4), "seconds": round(seconds, 4)}}


def _bar_candidates(evidence, bar, stop, singing, tier, soft=False):
    """(bar summary, primary candidates, reserve candidates) for one 4-beat bar.

    A thin, quiet bar takes one attack per beat; so does a soft one (below SOFT_RATIO of the heavy loudness)
    for its lead, as the lead and intensity checks judge it.
    """
    layers = evidence.layers
    arrangement = evidence.arrangement
    lead = "vocals" if bar in singing and isinstance(layers.get("vocals"), dict) else focus_lead(
        evidence.spans, bar + SALIENCE_BAR_BEATS / 2, layers)
    quiet = quiet_bar(evidence.report, arrangement, bar, bar + SALIENCE_BAR_BEATS)
    inside = lambda b: bar <= b < stop
    primary, reserve = [], []
    lead_support = []
    if lead:
        found = evidence.events(lead, ("spectral_flux", "pitch_change", "chord_change"), LEAD_SUPPORT_STRENGTH)
        lead_support = [b for b, *_ in found]
        details = {round(b, 9): (s, m, t) for b, s, m, t in found}
        for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in found],
                                                 1 if quiet or soft else DRUM_SLOTS_PER_BEAT):
            if strength >= LEAD_ONSET_STRENGTH and inside(beat):
                s, m, t = details[round(beat, 9)]
                primary.append(_candidate(beat, s, "lead", lead, m, beat, t))
        if lead == "vocals":
            for beat, strength, method, seconds in evidence.events("vocals", ("spectral_flux",), VOCAL_ONSET_STRENGTH):
                if inside(beat):
                    (reserve if quiet else primary).append(_candidate(beat, strength, "vocals", "vocals", method, beat,
                                                                      seconds))
        run = RUN_STRENGTH.get(tier)
        if run is not None and not quiet and not soft:
            for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in found], 4):
                if strength >= run and inside(beat):
                    s, m, t = details[round(beat, 9)]
                    primary.append(_candidate(beat, s, "run", lead, m, beat, t))
        # Fills where the lead rests a beat or more, well away from its attacks (never diluting its rhythm).
        for whole in range(int(bar), int(stop)):
            if any(whole - 0.25 <= b < whole + 1.25 for b in lead_support):
                continue
            others = [(s, b, name, m, t) for name in evidence.stems() if name not in ("mix", lead)
                      for b, s, m, t in evidence.events(name, ("spectral_flux", "pitch_change", "chord_change"),
                                                        LEAD_ONSET_STRENGTH)
                      if whole <= b < whole + 1 and not _near(lead_support, b, LEAD_GAP_BEATS)]
            if others:
                s, b, name, m, t = max(others)
                primary.append(_candidate(b, s, "fill", name, m, b, t))
    else:
        drums = [(b, s, m, t) for b, s, m, t in evidence.events("drums", ("spectral_flux",), DRUM_ONSET_STRENGTH)
                 if inside(b)]
        slots = strongest_per_slot([(b, s) for b, s, *_ in drums], DRUM_SLOTS_PER_BEAT)
        melody = melody_onsets(evidence.report, arrangement, bar, stop)
        if len(slots) >= DRUM_PATTERN_MIN_ONSETS:
            details = {round(b, 9): (s, m, t) for b, s, m, t in drums}
            for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in drums], 1 if quiet else DRUM_SLOTS_PER_BEAT):
                s, m, t = details[round(beat, 9)]
                primary.append(_candidate(beat, s, "drums", "drums", m, beat, t))
        elif len(melody) >= MELODY_MIN_CHANGES:
            changes = {round(b, 9): (s, t) for b, s, _, t in evidence.events("mix", ("melody_change",), 0.0)}
            for beat in melody:
                s, t = changes.get(round(beat, 9), (0.3, beat_to_seconds(beat, arrangement)))
                primary.append(_candidate(beat, s, "melody", "mix", "melody_change", beat, t, melodic=True))
        else:
            strongest = {}
            for name in evidence.stems():
                for b, s, m, t in evidence.events(name, ONSET_METHODS, ONSET_STRENGTH):
                    if inside(b) and (math.floor(b) not in strongest or strongest[math.floor(b)][1] < s):
                        strongest[math.floor(b)] = (b, s, name, m, t)
            for b, s, name, m, t in strongest.values():
                primary.append(_candidate(b, s, "onset", name, m, b, t))
    if not quiet:
        heavy = sorted(ensemble_accents(layers, arrangement, lead or "mix", bar, stop, evidence.cache.setdefault(
            "ensemble", {})), key=lambda a: -a[1])
        for beat, strength, name in heavy[:1]:
            if not lead_support or not _near(lead_support, beat, LEAD_GAP_BEATS) or _near(lead_support, beat,
                                                                                          SALIENCE_MATCH_BEATS):
                primary.append(_candidate(beat, strength, "ensemble", name, "spectral_flux", beat,
                                          beat_to_seconds(beat, arrangement)))
    # Reserve for heavier bars: the lead's (or the drum pattern's) sixteenths, then every stem's strongest attack
    # per half-beat that does not dilute the lead.
    rolling = lead or "drums"
    if not quiet and isinstance(layers.get(rolling), dict):
        events = evidence.events(rolling, ("spectral_flux", "pitch_change", "chord_change"), LEAD_ONSET_STRENGTH)
        details = {round(b, 9): (s, m, t) for b, s, m, t in events}
        for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in events if inside(b)], 4):
            s, m, t = details[round(beat, 9)]
            reserve.append(_candidate(beat, s, "intensity", rolling, m, beat, t))
    for name in evidence.stems():
        for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in evidence.events(
                name, ("spectral_flux", "pitch_change", "chord_change"), LEAD_ONSET_STRENGTH) if inside(b)]):
            if lead_support and _near(lead_support, beat, LEAD_GAP_BEATS) and not _near(lead_support, beat,
                                                                                         SALIENCE_MATCH_BEATS):
                continue
            reserve.append(_candidate(beat, strength, "intensity", name, "spectral_flux", beat,
                                      beat_to_seconds(beat, arrangement)))
    summary = {"start_beat": bar, "lead": lead, "quiet": quiet, "soft": soft}
    return summary, primary, reserve


def _near(values, beat, reach):
    index = bisect_left(values, beat - reach)
    return index < len(values) and values[index] <= beat + reach


def _clear(arrangement, start, end):
    """Remove the free literal notes in [start, end); arc and chain anchors and locked sections stay."""
    anchors = set()
    for section in arrangement["sections"]:
        base = _beat(section["start_beat"])
        for kind in ("arcs", "chains"):
            for item in section.get(kind, []):
                anchors.add((section["id"], base + _beat(item["beat"])))
                if kind == "arcs":
                    anchors.add((section["id"], base + _beat(item["tail_beat"])))
    kept = []
    for section in arrangement["sections"]:
        if section.get("locked"):
            continue
        base = _beat(section["start_beat"])
        section["notes"] = [n for n in section["notes"]
                            if not start <= base + _beat(n["beat"]) < end or (section["id"], base + _beat(n["beat"]))
                            in anchors]
        kept += [base + _beat(n["beat"]) for n in section["notes"] if start <= base + _beat(n["beat"]) < end]
    return sorted(kept)


def _with_notes(base, chosen):
    """``base`` plus one rhythm-only note per chosen time, in the unlocked section holding it."""
    draft = copy.deepcopy(base)
    spans = [(s, _beat(s["start_beat"]), _beat(s["start_beat"]) + _beat(s["length_beats"])) for s in draft["sections"]]
    for beat in sorted(chosen):
        for section, first, last in spans:
            if first <= beat < last and not section.get("locked"):
                taken = {n["id"] for n in section["notes"]}
                note_id = "r-" + str(beat).replace("/", "_")
                while note_id in taken:
                    note_id += "x"
                section["notes"].append({"id": note_id, "beat": _relative(beat - first)})
                break
    for section, _, _ in spans:
        section["notes"].sort(key=lambda n: _beat(n["beat"]))
    return draft


def _holds(arrangement):
    """[(head, tail)] beats where an arc or chain holds a saber, leaving one hand for every other sound."""
    spans = []
    for section in arrangement["sections"]:
        base = _beat(section["start_beat"])
        for kind in ("arcs", "chains"):
            spans += [(base + _beat(i["beat"]), base + _beat(i["tail_beat"])) for i in section.get(kind, [])]
    return spans


def _too_close(beat, others, holds, seconds):
    """True when ``beat`` crowds the other times: under MIN_GAP_BEATS from one, or, while a saber is held (the free
    hand takes every sound), completing BURST_SWINGS times each under BURST_SECONDS after the last."""
    if any(abs(beat - other) < MIN_GAP_BEATS for other in others):
        return True
    if not any(head < beat < tail for head, tail in holds):
        return False
    here = seconds(beat)
    near = sorted([here] + [seconds(o) for o in others if any(head < o < tail for head, tail in holds)
                            and abs(seconds(o) - here) < BURST_SECONDS * BURST_SWINGS])
    index = near.index(here)
    low = high = index
    while low and near[low] - near[low - 1] < BURST_SECONDS:
        low -= 1
    while high + 1 < len(near) and near[high + 1] - near[high] < BURST_SECONDS:
        high += 1
    return high - low + 1 >= BURST_SWINGS


def _spaced(candidates, fixed, holds, seconds):
    """Snap duplicates together and keep the best candidate per time, never crowding another (_too_close)."""
    best = {}
    for item in candidates:
        current = best.get(item["beat"])
        if current is None or (ROLE_RANK[item["role"]], -item["strength"]) < (ROLE_RANK[current["role"]],
                                                                              -current["strength"]):
            best[item["beat"]] = item
    chosen = {}
    for beat, item in sorted(best.items(), key=lambda kv: (ROLE_RANK[kv[1]["role"]], -kv[1]["strength"], kv[0])):
        if _too_close(beat, list(chosen) + fixed, holds, seconds):
            continue
        chosen[beat] = item
    return chosen


def propose_rhythm(arrangement: dict, report: dict, *, start: float | None = None, end: float | None = None,
                   tier: str | None = None) -> dict:
    """A rhythm draft for [start, end) (default: the whole song); see the module docstring.

    Returns ``{"range", "tier", "bars", "draft", "placement", "remaining", "rounds"}``. ``draft`` is the
    arrangement with the range's free notes replaced by rhythm-only notes (``id`` and ``beat``), ready to
    edit and save.
    """
    if not report:
        raise ValueError("No musical evidence run matches the current audio; run `music analyze` first")
    song_end = max(_beat(s["start_beat"]) + _beat(s["length_beats"]) for s in arrangement["sections"])
    first = Fraction(0) if start is None else Fraction(str(start))
    last = song_end if end is None else min(song_end, Fraction(str(end)))
    if not 0 <= first < last:
        raise ValueError("Choose an increasing beat range inside the song")
    tier = tier or arrangement["difficulty"].get("target_tier") or "band"
    if tier not in RUN_STRENGTH:
        raise ValueError(f"Unknown tier {tier!r}; use one of {', '.join(RUN_STRENGTH)}")
    base = copy.deepcopy(arrangement)
    fixed = _clear(base, first, last)
    evidence = _Evidence(base, report)
    # The rest of the map may itself be a rhythm-only draft: judge it as placed.
    context = place_arrangement(base, strict=False, alternatives=False)["arrangement"]
    singing = {b["start_beat"] for b in critique_arrangement(context, report)["metrics"]["salience"].get("bars", [])
               if b["salient"] == "vocals"}
    bars, pool, reserve = [], [], []
    first_bar = int(first // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS
    loudness = _loudness(evidence, 0, math.ceil(song_end))
    for bar in range(first_bar, math.ceil(last), SALIENCE_BAR_BEATS):
        summary, primary, extra = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier,
                                                  soft=loudness.get(bar, 1.0) < SOFT_RATIO)
        keep = lambda item: first <= item["beat"] < last and evidence.strength_at(item["beat"]) > 0
        pool += [c for c in primary if keep(c)]
        reserve += [c for c in extra if keep(c)]
        bars.append(summary)
    needs = _lead_needs(evidence, bars)
    evidence.soft = {bar["start_beat"]: bar["soft"] for bar in bars}
    holds = _holds(base)
    seconds = lambda beat: beat_to_seconds(beat, base)
    chosen = _spaced(pool, fixed, holds, seconds)
    removed, history = set(), []
    best = None
    for rounds in range(1, MAX_ROUNDS + 1):
        draft = _with_notes(base, chosen)
        placed = place_arrangement(draft, strict=False, alternatives=False)
        issues = [{"code": e["rule"], "beats": [e["beat"], e["beat"]], "object_ids": e["object_ids"],
                   "message": e["message"]} for e in placed["errors"]]
        critique = critique_arrangement(placed["arrangement"], report)
        issues += [w for w in critique["warnings"] if w["code"] in TARGET_CODES and _overlaps(w, placed, first, last)]
        score = len(issues)
        if best is None or score < best[0]:
            best = (score, dict(chosen), draft, placed, issues, rounds)
        if not issues:
            break
        changed = _adjust(chosen, issues, placed["arrangement"], evidence, reserve, fixed, removed, critique,
                          lambda beat, others: _too_close(beat, others, holds, seconds), needs)
        history.append({"round": rounds, "findings": _count(issues), "changes": changed})
        if not changed:
            break
    score, chosen, draft, placed, issues, rounds = best
    by_bar = {}
    for beat, item in sorted(chosen.items()):
        by_bar.setdefault(int(beat // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS, []).append(
            {"beat": _relative(beat), "role": item["role"], "evidence": item["evidence"]})
    for bar in bars:
        bar["relative_loudness"] = round(loudness.get(bar["start_beat"], 0.0), 3)
        bar["notes"] = by_bar.get(bar["start_beat"], [])
    return {"range": [_relative(first), _relative(last)], "tier": tier, "note_count": len(chosen),
            "bars": bars, "draft": draft, "placement": placed["report"], "rounds": rounds, "history": history,
            "remaining": [{k: w.get(k) for k in ("code", "beats", "message")} for w in issues]}


def _count(issues):
    counts = {}
    for issue in issues:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1
    return counts


def _overlaps(warning, placed, first, last):
    beats = warning.get("beats")
    if beats:
        return float(beats[0]) < float(last) and float(beats[1]) > float(first)
    ids = set(warning.get("object_ids") or [])
    from .arrangement import expanded_notes
    return any(float(first) <= float(n["beat"]) < float(last) for n in expanded_notes(placed["arrangement"])
               if n["id"] in ids) if ids else True


def _note_beats(arrangement, ids):
    from .arrangement import expanded_notes
    ids = set(ids)
    return [n["beat"] for n in expanded_notes(arrangement) if n["id"] in ids]


def _adjust(chosen, issues, placed, evidence, reserve, fixed, removed, critique, crowded, needs):
    """Change the draft's times against this round's findings; returns the number of changes.

    Thinning never takes a note the bar's declared lead needs (LEAD_MAPPED_THRESHOLD of its attacks), and a
    quiet window only sheds notes off the salient onsets, the ones its density check counts.
    """
    changes = 0
    salient, tolerance = salient_onsets(evidence.arrangement, evidence.report)

    def drop(beat, banned=True):
        """Remove a time; a banned one (no sound, diluting the lead, a movement conflict) never returns."""
        nonlocal changes
        if beat in chosen:
            del chosen[beat]
            if banned:
                removed.add(beat)
            changes += 1

    def add(item, force=False):
        nonlocal changes
        beat = item["beat"]
        if beat in chosen or (beat in removed and not force):
            return False
        others = [b for b in chosen if abs(b - beat) < 1]
        blocking = [b for b in others if crowded(beat, [b])]
        if crowded(beat, fixed) or (blocking and not force):
            return False
        if any(ROLE_RANK[chosen[b]["role"]] <= ROLE_RANK[item["role"]] for b in blocking):
            return False  # a note of the same or higher rank already sits on this sound
        for b in blocking:
            drop(b)
        chosen[beat] = item
        changes += 1
        return True

    def protected(beat):
        bar = int(beat // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS
        attacks = needs.get(bar)
        if not attacks or chosen[beat]["role"] == "anchor":
            return chosen[beat]["role"] == "anchor"
        times = [float(b) for b in list(chosen) + fixed if bar <= b < bar + SALIENCE_BAR_BEATS]
        mapped = lambda pool: sum(1 for a in attacks if any(abs(a - t) <= SALIENCE_MATCH_BEATS for t in pool))
        without = [t for t in times if t != float(beat)]
        return mapped(without) < LEAD_MAPPED_THRESHOLD * len(attacks) <= mapped(times)

    def weakest(beats, free_only=False):
        pool = [b for b in beats if b in chosen and not protected(b)
                and not (free_only and on_onset(salient, tolerance, beat_to_seconds(b, evidence.arrangement)))]
        return min(pool, key=lambda b: (-ROLE_RANK[chosen[b]["role"]], chosen[b]["strength"], b), default=None)

    def thin(beats, count, free_only=False):
        dropped = 0
        for _ in range(count):
            victim = weakest(beats, free_only)
            if victim is None:
                break
            drop(victim, banned=False)
            beats = [b for b in beats if b != victim]
            dropped += 1
        return dropped

    def raise_bars(bars, per_bar=2):
        added = 0
        for bar in bars:
            count = 0
            for item in sorted((c for c in reserve if bar <= c["beat"] < bar + INTENSITY_BAR_BEATS),
                               key=lambda c: (-c["strength"], c["beat"])):
                if add(item):
                    count += 1
                if count >= per_bar:
                    break
            added += count
        return added

    intensity = (critique["metrics"].get("intensity") or {}).get("bars", [])
    for issue in issues:
        code = issue["code"]
        span = [Fraction(str(round(float(issue["beats"][0]), 6))), Fraction(str(round(float(issue["beats"][1]), 6)))] \
            if issue.get("beats") else None
        inside = sorted(b for b in chosen if span and span[0] <= b < max(span[1], span[0] + Fraction(1, 64)))
        if code in ("note_without_audio", "lead_rhythm_diluted"):
            for beat in _note_beats(placed, issue.get("object_ids") or []):
                if beat in chosen and (code == "note_without_audio" or not protected(beat)):
                    drop(beat)
        elif code in ("one_hand_burst", "fast_direction_break", "flow_parity_break", "hidden_note",
                      "arc_note_conflict", "chain_note_conflict", "reach_proxy"):
            targets = [b for b in _note_beats(placed, issue.get("object_ids") or []) if b in chosen]
            victim = weakest(targets[1:-1] or targets) or (targets[1:-1] or targets or [None])[0]
            if victim is not None:
                drop(victim)
        elif code == "density_exceeds_audio":
            thin(inside, 2, free_only=True)
        elif code == "difficulty_exceeds_intensity":
            if not thin(inside, 2):
                # The soft bar holds only what its lead needs: raise the heavy bars' median (the reference its
                # allowance scales) until it covers this bar, starting with the lightest heavy bars.
                flagged = [b for b in intensity if b.get("allowed") and span[0] <= b["start_beat"] < span[1]]
                target = max((b["demand"] / (0.5 + 0.5 * b["relative"]) for b in flagged), default=0.0)
                loud = sorted((b for b in intensity if b.get("allowed") is None and b["swings"]),
                              key=lambda b: (b["demand"], b["start_beat"]))
                below = [b for b in loud if b["demand"] < target * 1.05]
                raise_bars([Fraction(b["start_beat"]) for b in below[:len(loud) // 2 + 1]])
        elif code == "lead_rhythm_unmapped":
            for item in sorted(_lead_pool(evidence, span), key=lambda c: (-c["strength"], c["beat"])):
                add(item, force=True)
        elif code == "intensity_underplayed":
            if not raise_bars(range(int(span[0]), int(span[1]), INTENSITY_BAR_BEATS)):
                # No attack left to add: the soft passages set too high a peak, so their densest bars ease off.
                soft = sorted((b for b in intensity if b.get("allowed") is not None and b["swings"]),
                              key=lambda b: (-b["demand"], b["start_beat"]))
                for bar in soft[:max(1, len(soft) // 10)]:
                    start = Fraction(bar["start_beat"])
                    thin([b for b in chosen if start <= b < start + INTENSITY_BAR_BEATS], 1)
    return changes


def _lead_needs(evidence, bars):
    """{bar: strong attacks of its declared instrument lead} for the bars lead_rhythm_unmapped judges."""
    needs = {}
    for bar in bars:
        if bar["quiet"] or bar["lead"] in (None, "vocals"):
            continue
        found = evidence.events(bar["lead"], ("spectral_flux", "pitch_change", "chord_change"), LEAD_SUPPORT_STRENGTH)
        inside = lambda b: bar["start_beat"] <= b < bar["start_beat"] + SALIENCE_BAR_BEATS
        attacks = [b for b, s in strongest_per_slot([(b, s) for b, s, *_ in found])
                   if s >= LEAD_ONSET_STRENGTH and inside(b)]
        if len(attacks) >= LEAD_MIN_ONSETS:
            needs[bar["start_beat"]] = attacks if not bar["soft"] else [
                b for b, s in strongest_per_slot([(b, s) for b, s, *_ in found], 1) if s >= LEAD_ONSET_STRENGTH and inside(b)]
    return needs


def _lead_pool(evidence, span):
    """Every strong attack of the bar's lead in ``span``, strongest per half-beat."""
    if not span:
        return []
    found = []
    for bar in range(int(span[0]) // SALIENCE_BAR_BEATS * SALIENCE_BAR_BEATS, int(span[1]), SALIENCE_BAR_BEATS):
        lead = focus_lead(evidence.spans, bar + SALIENCE_BAR_BEATS / 2, evidence.layers)
        if not lead:
            continue
        events = evidence.events(lead, ("spectral_flux", "pitch_change", "chord_change"), LEAD_SUPPORT_STRENGTH)
        details = {round(b, 9): (s, m, t) for b, s, m, t in events}
        slots = 1 if evidence.soft.get(bar) else DRUM_SLOTS_PER_BEAT
        for beat, strength in strongest_per_slot([(b, s) for b, s, *_ in events], slots):
            if strength >= LEAD_ONSET_STRENGTH and bar <= beat < bar + SALIENCE_BAR_BEATS:
                s, m, t = details[round(beat, 9)]
                item = _candidate(beat, s, "lead", lead, m, beat, t)
                if evidence.strength_at(item["beat"]) > 0:
                    found.append(item)
    return found


# ---------------------------------------------------------------------------------------------------------
# Suggestions for the audio and critique codes (project check)
# ---------------------------------------------------------------------------------------------------------

AUDIO_SUGGESTED = ("audio_unmapped", "note_without_audio", "density_exceeds_audio", "difficulty_exceeds_intensity",
                   "lead_rhythm_diluted", "lead_rhythm_unmapped", "vocal_line_unmapped", "drum_rhythm_unmapped",
                   "drum_entry_unmapped", "melody_unmapped", "ensemble_unmapped", "boundary_accent_unmapped",
                   "density_collapse", "intensity_underplayed", "focus_on_quiet_stem")
RETIME_REACH = Fraction(1, 2)


def audio_suggestions(arrangement: dict, report: dict | None, findings: list[dict]) -> None:
    """Attach concrete edits to audio and critique findings, drawn from the rhythm draft's own generators.

    ``arrangement`` is placed. Additions are rhythm-only notes (``beat`` plus the evidence) that the placer
    places on save; removals and retimes name the notes; ``set_weights`` rewrites a focus phrase.
    """
    wanted = [f for f in findings if f["code"] in AUDIO_SUGGESTED and not f["suggestions"]]
    if not wanted or not report:
        return
    from .arrangement import expanded_notes
    from .critique import intensity_bars
    evidence = _Evidence(arrangement, report)
    notes = expanded_notes(arrangement)
    times = sorted({n["beat"] for n in notes})
    by_id = {n["id"]: n for n in notes}
    context = critique_arrangement(arrangement, report)
    singing = {b["start_beat"] for b in context["metrics"]["salience"].get("bars", []) if b["salient"] == "vocals"}
    soft = {b["start_beat"] for b in intensity_bars(arrangement, report, notes)[1] if b.get("relative", 1.0) < SOFT_RATIO}
    tier = arrangement["difficulty"].get("target_tier") or "band"

    def open_times(candidates):
        """Candidates on a sound that crowd no note and no other candidate, strongest first."""
        chosen = []
        for item in sorted(candidates, key=lambda c: (ROLE_RANK[c["role"]], -c["strength"], c["beat"])):
            beat = item["beat"]
            if evidence.strength_at(beat) <= 0 and item["role"] not in ("lead", "melody", "ensemble"):
                continue
            nearby = times[bisect_left(times, beat - MIN_GAP_BEATS + Fraction(1, 10**6)):]
            if nearby and nearby[0] < beat + MIN_GAP_BEATS:
                continue
            if any(abs(beat - other["beat"]) < MIN_GAP_BEATS for other in chosen):
                continue
            chosen.append(item)
        return sorted(chosen, key=lambda c: c["beat"])

    def unmapped(candidates):
        """Candidates whose sound no note carries yet (none within SALIENCE_MATCH_BEATS)."""
        return [c for c in candidates if not _near([float(t) for t in times], c["evidence"]["onset_beat"],
                                                   SALIENCE_MATCH_BEATS)]

    def add(finding, candidates, why):
        found = open_times(unmapped(candidates))
        if found:
            finding["suggestions"].append({"op": "add", "notes": [
                {"beat": _relative(c["beat"]), "role": c["role"], "evidence": c["evidence"]} for c in found],
                "reason": why})

    def span_of(finding):
        beats = finding.get("beats") or []
        return (Fraction(str(beats[0])), Fraction(str(beats[1]))) if len(beats) == 2 else (None, None)

    def weakest(ids, count, why):
        """Remove the ``count`` note times under the weakest sounds (off-beat first), editable notes only."""
        editable = [by_id[i] for i in ids if i in by_id and "/note/" in i]
        ordered = sorted(editable, key=lambda n: (evidence.strength_at(n["beat"]), n["beat"].denominator == 1,
                                                  n["beat"]))
        victims = [n["id"] for n in ordered[:max(0, count)]]
        if victims:
            return {"op": "remove", "object_ids": victims, "reason": why}
        return None

    for finding in wanted:
        code = finding["code"]
        first, last = span_of(finding)
        if code == "audio_unmapped" and first is not None:
            pool = []
            for bar in range(int(first // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS, math.ceil(last), SALIENCE_BAR_BEATS):
                _, primary, _ = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier, bar in soft)
                pool += [c for c in primary if first <= c["beat"] < last]
            add(finding, pool, "map the stretch's audible layers (the rhythm draft for these bars)")
        elif code == "note_without_audio":
            for oid in finding["object_ids"]:
                note = by_id.get(oid)
                if note is None or "/note/" not in oid:
                    continue
                options = []
                for beat, strength, *_ in [e for name in evidence.layers
                                           for e in evidence.events(name, ONSET_METHODS, SUPPORT_STRENGTH)]:
                    target = grid_beat(beat)
                    if abs(target - note["beat"]) <= RETIME_REACH and target != note["beat"]:
                        crowded = any(abs(target - t) < MIN_GAP_BEATS for t in times if t != note["beat"])
                        if not crowded and evidence.strength_at(target) > 0:
                            options.append((abs(target - note["beat"]), -strength, target))
                if options:
                    finding["suggestions"].append({"op": "retime", "object_id": oid,
                                                   "to_beat": _relative(min(options)[2]),
                                                   "reason": "move onto the nearest supporting onset"})
                else:
                    finding["suggestions"].append({"op": "remove", "object_id": oid,
                                                   "reason": f"no onset within {RETIME_REACH} beat"})
        elif code == "lead_rhythm_diluted":
            stray = [i for i in finding["object_ids"] if "/note/" in i]
            if stray:
                finding["suggestions"].append({"op": "remove", "object_ids": stray,
                                               "reason": "these times sit between the lead's attacks"})
        elif code == "density_exceeds_audio" and first is not None:
            from .critique import beat_to_seconds as seconds, quiet_windows
            salient, tolerance = salient_onsets(arrangement, report)
            windows = [w for w in quiet_windows(arrangement, sorted(seconds(n["beat"], arrangement) for n in notes),
                                                report)[1]
                       if w.get("excess") and w["end_beat"] > float(first) and w["start_beat"] < float(last)]
            excess = max((math.ceil(w["free_notes"] - w["allowed_nps"] * (w["end_seconds"] - w["start_seconds"]))
                          for w in windows), default=1)
            free = [n["id"] for n in notes if first <= n["beat"] < last
                    and not on_onset(salient, tolerance, seconds(n["beat"], arrangement))]
            suggestion = weakest(free, excess, "thin the quiet passage: these notes sit on its weakest sounds, "
                                               "off the vocal, drum and melody onsets")
            if suggestion:
                finding["suggestions"].append(suggestion)
        elif code == "difficulty_exceeds_intensity" and first is not None:
            bars = [b for b in intensity_bars(arrangement, report, notes)[1]
                    if b.get("excess") and first <= b["start_beat"] < last]
            ids = [i for b in bars for i in b["note_ids"]]
            count = sum(math.ceil(b["swings"] * (1 - b["allowed"] / b["demand"])) for b in bars)
            suggestion = weakest(ids, count, "ease the soft bars: drop their weakest sounds")
            if suggestion:
                finding["suggestions"].append(suggestion)
        elif code in ("lead_rhythm_unmapped", "vocal_line_unmapped", "drum_rhythm_unmapped", "drum_entry_unmapped",
                      "melody_unmapped", "density_collapse", "intensity_underplayed") and first is not None:
            pool = []
            if code in ("drum_rhythm_unmapped", "drum_entry_unmapped"):
                hits = [(b, s) for b, s, *_ in evidence.events("drums", ("spectral_flux",), DRUM_ONSET_STRENGTH)
                        if float(first) <= b < float(last)]
                pool = [_candidate(b, s, "drums", "drums", "spectral_flux", b, beat_to_seconds(b, arrangement))
                        for b, s in strongest_per_slot(hits, DRUM_SLOTS_PER_BEAT)]
            elif code == "melody_unmapped":
                pool = [_candidate(b, 0.3, "melody", "mix", "melody_change", b, beat_to_seconds(b, arrangement),
                                   melodic=True) for b in melody_onsets(report, arrangement, float(first), float(last))]
            else:
                roles = {"lead_rhythm_unmapped": ("lead", "run"), "vocal_line_unmapped": ("lead", "vocals")}.get(code)
                for bar in range(int(first // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS, math.ceil(last),
                                 SALIENCE_BAR_BEATS):
                    _, primary, reserve = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier,
                                                          bar in soft)
                    picks = [c for c in primary if roles is None or c["role"] in roles]
                    picks += reserve if code in ("intensity_underplayed", "density_collapse") else []
                    pool += [c for c in picks if first <= c["beat"] < last]
            add(finding, pool, "map the sounds this finding names")
        elif code in ("ensemble_unmapped", "boundary_accent_unmapped"):
            targets = finding.get("targets") or ([[float(first), 1.0]] if first is not None else [])
            pool = [_candidate(beat, strength, "ensemble", "mix", "spectral_flux", beat, beat_to_seconds(beat, arrangement))
                    for beat, strength in targets]
            add(finding, pool, "map the band's heaviest accents")
        elif code == "focus_on_quiet_stem":
            finding["suggestions"] += focus_weights(arrangement, report, context, finding.get("section_id"))


def focus_weights(arrangement, report, context=None, section_id=None):
    """``set_weights`` suggestions dropping stems absent from a focus phrase (focus_on_quiet_stem).

    A stem QUIET_STEM_DB below its own usual level only carries separator bleed. When the declared lead is
    absent, the most active stem takes its weight and becomes the lead; when every stem is absent the phrase
    follows the mix.
    """
    from .critique import QUIET_STEM_DB
    context = context or critique_arrangement(arrangement, report)
    levels = {(p["section_id"], p["focus_id"]): p for p in context["metrics"]["focus_stems"].get("phrases", [])}
    found = []
    for section in arrangement["sections"]:
        if section.get("locked") or (section_id and section["id"] != section_id):
            continue
        for phrase in section.get("musical_focus") or []:
            level = levels.get((section["id"], phrase["id"]))
            if not level:
                continue
            db, active = level["db_vs_own_level"], level["most_active"]
            quiet = {name for name in phrase["weights"] if name in db and db[name] <= -QUIET_STEM_DB}
            if not quiet:
                continue
            weights = {name: w for name, w in phrase["weights"].items() if name not in quiet and w > 0}
            lead = phrase["lead"]
            if lead in quiet or not weights:
                lead = active if db[active] > -QUIET_STEM_DB else "mix"
                weights[lead] = weights.get(lead, 0) + phrase["weights"].get(phrase["lead"], 0) or 1.0
            total = sum(weights.values())
            weights = {name: round(w / total, 4) for name, w in weights.items()}
            weights[lead] = round(weights[lead] + 1 - sum(weights.values()), 4)
            found.append({"op": "set_weights", "section_id": section["id"], "focus_id": phrase["id"], "lead": lead,
                          "weights": weights, "reason": f"{', '.join(sorted(quiet))} absent here"})
    return found
