"""Descriptive, non-blocking critique of an arrangement.

Every finding is a warning: the critique never blocks compilation and never
models playability. It reports explicit, reproducible metrics so an authoring
agent can compare a rewrite against an earlier baseline.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from fractions import Fraction
import math
from statistics import median

from .arrangement import expanded_notes
from .audio_grounding import DEFINITIONS as AUDIO_DEFINITIONS, audio_findings
from .lighting import DEFINITIONS as LIGHT_DEFINITIONS, lighting_findings
from .movement import analyze_movement
from .tier_fit import DEFINITIONS as TIER_DEFINITIONS, tier_fit

MODEL_VERSION = "1.0"
WINDOW_SECONDS = 4.0
HOP_SECONDS = 1.0
HEAD_SECONDS = 8.0
TAIL_SECONDS = 8.0
PROBE_SECONDS = 2.0
PROBE_HOP_SECONDS = 0.5
COLLAPSE_RATIO = 0.6
MIN_COLLAPSE_NOTES = 8
CYCLE_RANGE = range(2, 17)
CYCLE_THRESHOLD = 0.6
ENTROPY_WINDOW = 64
ENTROPY_HOP = 16
ENTROPY_THRESHOLD = 2.5
TOP_ROW_THRESHOLD = 0.05
TOP_ROW_MIN_NOTES = 100
SEAM_BEATS = 0.25
ACCENT_STRENGTH = 0.7
SUSTAIN_SECONDS = 0.7
SUSTAIN_ARC_BEATS = 0.5
SALIENCE_BAR_BEATS = 4
SALIENCE_MATCH_BEATS = 0.13
VOCAL_ONSET_STRENGTH = 0.25
DRUM_ONSET_STRENGTH = 0.3
SINGING_SUSTAIN_COVERAGE = 0.25
SINGING_MIN_ONSETS = 2
DRUM_PATTERN_MIN_ONSETS = 6
VOCAL_MAPPED_THRESHOLD = 0.5
DRUM_MAPPED_THRESHOLD = 0.6
SALIENCE_MIN_BARS = 1
DRUM_SLOTS_PER_BEAT = 2
LEAD_ONSET_METHODS = ("spectral_flux", "pitch_change", "chord_change")
LEAD_ONSET_STRENGTH = 0.3
LEAD_SUPPORT_STRENGTH = 0.2
LEAD_MIN_ONSETS = 3
LEAD_MIN_NOTES = 4
LEAD_GAP_BEATS = 0.75
LEAD_MAPPED_THRESHOLD = 0.6
LEAD_CONSISTENT_THRESHOLD = 0.75
GRID_WINDOW_BEATS = 32
GRID_MIN_ONSETS = 8
GRID_ON_GRID_BEATS = 0.1
GRID_DRIFT_SECONDS = 0.03
QUIET_WINDOW_SECONDS = 8.0
QUIET_HOP_SECONDS = 2.0
QUIET_SUPPORT = 0.6
QUIET_ENERGY = 0.75
FULL_SUPPORT = 0.9
QUIET_DENSITY_TOLERANCE = 1.5
QUIET_MIN_NOTES = 6
QUIET_STEM_DB = 20.0
STEM_REFERENCE_PERCENTILE = 90
FOCUS_STEM_WEIGHT = 0.3
MELODY_LAYER = "mix"
MELODY_ONSET_STRENGTH = 0.3
MELODY_MIN_CHANGES = 3
MELODY_MAPPED_THRESHOLD = 0.5
# A bit of the whole band under the lead: the heaviest accents of the other stems.
ENSEMBLE_STRENGTH = 0.6
# A heavy hit is heard in the whole mix too: a stem's swell back from sidechain ducking (bass pumping
# after every kick) peaks in the stem's spectral flux but is no attack in the mix.
ENSEMBLE_MIX_STRENGTH = 0.3
ENSEMBLE_WINDOW_BEATS = 16
ENSEMBLE_MIN_ACCENTS = 3
ENSEMBLE_MIN_NOTES = 4
ENSEMBLE_MAPPED_THRESHOLD = 0.2
ENSEMBLE_ALLOWANCE_PER_BAR = 1
# A unison hit: the drums and at least two more separated stems attack together (each spectral_flux
# UNISON_STEM_STRENGTH or more within UNISON_SECONDS) under a mix attack among the song's loudest
# (UNISON_MIX_PERCENTILE of its mix attacks), in a loud bar. One hand cuts it as a stack, one longer note:
# two notes, three when UNISON_TALL_STEMS or more stems join.
UNISON_SECONDS = 0.05
UNISON_STEM_STRENGTH = 0.4
UNISON_MIN_STEMS = 3
UNISON_TALL_STEMS = 4
UNISON_MIX_PERCENTILE = 85
UNISON_PER_BAR = 3
ENTRY_LAYER = "drums"
ENTRY_WINDOW_BEATS = 4
ENTRY_MIN_HITS = 2
ENTRY_MAPPED_THRESHOLD = 0.5
FOCUS_CODES = ("vocal_line_unmapped", "drum_rhythm_unmapped", "lead_rhythm_unmapped",
               "lead_rhythm_diluted", "melody_unmapped", "focus_on_quiet_stem", "difficulty_exceeds_intensity",
               "intensity_underplayed", "drum_entry_unmapped", "ensemble_unmapped")
INTENSITY_BAR_BEATS = 4
INTENSITY_LOUD_PERCENTILE = 75
LOUD_RATIO = 0.9
SOFT_RATIO = 0.8
INTENSITY_MIN_LOUD_BARS = 4
INTENSITY_MIN_SWINGS = 4
DEMAND_TRAVEL_BEATS = 1.0
SOFT_PEAK_PERCENTILE = 90
UNDERPLAYED_MIN_BARS = 2

DEFINITIONS = {
    "rolling_nps": "Notes per second inside 4-second windows hopped every 1 second from the first note to the last.",
    "section_nps": "Notes in a section divided by that section's length in seconds.",
    "overall_nps": "All notes divided by the seconds between the first and the last note.",
    "distinct_placements": "Number of distinct (lane x, row y, colour, cut direction) tuples used anywhere in the map.",
    "placement_histogram": "The twelve most frequent placements with their counts.",
    "cycle_coverage": "For each period k in 2..16, the fraction of notes i >= k whose placement equals the placement k notes earlier; the reported k is the period with the highest fraction.",
    "placement_entropy": "Shannon entropy in bits of the placement distribution inside rolling windows of 64 consecutive notes hopped by 16 notes, reported as the minimum and median across windows.",
    "top_row_share": "Fraction of notes sitting on the top row (y == 2).",
    "lane_histogram": "Note counts per lane (x = 0..3).",
    "row_histogram": "Note counts per row (y = 0..2).",
    "arc_count": "Number of arcs (sliders), overall and per section.",
    "chain_count": "Number of chains (burst sliders), overall and per section.",
    "arc_vertical_travel": "Histogram of each arc's tail_y minus y, that is how many rows the arc travels.",
    "long_vocal_sustains": "Sustains of at least 0.7 s reported for a vocals layer, present only when the musical evidence run provides sustains.",
    "sustains_covered_by_arcs": "How many of those long vocal sustains start within 0.5 beat of an arc head.",
    "density_collapse": "At a section boundary S to T, the sparsest 2 s window (hopped 0.5 s) inside the last 8 s of S, ignoring windows an arc is held through, runs below 0.6 times the median rolling window fully inside S while the first 8 s of T runs above that median, and S holds at least 8 notes.",
    "repetitive_cycle": "The best cycle coverage over periods 2..16 reaches 0.6 or more, meaning most notes repeat the placement of a fixed number of notes earlier.",
    "low_placement_variety": "The median 64-note window placement entropy falls below 2.5 bits.",
    "top_row_starved": "Fewer than 5% of the notes sit on the top row in a map of at least 100 notes.",
    "boundary_accent_unmapped": "A non-energy_rise musical event of strength 0.7 or more sits within 0.25 beat of a section seam that carries no note within 0.25 beat.",
    "singing_bar": "A 4-beat bar (absolute beats 0, 4, 8...) where vocals sustains cover at least 25% and at least 2 vocals spectral_flux events of strength 0.25 or more start: articulated singing.",
    "vocal_line_unmapped": "One or more consecutive singing bars where fewer than 50% of those vocal onsets have a note within 0.13 beat or sit inside a vocal sustain held by an arc: the map follows another layer while the voice is the focal point.",
    "drum_rhythm_unmapped": "One or more consecutive non-singing bars (voice holding or resting) without a declared non-drum instrument lead (bar_lead), with at least 6 drums spectral_flux events of strength 0.3 or more (only the strongest per half-beat slot counts), fewer than 60% of which have a note within 0.13 beat.",
    "bar_lead": "The layer whose rhythm a 4-beat bar follows: vocals in a singing bar, otherwise the lead of the musical_focus phrase covering the bar's middle when that lead is an analyzed stem other than mix. Other bars have no declared lead and skip the lead checks.",
    "lead_rhythm_unmapped": "One or more consecutive bars led by an instrument stem (not vocals, which vocal_line_unmapped covers), outside thin, soft passages (mean passage support_score below 0.6 and energy_ratio below 0.75, where density_exceeds_audio sets the density), with at least 3 lead onsets (spectral_flux, pitch_change or chord_change of strength 0.3 or more, strongest per half-beat slot), fewer than 60% of which have a note within 0.13 beat. In a bar softer than 0.8 of the heavy passages' loudness (difficulty_exceeds_intensity), the onsets judged are the strongest per beat.",
    "lead_rhythm_diluted": "One or more consecutive bars with a declared lead, at least 3 lead onsets and at least 4 note times, where fewer than 75% of the note times follow the lead: a note follows it when a lead onset of strength 0.2 or more sits within 0.13 beat, when the lead is silent within 0.75 beat (a gap another layer may fill), or when an arc is held through it; a note on the bar's heaviest ensemble accent or on a unison_hit counts as following it. Filler between the lead's attacks flattens its syncopation into a metronome stream.",
    "melodic_bar": "A 4-beat bar that is not a singing bar, has no declared instrument lead (bar_lead) and fewer "
                   "than 6 strong drum hits: the drums do not carry it, so the pitched line is what the player hears.",
    "melody_unmapped": "One or more consecutive melodic bars with at least 3 mix melody_change events (the predominant "
                       "pitch settling on a new held note) of strength 0.3 or more, strongest per half-beat slot, "
                       "fewer than 50% of which have a note within 0.13 beat: the notes ignore the pitch changes of "
                       "a pad, choir or legato line.",
    "grid_alignment": "For each 32-beat window, the median signed offset in milliseconds of strong drums (else percussive, low or mix) spectral_flux onsets of strength 0.3 or more from the nearest quarter beat, counting only onsets within 0.1 beat of it; windows need at least 8 such onsets.",
    "grid_drift": "Some grid_alignment window's median offset differs from the song-wide median by more than 30 ms: the tempo or offset drifts there, so notes placed on the grid miss the audio.",
    "density_exceeds_audio": "An 8 s window (hopped 2 s) whose mean passage energy_ratio is below 0.75 and mean support_score "
                             "(drum onset density and mix energy, from the evidence run) below 0.6 holds at least 6 "
                             "notes and more than 1.5 "
                             "times support_score x the reference density, the median notes per second of windows "
                             "with support 0.9 or more, counting only notes that are not on a vocal, drum or melody onset the salience "
                             "checks count: the map plays a thin, quiet passage as hard as the full band.",
    "focus_on_quiet_stem": "A musical_focus phrase gives weight 0.3 or more to a separated stem whose median energy_contour level inside the phrase is at least 20 dB below that stem's own 90th-percentile level over the song: the stem is essentially absent there, so its events are separator bleed (for example vocals in an instrumental intro) or the instrument was routed to another stem (for example a soft solo piano in other while the piano stem is silent). The message names the most active stem, measured the same way.",
    "ensemble_accent": "The strongest spectral_flux attack per beat, of strength 0.6 or more, in a separated stem other "
                       "than the bar's lead (and not mix), with a mix spectral_flux onset of strength 0.3 or more and no "
                       "lead onset of strength 0.2 or more within 0.13 beat: the rest of the band hitting hard under "
                       "the lead, audible in the whole mix (a stem swelling back from sidechain ducking is not).",
    "ensemble_unmapped": "A 16-beat window (absolute beats 0, 16, 32...) with at least 4 note times whose bars have a lead "
                         "(the salient layer: vocals, a declared lead, or a drum pattern; thin, soft bars excluded) and at "
                         "least 3 ensemble accents, fewer than 20% of which have a note within 0.13 beat: the map follows "
                         "one layer alone instead of carrying the whole song's weight. A note on a bar's heaviest ensemble "
                         "accent also counts as following the lead for lead_rhythm_diluted (one per bar).",
    "unison_hit": "A mix spectral_flux attack at or above the song's 85th percentile of mix attacks (strength 0.3 or "
                  "more) where the drums and at least two other separated stems each attack (spectral_flux 0.4 or "
                  "more) within 0.05 s, in a bar with relative_loudness 0.9 or more that is not thin and soft; at "
                  "most the 3 strongest per 4-beat bar, a beat apart (within 0.13 beat), none while arcs or chains hold both sabers "
                  "(under one hold the free hand cuts it). "
                  "Its stack size is 3 when 4 or more stems join, else 2.",
    "unison_hit_unstacked": "A unison_hit whose sound (notes within 0.13 beat) carries no stack: no two notes of one "
                            "hand at one beat. Several instruments striking at once read as one heavier hit, cut by "
                            "one hand as a stack of 2 or 3 notes in a line along the cut.",
    "layer_entry": "A separated stem becoming audible (within 20 dB of its own 90th-percentile level and within 30 dB of "
                   "the mix) after at least 4 s of absence and staying audible for most of the next 2 s; the entry sits on "
                   "its first strong attack.",
    "drum_entry_unmapped": "At a drums layer_entry inside the map, the 4 beats from the entry hold at least 2 strong drum "
                           "hits (spectral_flux 0.3 or more, strongest per half-beat), fewer than 50% of which have a "
                           "note within 0.13 beat: the drums arrive and the map does not react.",
    "swing_demand": "Per 4-beat bar, the sum over its swings (movement-model swings; a same-hand chord is one) of 1 "
                    "plus the grid distance from the same hand's previous swing when that swing is at most 1 beat "
                    "earlier, divided by the bar's seconds: how often and how far the hands must move.",
    "relative_loudness": "A bar's mix energy_ratio (evidence passages, overlap-weighted) divided by the 75th "
                         "percentile over the mapped bars: 1.0 is the level of the song's loud, heavy passages.",
    "difficulty_exceeds_intensity": "One or more consecutive bars with relative_loudness below 0.8 and at least 4 "
                                    "swings whose swing_demand exceeds the median demand of the loud bars "
                                    "(relative_loudness 0.9 or more, at least 4 mapped) times (0.5 + 0.5 x "
                                    "relative_loudness): softer audio plays as hard as the heavy passages.",
    "intensity_underplayed": "Two or more consecutive loud bars (relative_loudness 0.9 or more) whose mean "
                             "swing_demand is below the 90th percentile of the softer bars' demand (relative_loudness "
                             "below 0.8, at least 2 mapped): the heavy passage plays easier than the quieter ones.",
    **AUDIO_DEFINITIONS,
    **LIGHT_DEFINITIONS,
    **TIER_DEFINITIONS,
}


def beat_to_seconds(beat, arrangement) -> float:
    """Convert an absolute beat to source-audio seconds; beat 0 is the audio offset."""
    beat = float(beat)
    tempo, previous = arrangement["song"]["bpm"], 0.0
    seconds = float(arrangement["song"]["audio_offset_seconds"])
    for event in sorted(arrangement.get("tempo_events", []) or [],
                        key=lambda e: float(Fraction(str(e["beat"])))):
        at = float(Fraction(str(event["beat"])))
        if beat < at:
            break
        seconds += (at - previous) * 60 / tempo
        previous, tempo = at, event["bpm"]
    return seconds + (beat - previous) * 60 / tempo


def _round(value, digits=6):
    return round(float(value), digits)


def _count_between(times, start, end):
    """Count sorted note times with start <= seconds < end."""
    return bisect_left(times, end) - bisect_left(times, start)


def _entropy(values):
    counts = Counter(values)
    total = sum(counts.values())
    return -sum((c / total) * math.log2(c / total) for c in counts.values()) if total else 0.0


def _rolling(times):
    if not times:
        return []
    first, last, windows, index = times[0], times[-1], [], 0
    while True:
        start = first + index * HOP_SECONDS
        windows.append({"start_seconds": _round(start), "end_seconds": _round(start + WINDOW_SECONDS),
                        "nps": _round(_count_between(times, start, start + WINDOW_SECONDS) / WINDOW_SECONDS)})
        index += 1
        if first + index * HOP_SECONDS >= last:
            return windows


def _sections(arrangement):
    spans = []
    for section in arrangement["sections"]:
        start = float(Fraction(str(section["start_beat"])))
        end = start + float(Fraction(str(section.get("length_beats", 0))))
        spans.append({"section": section, "id": section["id"], "start_beat": start, "end_beat": end,
                      "start_seconds": beat_to_seconds(start, arrangement),
                      "end_seconds": beat_to_seconds(end, arrangement)})
    return spans


def _empty_density(spans):
    return {"rolling_nps": [], "overall_nps": 0.0,
            "section_nps": [{"section_id": s["id"], "note_count": 0, "nps": 0.0,
                             "seconds": _round(s["end_seconds"] - s["start_seconds"])} for s in spans]}


def _empty_repetition():
    return {"distinct_placements": 0, "placement_histogram": [],
            "cycle_coverage": {"k": None, "coverage": 0.0},
            "placement_entropy": {"window_notes": ENTROPY_WINDOW, "hop_notes": ENTROPY_HOP,
                                  "windows": 0, "min": 0.0, "median": 0.0},
            "top_row_share": 0.0, "lane_histogram": {str(x): 0 for x in range(4)},
            "row_histogram": {str(y): 0 for y in range(3)}}


def _density(arrangement, notes, times, spans, warn):
    from .musical import seconds_to_beat
    rolling = _rolling(times)
    counts = Counter(note["section_id"] for note in notes)
    per_section = []
    for span in spans:
        seconds = span["end_seconds"] - span["start_seconds"]
        per_section.append({"section_id": span["id"], "note_count": counts.get(span["id"], 0),
                            "seconds": _round(seconds),
                            "nps": _round(counts.get(span["id"], 0) / seconds) if seconds > 0 else 0.0})
    span_seconds = times[-1] - times[0]
    # A hand holding an arc through a window is playing the held sound, not resting.
    holds = [(beat_to_seconds(span["start_beat"] + float(Fraction(str(arc["beat"]))), arrangement),
              beat_to_seconds(span["start_beat"] + float(Fraction(str(arc["tail_beat"]))), arrangement))
             for span in spans for arc in span["section"].get("arcs") or []]
    for left, right in zip(spans, spans[1:]):
        inside = [w["nps"] for w in rolling if w["start_seconds"] >= left["start_seconds"] - 1e-9
                  and w["end_seconds"] <= left["end_seconds"] + 1e-9]
        if not inside or counts.get(left["id"], 0) < MIN_COLLAPSE_NOTES:
            continue
        s_med = median(inside)
        if s_med <= 0:
            continue
        # Sparsest PROBE_SECONDS window inside the section's last TAIL_SECONDS, so a short
        # hole right before a denser section is not averaged away by a wide window.
        probes = []
        start = max(left["start_seconds"], left["end_seconds"] - TAIL_SECONDS)
        cursor = start
        while cursor + PROBE_SECONDS <= left["end_seconds"] + 1e-9:
            held = any(head < cursor + PROBE_SECONDS and tail > cursor for head, tail in holds)
            if not held:
                probes.append((cursor, _count_between(times, cursor, cursor + PROBE_SECONDS) / PROBE_SECONDS))
            cursor += PROBE_HOP_SECONDS
        if not probes:
            continue
        tail_start, pre = min(probes, key=lambda item: (item[1], -item[0]))
        head = _count_between(times, right["start_seconds"],
                              right["start_seconds"] + HEAD_SECONDS) / HEAD_SECONDS
        if pre >= COLLAPSE_RATIO * s_med or head <= s_med:
            continue
        tail_beat = seconds_to_beat(tail_start, arrangement)
        tail_end_beat = seconds_to_beat(tail_start + PROBE_SECONDS, arrangement)
        warn("density_collapse",
             f'Section "{left["id"]}" empties before "{right["id"]}": its sparsest {PROBE_SECONDS:g} s window '
             f'in the last {TAIL_SECONDS:g} s (beats {tail_beat:.2f}-{tail_end_beat:.2f}) runs {pre:.2f} nps '
             f'against a {s_med:.2f} nps section median, while "{right["id"]}" opens at {head:.2f} nps.',
             section_id=left["id"], value=_round(pre / s_med, 4), threshold=COLLAPSE_RATIO,
             beats=[_round(tail_beat, 4), _round(tail_end_beat, 4)],
             object_ids=[note["id"] for note in notes if note["section_id"] == left["id"]
                         and tail_start <= beat_to_seconds(note["beat"], arrangement) < tail_start + PROBE_SECONDS])
    return {"rolling_nps": rolling, "section_nps": per_section,
            "overall_nps": _round(len(times) / span_seconds) if span_seconds > 0 else 0.0}


def salient_onsets(arrangement, report):
    """(sorted seconds, tolerance) of the vocal, drum and melody onsets the salience checks count."""
    layers = (report or {}).get("layers") or {}
    found = sorted(float(e["seconds"]) for name, threshold, method in (
                       ("vocals", VOCAL_ONSET_STRENGTH, "spectral_flux"),
                       ("drums", DRUM_ONSET_STRENGTH, "spectral_flux"),
                       (MELODY_LAYER, MELODY_ONSET_STRENGTH, "melody_change"))
                   for e in (layers.get(name) or {}).get("events", [])
                   if e.get("method") == method and e.get("strength", 0) >= threshold)
    return found, SALIENCE_MATCH_BEATS * 60 / float(arrangement["song"]["bpm"])


def on_onset(onsets, tolerance, seconds):
    index = bisect_left(onsets, seconds - tolerance)
    return index < len(onsets) and onsets[index] <= seconds + tolerance


def quiet_windows(arrangement, times, report):
    """8 s windows with their audio support, note count and allowed notes per second.

    Returns ``(reference_nps, windows)``; ``reference_nps`` is None when the evidence run has no
    passages or the map never plays a full-intensity window.
    """
    passages = (report or {}).get("passages") or []
    if not passages or not times:
        return None, []
    from .musical import seconds_to_beat
    salient, tolerance = salient_onsets(arrangement, report)
    free = [t for t in times if not on_onset(salient, tolerance, t)]  # notes the voice, drums or melody do not justify
    end, windows, start = max(p["end_seconds"] for p in passages), [], 0.0
    while start + QUIET_WINDOW_SECONDS <= end + 1e-9:
        stop = start + QUIET_WINDOW_SECONDS
        inside = [p for p in passages if p["start_seconds"] >= start - 1e-9 and p["end_seconds"] <= stop + 1e-9]
        if inside:
            count = _count_between(times, start, stop)
            windows.append({"start_seconds": start, "end_seconds": stop,
                            "start_beat": seconds_to_beat(start, arrangement),
                            "end_beat": seconds_to_beat(stop, arrangement),
                            "support": sum(p["support_score"] for p in inside) / len(inside),
                            "energy": sum(p["energy_ratio"] for p in inside) / len(inside), "notes": count,
                            "nps": count / QUIET_WINDOW_SECONDS,
                            "free_notes": _count_between(free, start, stop)})
        start += QUIET_HOP_SECONDS
    full = [w["nps"] for w in windows if w["support"] >= FULL_SUPPORT and w["notes"]]
    if not full:
        return None, windows
    reference = median(full)
    for window in windows:
        window["allowed_nps"] = QUIET_DENSITY_TOLERANCE * window["support"] * reference
        window["excess"] = (window["support"] < QUIET_SUPPORT and window["energy"] < QUIET_ENERGY
                            and window["notes"] >= QUIET_MIN_NOTES
                            and window["free_notes"] > window["allowed_nps"] * QUIET_WINDOW_SECONDS + 1e-9)
    return reference, windows


def _quiet_density(arrangement, spans, notes, times, report, warn):
    """Flag thin, quiet passages mapped as densely as the full band."""
    reference, windows = quiet_windows(arrangement, times, report)
    if reference is None:
        return {"checked": False}
    runs = []
    for window in windows:
        if not window["excess"]:
            continue
        if runs and window["start_seconds"] <= runs[-1][-1]["end_seconds"]:
            runs[-1].append(window)
        else:
            runs.append([window])
    for run in runs:
        first, last = run[0], run[-1]
        worst = max(run, key=lambda w: w["free_notes"] / w["allowed_nps"])
        section = next((s["id"] for s in spans if s["start_beat"] <= first["start_beat"] < s["end_beat"]), None)
        ids = [n["id"] for n in notes
               if first["start_seconds"] <= beat_to_seconds(n["beat"], arrangement) < last["end_seconds"]]
        warn("density_exceeds_audio",
             f'Beats {first["start_beat"]:.1f}-{last["end_beat"]:.1f} ({first["start_seconds"]:g}-'
             f'{last["end_seconds"]:g} s): the audio is thin here (support {worst["support"]:.2f}, mix energy '
             f'{worst["energy"]:.2f}x the song median, few drum hits) but the map plays {worst["nps"]:.2f} nps, '
             f'{worst["free_notes"] / QUIET_WINDOW_SECONDS:.2f} of them off the vocal, drum and melody onsets, above the '
             f'{worst["allowed_nps"]:.2f} nps this support allows against the {reference:.2f} nps full-band reference. Keep the strongest '
             "onsets and drop the rest.",
             section_id=section, value=round(worst["free_notes"] / QUIET_WINDOW_SECONDS / (worst["allowed_nps"] / QUIET_DENSITY_TOLERANCE), 4),
             threshold=QUIET_DENSITY_TOLERANCE, object_ids=ids,
             beats=[_round(first["start_beat"], 4), _round(last["end_beat"], 4)])
    return {"checked": True, "reference_nps": _round(reference, 4),
            "flagged": [[_round(r[0]["start_seconds"], 3), _round(r[-1]["end_seconds"], 3)] for r in runs]}


def _percentile(values, percent):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent / 100 + 0.5))]


def intensity_bars(arrangement, report, notes=None):
    """Per 4-beat bar: loudness relative to the song's heavy passages beside the swing demand mapped there.

    Returns ``(context, bars)``. ``context`` is None when the evidence run has no passages, the notes do not
    form a movement model, or fewer than INTENSITY_MIN_LOUD_BARS loud bars are mapped; the bars are then
    unrated. Each rated bar carries ``allowed`` (soft bars only) and ``excess``.
    """
    passages = (report or {}).get("passages") or []
    notes = expanded_notes(arrangement) if notes is None else notes
    if not passages or not notes:
        return None, []
    bpm = float(arrangement["song"]["bpm"])
    try:
        swings = analyze_movement([{"id": n["id"], "beat": float(n["beat"]), "x": n["x"], "y": n["y"],
                                    "color": n["color"], "direction": n["direction"],
                                    "angle": n.get("angle", 0) or 0,
                                    "seconds": beat_to_seconds(n["beat"], arrangement)} for n in notes], bpm)["swings"]
    except ValueError:
        return None, []
    costs, previous = {}, {0: None, 1: None}
    for swing in swings:
        prior = previous[swing["hand"]]
        travel = (math.hypot(swing["x"] - prior["x"], swing["y"] - prior["y"])
                  if prior and swing["beat"] - prior["beat"] <= DEMAND_TRAVEL_BEATS else 0.0)
        costs.setdefault(int(swing["beat"] // INTENSITY_BAR_BEATS), []).append((1 + travel, swing["note_ids"]))
        previous[swing["hand"]] = swing
    bars = []
    for index in range(min(costs), max(costs) + 1):
        start = index * INTENSITY_BAR_BEATS
        first, last = beat_to_seconds(start, arrangement), beat_to_seconds(start + INTENSITY_BAR_BEATS, arrangement)
        weighted = [(min(last, p["end_seconds"]) - max(first, p["start_seconds"]), p["energy_ratio"])
                    for p in passages if p["end_seconds"] > first and p["start_seconds"] < last]
        weight = sum(w for w, _ in weighted)
        if weight <= 0 or last <= first:
            continue
        inside = costs.get(index, [])
        bars.append({"start_beat": start, "energy_ratio": sum(w * e for w, e in weighted) / weight,
                     "swings": len(inside), "demand": sum(c for c, _ in inside) / (last - first),
                     "note_ids": [i for _, ids in inside for i in ids]})
    loud_level = _percentile([b["energy_ratio"] for b in bars], INTENSITY_LOUD_PERCENTILE) if bars else 0.0
    if loud_level <= 1e-9:
        return None, bars
    for bar in bars:
        bar["relative"] = bar["energy_ratio"] / loud_level
    loud = [b["demand"] for b in bars if b["relative"] >= LOUD_RATIO and b["swings"]]
    if len(loud) < INTENSITY_MIN_LOUD_BARS:
        return None, bars
    reference = median(loud)
    for bar in bars:
        soft = bar["relative"] < SOFT_RATIO
        bar["allowed"] = reference * (0.5 + 0.5 * bar["relative"]) if soft else None
        bar["excess"] = bool(soft and bar["swings"] >= INTENSITY_MIN_SWINGS and bar["demand"] > bar["allowed"] + 1e-9)
    # What the soft passages actually reach: a heavy run below it plays easier than the intro or verse before it.
    soft = [b["demand"] for b in bars if b["allowed"] is not None and b["swings"]]
    peak = _percentile(soft, SOFT_PEAK_PERCENTILE) if len(soft) >= 2 else None
    return {"loud_level": loud_level, "reference_demand": reference, "soft_peak_demand": peak}, bars


def underplayed_runs(bars, context):
    """Runs of consecutive loud bars; a run is flagged where two adjacent loud bars average below the soft peak."""
    peak = (context or {}).get("soft_peak_demand")
    if peak is None:
        return []
    flagged = set()
    for left, right in zip(bars, bars[1:]):
        if (left["relative"] >= LOUD_RATIO and right["relative"] >= LOUD_RATIO
                and right["start_beat"] - left["start_beat"] == INTENSITY_BAR_BEATS
                and (left["demand"] + right["demand"]) / 2 < peak - 1e-9):
            flagged.update((left["start_beat"], right["start_beat"]))
    runs = []
    for bar in bars:
        if bar["start_beat"] not in flagged:
            continue
        if runs and runs[-1][-1]["start_beat"] + INTENSITY_BAR_BEATS == bar["start_beat"]:
            runs[-1].append(bar)
        else:
            runs.append([bar])
    return [run for run in runs if len(run) >= UNDERPLAYED_MIN_BARS]


def _intensity(arrangement, spans, notes, report, warn):
    """Flag soft bars mapped as hard as the heavy passages, and heavy runs easier than the soft peaks."""
    context, bars = intensity_bars(arrangement, report, notes)
    if context is None:
        return {"checked": False}

    def section_of(beat):
        return next((s["id"] for s in spans if s["start_beat"] <= beat < s["end_beat"]), None)

    reference = context["reference_demand"]
    runs = []
    for bar in bars:
        if not bar["excess"]:
            continue
        if runs and runs[-1][-1]["start_beat"] + INTENSITY_BAR_BEATS == bar["start_beat"]:
            runs[-1].append(bar)
        else:
            runs.append([bar])
    for run in runs:
        first, last = run[0]["start_beat"], run[-1]["start_beat"] + INTENSITY_BAR_BEATS
        worst = max(run, key=lambda b: b["demand"] / b["allowed"])
        warn("difficulty_exceeds_intensity",
             f'Beats {first:g}-{last:g}: the audio plays at {worst["relative"]:.2f}x the loudness of the heavy '
             f'passages, but the map asks a swing demand of {worst["demand"]:.2f}, above the {worst["allowed"]:.2f} '
             f'this loudness allows against the {reference:.2f} median of the loud bars. Softer audio must play '
             "easier than heavier audio: keep the strongest onsets, shorten hand travel, and drop fast "
             "alternations; or raise the heavy passages if they are the ones underplayed.",
             section_id=section_of(first), value=_round(worst["demand"] / worst["allowed"], 4), threshold=1.0,
             object_ids=[i for b in run for i in b["note_ids"]], beats=[first, last])
    peak = context["soft_peak_demand"]
    loud_runs = underplayed_runs(bars, context)
    for run in loud_runs:
        first, last = run[0]["start_beat"], run[-1]["start_beat"] + INTENSITY_BAR_BEATS
        mean = sum(b["demand"] for b in run) / len(run)
        warn("intensity_underplayed",
             f'Beats {first:g}-{last:g}: the heavy passage ({min(b["relative"] for b in run):.2f}x-'
             f'{max(b["relative"] for b in run):.2f}x the loud level) averages a swing demand of {mean:.2f}, '
             f'below the {peak:.2f} the softer passages reach. Heavier, louder audio must play harder: map more of '
             "the loud layer's attacks (declare the riff as the musical_focus lead when it carries the rhythm), "
             "with wider movement and bursts where it rolls.",
             section_id=section_of(first), value=_round(mean, 4), threshold=_round(peak, 4),
             object_ids=[i for b in run for i in b["note_ids"]], beats=[first, last])
    return {"checked": True, "loud_level": _round(context["loud_level"], 4),
            "reference_demand": _round(reference, 4),
            "soft_peak_demand": None if peak is None else _round(peak, 4),
            "bars": [{"start_beat": b["start_beat"], "relative": _round(b["relative"], 3),
                      "swings": b["swings"], "demand": _round(b["demand"], 3),
                      "allowed": None if b["allowed"] is None else _round(b["allowed"], 3)} for b in bars]}


def _repetition(notes, warn):
    placements = [(n["x"], n["y"], n["color"], n["direction"]) for n in notes]
    counts = Counter(placements)
    histogram = [{"x": p[0], "y": p[1], "color": p[2], "direction": p[3], "count": c}
                 for p, c in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]]
    best = {"k": None, "coverage": 0.0}
    for k in CYCLE_RANGE:
        if len(placements) <= k:
            break
        matches = sum(1 for i in range(k, len(placements)) if placements[i] == placements[i - k])
        coverage = _round(matches / (len(placements) - k), 4)
        if coverage > best["coverage"]:
            best = {"k": k, "coverage": coverage}
    if best["k"] is not None and best["coverage"] >= CYCLE_THRESHOLD:
        warn("repetitive_cycle",
             f'{best["coverage"] * 100:.1f}% of the notes repeat the placement {best["k"]} notes earlier; '
             "the map reads as one looping figure rather than an arrangement.",
             value=best["coverage"], threshold=CYCLE_THRESHOLD)
    # Fewer than one full window: treat the whole map as a single window so the metric stays defined.
    starts = range(0, max(1, len(placements) - ENTROPY_WINDOW + 1), ENTROPY_HOP)
    windows = [_entropy(placements[s:s + ENTROPY_WINDOW]) for s in starts]
    entropy = {"window_notes": ENTROPY_WINDOW, "hop_notes": ENTROPY_HOP, "windows": len(windows),
               "min": _round(min(windows), 4), "median": _round(median(windows), 4)}
    if entropy["median"] < ENTROPY_THRESHOLD:
        warn("low_placement_variety",
             f'The median {ENTROPY_WINDOW}-note window carries only {entropy["median"]:.2f} bits of placement '
             f'entropy (minimum {entropy["min"]:.2f}); the hands revisit the same few positions.',
             value=entropy["median"], threshold=ENTROPY_THRESHOLD)
    rows, lanes = Counter(n["y"] for n in notes), Counter(n["x"] for n in notes)
    top_share = rows.get(2, 0) / len(notes)
    if top_share < TOP_ROW_THRESHOLD and len(notes) >= TOP_ROW_MIN_NOTES:
        warn("top_row_starved",
             f'Only {rows.get(2, 0)} of {len(notes)} notes sit on the top row ({top_share * 100:.1f}%); '
             "the map almost never lifts the hands.",
             value=_round(top_share, 4), threshold=TOP_ROW_THRESHOLD)
    return {"distinct_placements": len(counts), "placement_histogram": histogram,
            "cycle_coverage": best, "placement_entropy": entropy, "top_row_share": _round(top_share, 4),
            "lane_histogram": {str(x): lanes.get(x, 0) for x in range(4)},
            "row_histogram": {str(y): rows.get(y, 0) for y in range(3)}}


def _boundary_accents(arrangement, spans, notes, report, warn):
    """Flag section seams that carry a strong non-energy_rise accent but no note."""
    if not report:
        return {"checked": False, "unmapped_sections": []}
    from .musical import seconds_to_beat
    beats, flagged = sorted(float(n["beat"]) for n in notes), []
    for span in spans[1:]:
        seam = span["start_beat"]
        if any(abs(beat - seam) <= SEAM_BEATS for beat in beats):
            continue
        best = None
        for name, layer in (report.get("layers") or {}).items():
            for event in layer.get("events", []):
                if event.get("strength", 0) < ACCENT_STRENGTH or event.get("method") == "energy_rise":
                    continue
                beat = seconds_to_beat(event["seconds"], arrangement)
                offset = abs(beat - seam)
                if offset <= SEAM_BEATS and (best is None or offset < best["offset"]):
                    best = {"layer": name, "id": event["id"], "beat": beat, "offset": offset,
                            "method": event["method"], "strength": event["strength"]}
        if not best:
            continue
        warn("boundary_accent_unmapped",
             f'Section "{span["id"]}" starts at beat {seam:g} on an unmapped accent: {best["layer"]} '
             f'{best["method"]} event {best["id"]} at beat {best["beat"]:.3f} (strength {best["strength"]:g}) '
             f'has no note within {SEAM_BEATS:g} beat.',
             section_id=span["id"], value=_round(best["offset"], 4), threshold=SEAM_BEATS,
             beats=[_round(best["beat"], 4), _round(best["beat"], 4)],
             object_ids=[best["id"]])
        flagged.append(span["id"])
    return {"checked": True, "unmapped_sections": flagged}


def _salience(arrangement, spans, notes, report, warn):
    """Flag bars where the salient layer (articulated singing, else a strong drum pattern) goes unmapped."""
    layers = (report or {}).get("layers") or {}
    if not isinstance(layers.get("vocals"), dict) or not isinstance(layers.get("drums"), dict) or not spans:
        return {"checked": False, "bars": []}
    from .musical import seconds_to_beat

    def onsets(name, threshold, slots=None):
        found = [(seconds_to_beat(e["seconds"], arrangement), e["strength"]) for e in layers[name].get("events", [])
                 if e.get("method") == "spectral_flux" and e.get("strength", 0) >= threshold]
        if slots:
            # Dense grooves (sixteenth hats) are judged at a mappable resolution: the strongest hit per slot.
            strongest = {}
            for beat, strength in found:
                slot = math.floor(beat * slots + 0.5)
                if slot not in strongest or strongest[slot][1] < strength:
                    strongest[slot] = (beat, strength)
            found = list(strongest.values())
        return sorted(beat for beat, _ in found)

    def near(beat):
        index = bisect_left(beats, beat - SALIENCE_MATCH_BEATS)
        return index < len(beats) and beats[index] <= beat + SALIENCE_MATCH_BEATS

    beats = sorted(float(n["beat"]) for n in notes)
    vocals, drums = onsets("vocals", VOCAL_ONSET_STRENGTH), onsets("drums", DRUM_ONSET_STRENGTH, DRUM_SLOTS_PER_BEAT)
    sustains = [(seconds_to_beat(s["start_seconds"], arrangement), seconds_to_beat(s["end_seconds"], arrangement))
                for s in layers["vocals"].get("sustains") or []]
    arcs = [(span["start_beat"] + float(Fraction(str(arc["beat"]))), span["start_beat"] + float(Fraction(str(arc["tail_beat"]))))
            for span in spans for arc in span["section"].get("arcs") or []]

    def held(beat):
        """A vocal onset inside a sung sustain that an arc holds is mapped by that arc (held singing as arcs)."""
        return (any(head <= beat <= tail for head, tail in arcs)
                and any(start <= beat <= end for start, end in sustains))
    end, bars = max(s["end_beat"] for s in spans), []
    for start in range(0, math.ceil(end), SALIENCE_BAR_BEATS):
        stop = start + SALIENCE_BAR_BEATS
        sung = [b for b in vocals if start <= b < stop]
        hits = [b for b in drums if start <= b < stop]
        coverage = sum(max(0.0, min(e, stop) - max(s, start)) for s, e in sustains) / SALIENCE_BAR_BEATS
        singing = coverage >= SINGING_SUSTAIN_COVERAGE and len(sung) >= SINGING_MIN_ONSETS
        # A declared instrument lead (a guitar riff, a synth line) outranks the drums while the voice rests;
        # lead_rhythm_unmapped and lead_rhythm_diluted judge those bars instead.
        declared = None if singing else focus_lead(spans, start + SALIENCE_BAR_BEATS / 2, layers)
        declared = None if declared == "drums" else declared
        onsets_in = sung if singing else [] if declared else hits
        mapped = sum(1 for b in onsets_in if near(b) or (singing and held(b)))
        code = None
        if singing and mapped < VOCAL_MAPPED_THRESHOLD * len(sung):
            code = "vocal_line_unmapped"
        elif not singing and len(onsets_in) >= DRUM_PATTERN_MIN_ONSETS and mapped < DRUM_MAPPED_THRESHOLD * len(hits):
            code = "drum_rhythm_unmapped"
        bars.append({"start_beat": start, "salient": "vocals" if singing else declared or ("drums" if hits else None),
                     "onsets": len(onsets_in), "mapped": mapped, "code": code})
    runs, current = [], []
    for bar in bars:
        if current and bar["code"] == current[-1]["code"]:
            current.append(bar)
            continue
        runs.append(current) if current and current[0]["code"] else None
        current = [bar]
    runs.append(current) if current and current[0]["code"] else None
    for run in runs:
        if len(run) < SALIENCE_MIN_BARS:
            continue
        code, first, last = run[0]["code"], run[0]["start_beat"], run[-1]["start_beat"] + SALIENCE_BAR_BEATS
        total, mapped = sum(b["onsets"] for b in run), sum(b["mapped"] for b in run)
        section = next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None)
        what = ("articulated singing leads, but notes follow another layer" if code == "vocal_line_unmapped"
                else "the voice holds or rests while the drums carry a strong pattern, but notes miss it")
        warn(code, f"Beats {first:g}-{last:g}: {what}; {mapped} of {total} "
                   f'{"vocal" if code == "vocal_line_unmapped" else "drum"} onsets carry a note.',
             section_id=section, value=_round(mapped / total, 4), beats=[first, last],
             threshold=VOCAL_MAPPED_THRESHOLD if code == "vocal_line_unmapped" else DRUM_MAPPED_THRESHOLD)
    return {"checked": True, "bars": bars}


def melody_onsets(report, arrangement, start, stop):
    """Sorted beats of strong mix melody changes in [start, stop), strongest per half-beat slot."""
    from .musical import seconds_to_beat
    layer = ((report or {}).get("layers") or {}).get(MELODY_LAYER) or {}
    found = [(seconds_to_beat(e["seconds"], arrangement), e["strength"]) for e in layer.get("events", [])
             if e.get("method") == "melody_change" and e.get("strength", 0) >= MELODY_ONSET_STRENGTH]
    return [beat for beat, _ in strongest_per_slot(found) if start <= beat < stop]


def _melody(arrangement, spans, notes, report, salience, warn):
    """Flag melodic bars (no singing, declared lead or drum pattern) whose notes miss the pitch changes."""
    if not salience.get("checked"):
        return {"checked": False, "bars": []}
    beats = sorted(float(n["beat"]) for n in notes)

    def near(beat):
        index = bisect_left(beats, beat - SALIENCE_MATCH_BEATS)
        return index < len(beats) and beats[index] <= beat + SALIENCE_MATCH_BEATS
    bars = []
    for bar in salience["bars"]:
        if bar["salient"] not in (None, "drums") or bar["onsets"] >= DRUM_PATTERN_MIN_ONSETS:
            continue
        start = bar["start_beat"]
        changes = melody_onsets(report, arrangement, start, start + SALIENCE_BAR_BEATS)
        if len(changes) < MELODY_MIN_CHANGES:
            continue
        mapped = sum(1 for beat in changes if near(beat))
        bars.append({"start_beat": start, "changes": len(changes), "mapped": mapped,
                     "code": "melody_unmapped" if mapped < MELODY_MAPPED_THRESHOLD * len(changes) else None,
                     "unmapped_beats": [_round(b, 4) for b in changes if not near(b)]})
    runs = []
    for bar in bars:
        if not bar["code"]:
            continue
        if runs and runs[-1][-1]["start_beat"] + SALIENCE_BAR_BEATS == bar["start_beat"]:
            runs[-1].append(bar)
        else:
            runs.append([bar])
    for run in runs:
        first, last = run[0]["start_beat"], run[-1]["start_beat"] + SALIENCE_BAR_BEATS
        total, mapped = sum(b["changes"] for b in run), sum(b["mapped"] for b in run)
        section = next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None)
        warn("melody_unmapped",
             f"Beats {first:g}-{last:g}: no voice, drum pattern or declared lead carries these bars, so the pitched "
             f"line leads, but only {mapped} of its {total} pitch changes carry a note. Put notes on the melody_change "
             "events (see `music rhythm --layers mix`) and let the rows follow the pitch contour.",
             section_id=section, value=_round(mapped / total, 4), threshold=MELODY_MAPPED_THRESHOLD,
             beats=[first, last])
    return {"checked": True, "bars": bars}


def focus_lead(spans, beat, layers):
    """The instrument stem a musical_focus phrase declares as lead at ``beat``, if analyzed and not mix."""
    for span in spans:
        if not span["start_beat"] <= beat < span["end_beat"]:
            continue
        for phrase in span["section"].get("musical_focus") or []:
            left = span["start_beat"] + float(Fraction(str(phrase["start_beat"])))
            right = span["start_beat"] + float(Fraction(str(phrase["end_beat"])))
            lead = phrase.get("lead")
            if left <= beat < right and lead != "mix" and isinstance(layers.get(lead), dict):
                return lead
    return None


def lead_onsets(layers, name, arrangement, threshold):
    """Sorted (beat, strength) lead events of one layer at or above ``threshold``."""
    from .musical import seconds_to_beat
    return sorted((seconds_to_beat(e["seconds"], arrangement), e["strength"])
                  for e in (layers.get(name) or {}).get("events", [])
                  if e.get("method") in LEAD_ONSET_METHODS and e.get("strength", 0) >= threshold)


def strongest_per_slot(onsets, slots=DRUM_SLOTS_PER_BEAT):
    """Keep the strongest (beat, strength) per 1/slots-beat slot, so a dense figure is judged at a mappable rate."""
    strongest = {}
    for beat, strength in onsets:
        slot = math.floor(beat * slots + 0.5)
        if slot not in strongest or strongest[slot][1] < strength:
            strongest[slot] = (beat, strength)
    return sorted(strongest.values())


def quiet_bar(report, arrangement, start, stop):
    """True when the evidence passages under [start, stop) beats are thin and soft (the density_exceeds_audio terms)."""
    from .musical import seconds_to_beat
    inside = [p for p in (report or {}).get("passages") or []
              if seconds_to_beat(p["start_seconds"], arrangement) < stop
              and seconds_to_beat(p["end_seconds"], arrangement) > start]
    if not inside:
        return False
    return (sum(p["support_score"] for p in inside) / len(inside) < QUIET_SUPPORT
            and sum(p["energy_ratio"] for p in inside) / len(inside) < QUIET_ENERGY)


def _lead_rhythm(arrangement, spans, notes, report, salience, warn):
    """Flag bars whose notes miss the declared lead's attacks or bury them in filler."""
    layers = (report or {}).get("layers") or {}
    if not layers or not spans:
        return {"checked": False, "bars": []}
    singing = {bar["start_beat"] for bar in salience.get("bars", []) if bar["salient"] == "vocals"}
    arcs = [(span["start_beat"] + float(Fraction(str(arc["beat"]))),
             span["start_beat"] + float(Fraction(str(arc["tail_beat"]))))
            for span in spans for arc in span["section"].get("arcs") or []]
    times = sorted({float(n["beat"]) for n in notes})
    ids = {}
    for n in notes:
        ids.setdefault(float(n["beat"]), []).append(n["id"])
    cache, bars, accents_cache = {}, [], {}

    def events(name):
        if name not in cache:
            cache[name] = lead_onsets(layers, name, arrangement, LEAD_SUPPORT_STRENGTH)
        return cache[name]

    def within(values, beat, reach):
        index = bisect_left(values, beat - reach)
        return index < len(values) and values[index] <= beat + reach

    # Softer audio plays easier (difficulty_exceeds_intensity): a soft bar is judged on its lead's strongest attack
    # per beat, the resolution a thin, quiet bar is drafted at, so the two checks never ask for opposite things.
    soft = {b["start_beat"] for b in intensity_bars(arrangement, report, notes)[1] if b.get("relative", 1.0) < SOFT_RATIO}
    end = max(s["end_beat"] for s in spans)
    loudness, unison_cache = bar_loudness(report, arrangement, 0, math.ceil(end)), {}
    for start in range(0, math.ceil(end), SALIENCE_BAR_BEATS):
        stop = start + SALIENCE_BAR_BEATS
        lead = ("vocals" if start in singing and isinstance(layers.get("vocals"), dict)
                else focus_lead(spans, start + SALIENCE_BAR_BEATS / 2, layers))
        if lead is None:
            continue
        found = events(lead)
        support = [b for b, _ in found]
        strong = [b for b, s in strongest_per_slot(found) if s >= LEAD_ONSET_STRENGTH and start <= b < stop]
        inside = [t for t in times if start <= t < stop]
        if len(strong) < LEAD_MIN_ONSETS:
            continue
        if start in soft:
            strong = [b for b, s in strongest_per_slot(found, 1) if s >= LEAD_ONSET_STRENGTH and start <= b < stop]
        mapped = sum(1 for b in strong if within(times, b, SALIENCE_MATCH_BEATS))
        # A note on the bar's heaviest hit of the rest of the band is the ensemble's weight, not filler;
        # more than ENSEMBLE_ALLOWANCE_PER_BAR of them is a second rhythm competing with the lead. A loud bar's
        # unison hits, the whole band striking at once, are that weight too.
        heavy = sorted(ensemble_accents(layers, arrangement, lead, start, stop, accents_cache), key=lambda a: -a[1])
        code, quiet = None, quiet_bar(report, arrangement, start, stop)
        accents = [b for b, _, _ in heavy[:ENSEMBLE_ALLOWANCE_PER_BAR]]
        if loudness.get(start, 0.0) >= LOUD_RATIO and not quiet:
            accents += [b for b, *_ in unison_hits(layers, arrangement, start, stop, unison_cache)]
        accents.sort()
        stray = [t for t in inside if within(support, t, LEAD_GAP_BEATS) and not within(support, t, SALIENCE_MATCH_BEATS)
                 and not within(accents, t, SALIENCE_MATCH_BEATS)
                 and not any(head <= t <= tail for head, tail in arcs)]
        # A thin, soft bar takes the lead's strongest attacks, not all of them (density_exceeds_audio).
        if lead != "vocals" and not quiet and mapped < LEAD_MAPPED_THRESHOLD * len(strong):
            code = "lead_rhythm_unmapped"
        elif len(inside) >= LEAD_MIN_NOTES and len(inside) - len(stray) < LEAD_CONSISTENT_THRESHOLD * len(inside):
            code = "lead_rhythm_diluted"
        bars.append({"start_beat": start, "lead": lead, "lead_onsets": len(strong), "mapped": mapped,
                     "note_times": len(inside), "off_lead": len(stray), "quiet": quiet, "code": code,
                     "stray_beats": [_round(t, 4) for t in stray]})
    runs = []
    for bar in bars:
        if (runs and bar["code"] and runs[-1][-1]["code"] == bar["code"] and runs[-1][-1]["lead"] == bar["lead"]
                and runs[-1][-1]["start_beat"] + SALIENCE_BAR_BEATS == bar["start_beat"]):
            runs[-1].append(bar)
        elif bar["code"]:
            runs.append([bar])
    for run in runs:
        code, lead = run[0]["code"], run[0]["lead"]
        first, last = run[0]["start_beat"], run[-1]["start_beat"] + SALIENCE_BAR_BEATS
        section = next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None)
        if code == "lead_rhythm_unmapped":
            total, mapped = sum(b["lead_onsets"] for b in run), sum(b["mapped"] for b in run)
            warn(code, f"Beats {first:g}-{last:g}: {lead} leads, but only {mapped} of its {total} attacks carry a "
                       "note; place the notes on its rhythm (see `music rhythm`).",
                 section_id=section, value=_round(mapped / total, 4), threshold=LEAD_MAPPED_THRESHOLD,
                 beats=[first, last])
        else:
            total, stray = sum(b["note_times"] for b in run), sum(b["off_lead"] for b in run)
            warn(code, f"Beats {first:g}-{last:g}: {lead} leads, but {stray} of {total} note times sit between its "
                       "attacks, flattening its rhythm into an even stream. Keep the notes on its attacks and fill "
                       "only its gaps of a beat or more (see `music rhythm`).",
                 section_id=section, value=_round((total - stray) / total, 4),
                 threshold=LEAD_CONSISTENT_THRESHOLD, beats=[first, last],
                 object_ids=[i for b in run for t in b["stray_beats"] for i in ids.get(t, [])])
    return {"checked": True, "bars": bars}


