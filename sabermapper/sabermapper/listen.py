"""Listen: song sections, moments and per-section mood derived from one evidence run.

Everything here is deterministic signal measurement (numpy/scipy) over the run's stems and the
project audio. Results are stored as ``listen.json`` inside the run directory, keyed to the
run's source audio hash, so they are reproducible and never outlive the audio they describe.
They describe the song for the agent's visual concept; they never place notes or events.
"""
from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path
import re

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import find_peaks, resample_poly, stft
import soundfile as sf

from .storage import now, read_json, write_json

LISTEN_VERSION = "1.0"
RATE = 22050
HOP = 1024
WINDOW = 4096
FRAME = HOP / RATE
CHROMA_HZ = (100.0, 2100.0)
HARMONIC_STEMS = {"bass": .5, "guitar": 1.0, "piano": 1.0, "other": 1.0, "vocals": .5}
# Sections: novelty over beat-synchronous features with a checkerboard kernel.
SECTION_MIN_SECONDS = 10.0
SECTION_KERNEL_SECONDS = 8.0
SECTION_PEAK_SIGMA = .3
REPEAT_THRESHOLD = .5
REPEAT_COMPARE_BEATS = 32
# Krumhansl-Kessler key profiles (major, minor), tonic first.
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
ONSET_STRENGTH = .3


