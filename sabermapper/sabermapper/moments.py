"""Moments: the song's structural events (drops, builds, breaks, key changes, final chorus...).

Rule-based, deterministic measurements over the frame features of ``listen.measure`` and the
evidence run's events. Every moment records the measurements and thresholds that triggered it,
so the agent can check why it exists. Strength is a 0-1 salience score, not a probability.
"""
from __future__ import annotations

import numpy as np

from .listen import FRAME, beat_of, decibels, key_estimate, smooth_db, PITCH_CLASSES

KINDS = ("silence", "break", "build", "drop", "key_change", "tempo_shift", "energy_shift", "final_chorus",
         "vocal_entry", "vocal_return", "layer_entry", "big_hit", "ending")
LOUD_PERCENTILE = 95
SILENCE_DB = -35.0          # below the song's loud level
SILENCE_MIN_SECONDS = .3
DRUM_ACTIVE_DB = -18.0      # drums stem against its own 90th percentile
BREAK_MIN_SECONDS = 2.0
BREAK_CONTEXT_SECONDS = 8.0
ENERGY_BREAK_DB = 9.0
DROP_JUMP_DB = 6.0
DROP_LOUD_DB = -8.0         # the level after a drop, against the loud level
DROP_LOW_JUMP_DB = 4.0
DROP_BASS_SLAM_DB = 12.0
DROP_SPACING_SECONDS = 8.0
BUILD_LENGTHS = (16.0, 12.0, 8.0, 6.0, 4.0)
BUILD_RISE_DB = 4.0
BUILD_CENTROID_OCTAVES = .5
BUILD_DENSITY_RISE = 2.0
BUILD_R2 = .5
BUILD_MAX_FALL_DB = -1.0
KEY_MIN_SECONDS = 8.0
KEY_COLLECTION_MARGIN = .04
KEY_REGION_SECONDS = 16.0
KEY_RETURN_SECONDS = 30.0
DIATONIC = np.array([0, 2, 4, 5, 7, 9, 11])
TEMPO_SHIFT_RATIO = .08
TEMPO_CLARITY = 2.5
ENERGY_SHIFT_DB = 5.0
VOCAL_RETURN_SECONDS = 8.0
LAYER_ENTRY_SECONDS = 8.0
LAYER_ENTRY_SHARE_DB = -12.0
HIT_MIN_STRENGTH = .5
HIT_SPACING_SECONDS = 6.0
HIT_CONTEXT_SECONDS = 4.0
ONSET_STRENGTH = .3


def _runs(mask):
    """(start, end) frame index pairs of True runs, end exclusive."""
    mask = np.asarray(mask, dtype=bool)
    edges = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()))


def _mean_db(rms, left, right):
    left = min(max(0, left), len(rms) - 1)
    right = min(len(rms), max(right, left + 1))
    return float(10 * np.log10(max(float(np.mean(np.asarray(rms[left:right], dtype=float) ** 2)), 1e-14)))


def _fit(values):
    """Least-squares slope per frame, total rise over the window and r^2."""
    x = np.arange(len(values), dtype=float)
    if len(values) < 3 or np.std(values) < 1e-9:
        return 0.0, 0.0, 0.0
    slope, intercept = np.polyfit(x, values, 1)
    residual = values - (slope * x + intercept)
    r2 = 1 - float(np.sum(residual ** 2)) / float(np.sum((values - values.mean()) ** 2))
    return float(slope), float(slope * (len(values) - 1)), r2


def _onsets(report, layer="mix", strength=ONSET_STRENGTH):
    events = ((report.get("layers") or {}).get(layer) or {}).get("events", [])
    return sorted((e["seconds"], e["strength"], e["id"]) for e in events
                  if e.get("method") == "spectral_flux" and e.get("strength", 0) >= strength)