def separated_stems(layers):
    """Names of separated audio stems (not the mix, not frequency bands)."""
    return [name for name, layer in layers.items()
            if name != "mix" and isinstance(layer, dict) and layer.get("kind") == "audio_layer"]


def ensemble_accents(layers, arrangement, lead, start, stop, cache):
    """(beat, strength, layer) ensemble accents in [start, stop): strongest per beat, off the lead's onsets."""
    from .musical import seconds_to_beat
    if "accents" not in cache:
        cache["accents"] = sorted((seconds_to_beat(e["seconds"], arrangement), e["strength"], name)
                                  for name in separated_stems(layers)
                                  for e in layers[name].get("events", [])
                                  if e.get("method") == "spectral_flux" and e.get("strength", 0) >= ENSEMBLE_STRENGTH)
    if "mix" not in cache:
        cache["mix"] = sorted(seconds_to_beat(e["seconds"], arrangement) for e in (layers.get("mix") or {}).get("events", [])
                              if e.get("method") == "spectral_flux" and e.get("strength", 0) >= ENSEMBLE_MIX_STRENGTH)
    if ("lead", lead) not in cache:
        cache[("lead", lead)] = [b for b, _ in lead_onsets(layers, lead, arrangement, LEAD_SUPPORT_STRENGTH)]
    heard, accents, mix = cache[("lead", lead)], cache["accents"], cache["mix"]
    checked_mix = isinstance(layers.get("mix"), dict)
    strongest = {}
    for beat, strength, name in accents[bisect_left(accents, (start,)):]:
        if beat >= stop:
            break
        if name == lead:
            continue
        index = bisect_left(heard, beat - SALIENCE_MATCH_BEATS)
        if index < len(heard) and heard[index] <= beat + SALIENCE_MATCH_BEATS:
            continue
        index = bisect_left(mix, beat - SALIENCE_MATCH_BEATS)
        if checked_mix and not (index < len(mix) and mix[index] <= beat + SALIENCE_MATCH_BEATS):
            continue  # not an attack in the mix: a swell, bleed or a masked detail
        slot = math.floor(beat + 0.5)
        if slot not in strongest or strongest[slot][1] < strength:
            strongest[slot] = (beat, strength, name)
    return sorted(strongest.values())


