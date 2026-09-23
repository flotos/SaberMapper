"""Rhythm drafts that follow the critique's own rules (SM-036).

``music rhythm --propose`` suggests note times, bar by bar, with the evidence behind each one. It uses the
functions the critique judges a map with, and the musical rules SM-036 records:

* **Each bar has one role, read from the evidence.** A bar is soft when it is quiet or the drums rest, a riff
  when the drums and a riff stem (the declared instrument lead, else guitar) play while the voice is not
  articulated, and sung otherwise. Loudness against the heavy bars and the difficulty's ``target_tier`` set how
  many note times a bar carries (the tier's 90th-percentile window density); heavy riff bars carry the most.
* **Riff bars follow the riff.** The riff's strongest attack per half-beat always carries a note, and the kick
  joins it on the sixteenth grid, except between two chugs, where the riff rests.
* **Sung bars follow the syllables first.** The band fills the voice's gaps of 0.75 beat or more and plays on the
  free hand under a held arc; elsewhere it keeps under 24% of the bar's note times.
* **Held and intense singing becomes an arc**, and so does a hold the user named. Its head sits on the sound
  nearest the sustain's start (the sung attack, which a pitch tracker hears late) and takes the placer's hand,
  cut and cell; its tail reverses the cut.
* **Soft bars map changes** (melody, chord and pitch changes, genuine attacks) at least half a beat apart.
* **Doubles mark the heaviest accents** of a loud bar (kick or crash hits in a riff, the heaviest ensemble accent
  and the snare backbeat in a sung bar). The sixteenth before one stays empty, and the placer brings both hands
  to it on one parity.
* **Stacks mark unison hits**: where the drums and two more instruments strike together on one of the song's
  loudest attacks (``critique.unison_hits``), one hand cuts two notes (three when four instruments join) in a
  line along the cut, one longer note. Under a held arc the free hand cuts it. A stack takes the place of a
  double on the same sound, and the sixteenth before it stays empty too.
* The declared lead's strongest attack per half-beat (per beat in a thin or soft bar) carries a note, as the
  lead check requires; every time is snapped to the coarsest grid that stays on its sound (within
  ``SNAP_SECONDS``, so a free-time passage such as a rubato choir keeps each note on its own sound).
* **The map's style tunes the draft** (:mod:`style`): ``arcs`` sets how short a held sound still becomes an arc,
  ``accents`` how many doubles a loud bar's heaviest hits get.
* **A returning part returns as a theme.** Parts that repeat an earlier one (listen repetition groups, or the
  stems' rhythm grid; :mod:`recurrence`) become ``themes``, and the placer plays each echo's notes with its
  statement's hands, cuts and cells where the times match, mirrored on a transposed or alternate return.

The draft is then placed and critiqued, and adjusted until none of the critique's rhythm findings remain:
unsupported notes and one-hand bursts lose a time, a quiet passage or a soft bar sheds its weakest times, a
bar that buries its lead loses its stray times, and a lead left unmapped or a heavy run played easier than the
soft passages gains attacks; a stack the placer cannot lay out beside its neighbours is cut as one note. What
cannot be resolved is reported in ``remaining``, never hidden: the rhythm findings above, and every salience,
ensemble, stack and timing finding ``project check`` raises on the draft (``FOLLOW_CODES``), each with the
suggestions check gives it. The draft is a starting point: the agent edits it, and ``project save`` places it
like any other rhythm.
"""

from __future__ import annotations

import copy
import math
from bisect import bisect_left
from fractions import Fraction

from .audio_grounding import ONSET_METHODS, SUPPORT_BEATS, SUPPORT_STRENGTH
from collections import Counter

from .movement import BURST_SECONDS, BURST_SWINGS, _OPPOSITE, _VECTORS
from .critique import (ENSEMBLE_MIX_STRENGTH, LOUD_RATIO, MELODY_ONSET_STRENGTH, DRUM_ONSET_STRENGTH, DRUM_PATTERN_MIN_ONSETS, DRUM_SLOTS_PER_BEAT, INTENSITY_BAR_BEATS,
                       LEAD_GAP_BEATS, LEAD_MAPPED_THRESHOLD, LEAD_MIN_ONSETS,
                       LEAD_ONSET_STRENGTH, LEAD_SUPPORT_STRENGTH,
                       MELODY_MIN_CHANGES, SALIENCE_BAR_BEATS, SALIENCE_MATCH_BEATS, SOFT_RATIO, VOCAL_ONSET_STRENGTH,
                       _sections, bar_loudness, beat_to_seconds, critique_arrangement, ensemble_accents, focus_lead,
                       lead_onsets, melody_onsets, on_onset, quiet_bar, salient_onsets, strongest_per_slot,
                       unison_hits)
from .placement import _holds as _anchors_and_holds, place_arrangement
from .recurrence import propose_themes
from .style import ARC_SCALE, DOUBLES_PER_BAR, settings_of
from .validation import _beat

TARGET_CODES = ("note_without_audio", "density_exceeds_audio", "lead_rhythm_diluted", "lead_rhythm_unmapped",
                "intensity_underplayed", "difficulty_exceeds_intensity", "one_hand_burst")
# Findings the draft reports in ``remaining`` with ``project check``'s suggestions. It does not apply them: they can
# contradict its musical rules (an ensemble accent on the kick between two chugs, which the riff rule leaves open).
FOLLOW_CODES = ("audio_unmapped", "vocal_line_unmapped", "drum_rhythm_unmapped", "drum_entry_unmapped",
                "melody_unmapped", "ensemble_unmapped", "boundary_accent_unmapped", "density_collapse",
                "unison_hit_unstacked", "stack_too_tall", "note_off_sound")
GRIDS = (1, 2, 4, 3, 8, 6, 16, 12)
SNAP_TOLERANCE = 0.07  # beats: a snapped time stays within the audio support window of its sound
SNAP_SECONDS = 0.035  # and within this of its sound, under note_off_sound's OFF_SOUND_SECONDS
FINEST_GRID = 48  # a sound no grid in GRIDS reaches keeps its own time on this grid
MIN_GAP_BEATS = Fraction(1, 4)
# Sixteenth runs of the lead join the draft at this attack strength; None keeps the tier to half-beats.
RUN_STRENGTH = {"below_band": None, "band": 0.6, "challenge": 0.5, "stretch": 0.45, "beyond": 0.4}
ONSET_STRENGTH = 0.3
MAX_ROUNDS = 16
ROLE_RANK = {"arc": 0, "lead": 1, "vocals": 1, "double": 2, "stack": 1, "drums": 2, "melody": 2, "riff": 3, "run": 3, "ensemble": 4,
             "onset": 4, "band_gap": 5, "band_hold": 5, "fill": 5, "band": 6, "intensity": 7}
