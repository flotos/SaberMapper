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
    "density_collapse": "At a section boundary S to T, the sparsest 2 s window (hopped 0.5 s) inside the last 8 s of S runs below 0.6 times the median rolling window fully inside S while the first 8 s of T runs above that median, and S holds at least 8 notes.",
    "repetitive_cycle": "The best cycle coverage over periods 2..16 reaches 0.6 or more, meaning most notes repeat the placement of a fixed number of notes earlier.",
    "low_placement_variety": "The median 64-note window placement entropy falls below 2.5 bits.",
    "top_row_starved": "Fewer than 5% of the notes sit on the top row in a map of at least 100 notes.",
    "boundary_accent_unmapped": "A non-energy_rise musical event of strength 0.7 or more sits within 0.25 beat of a section seam that carries no note within 0.25 beat.",
    "singing_bar": "A 4-beat bar (absolute beats 0, 4, 8...) where vocals sustains cover at least 25% and at least 2 vocals spectral_flux events of strength 0.25 or more start: articulated singing.",
    "vocal_line_unmapped": "One or more consecutive singing bars where fewer than 50% of those vocal onsets have a note within 0.13 beat: the map follows another layer while the voice is the focal point.",
    "drum_rhythm_unmapped": "One or more consecutive non-singing bars (voice holding or resting) with at least 6 drums spectral_flux events of strength 0.3 or more (only the strongest per half-beat slot counts), fewer than 60% of which have a note within 0.13 beat.",
    **AUDIO_DEFINITIONS,
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
    end, bars = max(s["end_beat"] for s in spans), []
    for start in range(0, math.ceil(end), SALIENCE_BAR_BEATS):
        stop = start + SALIENCE_BAR_BEATS
        sung = [b for b in vocals if start <= b < stop]
        hits = [b for b in drums if start <= b < stop]
        coverage = sum(max(0.0, min(e, stop) - max(s, start)) for s, e in sustains) / SALIENCE_BAR_BEATS
        singing = coverage >= SINGING_SUSTAIN_COVERAGE and len(sung) >= SINGING_MIN_ONSETS
        onsets_in = sung if singing else hits
        mapped = sum(1 for b in onsets_in if near(b))
        code = None
        if singing and mapped < VOCAL_MAPPED_THRESHOLD * len(sung):
            code = "vocal_line_unmapped"
        elif not singing and len(hits) >= DRUM_PATTERN_MIN_ONSETS and mapped < DRUM_MAPPED_THRESHOLD * len(hits):
            code = "drum_rhythm_unmapped"
        bars.append({"start_beat": start, "salient": "vocals" if singing else "drums" if hits else None,
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


def critique_arrangement(arrangement: dict, report: dict | None = None) -> dict:
    """Return warning-only density, repetition, seam and movement metrics."""
    warnings = []

    def warn(code, message, *, value, threshold, section_id=None, object_ids=(), beats=None):
        warnings.append({"severity": "warning", "code": code, "message": message,
                         "section_id": section_id, "object_ids": list(object_ids),
                         "value": value, "threshold": threshold})
        if beats is not None:  # absolute [start, end] beats of the finding, for automated repair
            warnings[-1]["beats"] = beats

    notes = expanded_notes(arrangement)
    spans = _sections(arrangement)
    times = sorted(beat_to_seconds(note["beat"], arrangement) for note in notes)
    metrics = {"note_count": len(notes), "section_count": len(spans),
               "density": _density(arrangement, notes, times, spans, warn) if notes else _empty_density(spans),
               "repetition": _repetition(notes, warn) if notes else _empty_repetition(),
               "movement_objects": _movement_objects(arrangement, spans, report),
               "boundary_accents": _boundary_accents(arrangement, spans, notes, report, warn),
               "salience": _salience(arrangement, spans, notes, report, warn)}
    # Audio grounding: blocking spans are save errors elsewhere; here every finding stays a warning.
    metrics["audio"], findings = audio_findings(arrangement, report)
    for finding in findings:
        warn(finding["code"], finding["message"], value=finding["value"], threshold=finding["threshold"],
             section_id=finding["section_id"], object_ids=finding["object_ids"])
    return {"model_version": MODEL_VERSION, "metrics": metrics, "warnings": warnings,
            "definitions": DEFINITIONS}