def bar_loudness(report, arrangement, first, last):
    """{bar start: loudness relative to the song's heavy bars}, as the intensity check measures it."""
    passages = (report or {}).get("passages") or []
    values = {}
    for start in range(first, last, INTENSITY_BAR_BEATS):
        a = beat_to_seconds(start, arrangement)
        b = beat_to_seconds(start + INTENSITY_BAR_BEATS, arrangement)
        weighted = [(min(b, p["end_seconds"]) - max(a, p["start_seconds"]), p["energy_ratio"])
                    for p in passages if p["end_seconds"] > a and p["start_seconds"] < b]
        weight = sum(w for w, _ in weighted)
        if weight > 0:
            values[start] = sum(w * e for w, e in weighted) / weight
    loud = _percentile(list(values.values()), INTENSITY_LOUD_PERCENTILE) if values else 0.0
    return {start: value / loud for start, value in values.items()} if loud > 1e-9 else {}


def unison_hits(layers, arrangement, start, stop, cache):
    """(beat, stack size, stems, mix strength) unison hits in the bar [start, stop), strongest first.

    See UNISON_*: at most UNISON_PER_BAR, a beat apart. The caller decides whether the bar is loud.
    """
    if "unison" not in cache:
        from .musical import seconds_to_beat
        stems = separated_stems(layers)
        mix = sorted((float(e["seconds"]), e["strength"]) for e in (layers.get("mix") or {}).get("events", [])
                     if e.get("method") == "spectral_flux" and e.get("strength", 0) >= ENSEMBLE_MIX_STRENGTH)
        found = []
        if "drums" in stems and len(stems) >= UNISON_MIN_STEMS and mix:
            floor = _percentile([strength for _, strength in mix], UNISON_MIX_PERCENTILE)
            onsets = {name: sorted(float(e["seconds"]) for e in layers[name].get("events", [])
                                   if e.get("method") == "spectral_flux" and e.get("strength", 0) >= UNISON_STEM_STRENGTH)
                      for name in stems}
            for seconds, strength in mix:
                if strength < floor:
                    continue
                joined = []
                for name, times in onsets.items():
                    index = bisect_left(times, seconds - UNISON_SECONDS)
                    if index < len(times) and times[index] <= seconds + UNISON_SECONDS:
                        joined.append(name)
                if "drums" in joined and len(joined) >= UNISON_MIN_STEMS:
                    found.append((seconds_to_beat(seconds, arrangement),
                                  3 if len(joined) >= UNISON_TALL_STEMS else 2, sorted(joined), strength))
        cache["unison"] = found
    hits = sorted((h for h in cache["unison"] if start <= h[0] < stop), key=lambda h: (-h[3], h[0]))
    chosen = []
    for hit in hits:
        if len(chosen) < UNISON_PER_BAR and all(abs(hit[0] - other[0]) >= 1 - SALIENCE_MATCH_BEATS
                                                for other in chosen):
            chosen.append(hit)
    return sorted(chosen)