def detect_moments(frames, sections, report, arrangement=None):
    """All moments, sorted by time, with ids ``<kind>-<n>`` numbered in time order within each kind."""
    mix, stems, duration = frames["mix"], frames["stems"], frames["duration"]
    rms = np.asarray(mix["rms"], dtype=float)
    level = smooth_db(rms, .5)
    audible = level[level > -80]
    loud = float(np.percentile(audible, LOUD_PERCENTILE)) if len(audible) else 0.0
    context = {"loud_level_db": round(loud, 2), "frame_seconds": round(FRAME, 6)}
    found = []
    found += _silences(rms, loud, duration)
    found += _breaks(rms, stems, loud, found)
    drops = _drops(frames, report, loud, sections)
    builds = _builds(frames, report, loud, sections, drops, found)
    for drop in drops:
        before = [m for m in builds + found if m["kind"] in ("build", "break", "silence")
                  and abs(m["time"] + (m.get("duration") or 0) - drop["time"]) <= 1.5]
        if before:
            drop["strength"] = round(min(1.0, drop["strength"] + .15), 3)
            drop["evidence"]["after"] = [m["kind"] for m in before]
    found += builds + drops
    found += _key_changes(frames, sections)
    found += _tempo_shifts(frames, sections, report, arrangement)
    found += _energy_shifts(sections, found)
    found += _final_chorus(sections)
    found += _entries(report, frames)
    found += _big_hits(report, rms, duration, found)
    found += _ending(rms, report, loud, duration)
    found.sort(key=lambda m: (m["time"], KINDS.index(m["kind"])))
    counters = {}
    for moment in found:
        counters[moment["kind"]] = counters.get(moment["kind"], 0) + 1
        moment["id"] = f"{moment['kind']}-{counters[moment['kind']]}"
        moment["time"] = round(moment["time"], 3)
        moment["beat"] = beat_of(moment["time"], arrangement)
        if moment.get("duration") is not None:
            moment["duration"] = round(moment["duration"], 3)
        moment["section_id"] = next((s["id"] for s in sections if s["start"] <= moment["time"] < s["end"]),
                                    sections[-1]["id"] if sections else None)
        moment["evidence"]["context"] = context
    return [{key: m[key] for key in ("id", "kind", "time", "beat", "strength", "duration", "section_id", "evidence")
             if key in m} for m in found]


def _moment(kind, time, strength, evidence, duration=None):
    item = {"kind": kind, "time": float(time), "strength": round(float(np.clip(strength, 0, 1)), 3),
            "evidence": evidence}
    if duration is not None:
        item["duration"] = float(duration)
    return item


def _silences(rms, loud, duration):
    quiet = smooth_db(rms, .2) < loud + SILENCE_DB
    found = []
    for left, right in _runs(quiet):
        seconds = (right - left) * FRAME
        if left == 0 or right >= len(rms) - 1 or seconds < SILENCE_MIN_SECONDS:
            continue  # leading and trailing silence are the song's edges, not moments
        found.append(_moment("silence", left * FRAME, .4 + .3 * min(2.0, seconds), duration=seconds, evidence={
            "rule": f"mix level (0.2 s) below loud level {SILENCE_DB:g} dB for >= {SILENCE_MIN_SECONDS:g} s",
            "min_level_db": round(float(smooth_db(rms, .2)[left:right].min()), 2)}))
    return found


def _breaks(rms, stems, loud, silences):
    """Drums drop out (stem inactive) or the mix falls well below its recent level, then returns."""
    candidates = []
    min_frames, context = round(BREAK_MIN_SECONDS / FRAME), round(BREAK_CONTEXT_SECONDS / FRAME)
    mix_level = smooth_db(rms, .5)
    if "drums" in stems:
        drums = smooth_db(stems["drums"]["rms"], .5)
        reference = float(np.percentile(drums, 90))
        active = (drums > reference + DRUM_ACTIVE_DB) & (drums > mix_level - 30)
        for left, right in _runs(~active):
            if right - left < min_frames or left == 0 or right >= len(active):
                continue
            before = active[max(0, left - context):left]
            after = active[right:right + min_frames]
            if before.mean() >= .5 and after.mean() >= .5:
                depth = float(np.median(drums[max(0, left - context):left]) - np.median(drums[left:right]))
                candidates.append((left, right, {"rule": "drums stem inactive (below its 90th percentile "
                                                 f"{DRUM_ACTIVE_DB:g} dB) for >= {BREAK_MIN_SECONDS:g} s after "
                                                 "being active, then back", "source": "drums",
                                                 "drum_drop_db": round(depth, 2),
                                                 "mix_drop_db": round(_mean_db(rms, left - context, left) -
                                                                      _mean_db(rms, left, right), 2)}))
    median_before = np.array([np.median(mix_level[max(0, i - context):i]) if i else mix_level[0]
                              for i in range(0, len(mix_level), 5)])
    coarse = mix_level[::5]
    low = coarse < median_before - ENERGY_BREAK_DB
    low &= coarse > loud + SILENCE_DB  # near-silence is a silence moment
    for left, right in _runs(low):
        left, right = left * 5, min(len(rms), right * 5)
        if right - left < round(1.5 / FRAME) or left < context or right >= len(rms) - min_frames:
            continue
        if _mean_db(rms, right, right + min_frames) < _mean_db(rms, left, right) + ENERGY_BREAK_DB / 2:
            continue  # it has to come back
        candidates.append((left, right, {"rule": f"mix level >= {ENERGY_BREAK_DB:g} dB below the median of the "
                                         f"preceding {BREAK_CONTEXT_SECONDS:g} s for >= 1.5 s, then back",
                                         "source": "mix", "mix_drop_db": round(_mean_db(rms, left - context, left) -
                                                                              _mean_db(rms, left, right), 2)}))
    candidates.sort(key=lambda c: c[0])
    merged = []
    for left, right, evidence in candidates:
        if merged and left <= merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], right), {**previous[2], "also": evidence["source"]})
        else:
            merged.append((left, right, evidence))
    found = []
    for left, right, evidence in merged:
        start, seconds = left * FRAME, (right - left) * FRAME
        covered = sum(max(0.0, min(start + seconds, s["time"] + s["duration"]) - max(start, s["time"]))
                      for s in silences)
        if covered >= .8 * seconds:
            continue
        depth = max(evidence.get("mix_drop_db", 0), evidence.get("drum_drop_db", 0) / 2)
        found.append(_moment("break", start, .5 * min(1, seconds / 8) + .5 * min(1, depth / 20), evidence,
                             duration=seconds))
    return found


