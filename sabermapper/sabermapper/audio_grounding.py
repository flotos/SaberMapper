"""Audio grounding: the map exists to put the song's audio under the player's sabers.

Three checks compare an arrangement with a musical evidence run:

* underfilled audio: a stretch where the mix is audibly active and the stems carry strong
  onsets, yet the map holds at most one note per 4-second window. A stretch of
  BLOCKING_SECONDS or more is an error: saving refuses it.
* unsupported notes: notes with no onset, pitch or melody change in any layer near their time,
  meaning they were placed on a grid rather than on a sound.
* notes off their sound: a sound sits under the note, but OFF_SOUND_SECONDS or more away. One such note in a
  steady groove passes, since the drums carry the beat; several close together, or one where no drum plays (a
  free-time choir snapped to a grid it does not follow), are heard as off-rhythm.
"""

from __future__ import annotations

from bisect import bisect_left
from fractions import Fraction
from pathlib import Path
from statistics import median

from .arrangement import expanded_notes

WINDOW_SECONDS = 4.0
HOP_SECONDS = 0.5
AUDIBLE_FLOOR = 0.01
ACTIVE_LEVEL = 0.5
ACTIVE_SHARE = 0.6
ONSET_STRENGTH = 0.3
ONSET_RATE = 1.5
MAX_WINDOW_NOTES = 1
BLOCKING_SECONDS = 8.0
SUPPORT_STRENGTH = 0.2
SUPPORT_BEATS = 0.13
SUPPORT_SHARE = 0.9
UNSUPPORTED_RUN = 4
ONSET_METHODS = ("spectral_flux", "pitch_change", "melody_change")
OFF_SOUND_SECONDS = 0.04
OFF_SOUND_RUN = 3
OFF_SOUND_WINDOW = 6
PULSE_BEATS = 2  # a drum attack this close carries the beat for a note off its sound

DEFINITIONS = {
    "active_audio": f"A mix energy frame at or above {ACTIVE_LEVEL:g} times the median of audible mix frames "
                    f"(frames above {AUDIBLE_FLOOR:g} times the loudest frame).",
    "audio_unmapped": f"A stretch built from {WINDOW_SECONDS:g} s windows (hopped {HOP_SECONDS:g} s) where at least "
                      f"{ACTIVE_SHARE:.0%} of mix frames are active audio and the stems carry at least {ONSET_RATE:g} "
                      f"strong onsets per second (spectral_flux, pitch_change or melody_change, strength {ONSET_STRENGTH:g} or more), "
                      f"yet the map holds at most {MAX_WINDOW_NOTES} note in each window. Blocking at "
                      f"{BLOCKING_SECONDS:g} s or longer.",
    "note_support": f"A note is supported when some layer has a spectral_flux, pitch_change or melody_change event of strength "
                    f"{SUPPORT_STRENGTH:g} or more within {SUPPORT_BEATS:g} beat of it.",
    "low_audio_support": f"Fewer than {SUPPORT_SHARE:.0%} of the map's note times are supported by an audio event.",
    "note_without_audio": f"{UNSUPPORTED_RUN} or more consecutive note times with no supporting audio event: "
                          "notes placed on the grid rather than on a sound.",
    "note_off_sound": f"{OFF_SOUND_RUN} or more of {OFF_SOUND_WINDOW} consecutive note times, or any one with no drum "
                      f"attack within {PULSE_BEATS} beats, sit {OFF_SOUND_SECONDS * 1000:g} ms or more from the nearest "
                      "supporting audio event: notes near a sound but off its time, heard as off-rhythm.",
    "audio_evidence_missing": "No musical evidence run matches the project's current audio, so the audio checks "
                              "did not run.",
}


def _beat_seconds(arrangement):
    from .critique import beat_to_seconds
    return lambda beat: beat_to_seconds(beat, arrangement)


def _count(values, start, end):
    return bisect_left(values, end) - bisect_left(values, start)


def _stem_onsets(report, strength, *, include_mix=False):
    """Onset times per layer; the mix is excluded when stems exist unless asked for."""
    layers = report.get("layers") or {}
    names = [n for n in layers if include_mix or n != "mix"] or list(layers)
    return {name: sorted(float(e["seconds"]) for e in layers[name].get("events", [])
                         if e.get("method") in ONSET_METHODS and e.get("strength", 0) >= strength)
            for name in names}


def _activity(report):
    """Return (frame times, active flags) from the mix energy contour."""
    contour = ((report.get("layers") or {}).get("mix") or {}).get("energy_contour") or []
    if not contour:
        return [], []
    loudest = max(float(c["energy"]) for c in contour)
    audible = [float(c["energy"]) for c in contour if float(c["energy"]) > AUDIBLE_FLOOR * loudest]
    level = ACTIVE_LEVEL * median(audible) if audible else float("inf")
    return [float(c["seconds"]) for c in contour], [float(c["energy"]) >= level for c in contour]