def _unison(arrangement, spans, notes, report, warn):
    """Flag unison hits (see unison_hit) that the map cuts without a stack."""
    layers = (report or {}).get("layers") or {}
    if len(separated_stems(layers)) < UNISON_MIN_STEMS or not spans or not notes:
        return {"checked": False, "hits": []}
    end = max(s["end_beat"] for s in spans)
    loudness = bar_loudness(report, arrangement, 0, math.ceil(end))
    holds = [(s["start_beat"] + float(Fraction(str(item["beat"]))), s["start_beat"] + float(Fraction(str(item["tail_beat"]))))
             for s in spans for kind in ("arcs", "chains") for item in s["section"].get(kind, [])]
    beats = [float(n["beat"]) for n in notes]
    cache, found = {}, []
    for bar in range(0, math.ceil(end), SALIENCE_BAR_BEATS):
        if loudness.get(bar, 0.0) < LOUD_RATIO or quiet_bar(report, arrangement, bar, bar + SALIENCE_BAR_BEATS):
            continue
        for beat, size, stems, strength in unison_hits(layers, arrangement, bar, bar + SALIENCE_BAR_BEATS, cache):
            if sum(1 for head, tail in holds if head < beat < tail) >= 2:
                continue  # both sabers held: no hand is free to cut a stack
            near = [n for n, b in zip(notes, beats) if abs(b - beat) <= SALIENCE_MATCH_BEATS]
            stacked = any(count >= 2 for count in Counter((n["beat"], n["color"]) for n in near).values())
            found.append({"beat": _round(beat, 4), "size": size, "stems": stems, "stacked": stacked})
            if stacked:
                continue
            section = next((s["id"] for s in spans if s["start_beat"] <= beat < s["end_beat"]), None)
            what = f"{len(near)} unstacked note(s)" if near else "no note"
            warn("unison_hit_unstacked",
                 f"Beat {beat:.2f} ({beat_to_seconds(beat, arrangement):.2f} s): {', '.join(stems)} strike together "
                 f"(mix {strength:.2f}), and the map puts {what} there. Cut it as a stack of {size} on one hand, in "
                 "a line along the cut, so the heavier hit reads as one longer note.",
                 section_id=section, value=0, threshold=2, object_ids=[n["id"] for n in near],
                 beats=[_round(beat, 4), _round(beat, 4)], targets=[[_round(beat, 4), size]])
    return {"checked": True, "hits": found}