MUST_ROLES = ("arc", "lead", "vocals")  # kept past a bar's cap: the lead and salience checks need them
LEAD_METHODS = ("spectral_flux", "pitch_change", "chord_change")
# A riff bar's stem when no instrument lead is declared, and the band that fills a sung bar's gaps and holds.
RIFF_STEMS = ("guitar", "other", "piano", "bass")
BAND_STEMS = ("drums", "guitar", "bass", "other", "piano")
BAND_SHARE = 0.24  # band attacks outside the voice's gaps and holds, below lead_rhythm_diluted's 25%
SOFT_GAP_BEATS = Fraction(1, 2)  # soft bars map their changes at least half a beat apart
DOUBLE_STRENGTH = 0.8
DOUBLES_PER_LOUD_BAR = 2
# Held singing becomes an arc: a sustain of ARC_SECONDS and ARC_BEATS; intense singing (sustain strength
# INTENSE_STRENGTH or more) of INTENSE_SECONDS and INTENSE_BEATS; a hold the user named of NAMED_BEATS,
# its sustain starting within NAMED_REACH_BEATS of the named time.
ARC_SECONDS, ARC_BEATS = 0.7, 1.25
INTENSE_STRENGTH, INTENSE_SECONDS, INTENSE_BEATS = 0.45, 0.62, 1.2
NAMED_BEATS, NAMED_REACH_BEATS = 0.9, 1.5
# Note times a loud bar may carry, per tier, when no tier reference is supplied (the corpus' 90th percentiles),
# and the share of it the softest bars keep.
TIER_NOTES_PER_BEAT = {"below_band": 2.25, "band": 3.75, "challenge": 4.0, "stretch": 4.0, "beyond": 4.0}
TIER_NPS = {"below_band": 7.5, "band": 11.67, "challenge": 12.04, "stretch": 13.33, "beyond": 16.0}
CAP_FLOOR = 0.35


def snap_reach(arrangement) -> float:
    """How far (beats) a drafted time may sit from its sound: SNAP_TOLERANCE, and under SNAP_SECONDS at any tempo,
    so a slow song's notes stay as close to their sounds as a fast song's."""
    return min(SNAP_TOLERANCE, SNAP_SECONDS * float(arrangement["song"]["bpm"]) / 60)


def grid_beat(beat: float, reach: float = SNAP_TOLERANCE) -> Fraction:
    """The coarsest grid position within ``reach`` of ``beat``, else the nearest 1/FINEST_GRID beat."""
    for denominator in GRIDS:
        candidate = Fraction(round(beat * denominator), denominator)
        if abs(float(candidate) - beat) <= reach:
            return candidate
    return Fraction(round(beat * FINEST_GRID), FINEST_GRID)


def melody_beat(beat: float, reach: float = SNAP_TOLERANCE) -> Fraction:
    """A whole or half beat within ``reach`` of a melody change, else the coarsest grid that stays on it.

    A free-time passage (a rubato choir, a sung intro before the drums) keeps each change on its own time: the
    nearest quarter beat can sit a sixteenth off the sound, which the player hears as off-rhythm.
    """
    for denominator in (1, 2):
        candidate = Fraction(round(beat * denominator), denominator)
        if abs(float(candidate) - beat) <= reach:
            return candidate
    return grid_beat(beat, reach)


def _relative(beat: Fraction):
    return int(beat) if beat.denominator == 1 else str(beat)


class _Evidence:
    """The evidence run seen from the arrangement's beat grid."""

    def __init__(self, arrangement, report):
        from .musical import seconds_to_beat
        self.arrangement, self.report = arrangement, report
        self.layers = report.get("layers") or {}
        self.to_beat = lambda seconds: seconds_to_beat(seconds, arrangement)
        self.doubles = DOUBLES_PER_BAR[settings_of(arrangement)["accents"]]  # the style's accents
        support = sorted((float(e["seconds"]), e.get("strength", 0))
                         for layer in self.layers.values() for e in layer.get("events", [])
                         if e.get("method") in ONSET_METHODS and e.get("strength", 0) >= SUPPORT_STRENGTH)
        self.support = [t for t, _ in support]
        self.support_strength = [s for _, s in support]
        self.tolerance = SUPPORT_BEATS * 60 / float(arrangement["song"]["bpm"])
        self.reach = snap_reach(arrangement)
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
    return bar_loudness(evidence.report, evidence.arrangement, first, last)


def _candidate(evidence, beat, strength, role, layer, method, onset, seconds, melodic=False):
    snap = melody_beat if melodic else grid_beat
    return {"beat": snap(onset, evidence.reach), "strength": round(strength, 4), "role": role,
            "evidence": {"layer": layer, "method": method, "strength": round(strength, 4),
                         "onset_beat": round(onset, 4), "seconds": round(seconds, 4)}}


def _riff_stem(evidence, bar, stop, declared):
    """The stem carrying a riff bar: the declared instrument lead, else the first rhythm stem that plays."""
    candidates = [declared] if declared and declared not in ("vocals", "drums", "mix") else []
    candidates += [name for name in RIFF_STEMS if name not in candidates]
    for name in candidates:
        if not isinstance(evidence.layers.get(name), dict):
            continue
        attacks = [b for b, *_ in evidence.events(name, LEAD_METHODS, LEAD_ONSET_STRENGTH) if bar <= b < stop]
        if len(strongest_per_slot([(b, 1.0) for b in attacks])) >= LEAD_MIN_ONSETS:
            return name
    return None


def _role(evidence, bar, stop, singing, quiet, declared):
    """(role, riff stem): soft when the bar is quiet or the drums rest, riff when drums and a riff stem play
    and the voice is not articulated, else sung."""
    drums = [b for b, *_ in evidence.events("drums", ("spectral_flux",), DRUM_ONSET_STRENGTH) if bar <= b < stop]
    if quiet or not drums:
        return "soft", None
    if bar in singing:
        return "sung", None
    riff = _riff_stem(evidence, bar, stop, declared)
    return ("riff", riff) if riff else ("sung", None)


def _with_mix(evidence, beat):
    """True when the mix carries an attack under ``beat`` (a stem peak the mix does not hear is bleed or a swell)."""
    mix = evidence.cache.get("mix_attacks")
    if mix is None:
        mix = evidence.cache["mix_attacks"] = [b for b, *_ in evidence.events("mix", ("spectral_flux",),
                                                                                ENSEMBLE_MIX_STRENGTH)]
    return not mix or _near(mix, beat, SALIENCE_MATCH_BEATS)  # a run without mix attacks cannot gate