def _low_rms(frames):
    stems = frames["stems"]
    if "drums" in stems or "bass" in stems:
        parts = [np.asarray(stems[name]["rms"], dtype=float) ** 2 for name in ("drums", "bass") if name in stems]
        return np.sqrt(np.sum(parts, axis=0)), "drums+bass"
    mix = frames["mix"]
    return np.asarray(mix["rms"], dtype=float) * np.sqrt(np.asarray(mix["low_share"], dtype=float)), "mix<250Hz"


def _drops(frames, report, loud, sections):
    rms = np.asarray(frames["mix"]["rms"], dtype=float)
    low, low_source = _low_rms(frames)
    times = {round(t, 3): (s, i) for t, s, i in _onsets(report)}
    for section in sections[1:]:
        times.setdefault(round(section["start"], 3), (None, None))
    level = smooth_db(rms, .5)
    audible = np.flatnonzero(level >= loud + SILENCE_DB)
    first = audible[0] * FRAME if len(audible) else 0.0
    scored = []
    for time, (strength, event_id) in sorted(times.items()):
        if time < first + 3:
            continue  # the first sound of the song is its start, not a drop
        index = round(time / FRAME)
        before = _mean_db(rms, index - round(3 / FRAME), index - round(.25 / FRAME))
        after = _mean_db(rms, index + 1, index + round(2.5 / FRAME))
        low_jump = (_mean_db(low, index + 1, index + round(2.5 / FRAME)) -
                    _mean_db(low, index - round(3 / FRAME), index - round(.25 / FRAME)))
        jump = after - before
        # A drop: the mix jumps and the low end comes in, or (after a loud riser) the low end slams in while
        # the mix holds its level.
        if after < loud + DROP_LOUD_DB or not ((jump >= DROP_JUMP_DB and low_jump >= DROP_LOW_JUMP_DB) or
                                               (jump >= 0 and low_jump >= DROP_BASS_SLAM_DB)):
            continue
        score = .5 * min(1, max(jump, low_jump / 2) / 12 + .1) + .5 * min(1, max(0, (after - loud - DROP_LOUD_DB) / 8))
        scored.append((score, time, {"rule": f"level after >= loud level {DROP_LOUD_DB:g} dB and either mix "
                                     f"+{DROP_JUMP_DB:g} dB with low end +{DROP_LOW_JUMP_DB:g} dB, or mix not quieter "
                                     f"with low end +{DROP_BASS_SLAM_DB:g} dB (3 s before vs 2.5 s after)",
                                     "jump_db": round(jump, 2), "after_db": round(after, 2),
                                     "low_jump_db": round(low_jump, 2), "low_source": low_source,
                                     "onset_event": event_id, "onset_strength": strength}))
    chosen = []
    for score, time, evidence in sorted(scored, key=lambda s: -s[0]):
        if all(abs(time - other[1]) >= DROP_SPACING_SECONDS for other in chosen):
            chosen.append((score, time, evidence))
    return [_moment("drop", time, score, evidence) for score, time, evidence in chosen]