def underfilled_spans(arrangement: dict, report: dict) -> list[dict]:
    """Stretches of active, rhythmic audio that the map leaves (nearly) empty."""
    from .musical import seconds_to_beat
    frames, active = _activity(report)
    if not frames:
        return []
    to_seconds = _beat_seconds(arrangement)
    times = sorted(to_seconds(n["beat"]) for n in expanded_notes(arrangement))
    onsets = _stem_onsets(report, ONSET_STRENGTH)
    merged = sorted(t for values in onsets.values() for t in values)
    duration = float((report.get("source") or {}).get("duration_seconds") or frames[-1])
    flagged, start = [], 0.0
    while start + WINDOW_SECONDS <= duration + 1e-9:
        end = start + WINDOW_SECONDS
        lo, hi = bisect_left(frames, start), bisect_left(frames, end)
        share = sum(active[lo:hi]) / (hi - lo) if hi > lo else 0.0
        if (share >= ACTIVE_SHARE and _count(merged, start, end) >= ONSET_RATE * WINDOW_SECONDS
                and _count(times, start, end) <= MAX_WINDOW_NOTES):
            if flagged and start <= flagged[-1][1]:
                flagged[-1][1] = end
            else:
                flagged.append([start, end])
        start += HOP_SECONDS
    spans = []
    for first, last in flagged:
        spans.append({"start_seconds": round(first, 3), "end_seconds": round(last, 3),
                      "seconds": round(last - first, 3),
                      "start_beat": round(seconds_to_beat(first, arrangement), 3),
                      "end_beat": round(seconds_to_beat(last, arrangement), 3),
                      "note_count": _count(times, first, last),
                      "strong_onsets": {name: _count(values, first, last) for name, values in onsets.items()
                                        if _count(values, first, last)},
                      "blocking": last - first >= BLOCKING_SECONDS})
    return spans


def note_support(arrangement: dict, report: dict) -> dict:
    """Which note times sit on an audio event, and the runs that do not."""
    from .critique import DRUM_ONSET_STRENGTH
    onsets = sorted(t for values in _stem_onsets(report, SUPPORT_STRENGTH, include_mix=True).values()
                    for t in values)
    to_seconds, tempo = _beat_seconds(arrangement), float(arrangement["song"]["bpm"])
    drum_layer = (report.get("layers") or {}).get("drums")
    drums = sorted(float(e["seconds"]) for e in drum_layer.get("events", []) if e.get("method") == "spectral_flux"
                   and e.get("strength", 0) >= DRUM_ONSET_STRENGTH) if isinstance(drum_layer, dict) else None
    pulse_reach = PULSE_BEATS * 60 / tempo
    by_beat = {}
    for note in expanded_notes(arrangement):
        by_beat.setdefault(Fraction(str(note["beat"])), []).append(note["id"])
    rows = []
    for beat in sorted(by_beat):
        seconds = to_seconds(beat)
        tolerance = SUPPORT_BEATS * 60 / tempo
        index = bisect_left(onsets, seconds - tolerance)
        after = bisect_left(onsets, seconds)
        nearest = min((abs(onsets[i] - seconds) for i in (after - 1, after) if 0 <= i < len(onsets)), default=None)
        rows.append({"beat": float(beat), "seconds": seconds, "ids": by_beat[beat],
                     "supported": index < len(onsets) and onsets[index] <= seconds + tolerance,
                     "offset": None if nearest is None or nearest > tolerance else nearest,
                     # Without a drum stem there is no telling; the beat is taken as carried.
                     "pulse": drums is None or _count(drums, seconds - pulse_reach, seconds + pulse_reach + 1e-9) > 0})
    runs, current = [], []
    for row in rows + [{"supported": True}]:
        if not row["supported"]:
            current.append(row)
            continue
        if len(current) >= UNSUPPORTED_RUN:
            runs.append({"start_beat": current[0]["beat"], "end_beat": current[-1]["beat"],
                         "note_times": len(current), "object_ids": [i for r in current for i in r["ids"]]})
        current = []
    supported = sum(1 for r in rows if r["supported"])
    return {"note_times": len(rows), "supported": supported,
            "share": round(supported / len(rows), 4) if rows else 1.0, "unsupported_runs": runs,
            "off_sound_runs": _off_sound_runs(rows)}