def bar_leads(arrangement, spans, report, salience):
    """{bar start beat: lead layer} for bars that follow one layer (the salient layer, else a declared lead)."""
    layers = (report or {}).get("layers") or {}
    if salience.get("checked"):
        return {bar["start_beat"]: bar["salient"] for bar in salience["bars"] if bar["salient"]}
    end = max((s["end_beat"] for s in spans), default=0)
    found = {start: focus_lead(spans, start + SALIENCE_BAR_BEATS / 2, layers)
             for start in range(0, math.ceil(end), SALIENCE_BAR_BEATS)}
    return {start: lead for start, lead in found.items() if lead}


def _ensemble(arrangement, spans, notes, report, salience, warn):
    """Flag windows where the notes follow the lead alone and skip every heavy hit of the rest of the band."""
    layers = (report or {}).get("layers") or {}
    if len(separated_stems(layers)) < 2 or not spans:
        return {"checked": False, "windows": []}
    leads, cache = bar_leads(arrangement, spans, report, salience), {}
    times = sorted({float(n["beat"]) for n in notes})

    def near(beat):
        index = bisect_left(times, beat - SALIENCE_MATCH_BEATS)
        return index < len(times) and times[index] <= beat + SALIENCE_MATCH_BEATS
    end, windows = max(s["end_beat"] for s in spans), []
    for first in range(0, math.ceil(end), ENSEMBLE_WINDOW_BEATS):
        last = first + ENSEMBLE_WINDOW_BEATS
        accents, followed = [], set()
        for bar in range(first, last, SALIENCE_BAR_BEATS):
            lead = leads.get(bar)
            if not lead or lead == "mix" or quiet_bar(report, arrangement, bar, bar + SALIENCE_BAR_BEATS):
                continue
            followed.add(lead)
            accents += ensemble_accents(layers, arrangement, lead, bar, bar + SALIENCE_BAR_BEATS, cache)
        count = sum(1 for t in times if first <= t < last)
        if len(accents) < ENSEMBLE_MIN_ACCENTS or count < ENSEMBLE_MIN_NOTES:
            continue
        mapped = sum(1 for beat, _, _ in accents if near(beat))
        windows.append({"start_beat": first, "leads": sorted(followed), "accents": len(accents), "mapped": mapped})
        if mapped >= ENSEMBLE_MAPPED_THRESHOLD * len(accents):
            continue
        need = max(1, math.ceil(ENSEMBLE_MAPPED_THRESHOLD * len(accents))) - mapped
        heaviest = sorted((a for a in accents if not near(a[0])), key=lambda a: -a[1])[:need]
        layers_text = ", ".join(f"{name} {n}" for name, n in Counter(a[2] for a in accents).most_common())
        section = next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None)
        warn("ensemble_unmapped",
             f"Beats {first:g}-{last:g}: the notes follow {'/'.join(sorted(followed))} alone; {mapped} of "
             f"{len(accents)} heavy hits from the rest of the band ({layers_text}) carry a note. Add the heaviest "
             f"(beat {', '.join(f'{b:.2f} {n}' for b, _, n in heaviest)}) so the map carries the whole song's weight.",
             section_id=section, value=_round(mapped / len(accents), 4), threshold=ENSEMBLE_MAPPED_THRESHOLD,
             beats=[first, last], targets=[[_round(b, 4), s] for b, s, _ in heaviest])
    return {"checked": True, "windows": windows}