def _band(evidence, bar, stop, slots=DRUM_SLOTS_PER_BEAT):
    """The band's strongest attack per slot with a mix attack under it: kick or snare, a guitar chug, a bass note."""
    found = []
    for name in BAND_STEMS:
        found += [(b, s, name, m, t) for b, s, m, t in evidence.events(name, ("spectral_flux",), LEAD_ONSET_STRENGTH)
                  if bar <= b < stop and _with_mix(evidence, b)]
    strongest = {}
    for b, s, name, m, t in found:
        slot = math.floor(b * slots + 0.5)
        if slot not in strongest or strongest[slot][1] < s:
            strongest[slot] = (b, s, name, m, t)
    return sorted(strongest.values())


def _bar_candidates(evidence, bar, stop, singing, tier, soft=False, holds=(), loud=False):
    """(bar summary, primary candidates, reserve candidates, double candidates) for one 4-beat bar.

    The bar's role (soft, riff or sung) decides which sounds carry notes; see the module docstring.
    """
    layers = evidence.layers
    arrangement = evidence.arrangement
    inside = lambda b: bar <= b < stop
    quiet = quiet_bar(evidence.report, arrangement, bar, bar + SALIENCE_BAR_BEATS)
    declared = focus_lead(evidence.spans, bar + SALIENCE_BAR_BEATS / 2, layers)
    role, riff = _role(evidence, bar, stop, singing, quiet, declared)
    lead = "vocals" if bar in singing and isinstance(layers.get("vocals"), dict) else (declared or riff)
    primary, reserve, doubles = [], [], []
    lead_support = [b for b, *_ in evidence.events(lead, LEAD_METHODS, LEAD_SUPPORT_STRENGTH)] if lead else []
    # lead_rhythm_diluted judges the voice while it sings, else a declared lead: only those set what is filler.
    judged = "vocals" if bar in singing and isinstance(layers.get("vocals"), dict) else declared
    judged_support = [b for b, *_ in evidence.events(judged, LEAD_METHODS, LEAD_SUPPORT_STRENGTH)] if judged else []

    def per_slot(name, methods, threshold, slots, role_name, melodic=False):
        found = [(b, s, m, t) for b, s, m, t in evidence.events(name, methods, threshold) if inside(b)]
        details = {round(b, 9): (s, m, t) for b, s, m, t in found}
        return [_candidate(evidence, b, details[round(b, 9)][0], role_name, name, details[round(b, 9)][1], b,
                           details[round(b, 9)][2], melodic=melodic)
                for b, _ in strongest_per_slot([(b, s) for b, s, *_ in found], slots)]

    # The declared lead's strongest attack per half-beat (per beat in thin or soft bars): the lead check's rule.
    if declared and declared != "vocals" and bar not in singing:
        primary += per_slot(declared, LEAD_METHODS, LEAD_ONSET_STRENGTH, 1 if quiet or soft else DRUM_SLOTS_PER_BEAT,
                            "lead")
    if role == "soft":
        if bar in singing:
            primary += per_slot("vocals", ("spectral_flux",), VOCAL_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT, "vocals")
        primary += per_slot("mix", ("melody_change",), MELODY_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT, "melody",
                            melodic=True)
        primary += per_slot("vocals", ("pitch_change", "melody_change"), MELODY_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT,
                            "melody", melodic=True)
        for name in evidence.stems():
            if name not in ("vocals", "drums"):
                primary += per_slot(name, ("chord_change",), LEAD_ONSET_STRENGTH, 1, "melody", melodic=True)
        strongest = {}
        for name in evidence.stems():
            for b, s, m, t in evidence.events(name, ("spectral_flux", "pitch_change"), ONSET_STRENGTH):
                if inside(b) and (math.floor(b) not in strongest or strongest[math.floor(b)][1] < s):
                    strongest[math.floor(b)] = (b, s, name, m, t)
        primary += [_candidate(evidence, b, s, "onset", name, m, b, t) for b, s, name, m, t in strongest.values()]
    elif role == "riff":
        riff_support = [b for b, *_ in evidence.events(riff, LEAD_METHODS, LEAD_SUPPORT_STRENGTH)]
        # The riff leads its bar unless the arrangement declares another lead (the one the lead check judges).
        primary += per_slot(riff, LEAD_METHODS, LEAD_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT,
                            "lead" if declared in (None, riff) else "riff")
        run = RUN_STRENGTH.get(tier)
        if run is not None:
            primary += [c for c in per_slot(riff, LEAD_METHODS, LEAD_ONSET_STRENGTH, 4, "run")
                        if c["strength"] >= run]
        # The kick joins the riff on the sixteenth grid, except between two chugs, where the riff rests.
        for item in per_slot("drums", ("spectral_flux",), DRUM_ONSET_STRENGTH, 4, "drums"):
            onset = item["evidence"]["onset_beat"]
            if _near(riff_support, onset, SALIENCE_MATCH_BEATS) or not _near(riff_support, onset, LEAD_GAP_BEATS):
                primary.append(item)
    else:  # sung (or a groove the voice has left): syllables first, the band in the voice's gaps and under holds
        syllables = sorted(b for b, *_ in evidence.events("vocals", ("spectral_flux",), VOCAL_ONSET_STRENGTH)
                           if inside(b)) if bar in singing else []
        if bar in singing:
            primary += per_slot("vocals", ("spectral_flux",), VOCAL_ONSET_STRENGTH, 4, "vocals")
        edges = [bar - LEAD_GAP_BEATS] + syllables + [stop + LEAD_GAP_BEATS]
        gaps = [(a, b) for a, b in zip(edges, edges[1:]) if b - a >= LEAD_GAP_BEATS]
        for beat, strength, name, method, seconds in _band(evidence, bar, stop):
            if any(a + SALIENCE_MATCH_BEATS < beat < b - SALIENCE_MATCH_BEATS for a, b in gaps):
                primary.append(_candidate(evidence, beat, strength, "band_gap", name, method, beat, seconds))
            elif any(head < beat < tail for head, tail in holds):
                primary.append(_candidate(evidence, beat, strength, "band_hold", name, method, beat, seconds))
            elif not _near(lead_support, beat, LEAD_GAP_BEATS) or _near(lead_support, beat, SALIENCE_MATCH_BEATS):
                primary.append(_candidate(evidence, beat, strength, "band", name, method, beat, seconds))
    if not quiet and role != "soft":
        heavy = sorted(ensemble_accents(layers, arrangement, lead or "mix", bar, stop, evidence.cache.setdefault(
            "ensemble", {})), key=lambda a: -a[1])
        for beat, strength, name in heavy[:1]:
            if not _near(lead_support, beat, LEAD_GAP_BEATS) or _near(lead_support, beat, SALIENCE_MATCH_BEATS):
                primary.append(_candidate(evidence, beat, strength, "ensemble", name, "spectral_flux", beat,
                                          beat_to_seconds(beat, arrangement)))
    if loud and role != "soft" and not quiet:
        doubles = _stack_candidates(evidence, bar, stop, holds)
        stacked = {c["beat"] for c in doubles}
        doubles += [c for c in _double_candidates(evidence, bar, stop, role, lead, holds) if c["beat"] not in stacked]
    # Reserve for heavier bars: the lead's (or the drum pattern's) sixteenths, then every stem's strongest attack
    # per half-beat that does not dilute the lead.
    rolling = riff or lead or "drums"
    if not quiet and role != "soft" and isinstance(layers.get(rolling), dict):
        reserve += per_slot(rolling, LEAD_METHODS, LEAD_ONSET_STRENGTH, 4, "intensity")
    for name in evidence.stems():
        for item in per_slot(name, LEAD_METHODS, LEAD_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT, "intensity"):
            onset = item["evidence"]["onset_beat"]
            if lead_support and _near(lead_support, onset, LEAD_GAP_BEATS) and not _near(lead_support, onset,
                                                                                         SALIENCE_MATCH_BEATS):
                continue
            reserve.append(item)
    summary = {"start_beat": bar, "role": role, "lead": lead, "riff": riff, "quiet": quiet, "soft": soft,
               "declared": None if bar in singing else declared, "judged": judged}
    if judged_support:
        # Nothing but the lead itself, a held arc's free hand, the voice's gaps (capped by _band_share) and the
        # bar's heaviest ensemble accent may sit off the lead's attacks: that is what lead_rhythm_diluted counts.
        def on_lead(item):
            onset = float(item["beat"])
            return (item["role"] in ("lead", "vocals", "ensemble", "stack", "band_hold", "band_gap", "band")
                    or not _near(judged_support, onset, LEAD_GAP_BEATS) or _near(judged_support, onset,
                                                                                 SALIENCE_MATCH_BEATS))
        primary = [c for c in primary if on_lead(c)]
        reserve = [c for c in reserve if on_lead(c)]
        doubles = [c for c in doubles if on_lead(c) or _near(judged_support, float(c["beat"]), SALIENCE_MATCH_BEATS)]
    return summary, primary, reserve, doubles