def _density(report, count):
    """Strong mix onsets per second, per frame (1 s box)."""
    series = np.zeros(count)
    for seconds, _, _ in _onsets(report):
        index = int(seconds / FRAME)
        if 0 <= index < count:
            series[index] += 1
    width = max(1, round(1 / FRAME))
    return np.convolve(series, np.ones(width), mode="same")


def _builds(frames, report, loud, sections, drops, quiet):
    mix = frames["mix"]
    rms = np.asarray(mix["rms"], dtype=float)
    level = smooth_db(rms, 1.0)
    centroid = np.log2(np.maximum(np.convolve(np.asarray(mix["centroid_hz"], dtype=float),
                                              np.ones(round(1 / FRAME)) / round(1 / FRAME), mode="same"), 20))
    density = _density(report, len(rms))
    ends = {round(d["time"], 3) for d in drops}
    for previous, section in zip(sections, sections[1:]):
        if section.get("level_db", -99) >= previous.get("level_db", -99) + 2:
            ends.add(round(section["start"], 3))
    gaps = [(m["time"], m["time"] + m["duration"]) for m in quiet if m["kind"] == "silence"]
    found = []
    for end in sorted(ends):
        for length in BUILD_LENGTHS:
            start = end - length
            if start < 0 or any(a < end - .1 and b > start for a, b in gaps):
                continue
            left, right = round(start / FRAME), round((end - .1) / FRAME)
            if right - left < 10 or float(np.median(level[left:right])) < loud + SILENCE_DB:
                continue
            _, rise, r2 = _fit(level[left:right])
            _, octaves, c2 = _fit(centroid[left:right])
            _, denser, d2 = _fit(density[left:right])
            reasons = [name for name, ok in (("level", rise >= BUILD_RISE_DB and r2 >= BUILD_R2),
                                             ("brightness", octaves >= BUILD_CENTROID_OCTAVES and c2 >= BUILD_R2),
                                             ("onset_density", denser >= BUILD_DENSITY_RISE and d2 >= .4)) if ok]
            if rise < BUILD_MAX_FALL_DB:
                continue  # a filter opening while the band fades out is not a build
            if not reasons:
                continue
            strength = .3 + .3 * min(1, max(rise, 0) / 10) + .2 * min(1, max(octaves, 0)) + .2 * min(1, length / 16)
            found.append(_moment("build", start, strength, duration=length, evidence={
                "rule": f"over the window: level +{BUILD_RISE_DB:g} dB, centroid +{BUILD_CENTROID_OCTAVES:g} octave or "
                        f"onset density +{BUILD_DENSITY_RISE:g}/s, each with a linear fit r^2 >= {BUILD_R2:g}; "
                        f"level never falls more than {abs(BUILD_MAX_FALL_DB):g} dB",
                "rising": reasons, "resolves_at": end, "level_rise_db": round(rise, 2), "level_r2": round(r2, 3),
                "centroid_rise_octaves": round(octaves, 3), "centroid_r2": round(c2, 3),
                "onset_density_rise": round(denser, 2), "onset_density_r2": round(d2, 3)}))
            break
    found.sort(key=lambda m: -m["duration"])
    kept = []
    for build in found:  # longest first; drop builds mostly inside a kept one
        span = (build["time"], build["time"] + build["duration"])
        if all(min(span[1], k["time"] + k["duration"]) - max(span[0], k["time"]) < .5 * build["duration"] for k in kept):
            kept.append(build)
    return kept


def collection_fits(chroma_mean):
    """Share of chroma energy inside each of the 12 diatonic collections (index = major tonic)."""
    vector = np.maximum(np.asarray(chroma_mean, dtype=float), 0)
    vector = vector / (vector.sum() or 1.0)
    return np.array([vector[(DIATONIC + tonic) % 12].sum() for tonic in range(12)])