def _entries(arrangement, spans, notes, report, warn):
    """Report stem entries; flag drum entries the map ignores."""
    from .musical import layer_entries, seconds_to_beat
    layers = (report or {}).get("layers") or {}
    if not spans or not isinstance(layers.get(ENTRY_LAYER), dict):
        return {"checked": False, "entries": []}
    end = max(s["end_beat"] for s in spans)
    times = sorted({float(n["beat"]) for n in notes})
    hits = strongest_per_slot([(seconds_to_beat(e["seconds"], arrangement), e["strength"])
                               for e in layers[ENTRY_LAYER].get("events", [])
                               if e.get("method") == "spectral_flux" and e.get("strength", 0) >= DRUM_ONSET_STRENGTH])

    def near(beat):
        index = bisect_left(times, beat - SALIENCE_MATCH_BEATS)
        return index < len(times) and times[index] <= beat + SALIENCE_MATCH_BEATS
    found = []
    for entry in (report["layer_entries"] if "layer_entries" in report else layer_entries(report)):
        beat = seconds_to_beat(entry["seconds"], arrangement)
        if not 0 <= beat < end:
            continue
        row = {"layer": entry["layer"], "beat": _round(beat, 4), "seconds": entry["seconds"],
               "silent_before_seconds": entry["silent_before_seconds"]}
        found.append(row)
        if entry["layer"] != ENTRY_LAYER:
            continue
        inside = [b for b, _ in hits if beat - SALIENCE_MATCH_BEATS <= b < beat + ENTRY_WINDOW_BEATS]
        mapped = sum(1 for b in inside if near(b))
        row.update(hits=len(inside), mapped=mapped)
        if len(inside) >= ENTRY_MIN_HITS and mapped < ENTRY_MAPPED_THRESHOLD * len(inside):
            section = next((s["id"] for s in spans if s["start_beat"] <= beat < s["end_beat"]), None)
            warn("drum_entry_unmapped",
                 f"Beat {beat:.2f} ({entry['seconds']:.1f} s): the drums enter after "
                 f"{entry['silent_before_seconds']:g} s away, but only {mapped} of their {len(inside)} hits in the "
                 f"next {ENTRY_WINDOW_BEATS} beats carry a note. Let the focus move to the drums as they arrive, "
                 "then hand it back.",
                 section_id=section, value=_round(mapped / len(inside), 4), threshold=ENTRY_MAPPED_THRESHOLD,
                 beats=[_round(beat - SALIENCE_MATCH_BEATS, 4), _round(beat + ENTRY_WINDOW_BEATS, 4)])
    return {"checked": True, "entries": found}