def _stack_candidates(evidence, bar, stop, holds):
    """The bar's unison hits as stacks (``stack``: 2 or 3 notes for one hand). A stack needs one hand: under a held
    arc or chain the free hand cuts it; only while both sabers are held is there none."""
    found = []
    for beat, size, stems, strength in unison_hits(evidence.layers, evidence.arrangement, bar, stop,
                                                   evidence.cache.setdefault("unison", {})):
        item = _candidate(evidence, beat, strength, "stack", "mix", "spectral_flux", beat,
                          beat_to_seconds(beat, evidence.arrangement))
        item["evidence"]["stems"] = stems
        if sum(1 for head, tail in holds if head < item["beat"] < tail) < 2:
            found.append({**item, "stack": size})
    return found


def _double_candidates(evidence, bar, stop, role, lead, holds):
    """Up to ``evidence.doubles`` accents for both hands (the style's ``accents``: DOUBLES_PER_LOUD_BAR by
    default): kick or crash hits in a riff bar, the heaviest ensemble accent and the snare backbeat in a sung bar.
    Never while an arc or chain holds a saber."""
    arrangement = evidence.arrangement
    hits = [(b, s, m, t) for b, s, m, t in evidence.events("drums", ("spectral_flux",), DOUBLE_STRENGTH)
            if bar <= b < stop and _with_mix(evidence, b)]
    found = []
    if role == "riff":
        found = [_candidate(evidence, b, s, "double", "drums", m, b, t) for b, s, m, t in sorted(hits, key=lambda h: -h[1])]
    else:
        heavy = sorted(ensemble_accents(evidence.layers, arrangement, lead or "mix", bar, stop,
                                        evidence.cache.setdefault("ensemble", {})), key=lambda a: -a[1])
        found = [_candidate(evidence, b, s, "double", name, "spectral_flux", b, beat_to_seconds(b, arrangement))
                 for b, s, name in heavy[:1] if s >= DOUBLE_STRENGTH]
        for backbeat in (bar + 1, bar + 3):
            near = [h for h in evidence.events("drums", ("spectral_flux",), DRUM_ONSET_STRENGTH)
                    if abs(h[0] - backbeat) <= SALIENCE_MATCH_BEATS and _with_mix(evidence, h[0])]
            if near:
                b, s, m, t = max(near, key=lambda h: h[1])
                found.append(_candidate(evidence, b, s, "double", "drums", m, b, t))
    free = [c for c in found if not any(head <= c["beat"] <= tail for head, tail in holds)]
    unique = []
    for item in free:
        if all(abs(item["beat"] - other["beat"]) >= 1 for other in unique):
            unique.append(item)
    return unique[:evidence.doubles]


def _arcs(evidence, first, last, base, held=(), scale=1.0):
    """Arcs for held and intense singing: [(head, tail, evidence)] inside one unlocked section each.

    A vocal sustain becomes an arc when it lasts ARC_SECONDS and ARC_BEATS (intense singing, strength
    INTENSE_STRENGTH or more: INTENSE_SECONDS and INTENSE_BEATS). A hold the user named (``held``, source
    seconds) needs NAMED_BEATS, with its sustain starting within NAMED_REACH_BEATS of the named time. ``scale``
    (the style's ``arcs``) multiplies the held and intense lengths: below 1 shorter holds become arcs too.
    """
    arrangement = evidence.arrangement
    sections = [(s, _beat(s["start_beat"]), _beat(s["start_beat"]) + _beat(s["length_beats"]))
                for s in base["sections"]]
    taken = _holds(base)
    named = [evidence.to_beat(float(t)) for t in held]
    found = []
    for sustain in sorted(evidence.layers.get("vocals", {}).get("sustains") or [], key=lambda s: s["start_seconds"]):
        seconds = sustain["end_seconds"] - sustain["start_seconds"]
        start, end = evidence.to_beat(sustain["start_seconds"]), evidence.to_beat(sustain["end_seconds"])
        beats = end - start
        strength = sustain.get("strength", 0)
        qualifies = ((seconds >= ARC_SECONDS * scale and beats >= ARC_BEATS * scale)
                     or (strength >= INTENSE_STRENGTH and seconds >= INTENSE_SECONDS * scale
                         and beats >= INTENSE_BEATS * scale)
                     or (beats >= NAMED_BEATS and any(abs(start - t) <= NAMED_REACH_BEATS for t in named)))
        if not qualifies:
            continue
        head, tail = _arc_head(evidence, sustain["start_seconds"]), grid_beat(end, evidence.reach)
        if not first <= head < tail < last or tail - head < Fraction(1, 2):
            continue
        section = next(((s, a, b) for s, a, b in sections if a <= head < b), None)
        if quiet_bar(evidence.report, arrangement, float(head), float(tail)):
            continue  # a sustain under a thin, quiet passage is no held singing to carry
        if section is None or section[0].get("locked") or not tail < section[2]:
            continue  # an arc ends inside its own section
        if any(head <= t and h <= tail for h, t in taken):
            continue
        taken.append((head, tail))
        found.append((head, tail, {"layer": "vocals", "method": "sustain", "strength": round(strength, 4),
                                   "onset_beat": round(start, 4), "seconds": round(sustain["start_seconds"], 4),
                                   "hold_seconds": round(seconds, 3)}))
    return found