def _key_changes(frames, sections):
    """Modulations: the best-fitting diatonic collection changes and stays changed.

    Relative major/minor share a collection, so they never count. Consecutive sections with the same
    collection form a region; a region change counts when each side fits its own collection at least
    KEY_COLLECTION_MARGIN better than the other's and the new region lasts KEY_REGION_SECONDS (or ends
    the song) without returning straight to the old collection within KEY_RETURN_SECONDS.
    """
    from .listen import harmonic_chroma
    tonal = harmonic_chroma(frames)
    usable = [s for s in sections if s.get("key") and s["end"] - s["start"] >= KEY_MIN_SECONDS
              and s.get("level_db", 0) > -45]
    regions = []
    for section in usable:
        fits = collection_fits(tonal[:, int(section["start"] / FRAME):int(section["end"] / FRAME)].mean(axis=1))
        best = int(np.argmax(fits))
        if regions and regions[-1]["collection"] == best:
            regions[-1]["sections"].append(section)
            regions[-1]["fits"].append(fits)
            continue
        regions.append({"collection": best, "sections": [section], "fits": [fits]})
    found = []
    for index in range(1, len(regions)):
        old, new = regions[index - 1], regions[index]
        old_fit, new_fit = np.mean(old["fits"], axis=0), np.mean(new["fits"], axis=0)
        margins = (float(old_fit[old["collection"]] - old_fit[new["collection"]]),
                   float(new_fit[new["collection"]] - new_fit[old["collection"]]))
        length = new["sections"][-1]["end"] - new["sections"][0]["start"]
        returns = index + 1 < len(regions) and regions[index + 1]["collection"] == old["collection"]
        last = index == len(regions) - 1
        first = new["sections"][0]
        transposed = [r for r in first.get("repeats", []) if r.get("transposed_semitones")]
        if min(margins) < KEY_COLLECTION_MARGIN and not transposed:
            continue
        if (length < KEY_REGION_SECONDS and not last) or (returns and length < KEY_RETURN_SECONDS):
            continue
        shift = (new["collection"] - old["collection"]) % 12
        a, b = old["sections"][-1]["key"], first["key"]
        found.append(_moment("key_change", first["start"], .4 + min(.4, 4 * min(margins)) + (.2 if transposed else 0),
                             evidence={
            "rule": f"best diatonic collection of sections >= {KEY_MIN_SECONDS:g} s changes, each side fits its own "
                    f">= {KEY_COLLECTION_MARGIN:g} better, the new region lasts >= {KEY_REGION_SECONDS:g} s (or ends the "
                    f"song) and does not return within {KEY_RETURN_SECONDS:g} s; or a transposed repeat",
            "from_key": f"{a['tonic']} {a['mode']}", "to_key": f"{b['tonic']} {b['mode']}",
            "from_collection": f"{PITCH_CLASSES[old['collection']]} major / {PITCH_CLASSES[(old['collection'] + 9) % 12]} minor",
            "to_collection": f"{PITCH_CLASSES[new['collection']]} major / {PITCH_CLASSES[(new['collection'] + 9) % 12]} minor",
            "semitones": shift if shift <= 6 else shift - 12, "margins": [round(m, 3) for m in margins],
            "region_seconds": round(length, 2), "transposed_repeat_of": [r["section_id"] for r in transposed]}))
    return found


def section_tempo(frames, section, arrangement=None):
    """Onset-autocorrelation tempo (60-200 BPM) inside a section, folded to the octave nearest the map BPM."""
    flux = np.asarray(frames["mix"]["flux"], dtype=float)
    left, right = int(section["start"] / FRAME), int(section["end"] / FRAME)
    values = flux[left:right] - flux[left:right].mean()
    if len(values) < round(6 / FRAME) or np.std(values) < 1e-9:
        return None
    correlation = np.correlate(values, values, mode="full")[len(values) - 1:]
    lags = np.arange(len(correlation)) * FRAME
    window = (lags >= 60 / 200) & (lags <= 60 / 60)
    if not window.any() or correlation[0] <= 0:
        return None
    index = np.flatnonzero(window)[int(np.argmax(correlation[window]))]
    clarity = float(correlation[index] / (np.median(np.abs(correlation[window])) + 1e-9))
    bpm = 60 / lags[index]
    reference = (arrangement or {}).get("song", {}).get("bpm")
    if reference:
        bpm = min((bpm * f for f in (.5, 1, 2)), key=lambda value: abs(np.log2(value / reference)))
    return {"bpm": round(float(bpm), 2), "clarity": round(clarity, 2)}