def _mono(samples, rate):
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    mono = np.asarray(mono, dtype=np.float32)
    if rate != RATE:
        divisor = math.gcd(int(rate), RATE)
        mono = resample_poly(mono, RATE // divisor, int(rate) // divisor).astype(np.float32)
    return mono


def load_signal(path):
    """Mono float32 at RATE from any supported audio (stems are WAV, the project audio is OGG)."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        samples, rate = sf.read(path, dtype="float32", always_2d=True)
    else:
        from .audio import _decode
        samples, rate, _ = _decode(path)
    return _mono(samples, rate)


def frame_rms(signal, count):
    """RMS over a WINDOW centred on each frame, from cumulative squares (absolute, full-scale 1.0)."""
    squares = np.concatenate([[0.0], np.cumsum(np.asarray(signal, dtype=np.float64) ** 2)])
    centres = np.arange(count) * HOP
    left = np.clip(centres - WINDOW // 2, 0, len(signal))
    right = np.clip(centres + WINDOW // 2, 0, len(signal))
    return np.sqrt((squares[right] - squares[left]) / np.maximum(right - left, 1))


def spectral_features(signal, count, *, hpss=False):
    """Per-frame spectral descriptors: centroid, flatness, band shares, flux and a 12-bin chroma."""
    frequencies, _, spectrum = stft(np.pad(signal, (0, max(0, WINDOW - len(signal)))), fs=RATE,
                                    nperseg=WINDOW, noverlap=WINDOW - HOP, boundary="zeros", padded=True)
    magnitude = np.abs(spectrum).astype(np.float32)[:, :count]
    if magnitude.shape[1] < count:
        magnitude = np.pad(magnitude, ((0, 0), (0, count - magnitude.shape[1])))
    power = magnitude ** 2
    total = power.sum(axis=0) + 1e-20
    weight = magnitude.sum(axis=0) + 1e-20
    def flatness(low, high):
        # Geometric over arithmetic mean power (<= 1); the floor keeps silent frames at 1, not overflowing.
        values = power[(frequencies >= low) & (frequencies < high)].astype(np.float64) + 1e-10
        return np.exp(np.log(values).mean(axis=0)) / values.mean(axis=0)
    features = {
        "centroid_hz": (frequencies[:, None] * magnitude).sum(axis=0) / weight,
        "flatness": flatness(100, 8000),
        "presence_flatness": flatness(1000, 6000),
        "low_share": power[frequencies < 250].sum(axis=0) / total,
        "high_share": power[frequencies >= 4000].sum(axis=0) / total,
        "air_share": power[frequencies >= 8000].sum(axis=0) / total,
    }
    scale = float(magnitude.max()) or 1.0
    compressed = np.log1p(1000 * magnitude / scale)
    features["flux"] = np.maximum(0, np.diff(compressed, axis=1, prepend=compressed[:, :1])).sum(axis=0)
    keep = (frequencies >= CHROMA_HZ[0]) & (frequencies < CHROMA_HZ[1])
    classes = np.round(12 * np.log2(frequencies[keep] / 440.0) + 69).astype(int) % 12
    chroma = np.zeros((12, count), dtype=np.float32)
    np.add.at(chroma, classes, magnitude[keep])
    features["chroma"] = chroma
    if hpss:
        # Harmonic/percussive share on 96 log-spaced bands: time-median = harmonic, band-median = percussive.
        edges = np.geomspace(40, 10000, 97)
        index = np.digitize(frequencies, edges) - 1
        pooled = np.zeros((96, count), dtype=np.float32)
        inside = (index >= 0) & (index < 96)
        np.add.at(pooled, index[inside], power[inside])
        harmonic = median_filter(pooled, size=(1, 17)) ** 2
        percussive = median_filter(pooled, size=(9, 1)) ** 2
        mask = harmonic / (harmonic + percussive + 1e-30)
        features["harmonic_ratio"] = (mask * pooled).sum(axis=0) / (pooled.sum(axis=0) + 1e-20)
    return features


def stem_paths(run_dir, report):
    """Separated stem WAVs of the run (name -> path) that exist on disk."""
    found = {}
    for name, layer in (report.get("layers") or {}).items():
        if name != "mix" and isinstance(layer, dict) and layer.get("kind") == "audio_layer" and layer.get("audio_file"):
            path = Path(run_dir) / layer["audio_file"]
            if path.is_file():
                found[name] = path
    return found


def measure(audio, run_dir, report):
    """Frame-level measurements of the mix and every stem, one stem in memory at a time."""
    mix = load_signal(audio)
    count = max(1, len(mix) // HOP + 1)
    frames = {"count": count, "duration": len(mix) / RATE, "mix": {"rms": frame_rms(mix, count),
                                                                   **spectral_features(mix, count, hpss=True)},
              "stems": {}}
    del mix
    for name, path in stem_paths(run_dir, report).items():
        signal = load_signal(path)
        entry = {"rms": frame_rms(signal, count)}
        entry.update(spectral_features(signal, count))
        frames["stems"][name] = entry
        del signal
    return frames


def decibels(values, floor=1e-7):
    return 20 * np.log10(np.maximum(np.asarray(values, dtype=float), floor))


def smooth_db(rms, seconds):
    """Level in dB after averaging power over ``seconds``."""
    size = max(1, round(seconds / FRAME))
    return 10 * np.log10(np.maximum(uniform_filter1d(np.asarray(rms, dtype=float) ** 2, size, mode="nearest"), 1e-14))


# ---- beat grid -------------------------------------------------------------------------------------

def seconds_to_beat(seconds, arrangement):
    from .musical import seconds_to_beat as convert
    return convert(seconds, arrangement)


def beat_to_seconds(beat, arrangement):
    from .critique import beat_to_seconds as convert
    return convert(beat, arrangement)


def grid_of(arrangement):
    if not arrangement:
        return None
    song = arrangement.get("song") or {}
    return {"bpm": song.get("bpm"), "audio_offset_seconds": song.get("audio_offset_seconds"),
            "tempo_events": arrangement.get("tempo_events", [])}


def beat_of(seconds, arrangement):
    return None if not arrangement else round(seconds_to_beat(seconds, arrangement), 3)


def beat_times(arrangement, duration):
    """Beat start times inside the audio: the arrangement grid, else 0.5 s pseudo-beats."""
    if not arrangement:
        return np.arange(0, duration, .5)
    last = int(seconds_to_beat(duration, arrangement))
    times = np.array([beat_to_seconds(b, arrangement) for b in range(0, last + 1)])
    return times[(times >= 0) & (times < duration)]


def _pool(values, starts, count):
    """Mean of per-frame ``values`` (1-D or rows x frames) between consecutive frame indices."""
    values = np.asarray(values, dtype=float)
    bounds = np.append(starts, count)
    columns = []
    for left, right in zip(bounds[:-1], bounds[1:]):
        right = max(right, left + 1)
        columns.append(values[..., left:right].mean(axis=-1))
    return np.stack(columns, axis=-1)


# ---- key ---------------------------------------------------------------------------------------------

def key_estimate(chroma_mean):
    """Krumhansl-Schmuckler key: (tonic, mode, correlation, margin to the best other key, major-minor score)."""
    vector = np.asarray(chroma_mean, dtype=float)
    if vector.std() < 1e-9:
        return None
    scores = []
    for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        for tonic in range(12):
            scores.append((float(np.corrcoef(vector, np.roll(profile, tonic))[0, 1]), tonic, mode))
    scores.sort(reverse=True)
    best = scores[0]
    major = max(s[0] for s in scores if s[2] == "major")
    minor = max(s[0] for s in scores if s[2] == "minor")
    return {"tonic": PITCH_CLASSES[best[1]], "tonic_index": best[1], "mode": best[2],
            "correlation": round(best[0], 4), "margin": round(best[0] - scores[1][0], 4),
            "major_minus_minor": round(major - minor, 4)}


def harmonic_chroma(frames):
    """Chroma of the pitched stems (drums excluded), else of the mix."""
    stems = frames["stems"]
    parts = [HARMONIC_STEMS[name] * stems[name]["chroma"] for name in HARMONIC_STEMS if name in stems]
    return np.sum(parts, axis=0) if parts else frames["mix"]["chroma"]


# ---- sections ----------------------------------------------------------------------------------------

def _novelty(features, half):
    """Foote novelty: a Gaussian-tapered checkerboard kernel slid along the self-similarity diagonal."""
    count = len(features)
    normed = features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-9)
    similarity = normed @ normed.T
    axis = np.arange(-half, half)
    taper = np.exp(-((axis + .5) / (half * .5)) ** 2)
    kernel = np.outer(taper, taper) * np.outer(np.sign(axis + .5), np.sign(axis + .5))
    padded = np.pad(similarity, half, mode="edge")
    novelty = np.array([float(np.sum(kernel * padded[i:i + 2 * half, i:i + 2 * half])) for i in range(count)])
    return np.maximum(-novelty, 0) if novelty.mean() < 0 else np.maximum(novelty, 0)


def segment(frames, arrangement, silence_mask=None):
    """Audio sections (seconds, beats, repetition group) from beat-synchronous chroma, level and timbre."""
    duration, count = frames["duration"], frames["count"]
    times = beat_times(arrangement, duration)
    if len(times) < 8:
        return [{"id": "sec-01", "start": 0.0, "end": round(duration, 3)}], times
    period = float(np.median(np.diff(times)))
    starts = np.clip(np.round(times / FRAME).astype(int), 0, count - 1)
    mix = frames["mix"]
    chroma = _pool(harmonic_chroma(frames), starts, count)
    chroma = chroma / np.maximum(chroma.sum(axis=0, keepdims=True), 1e-9)
    level = _pool(decibels(mix["rms"]), starts, count)
    columns = [chroma.T * 3.0]
    for values, scale in ((level, 1.5), (np.log(_pool(mix["centroid_hz"], starts, count) + 1), 1.0),
                          (_pool(mix["flux"], starts, count), 1.0), (_pool(mix["harmonic_ratio"], starts, count), 1.0)):
        columns.append(((values - values.mean()) / (values.std() + 1e-9) * scale)[:, None] * .3)
    for stem in frames["stems"].values():
        share = _pool(decibels(stem["rms"]) - decibels(mix["rms"]), starts, count)
        columns.append((np.clip(share, -40, 0) / 40.0)[:, None] * .6)
    features = np.hstack(columns)
    features = features - features.mean(axis=0)
    half = max(4, round(SECTION_KERNEL_SECONDS / period / 2) * 2)
    novelty = _novelty(features, half)
    minimum = max(8, round(SECTION_MIN_SECONDS / period))
    height = float(novelty.mean() + SECTION_PEAK_SIGMA * novelty.std())
    peaks, _ = find_peaks(novelty, height=height, distance=minimum)
    peaks = [int(p) for p in peaks if minimum // 2 <= p <= len(times) - minimum // 2]
    if arrangement and peaks:
        # Snap to the bar phase (downbeats) within two beats: the phase the map's sections start on,
        # else the phase most novelty peaks already sit on.
        phase = bar_phase(arrangement)
        if phase is None:
            phase = max(range(4), key=lambda p: (sum(b % 4 == p for b in peaks), sum(novelty[b] for b in peaks if b % 4 == p)))
        snapped = []
        for p in peaks:
            options = [b for b in range(p - 2, p + 3) if 0 < b < len(times) and b % 4 == phase]
            snapped.append(max(options, key=lambda b: novelty[b] - .02 * abs(b - p)) if options else p)
        peaks = sorted(set(snapped))
    bounds = [0.0] + [float(times[p]) for p in peaks] + [duration]
    sections = []
    for index, (left, right) in enumerate(zip(bounds[:-1], bounds[1:])):
        if right - left < 1e-3:
            continue
        sections.append({"id": f"sec-{len(sections) + 1:02d}", "start": round(left, 3), "end": round(right, 3),
                         "novelty": round(float(novelty[peaks[index - 1]]) / (float(novelty.max()) or 1), 3)
                         if index else None})
    beat_chroma = chroma.T
    for section in sections:
        section["beat_range"] = [int(np.searchsorted(times, section["start"] - 1e-6)),
                                 int(np.searchsorted(times, section["end"] - 1e-6))]
    _repetition(sections, beat_chroma, level)
    return sections, times


def bar_phase(arrangement):
    """Beat index mod 4 that most whole-beat arrangement sections start on, when at least 60% agree."""
    phases = []
    for section in arrangement.get("sections", []):
        try:
            start = Fraction(str(section["start_beat"]))
        except (KeyError, ValueError, ZeroDivisionError):
            continue
        if start.denominator == 1:
            phases.append(int(start) % 4)
    if not phases:
        return None
    best = max(range(4), key=phases.count)
    return best if phases.count(best) >= .6 * len(phases) else None


def _repetition(sections, beat_chroma, level):
    """Group sections whose chord sequences match (song-mean chroma removed; transposition allowed)."""
    centred = beat_chroma - beat_chroma.mean(axis=0)
    levels = [float(level[s["beat_range"][0]:max(s["beat_range"][1], s["beat_range"][0] + 1)].mean())
              for s in sections]

    def compare(a, b):
        first, second = (centred[s["beat_range"][0]:s["beat_range"][1]][:REPEAT_COMPARE_BEATS] for s in (a, b))
        if min(len(first), len(second)) < 8:
            return 0.0, 0
        best = (-1.0, 0)
        for lag in range(-2, 3):
            x = first[max(0, lag):]
            y = second[max(0, -lag):]
            length = min(len(x), len(y))
            if length < 8:
                continue
            x, y = x[:length], y[:length]
            for shift in range(12):
                rolled = np.roll(y, -shift, axis=1)
                norms = np.linalg.norm(x, axis=1) * np.linalg.norm(rolled, axis=1)
                value = float(np.mean(np.sum(x * rolled, axis=1) / np.maximum(norms, 1e-9)))
                value -= .08 if shift else 0.0  # an exact repeat beats a transposed one
                best = max(best, (value, shift))
        return best
    groups = list(range(len(sections)))

    def root(i):
        while groups[i] != i:
            i = groups[i]
        return i
    matches = {}
    for i in range(len(sections)):
        for j in range(i):
            ratio = (sections[i]["end"] - sections[i]["start"]) / max(sections[j]["end"] - sections[j]["start"], 1e-6)
            if not 1 / 3 <= ratio <= 3:
                continue
            value, shift = compare(sections[j], sections[i])
            value *= math.exp(-abs(levels[i] - levels[j]) / 12)
            if value >= REPEAT_THRESHOLD:
                groups[root(i)] = root(j)
                matches.setdefault(i, []).append({"section_id": sections[j]["id"], "similarity": round(value, 3),
                                                  "transposed_semitones": (shift if shift <= 6 else shift - 12)})
    labels = {}
    for index, section in enumerate(sections):
        group = root(index)
        labels.setdefault(group, chr(ord("A") + len(labels) % 26) + ("" if len(labels) < 26 else str(len(labels) // 26)))
        section["group"] = labels[group]
        section["repeats"] = matches.get(index, [])
        section["level_db"] = round(levels[index], 2)


# ---- orchestration -----------------------------------------------------------------------------------

def listen_path(run_dir):
    return Path(run_dir) / "listen.json"


def compute_listen(project_dir, run_id, report, arrangement=None, *, mood_backend="heuristic", mood_options=None):
    """Measure the run's audio and derive sections, moments and mood; returns the listen document."""
    project_dir = Path(project_dir)
    run_dir = project_dir / "musical" / run_id
    frames = measure(project_dir / "song.ogg", run_dir, report)
    options = {**(mood_options or {}), "audio": str(project_dir / "song.ogg"),
               "stems": {name: str(path) for name, path in stem_paths(run_dir, report).items()}}
    return derive(frames, run_id, report, arrangement, mood_backend=mood_backend, mood_options=options)


def derive(frames, run_id, report, arrangement=None, *, mood_backend="heuristic", mood_options=None):
    """Sections, keys, moments and mood from frame measurements (``measure``)."""
    from .moments import detect_moments
    from .mood import section_moods
    sections, times = segment(frames, arrangement)
    tonal = harmonic_chroma(frames)
    for section in sections:
        left, right = (int(section[k] / FRAME) for k in ("start", "end"))
        section["key"] = key_estimate(tonal[:, left:max(right, left + 1)].mean(axis=1))
        section["duration"] = round(section["end"] - section["start"], 3)
        if arrangement:
            section["start_beat"], section["end_beat"] = (beat_of(section[k], arrangement) for k in ("start", "end"))
            section["map_sections"] = map_sections(arrangement, section["start_beat"], section["end_beat"])
    moments = detect_moments(frames, sections, report, arrangement)
    mood = section_moods(frames, sections, report, arrangement, backend=mood_backend, options=mood_options)
    for section in sections:
        section.pop("beat_range", None)
    stems = sorted(frames["stems"])
    return {"schema_version": LISTEN_VERSION, "created_at": now(), "run_id": run_id,
            "source_sha256": report["source"]["sha256"], "grid": grid_of(arrangement),
            "measurement": {"sample_rate": RATE, "hop_seconds": round(FRAME, 6), "window_seconds": round(WINDOW / RATE, 6),
                            "stems": stems, "duration_seconds": round(frames["duration"], 3),
                            "beats": len(times) if arrangement else None},
            "sections": sections, "moments": moments, "mood": mood,
            "limitations": [
                "Sections come from novelty in beat-synchronous chroma, level and stem balance; boundaries are "
                "candidates, snapped to the most common bar phase, not labelled verse/chorus.",
                "Repetition groups compare chord sequences with the song's mean chroma removed; a group letter means "
                "similar harmony and level, not identical audio.",
                "Keys use Krumhansl-Kessler profiles on stem chroma; relative major/minor share one pitch set, so "
                "mode is the least reliable field (see key.major_minus_minor).",
                "Moments are rule-based measurements with the thresholds recorded in each moment's evidence; "
                "strength is a 0-1 salience score, not a probability.",
                "Mood (valence/arousal) and timbre tags are documented heuristics over measured features, not a "
                "trained model or a human judgement.",
                "Nothing here implies human listening review or a playtest."]}


def map_sections(arrangement, start_beat, end_beat):
    """Arrangement section IDs overlapping a beat range."""
    found = []
    for section in arrangement.get("sections", []):
        try:
            left = float(Fraction(str(section["start_beat"])))
            right = left + float(Fraction(str(section.get("length_beats", 0))))
        except (KeyError, ValueError, ZeroDivisionError):
            continue
        if left < end_beat and right > start_beat:
            found.append(section.get("id"))
    return found


def _resolve_run(directory, project_id, run_id=None):
    """(run_id, report): the named run of the current audio, else the newest one."""
    from .audio import _hash
    from .lyrics import ListenError
    from .musical import latest_run
    if run_id is None:
        run_id, report = latest_run(directory)
        if report is None:
            raise ListenError("evidence_missing", "No evidence run matches the project's current audio",
                              f"Run `music analyze {project_id} --backend ensemble` first")
        return run_id, report
    if not re.fullmatch(r"[a-f0-9]{32}", run_id) or not (directory / "musical" / run_id / "report.json").is_file():
        raise ListenError("run_unknown", f"Unknown evidence run {run_id}", f"List runs with `music list {project_id}`")
    report = read_json(directory / "musical" / run_id / "report.json")
    if report["source"]["sha256"] != _hash(directory / "song.ogg"):
        raise ListenError("run_stale", "That evidence run analyzed different audio",
                          f"Analyze the current audio with `music analyze {project_id} --backend ensemble`")
    return run_id, report


def listen_project(store, project_id, run_id=None, *, force=False, mood_backend="heuristic", mood_options=None):
    """Compute (or reuse) listen.json for a run of the project's current audio; returns a summary."""
    directory = store.directory(project_id)
    run_id, report = _resolve_run(directory, project_id, run_id)
    path = listen_path(directory / "musical" / run_id)
    arrangement = read_json(directory / "arrangement.json") if (directory / "arrangement.json").exists() else None
    reused = False
    if path.exists() and not force:
        document = read_json(path)
        if document.get("schema_version") == LISTEN_VERSION and document.get("mood", {}).get("backend") == mood_backend:
            reused = True
            document = rebeat(document, arrangement)
        else:
            document = None
    else:
        document = None
    if document is None:
        document = compute_listen(directory, run_id, report, arrangement, mood_backend=mood_backend,
                                  mood_options=mood_options)
        write_json(path, document)
    write_json(directory / "musical" / run_id / "moments.json", moments_file(document))
    return {"project": project_id, "run_id": run_id, "path": str(path), "reused": reused,
            **summary(document)}


def moments_file(document):
    """``moments.json`` in the show compiler's driver shape: items with seconds, end_seconds, kind, strength."""
    items = []
    for moment in document.get("moments", []):
        item = {"id": moment["id"], "kind": moment["kind"], "seconds": moment["time"], "beat": moment.get("beat"),
                "strength": moment["strength"], "section_id": moment.get("section_id")}
        if moment.get("duration"):
            item["end_seconds"] = round(moment["time"] + moment["duration"], 3)
        items.append(item)
    return {"schema_version": LISTEN_VERSION, "run_id": document.get("run_id"),
            "source_sha256": document.get("source_sha256"), "derived_from": "listen.json", "moments": items}


def summary(document):
    """Compact view for the agent: sections with mood, and the moment list."""
    moods = (document.get("mood") or {}).get("sections", {})
    sections = []
    for section in document.get("sections", []):
        mood = moods.get(section["id"], {})
        sections.append({key: section.get(key) for key in ("id", "start", "end", "start_beat", "end_beat", "group",
                                                            "level_db", "map_sections")}
                        | {"key": (f"{section['key']['tonic']} {section['key']['mode']}" if section.get("key") else None),
                           "valence": mood.get("valence"), "arousal": mood.get("arousal"),
                           "tags": [t["tag"] for t in mood.get("tags", []) if t["confidence"] >= .5]})
    return {"sections": sections,
            "moments": [{key: m.get(key) for key in ("id", "kind", "time", "beat", "strength", "duration", "section_id")}
                        for m in document.get("moments", [])],
            "song_mood": (document.get("mood") or {}).get("song"),
            "next": "Read listen.json for evidence per moment and mood features; `concept template` pre-fills a concept "
                    "from it."}


def rebeat(document, arrangement):
    """Refresh beat fields when the map grid changed since listen.json was written (times are fixed)."""
    if not arrangement or document.get("grid") == grid_of(arrangement):
        return document
    for moment in document.get("moments", []):
        moment["beat"] = beat_of(moment["time"], arrangement)
    for section in document.get("sections", []):
        section["start_beat"], section["end_beat"] = (beat_of(section[k], arrangement) for k in ("start", "end"))
        section["map_sections"] = map_sections(arrangement, section["start_beat"], section["end_beat"])
    document["grid"] = grid_of(arrangement)
    document["rebeat"] = "beats recomputed against the current arrangement grid"
    return document


def latest_listen(project_dir):
    """Integration entry point: {run_id, moments, mood, lyrics, sections, ...} for the newest run of the
    project's current audio. ``available`` is False (lists empty) until `music listen` has run; ``lyrics``
    is None until `music lyrics` has run. Beats follow the current arrangement grid."""
    from .musical import latest_run
    project_dir = Path(project_dir)
    run_id, report = latest_run(project_dir)
    result = {"run_id": run_id, "available": False, "moments": [], "mood": {}, "sections": [], "lyrics": None,
              "path": None}
    if report is None:
        result["hint"] = "No evidence run matches the current audio; run `music analyze` then `music listen`."
        return result
    run_dir = project_dir / "musical" / run_id
    arrangement = read_json(project_dir / "arrangement.json") if (project_dir / "arrangement.json").exists() else None
    lyrics_file = run_dir / "lyrics.json"
    if lyrics_file.exists():
        from .lyrics import rebeat_lyrics
        lyrics = read_json(lyrics_file)
        result["lyrics"] = rebeat_lyrics(lyrics, arrangement) if arrangement else lyrics
    if not listen_path(run_dir).exists():
        result["hint"] = "Run `music listen` to compute moments and mood for this run."
        return result
    document = rebeat(read_json(listen_path(run_dir)), arrangement)
    result.update(available=True, moments=document.get("moments", []), mood=document.get("mood", {}),
                  sections=document.get("sections", []), path=str(listen_path(run_dir)),
                  schema_version=document.get("schema_version"),
                  stale=document.get("schema_version") != LISTEN_VERSION)
    return result