def _arc_head(evidence, seconds):
    """An arc head on the sound nearest a sustain's start (a pitch tracker starts a held note after its sung
    attack), snapped within SNAP_SECONDS of it; the start itself when no sound is within the support window."""
    lo = bisect_left(evidence.support, seconds - evidence.tolerance)
    hi = bisect_left(evidence.support, seconds + evidence.tolerance + 1e-12)
    near = min(evidence.support[lo:hi], key=lambda t: abs(t - seconds), default=seconds)
    return grid_beat(evidence.to_beat(near), evidence.reach)


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


def _holds(arrangement):
    """[(head, tail)] beats where an arc or chain holds a saber, leaving one hand for every other sound."""
    spans = []
    for section in arrangement["sections"]:
        base = _beat(section["start_beat"])
        for kind in ("arcs", "chains"):
            spans += [(base + _beat(i["beat"]), base + _beat(i["tail_beat"])) for i in section.get(kind, [])]
    return spans


def _too_close(beat, others, holds, seconds, gap=MIN_GAP_BEATS):
    """True when ``beat`` crowds the other times: under ``gap`` beats from one, or, while a saber is held (the free
    hand takes every sound), completing BURST_SWINGS times each under BURST_SECONDS after the last."""
    if any(abs(beat - other) < gap for other in others):
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