def _tempo_shifts(frames, sections, report, arrangement):
    from fractions import Fraction
    found = []
    if arrangement:
        bpm = arrangement["song"]["bpm"]
        from .listen import beat_to_seconds
        for event in sorted(arrangement.get("tempo_events", []) or [], key=lambda e: float(Fraction(str(e["beat"])))):
            seconds = beat_to_seconds(float(Fraction(str(event["beat"]))), arrangement)
            change = abs(event["bpm"] - bpm) / bpm
            found.append(_moment("tempo_shift", seconds, .4 + min(.6, change * 3), evidence={
                "rule": "arrangement tempo event", "source": "arrangement.tempo_events",
                "from_bpm": bpm, "to_bpm": event["bpm"]}))
            bpm = event["bpm"]
    tempos = [(s, section_tempo(frames, s, arrangement)) for s in sections if s["end"] - s["start"] >= 8]
    for (a, ta), (b, tb) in zip(tempos, tempos[1:]):
        if not ta or not tb or min(ta["clarity"], tb["clarity"]) < TEMPO_CLARITY:
            continue
        ratio = tb["bpm"] / ta["bpm"]
        if abs(ratio - 1) < TEMPO_SHIFT_RATIO or any(abs(ratio - r) < .04 for r in (.5, 2, 2 / 3, 1.5, .75, 4 / 3)):
            continue
        if any(abs(m["time"] - b["start"]) < 2 for m in found):
            continue
        found.append(_moment("tempo_shift", b["start"], .3 + min(.5, abs(ratio - 1) * 2), evidence={
            "rule": f"section onset-autocorrelation tempo differs by >= {TEMPO_SHIFT_RATIO:.0%} (not a simple ratio), "
                    f"both with clarity >= {TEMPO_CLARITY:g}", "source": "audio",
            "from_bpm": ta["bpm"], "to_bpm": tb["bpm"], "clarity": [ta["clarity"], tb["clarity"]]}))
    return found


def _energy_shifts(sections, found):
    shifts = []
    for previous, section in zip(sections, sections[1:]):
        delta = section.get("level_db", 0) - previous.get("level_db", 0)
        if abs(delta) < ENERGY_SHIFT_DB or section.get("level_db", 0) < -45 or previous.get("level_db", 0) < -45:
            continue
        if any(m["kind"] in ("drop", "break", "silence", "build") and
               (abs(m["time"] - section["start"]) <= 2 or
                (m["kind"] == "build" and abs(m["time"] + m["duration"] - section["start"]) <= 2)) for m in found):
            continue
        shifts.append(_moment("energy_shift", section["start"], .3 + min(.6, (abs(delta) - ENERGY_SHIFT_DB) / 10 + .1),
                              evidence={"rule": f"section level differs by >= {ENERGY_SHIFT_DB:g} dB from the previous "
                                                "section", "direction": "up" if delta > 0 else "down",
                                        "delta_db": round(delta, 2), "from_section": previous["id"]}))
    return shifts


def _final_chorus(sections):
    audible = [s for s in sections if s.get("level_db", -99) > -45]
    if len(audible) < 3:
        return []
    median = float(np.median([s["level_db"] for s in audible]))
    groups = {}
    for section in audible:
        groups.setdefault(section["group"], []).append(section)
    candidates = [(len(members), float(np.mean([m["level_db"] for m in members])), group, members)
                  for group, members in groups.items() if len(members) >= 2]
    candidates = [c for c in candidates if c[1] >= median]
    if candidates:
        count, mean, group, members = max(candidates, key=lambda c: (c[0], c[1]))
        last = members[-1]
        return [_moment("final_chorus", last["start"], min(1.0, .6 + .1 * (count - 2) + .05 * max(0, mean - median)),
                        duration=last["end"] - last["start"], evidence={
                            "rule": "last occurrence of the most repeated section group whose mean level is at or "
                                    "above the median section level", "group": group, "occurrences": count,
                            "occurrence_ids": [m["id"] for m in members], "group_level_db": round(mean, 2),
                            "median_section_level_db": round(median, 2)})]
    tail = [s for s in audible if s["start"] >= .6 * audible[-1]["end"]]
    if not tail:
        return []
    last = max(tail, key=lambda s: s["level_db"])
    return [_moment("final_chorus", last["start"], .35, duration=last["end"] - last["start"], evidence={
        "rule": "fallback: no repeated high-level section group; loudest section in the last 40% of the song",
        "group": last["group"], "fallback": True})]