def grid_alignment(arrangement, report):
    """Median signed offset of strong percussive onsets from the quarter-beat grid, per window."""
    from .musical import seconds_to_beat
    layers = (report or {}).get("layers") or {}
    name = next((n for n in ("drums", "percussive", "low", "mix") if isinstance(layers.get(n), dict)), None)
    if name is None:
        return {"checked": False, "windows": []}
    offsets = []
    for event in layers[name].get("events", []):
        if event.get("method") != "spectral_flux" or event.get("strength", 0) < DRUM_ONSET_STRENGTH:
            continue
        beat = seconds_to_beat(event["seconds"], arrangement)
        nearest = round(beat * 4) / 4
        if beat >= 0 and abs(beat - nearest) <= GRID_ON_GRID_BEATS:
            offsets.append((beat, event["seconds"] - beat_to_seconds(nearest, arrangement)))
    windows = {}
    for beat, offset in offsets:
        windows.setdefault(int(beat // GRID_WINDOW_BEATS), []).append(offset)
    rows = [{"start_beat": key * GRID_WINDOW_BEATS, "end_beat": (key + 1) * GRID_WINDOW_BEATS,
             "onsets": len(values), "median_offset_ms": _round(median(values) * 1000, 2),
             "median_abs_offset_ms": _round(median(abs(v) for v in values) * 1000, 2)}
            for key, values in sorted(windows.items()) if len(values) >= GRID_MIN_ONSETS]
    overall = median(v for _, v in offsets) if offsets else 0.0
    return {"checked": bool(rows), "layer": name, "median_offset_ms": _round(overall * 1000, 2), "windows": rows}


def _focus_stems(arrangement, spans, report, warn):
    """Flag focus phrases that weight a stem far quieter than the loudest stem in the same span."""
    layers = {name: layer for name, layer in ((report or {}).get("layers") or {}).items()
              if name != "mix" and isinstance(layer, dict) and layer.get("kind") != "frequency_band"
              and layer.get("energy_contour")}
    if len(layers) < 2:
        return {"checked": False, "phrases": []}
    # Each stem is measured against its own typical level: stems differ in spectral level (bass reads loud).
    reference = {}
    for name, layer in layers.items():
        values = sorted(p["energy"] for p in layer["energy_contour"])
        reference[name] = values[min(len(values) - 1, int(len(values) * STEM_REFERENCE_PERCENTILE / 100))]
    phrases = []
    for span in spans:
        for phrase in span["section"].get("musical_focus") or []:
            first = beat_to_seconds(span["start_beat"] + float(Fraction(str(phrase["start_beat"]))), arrangement)
            last = beat_to_seconds(span["start_beat"] + float(Fraction(str(phrase["end_beat"]))), arrangement)
            db = {}
            for name, layer in layers.items():
                inside = [p["energy"] for p in layer["energy_contour"] if first <= p["seconds"] < last]
                if inside and reference[name] > 1e-12:
                    db[name] = _round(20 * math.log10(max(median(inside), 1e-12) / reference[name]), 2)
            if not db:
                continue
            active = max(db, key=db.get)
            phrases.append({"section_id": span["id"], "focus_id": phrase["id"], "most_active": active,
                            "db_vs_own_level": db})
            for name, weight in phrase["weights"].items():
                if name in db and weight >= FOCUS_STEM_WEIGHT and db[name] <= -QUIET_STEM_DB:
                    warn("focus_on_quiet_stem",
                         f'Focus "{phrase["id"]}" in "{span["id"]}" (source {first:.1f}-{last:.1f} s) weights '
                         f'{name} at {weight:g}, but {name} sits {-db[name]:.1f} dB below its usual level there, so '
                         f'its events are separator bleed or the instrument was routed to another stem. The most '
                         f'active stem there is {active} ({db[active]:+.1f} dB vs its usual level).',
                         section_id=span["id"], value=db[name], threshold=-QUIET_STEM_DB,
                         beats=[span["start_beat"] + float(Fraction(str(phrase["start_beat"]))),
                                span["start_beat"] + float(Fraction(str(phrase["end_beat"])))])
    return {"checked": True, "phrases": phrases}


def focus_findings(arrangement: dict, report: dict | None) -> list[dict]:
    """The focus, salience and intensity warnings, as project diagnostics (never blocking)."""
    if not report:
        return []
    return [{**w, "model_version": MODEL_VERSION} for w in critique_arrangement(arrangement, report)["warnings"]
            if w["code"] in FOCUS_CODES]


def _grid(arrangement, report, warn):
    alignment = grid_alignment(arrangement, report)
    drifting = [w for w in alignment["windows"]
                if abs(w["median_offset_ms"] - alignment["median_offset_ms"]) > GRID_DRIFT_SECONDS * 1000]
    if drifting:
        worst = max(drifting, key=lambda w: abs(w["median_offset_ms"] - alignment["median_offset_ms"]))
        spread = worst["median_offset_ms"] - alignment["median_offset_ms"]
        warn("grid_drift",
             f'{alignment["layer"]} onsets drift off the beat grid in {len(drifting)} window(s); worst beats '
             f'{worst["start_beat"]}-{worst["end_beat"]} sit {spread:+.1f} ms from the song-wide '
             f'{alignment["median_offset_ms"]:+.1f} ms. Check the BPM and offset there, or add tempo events.',
             value=_round(abs(spread) / 1000, 4), threshold=GRID_DRIFT_SECONDS,
             beats=[worst["start_beat"], worst["end_beat"]])
    return alignment


def _movement_objects(arrangement, spans, report):
    """Count arcs and chains for before/after comparison; this emits no warnings."""
    per_section, arcs, chains, travel, heads = [], 0, 0, Counter(), []
    for span in spans:
        section_arcs = span["section"].get("arcs") or []
        section_chains = span["section"].get("chains") or []
        arcs, chains = arcs + len(section_arcs), chains + len(section_chains)
        for arc in section_arcs:
            travel[arc["tail_y"] - arc["y"]] += 1
            heads.append(span["start_beat"] + float(Fraction(str(arc["beat"]))))
        per_section.append({"section_id": span["id"], "arc_count": len(section_arcs),
                            "chain_count": len(section_chains)})
    result = {"arc_count": arcs, "chain_count": chains, "per_section": per_section,
              "arc_vertical_travel": {str(key): travel[key] for key in sorted(travel)}}
    # Schema 1.1 evidence runs may add per-layer sustains; absence is normal.
    vocals = ((report or {}).get("layers") or {}).get("vocals") or {}
    sustains = vocals.get("sustains") if isinstance(vocals, dict) else None
    if isinstance(sustains, list):
        from .musical import seconds_to_beat
        long = [s for s in sustains
                if float(s.get("end_seconds", 0)) - float(s.get("start_seconds", 0)) >= SUSTAIN_SECONDS]
        result["long_vocal_sustains"] = len(long)
        result["sustains_covered_by_arcs"] = sum(
            1 for s in long
            if any(abs(head - seconds_to_beat(float(s["start_seconds"]), arrangement)) <= SUSTAIN_ARC_BEATS
                   for head in heads))
    return result


def critique_arrangement(arrangement: dict, report: dict | None = None, tier_reference: dict | None = None) -> dict:
    """Return warning-only density, repetition, seam, movement and star-tier metrics."""
    warnings = []

    def warn(code, message, *, value, threshold, section_id=None, object_ids=(), beats=None, targets=None):
        warnings.append({"severity": "warning", "code": code, "message": message,
                         "section_id": section_id, "object_ids": list(object_ids),
                         "value": value, "threshold": threshold})
        if beats is not None:  # absolute [start, end] beats of the finding, for project check's suggestions
            warnings[-1]["beats"] = beats
        if targets is not None:  # [beat, strength] onsets the suggested edit maps
            warnings[-1]["targets"] = targets

    notes = expanded_notes(arrangement)
    spans = _sections(arrangement)
    times = sorted(beat_to_seconds(note["beat"], arrangement) for note in notes)
    metrics = {"note_count": len(notes), "section_count": len(spans),
               "density": _density(arrangement, notes, times, spans, warn) if notes else _empty_density(spans),
               "repetition": _repetition(notes, warn) if notes else _empty_repetition(),
               "movement_objects": _movement_objects(arrangement, spans, report),
               "boundary_accents": _boundary_accents(arrangement, spans, notes, report, warn),
               "salience": _salience(arrangement, spans, notes, report, warn),
               "quiet_density": _quiet_density(arrangement, spans, notes, times, report, warn)}
    metrics["lead_rhythm"] = _lead_rhythm(arrangement, spans, notes, report, metrics["salience"], warn)
    metrics["melody"] = _melody(arrangement, spans, notes, report, metrics["salience"], warn)
    metrics["ensemble"] = _ensemble(arrangement, spans, notes, report, metrics["salience"], warn)
    metrics["unison"] = _unison(arrangement, spans, notes, report, warn)
    metrics["layer_entries"] = _entries(arrangement, spans, notes, report, warn)
    metrics["grid_alignment"] = _grid(arrangement, report, warn)
    metrics["focus_stems"] = _focus_stems(arrangement, spans, report, warn)
    metrics["intensity"] = _intensity(arrangement, spans, notes, report, warn)
    metrics["tier_fit"] = tier_fit(arrangement, tier_reference, warn) if notes else {"checked": False}
    # Audio grounding: blocking spans are save errors elsewhere; here every finding stays a warning.
    metrics["audio"], findings = audio_findings(arrangement, report)
    for finding in findings:
        warn(finding["code"], finding["message"], value=finding["value"], threshold=finding["threshold"],
             section_id=finding["section_id"], object_ids=finding["object_ids"])
    metrics["lighting"], findings = lighting_findings(arrangement, report)
    for finding in findings:
        warn(finding["code"], finding["message"], value=finding["value"], threshold=finding["threshold"],
             section_id=finding["section_id"], beats=finding.get("beats"))
    return {"model_version": MODEL_VERSION, "metrics": metrics, "warnings": warnings,
            "definitions": DEFINITIONS}