def _bar_of(beat):
    return int(beat // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS


def _spaced(candidates, fixed, holds, seconds, caps=None, gaps=None):
    """Keep the best candidate per time, never crowding another (_too_close), within each bar's cap.

    Arc anchors, the lead's attacks and the syllables are kept past the cap: the checks need them.
    """
    best = {}
    for item in candidates:
        current = best.get(item["beat"])
        if current is None or (ROLE_RANK[item["role"]], -item["strength"]) < (ROLE_RANK[current["role"]],
                                                                              -current["strength"]):
            best[item["beat"]] = item
    chosen, counts = {}, Counter()
    for beat, item in sorted(best.items(), key=lambda kv: (ROLE_RANK[kv[1]["role"]], -kv[1]["strength"], kv[0])):
        bar = _bar_of(beat)
        if caps and item["role"] not in MUST_ROLES and counts[bar] >= caps.get(bar, len(best)):
            continue
        if _too_close(beat, list(chosen) + fixed, holds, seconds, (gaps or {}).get(bar, MIN_GAP_BEATS)):
            continue
        chosen[beat] = item
        counts[bar] += 1
    return chosen


def _band_share(chosen, bars, evidence, holds):
    """Times off the bar's lead keep under BAND_SHARE of its note times.

    A time is off the lead when the lead has an attack within LEAD_GAP_BEATS of it but none within
    SALIENCE_MATCH_BEATS, exactly as lead_rhythm_diluted counts it; times under a held arc and the bar's heaviest
    ensemble accent do not count. The weakest, lowest-ranked such times go first.
    """
    for bar in bars:
        lead = bar["judged"]
        if not lead:
            continue
        start = bar["start_beat"]
        support = [b for b, *_ in evidence.events(lead, LEAD_METHODS, LEAD_SUPPORT_STRENGTH)]
        inside = [b for b in chosen if start <= b < start + SALIENCE_BAR_BEATS]
        stray = sorted((b for b in inside if chosen[b]["role"] not in ("arc", "ensemble", "stack", "band_hold")
                        and not chosen[b].get("stack")
                        and not any(head <= b <= tail for head, tail in holds)
                        and _near(support, float(b), LEAD_GAP_BEATS) and not _near(support, float(b),
                                                                                  SALIENCE_MATCH_BEATS)),
                       key=lambda b: (-ROLE_RANK[chosen[b]["role"]], chosen[b]["strength"], b))
        while stray and len(stray) >= BAND_SHARE * len(inside) + 1e-9:
            del chosen[stray.pop(0)]
            inside = [b for b in chosen if start <= b < start + SALIENCE_BAR_BEATS]


def _mark_doubles(chosen, doubles, fixed, holds, seconds):
    """Put a double (or a stack) on each accent: the time joins the draft (displacing a lesser note on the same
    sound) and the sixteenth before it stays empty unless it carries the lead's strongest attack of that half beat.
    A stack wins over a double on the same time, and over a note snapped to a neighbouring time on the same sound
    (its onset within SALIENCE_MATCH_BEATS of the stack's)."""
    for item in sorted(doubles, key=lambda c: "stack" not in c):
        beat = item["beat"]
        if beat not in chosen:
            crowd = [b for b in chosen if abs(b - beat) < MIN_GAP_BEATS]
            onset = item["evidence"]["onset_beat"]
            same = lambda b: (item.get("stack") and chosen[b]["role"] != "arc"
                              and abs(chosen[b]["evidence"]["onset_beat"] - onset) <= SALIENCE_MATCH_BEATS)
            if any(ROLE_RANK[chosen[b]["role"]] <= ROLE_RANK["double"] and not same(b) for b in crowd) or any(
                    abs(beat - f) < MIN_GAP_BEATS for f in fixed):
                continue
            for b in crowd:
                del chosen[b]
            chosen[beat] = item
        if item.get("stack"):
            chosen[beat] = {**{k: v for k, v in chosen[beat].items() if k != "double"}, "stack": item["stack"]}
        elif not chosen[beat].get("stack"):
            chosen[beat] = {**chosen[beat], "double": True}
        before = beat - Fraction(1, 4)
        if before in chosen and chosen[before]["role"] not in ("lead", "arc"):
            del chosen[before]


def _bar_caps(bars, loudness, tier, tier_reference, seconds):
    """Note times a bar may carry: the tier's 90th-percentile window density, scaled by the bar's loudness."""
    row = next((t for t in (tier_reference or {}).get("tiers", []) if t.get("id") == tier), None)
    per_beat = ((row or {}).get("window_notes_per_beat") or {}).get("p90") or TIER_NOTES_PER_BEAT[tier]
    nps = ((row or {}).get("window_nps") or {}).get("p90") or TIER_NPS[tier]
    caps = {}
    for bar in bars:
        start = bar["start_beat"]
        span = seconds(start + SALIENCE_BAR_BEATS) - seconds(start)
        scale = min(1.0, max(CAP_FLOOR, CAP_FLOOR + (1 - CAP_FLOOR) * loudness.get(start, 1.0)))
        caps[start] = max(1, math.floor(min(per_beat * SALIENCE_BAR_BEATS, nps * span) * scale))
    return caps


def _with_notes(base, chosen, arcs=()):
    """``base`` plus rhythm-only notes (two on a double, two or three marked ``stack`` on a stack) for the chosen
    times, in the unlocked section holding them.

    ``arcs`` are (head, tail, arc fields) to add to the section holding the head.
    """
    draft = copy.deepcopy(base)
    spans = [(s, _beat(s["start_beat"]), _beat(s["start_beat"]) + _beat(s["length_beats"])) for s in draft["sections"]]
    for beat in sorted(chosen):
        for section, first, last in spans:
            if first <= beat < last and not section.get("locked"):
                taken = {n["id"] for n in section["notes"]}
                stack = chosen[beat].get("stack")
                for suffix in ("", "-b", "-c")[:stack or (2 if chosen[beat].get("double") else 1)]:
                    note_id = "r-" + str(beat).replace("/", "_") + suffix
                    while note_id in taken:
                        note_id += "x"
                    taken.add(note_id)
                    section["notes"].append({"id": note_id, "beat": _relative(beat - first),
                                             **({"stack": True} if stack else {})})
                break
    for head, tail, fields in arcs:
        for section, first, last in spans:
            if first <= head < last:
                taken = {a["id"] for a in section.get("arcs", [])}
                arc_id = "va-" + str(head).replace("/", "_")
                while arc_id in taken:
                    arc_id += "x"
                section.setdefault("arcs", []).append({"id": arc_id, "beat": _relative(head - first), **fields,
                                                       "tail_beat": _relative(tail - first)})
                break
    for section, _, _ in spans:
        section["notes"].sort(key=lambda n: _beat(n["beat"]))
    return draft


def _arc_fields(placed, head, tail):
    """Hand, cut and cell of a drafted arc: the head takes the placer's choice for its note, and the tail cut
    reverses it one cell along the head's cut, so the saber returns the way it went."""
    from .arrangement import expanded_notes
    notes = [n for n in expanded_notes(placed) if n["beat"] in (head, tail)]
    at_head = [n for n in notes if n["beat"] == head]
    if len(at_head) != 1:
        return None
    note = at_head[0]
    direction = note["direction"] if note["direction"] != 8 else 1
    vx, vy = _VECTORS[direction]
    x, y = min(3, max(0, note["x"] + vx)), min(2, max(0, note["y"] + vy))
    busy = {(n["x"], n["y"]) for n in notes if n["beat"] == tail and n["color"] != note["color"]}
    if (x, y) in busy:
        x, y = note["x"], note["y"]
    return {"x": note["x"], "y": note["y"], "color": note["color"], "direction": direction,
            "tail_x": x, "tail_y": y, "tail_direction": _OPPOSITE[direction]}


def _place_draft(base, chosen, arcs):
    """(draft, placement) for the chosen times; drafted arcs take their hand, cut and cell from a first placement."""
    draft = _with_notes(base, chosen)
    placed = place_arrangement(draft, strict=False, alternatives=False, thorough=False)
    if not arcs:
        return draft, placed
    fields = [(head, tail, _arc_fields(placed["arrangement"], head, tail)) for head, tail, _ in arcs]
    draft = _with_notes(base, chosen, [(h, t, f) for h, t, f in fields if f is not None])
    return draft, place_arrangement(draft, strict=False, alternatives=False, thorough=False)


def propose_rhythm(arrangement: dict, report: dict, *, start: float | None = None, end: float | None = None,
                   tier: str | None = None, tier_reference: dict | None = None, held=(),
                   listen: list | None = None) -> dict:
    """A rhythm draft for [start, end) (default: the whole song); see the module docstring.

    Returns ``{"range", "tier", "bars", "arcs", "themes", "draft", "placement", "remaining", "rounds"}``.
    ``draft`` is the arrangement with the range's free notes replaced by rhythm-only notes (``id`` and ``beat``,
    two on a double, two or three marked ``stack`` on a stack) and the drafted arcs, ready to edit and save.
    ``held`` names held vocals (source seconds) the user asked for. ``listen`` is the listen run's section list:
    with the stems' rhythm it finds the song's recurring parts, and the draft declares a theme for each one
    touching the range (``themes``, kept beside any the arrangement already declares), so the placer plays a
    returning part like its first occurrence.
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
    themes = [t for t in propose_themes(base, report, listen)
              if any(_beat(span["start_beat"]) < last and first < _beat(span["end_beat"])
                     for span in t["spans"])]
    if themes:
        base["themes"] = list(base.get("themes") or []) + themes
    evidence = _Evidence(base, report)
    # The rest of the map may itself be a rhythm-only draft: judge it as placed.
    context = place_arrangement(base, strict=False, alternatives=False)["arrangement"]
    singing = {b["start_beat"] for b in critique_arrangement(context, report)["metrics"]["salience"].get("bars", [])
               if b["salient"] == "vocals"}
    seconds = lambda beat: beat_to_seconds(beat, base)
    arcs = _arcs(evidence, first, last, base, held, ARC_SCALE[settings_of(base)["arcs"]])
    holds = _holds(base) + [(head, tail) for head, tail, _ in arcs]
    bars, pool, reserve, doubles = [], [], [], []
    first_bar = int(first // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS
    loudness = _loudness(evidence, 0, math.ceil(song_end))
    keep = lambda item: first <= item["beat"] < last and evidence.strength_at(item["beat"]) > 0
    for bar in range(first_bar, math.ceil(last), SALIENCE_BAR_BEATS):
        relative = loudness.get(bar, 1.0)
        summary, primary, extra, accents = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier,
                                                           soft=relative < SOFT_RATIO, holds=holds,
                                                           loud=relative >= LOUD_RATIO)
        pool += [c for c in primary if keep(c)]
        reserve += [c for c in extra if keep(c)]
        doubles += [c for c in accents if keep(c)]
        bars.append(summary)
    for head, tail, found in arcs:
        pool += [{"beat": head, "strength": 1.0, "role": "arc", "evidence": found},
                 {"beat": tail, "strength": 1.0, "role": "arc", "evidence": {**found, "role": "tail"}}]
    needs = _lead_needs(evidence, bars)
    evidence.soft = {bar["start_beat"]: bar["soft"] for bar in bars}
    caps = _bar_caps(bars, loudness, tier, tier_reference, seconds)
    gaps = {bar["start_beat"]: SOFT_GAP_BEATS for bar in bars if bar["role"] == "soft"}
    chosen = _spaced(pool, fixed, holds, seconds, caps, gaps)
    _band_share(chosen, bars, evidence, holds)
    _mark_doubles(chosen, doubles, fixed, holds, seconds)
    removed, history = set(), []
    best = None
    crowded = lambda beat, others: _too_close(beat, others, holds, seconds, gaps.get(_bar_of(beat), MIN_GAP_BEATS))
    for rounds in range(1, MAX_ROUNDS + 1):
        live = [(h, t, e) for h, t, e in arcs if h in chosen and t in chosen]
        draft, placed = _place_draft(base, chosen, live)
        issues = [{"code": e["rule"], "beats": [e["beat"], e["beat"]], "object_ids": e["object_ids"],
                   "message": e["message"]} for e in placed["errors"]]
        critique = critique_arrangement(placed["arrangement"], report)
        issues += [w for w in critique["warnings"] if w["code"] in TARGET_CODES and _overlaps(w, placed, first, last)]
        score = len(issues)
        if best is None or score < best[0]:
            best = (score, {b: dict(i) for b, i in chosen.items()}, draft, placed, issues, rounds, live, critique)
        if not issues:
            break
        changed = _adjust(chosen, issues, placed["arrangement"], evidence, reserve, fixed, removed, critique,
                          crowded, needs, arcs)
        history.append({"round": rounds, "findings": _count(issues), "changes": changed})
        if not changed:
            break
    score, chosen, draft, placed, issues, rounds, live, critique = best
    issues = issues + _follow_findings(placed, report, critique, first, last)
    by_bar = {}
    for beat, item in sorted(chosen.items()):
        by_bar.setdefault(_bar_of(beat), []).append(
            {"beat": _relative(beat), "role": item["role"], "evidence": item["evidence"],
             **({"double": True} if item.get("double") else {}),
             **({"stack": item["stack"]} if item.get("stack") else {})})
    for bar in bars:
        bar["relative_loudness"] = round(loudness.get(bar["start_beat"], 0.0), 3)
        bar["cap"] = caps.get(bar["start_beat"])
        bar["notes"] = by_bar.get(bar["start_beat"], [])
    return {"range": [_relative(first), _relative(last)], "tier": tier,
            "note_count": sum(i.get("stack") or (2 if i.get("double") else 1) for i in chosen.values()),
            "bars": bars, "arcs": [{"head": _relative(h), "tail": _relative(t), "evidence": e} for h, t, e in live],
            "themes": themes,
            "draft": draft, "placement": placed["report"], "rounds": rounds, "history": history,
            "remaining": [{k: w.get(k) for k in ("code", "beats", "message", "suggestions") if k in w}
                          for w in issues]}


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


def _follow_findings(placed, report, critique, first, last):
    """``project check``'s FOLLOW_CODES findings on the placed draft inside [first, last), with its suggestions."""
    from .arrangement import expanded_notes
    from .audio_grounding import audio_findings
    from .check import _finding
    arrangement = placed["arrangement"]
    beats = {n["id"]: float(n["beat"]) for n in expanded_notes(arrangement)}
    raw = [w for w in critique["warnings"] if w["code"] in FOLLOW_CODES]
    raw += [f for f in audio_findings(arrangement, report)[1] if f["code"] in FOLLOW_CODES]
    found = [_finding(f, "draft", beats) for f in raw if _overlaps(f, placed, first, last)]
    if found:
        audio_suggestions(arrangement, report, found)
    return found


def _note_beats(arrangement, ids):
    from .arrangement import expanded_notes
    ids = set(ids)
    return [n["beat"] for n in expanded_notes(arrangement) if n["id"] in ids]


def _adjust(chosen, issues, placed, evidence, reserve, fixed, removed, critique, crowded, needs, arcs=None):
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

    def move_arc_head(old, new):
        """Start a drafted arc on ``new`` (a lead attack its head crowds), keeping at least half a beat of hold."""
        for index, (head, tail, found) in enumerate(arcs or []):
            if head == old and tail - new >= Fraction(1, 2):
                arcs[index] = (new, tail, found)
                chosen[new] = {**chosen.pop(old), "beat": new}
                return True
        return False

    def add(item, force=False):
        nonlocal changes
        beat = item["beat"]
        if beat in chosen or (beat in removed and not force):
            return False
        others = [b for b in chosen if abs(b - beat) < 1]
        blocking = [b for b in others if crowded(beat, [b])]
        if force and item["role"] == "lead" and len(blocking) == 1 and chosen[blocking[0]]["role"] == "arc":
            if move_arc_head(blocking[0], beat):
                changes += 1
                return True
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
        if chosen[beat]["role"] == "arc":
            return True  # an arc's head or tail note
        if not attacks:
            return False
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
        elif code in ("stack_shape", "stack_touch", "cut_path_blocked") and any(
                chosen.get(b, {}).get("stack") for b in _note_beats(placed, issue.get("object_ids") or [])):
            # A stack the placer cannot lay out beside its neighbours is cut as one note.
            for beat in _note_beats(placed, issue.get("object_ids") or []):
                if chosen.get(beat, {}).get("stack"):
                    chosen[beat] = {k: v for k, v in chosen[beat].items() if k != "stack"}
                    changes += 1
        elif code in ("one_hand_burst", "fast_direction_break", "flow_parity_break", "wrist_roll", "hidden_note",
                      "arc_note_conflict", "chain_note_conflict", "reach_proxy", "stack_shape", "stack_touch",
                      "cut_path_blocked"):
            targets = sorted({b for b in _note_beats(placed, issue.get("object_ids") or []) if b in chosen})
            # Dropping any swing of a run exactly BURST_SWINGS long ends it, so the weakest sound goes; a longer
            # run splits in the middle.
            inner = targets if code == "one_hand_burst" and len(targets) <= BURST_SWINGS else targets[1:-1]
            victim = weakest(inner or targets) or (inner or targets or [None])[0]
            if victim is not None:
                drop(victim)
        elif code == "density_exceeds_audio":
            if not thin(inside, 2, free_only=True):
                # Only arc anchors are left: a drafted arc inside a thin passage gives way.
                for head, tail, found in list(arcs or []):
                    if span[0] <= head < span[1]:
                        arcs.remove((head, tail, found))
                        drop(head, banned=False)
                        drop(tail, banned=False)
                        break
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
        if bar["quiet"] or bar["declared"] in (None, "vocals"):
            continue
        found = evidence.events(bar["declared"], LEAD_METHODS, LEAD_SUPPORT_STRENGTH)
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
                item = _candidate(evidence, beat, s, "lead", lead, m, beat, t)
                if evidence.strength_at(item["beat"]) > 0:
                    found.append(item)
    return found


# ---------------------------------------------------------------------------------------------------------
# Suggestions for the audio and critique codes (project check)
# ---------------------------------------------------------------------------------------------------------

AUDIO_SUGGESTED = ("audio_unmapped", "note_without_audio", "density_exceeds_audio", "difficulty_exceeds_intensity",
                   "lead_rhythm_diluted", "lead_rhythm_unmapped", "vocal_line_unmapped", "drum_rhythm_unmapped",
                   "drum_entry_unmapped", "melody_unmapped", "ensemble_unmapped", "boundary_accent_unmapped",
                   "density_collapse", "intensity_underplayed", "focus_on_quiet_stem", "unison_hit_unstacked",
                   "stack_too_tall", "note_off_sound")
RETIME_REACH = Fraction(1, 2)


def audio_suggestions(arrangement: dict, report: dict | None, findings: list[dict]) -> None:
    """Attach concrete edits to audio and critique findings, drawn from the rhythm draft's own generators.

    ``arrangement`` is placed. Additions are rhythm-only notes (``beat`` plus the evidence) that the placer
    places on save; removals and retimes name the notes; ``set_weights`` rewrites a focus phrase; ``stack`` turns
    the note on a unison hit into a stack (a note of the other hand at that time stays).
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
    # An arc or chain end is a note of its own: removing it leaves the arc without the note it needs.
    anchored = {(beat, values["color"]) for beat, values, _ in _anchors_and_holds(arrangement)[0]}
    removable = lambda note: (note["beat"], note["color"]) not in anchored

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
        editable = [by_id[i] for i in ids if i in by_id and "/note/" in i and removable(by_id[i])]
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
                _, primary, _, _ = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier, bar in soft)
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
                    target = grid_beat(beat, evidence.reach)
                    if abs(target - note["beat"]) <= RETIME_REACH and target != note["beat"]:
                        crowded = any(abs(target - t) < MIN_GAP_BEATS for t in times if t != note["beat"])
                        if not crowded and evidence.strength_at(target) > 0:
                            options.append((abs(target - note["beat"]), -strength, target))
                if options:
                    finding["suggestions"].append({"op": "retime", "object_id": oid,
                                                   "to_beat": _relative(min(options)[2]),
                                                   "reason": "move onto the nearest supporting onset"})
                elif removable(note):
                    finding["suggestions"].append({"op": "remove", "object_id": oid,
                                                   "reason": f"no onset within {RETIME_REACH} beat"})
        elif code == "note_off_sound":
            # A retime carries the arc or chain end on the note with it; an end cannot be removed.
            for oid in finding["object_ids"]:
                note = by_id.get(oid)
                if note is None or "/note/" not in oid:
                    continue
                target = _on_sound(evidence, note["beat"])
                if target is None or target == note["beat"]:
                    continue
                if not any(abs(target - t) < MIN_GAP_BEATS for t in times if t != note["beat"]):
                    finding["suggestions"].append({"op": "retime", "object_id": oid, "to_beat": _relative(target),
                                                   "reason": "move onto the strongest sound under the note, "
                                                             "on its own time"})
                elif (note["beat"], note["color"]) not in anchored:
                    finding["suggestions"].append({"op": "remove", "object_id": oid,
                                                   "reason": "its sound sits within a sixteenth of the next note"})
        elif code == "lead_rhythm_diluted":
            stray = [i for i in finding["object_ids"] if "/note/" in i and i in by_id and removable(by_id[i])]
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
                pool = [_candidate(evidence, b, s, "drums", "drums", "spectral_flux", b, beat_to_seconds(b, arrangement))
                        for b, s in strongest_per_slot(hits, DRUM_SLOTS_PER_BEAT)]
            elif code == "melody_unmapped":
                pool = [_candidate(evidence, b, 0.3, "melody", "mix", "melody_change", b, beat_to_seconds(b, arrangement),
                                   melodic=True) for b in melody_onsets(report, arrangement, float(first), float(last))]
            else:
                roles = {"lead_rhythm_unmapped": ("lead", "run"), "vocal_line_unmapped": ("lead", "vocals")}.get(code)
                for bar in range(int(first // SALIENCE_BAR_BEATS) * SALIENCE_BAR_BEATS, math.ceil(last),
                                 SALIENCE_BAR_BEATS):
                    _, primary, reserve, _ = _bar_candidates(evidence, bar, bar + SALIENCE_BAR_BEATS, singing, tier,
                                                          bar in soft)
                    picks = [c for c in primary if roles is None or c["role"] in roles]
                    picks += reserve if code in ("intensity_underplayed", "density_collapse") else []
                    pool += [c for c in picks if first <= c["beat"] < last]
            add(finding, pool, "map the sounds this finding names")
        elif code in ("ensemble_unmapped", "boundary_accent_unmapped"):
            targets = finding.get("targets") or ([[float(first), 1.0]] if first is not None else [])
            pool = [_candidate(evidence, beat, strength, "ensemble", "mix", "spectral_flux", beat, beat_to_seconds(beat, arrangement))
                    for beat, strength in targets]
            add(finding, pool, "map the band's heaviest accents")
        elif code == "focus_on_quiet_stem":
            finding["suggestions"] += focus_weights(arrangement, report, context, finding.get("section_id"))
        elif code == "stack_too_tall":
            # Drop the stack's last note (an added partner before the note it was built on); the rest stays a pair.
            literal = sorted((i for i in finding["object_ids"] if "/note/" in i),
                             key=lambda i: (i.split("/")[-1].startswith(("k-", "r-")), i))
            if len(literal) >= 3:
                finding["suggestions"].append({"op": "remove", "object_id": literal[-1],
                                               "reason": "a stack of two carries this hit"})
        elif code == "unison_hit_unstacked" and finding.get("targets"):
            onset, size = finding["targets"][0]
            target = grid_beat(float(onset), evidence.reach)
            literal = sorted((by_id[i] for i in finding["object_ids"] if i in by_id and "/note/" in i),
                             key=lambda n: (abs(n["beat"] - target), n["beat"]))
            why = "cut the unison hit as a stack: one hand, notes in a line along the cut"
            if literal:
                finding["suggestions"].append({"op": "stack", "object_id": literal[0]["id"], "size": size,
                                               "reason": why})
            elif not any(abs(target - t) < MIN_GAP_BEATS for t in times):
                finding["suggestions"].append({"op": "stack", "beat": _relative(target), "size": size,
                                               "reason": why})


def _on_sound(evidence, beat):
    """The time of the strongest supporting sound under ``beat`` (within the audio support window), snapped to
    the coarsest grid that stays within SNAP_SECONDS of it; None when no sound is there."""
    seconds = beat_to_seconds(beat, evidence.arrangement)
    lo = bisect_left(evidence.support, seconds - evidence.tolerance)
    hi = bisect_left(evidence.support, seconds + evidence.tolerance + 1e-12)
    if lo == hi:
        return None
    strongest = max(range(lo, hi), key=lambda i: (evidence.support_strength[i], -abs(evidence.support[i] - seconds)))
    return grid_beat(evidence.to_beat(evidence.support[strongest]), evidence.reach)


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