def _entries(report, frames):
    found, first_vocal = [], None
    stems = frames["stems"]
    mix_db = decibels(frames["mix"]["rms"])
    for entry in report.get("layer_entries", []) or []:
        layer, seconds, silent = entry["layer"], entry["seconds"], entry.get("silent_before_seconds", 0)
        evidence = {"rule": "evidence run layer_entries (stem audible after silence)", "layer": layer,
                    "silent_before_seconds": silent, "event_id": entry.get("event_id")}
        if layer == "vocals":
            if first_vocal is None:
                first_vocal = seconds
                found.append(_moment("vocal_entry", seconds, 1.0, evidence))
            elif silent >= VOCAL_RETURN_SECONDS:
                found.append(_moment("vocal_return", seconds, .2 + .6 * min(1, silent / 16), evidence))
            continue
        if silent < LAYER_ENTRY_SECONDS or seconds < 1 or layer not in stems:
            continue
        index = int(seconds / FRAME)
        share = float(np.median(decibels(stems[layer]["rms"][index:index + round(2 / FRAME)]) -
                                mix_db[index:index + round(2 / FRAME)]))
        if share < LAYER_ENTRY_SHARE_DB:
            continue
        evidence["share_db"] = round(share, 2)
        found.append(_moment("layer_entry", seconds, .3 + .4 * min(1, silent / 20) + .3 * min(1, (share + 12) / 12),
                             evidence))
    return found


def _big_hits(report, rms, duration, found):
    onsets = _onsets(report, strength=.05)
    times = np.array([o[0] for o in onsets])
    strengths = np.array([o[1] for o in onsets])
    if not len(times):
        return []
    scored = []
    for seconds, strength, event_id in onsets:
        if strength < HIT_MIN_STRENGTH:
            continue
        near = strengths[(np.abs(times - seconds) <= HIT_CONTEXT_SECONDS) & (np.abs(times - seconds) > .05)]
        contrast = strength / (float(np.median(near)) if len(near) else .05)
        index = round(seconds / FRAME)
        jump = _mean_db(rms, index, index + round(.3 / FRAME)) - _mean_db(rms, index - round(.5 / FRAME), index - 1)
        score = strength * min(1, contrast / 2.5) * (1 if jump >= 3 else .8 if jump >= 0 else .5)
        scored.append((score, seconds, {"rule": f"mix spectral_flux onset >= {HIT_MIN_STRENGTH:g} standing out from the "
                                        f"onsets within {HIT_CONTEXT_SECONDS:g} s", "onset_event": event_id,
                                        "onset_strength": strength, "contrast": round(contrast, 2),
                                        "level_jump_db": round(jump, 2)}))
    limit = int(np.clip(duration / 25, 3, 12))
    taken = [m["time"] for m in found if m["kind"] == "drop"]
    hits = []
    for score, seconds, evidence in sorted(scored, key=lambda s: -s[0]):
        if len(hits) >= limit:
            break
        if all(abs(seconds - t) >= HIT_SPACING_SECONDS for t in [h["time"] for h in hits]) and \
                all(abs(seconds - t) >= 1.5 for t in taken):
            hits.append(_moment("big_hit", seconds, score, evidence))
    return hits


def _ending(rms, report, loud, duration):
    level = smooth_db(rms, .5)
    audible = np.flatnonzero(level >= loud + SILENCE_DB)
    if not len(audible):
        return []
    end = (audible[-1] + 1) * FRAME
    onsets = [o for o in _onsets(report) if end - 20 <= o[0] <= end]
    start = onsets[-1][0] if onsets else max(0.0, end - 2)
    tail = level[max(0, int((end - 10) / FRAME)):audible[-1] + 1]
    _, fall, r2 = _fit(tail) if len(tail) > 3 else (0, 0, 0)
    fade = bool(fall <= -12 and r2 >= .6)
    if fade:
        start = end - 10
    return [_moment("ending", start, .7, duration=end - start, evidence={
        "rule": f"last strong mix onset before the level falls {abs(SILENCE_DB):g} dB below the loud level for good"
                " (the start of the last 10 s when it fades out)", "audible_end": round(end, 3), "fade_out": fade,
        "fade_db": round(fall, 2)})]


def latest_listen(project_dir):
    """Re-export of :func:`sabermapper.listen.latest_listen` for callers that import from moments."""
    from .listen import latest_listen as load
    return load(project_dir)


__all__ = ["KINDS", "detect_moments", "latest_listen", "section_tempo", "PITCH_CLASSES"]