def _off_sound_runs(rows):
    """Runs of note times near a sound but OFF_SOUND_SECONDS or more from it: OFF_SOUND_RUN of any
    OFF_SOUND_WINDOW consecutive note times, or any one with no drum attack within PULSE_BEATS, joined while
    they overlap."""
    off = [i for i, r in enumerate(rows) if r["offset"] is not None and r["offset"] >= OFF_SOUND_SECONDS]
    flagged = {i for i in off if not rows[i]["pulse"]}
    for k, first in enumerate(off):
        window = [i for i in off[k:] if i < first + OFF_SOUND_WINDOW]
        if len(window) >= OFF_SOUND_RUN:
            flagged.update(window)
    runs = []
    for i in sorted(flagged):
        if runs and i - runs[-1][-1] < OFF_SOUND_WINDOW:
            runs[-1].append(i)
        else:
            runs.append([i])
    return [{"start_beat": rows[run[0]]["beat"], "end_beat": rows[run[-1]]["beat"], "note_times": len(run),
             "offsets_ms": [round(rows[i]["offset"] * 1000) for i in run],
             "object_ids": [n for i in run for n in rows[i]["ids"]]} for run in runs]


def _section_at(arrangement, beat):
    for section in arrangement["sections"]:
        start = float(Fraction(str(section["start_beat"])))
        if start <= beat < start + float(Fraction(str(section.get("length_beats", 0)))):
            return section["id"]
    return None


def _layers_text(counts):
    return ", ".join(f"{name} {count}" for name, count in sorted(counts.items(), key=lambda i: -i[1])) or "none"


def audio_findings(arrangement: dict, report: dict | None) -> tuple[dict, list[dict]]:
    """Return (metrics, findings). Findings use the diagnostic shape plus value and threshold."""
    if not report:
        return {"checked": False}, []
    findings = []

    def add(severity, code, message, *, value, threshold, section_id=None, object_ids=(), beats=None):
        findings.append({"severity": severity, "code": code, "message": message, "section_id": section_id,
                         "object_ids": list(object_ids), "value": value, "threshold": threshold})
        if beats is not None:
            findings[-1]["beats"] = beats

    spans = underfilled_spans(arrangement, report)
    for span in spans:
        add("error" if span["blocking"] else "warning", "audio_unmapped",
            f'{span["start_seconds"]:.1f}-{span["end_seconds"]:.1f} s (beats {span["start_beat"]:g}-'
            f'{span["end_beat"]:g}): the song is playing but the map holds only {span["note_count"]} note(s) '
            f'over {span["seconds"]:.1f} s. Strong onsets there: {_layers_text(span["strong_onsets"])}. '
            "Map the audible layers in this stretch.",
            value=span["seconds"], threshold=BLOCKING_SECONDS,
            section_id=_section_at(arrangement, span["start_beat"]), beats=[span["start_beat"], span["end_beat"]])
    support = note_support(arrangement, report) if arrangement["sections"] else {
        "note_times": 0, "supported": 0, "share": 1.0, "unsupported_runs": [], "off_sound_runs": []}
    if support["note_times"] and support["share"] < SUPPORT_SHARE:
        add("warning", "low_audio_support",
            f'Only {support["supported"]} of {support["note_times"]} note times ({support["share"]:.0%}) sit on an '
            "audio onset or pitch change; move grid filler onto sounds or remove it.",
            value=support["share"], threshold=SUPPORT_SHARE)
    for run in support["unsupported_runs"]:
        add("warning", "note_without_audio",
            f'Beats {run["start_beat"]:g}-{run["end_beat"]:g}: {run["note_times"]} consecutive note times have no '
            "audio event under them.",
            value=run["note_times"], threshold=UNSUPPORTED_RUN,
            section_id=_section_at(arrangement, run["start_beat"]), object_ids=run["object_ids"],
            beats=[run["start_beat"], run["end_beat"]])
    for run in support["off_sound_runs"]:
        add("warning", "note_off_sound",
            f'Beats {run["start_beat"]:g}-{run["end_beat"]:g}: {run["note_times"]} note time(s) sit '
            f'{min(run["offsets_ms"])}-{max(run["offsets_ms"])} ms from the sound under them, heard as off-rhythm. '
            "Move each onto its sound's own time, off the grid where the music does not follow it.",
            value=run["note_times"], threshold=OFF_SOUND_RUN,
            section_id=_section_at(arrangement, run["start_beat"]), object_ids=run["object_ids"],
            beats=[run["start_beat"], run["end_beat"]])
    metrics = {"checked": True, "unmapped_spans": spans,
               "note_support": {k: v for k, v in support.items() if k not in ("unsupported_runs", "off_sound_runs")},
               "unsupported_runs": [{k: v for k, v in r.items() if k != "object_ids"}
                                    for r in support["unsupported_runs"]],
               "off_sound_runs": [{k: v for k, v in r.items() if k != "object_ids"} for r in support["off_sound_runs"]]}
    return metrics, findings


def project_audio_findings(directory: Path, arrangement: dict) -> tuple[str | None, dict, list[dict]]:
    """Run the audio checks against the project's newest evidence run for its current audio."""
    from .musical import latest_run
    run_id, report = latest_run(directory)
    if report is None:
        return None, {"checked": False}, []
    metrics, findings = audio_findings(arrangement, report)
    return run_id, metrics, findings
