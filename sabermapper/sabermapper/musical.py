"""Local musical evidence for an independently invoked authoring agent.

No note generation, automatic instrument selection, or provider calls. Evidence
uses source-audio seconds; beat conversion happens against the current map grid.
"""
from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path
import re
import subprocess
import sys
import uuid

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import soundfile as sf
from scipy.fft import irfft, next_fast_len, rfft
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, istft, resample_poly, stft

from .audio import _decode, _hash
from .storage import now, read_json, write_json

RATE = 22050
HOP = 220
WINDOW = 1024
BACKENDS = ("bands", "hpss", "demucs", "import")
# Monophonic f0 search range and YIN geometry; the comparison window is centred on the frame.
MINIMUM_HZ, MAXIMUM_HZ = 70.0, 1100.0
MAXIMUM_LAG, MINIMUM_LAG = int(RATE / MINIMUM_HZ), max(2, int(RATE / MAXIMUM_HZ))
PITCH_WINDOW = 1024
PITCH_FRAME = PITCH_WINDOW + MAXIMUM_LAG + 1
PITCH_FFT = next_fast_len(PITCH_FRAME + PITCH_WINDOW)
LAGS = np.arange(MAXIMUM_LAG + 1)
VOICED_CONFIDENCE = .55
STABLE_CONFIDENCE = .6
PITCH_MEDIAN_FRAMES = 7
CONTINUITY_SEMITONES = 2.0
SUSTAIN_GAP_SECONDS = .05
SUSTAIN_MINIMUM_SECONDS = .35
SUSTAIN_SHAPE_SEMITONES = .8
UNSTABLE_RESIDUAL_SEMITONES = 3.0
CHANGE_SEMITONES = .8
CHANGE_HOLD_SECONDS = .1
CHANGE_TOLERANCE_SEMITONES = .6
CHANGE_TRANSITION_FRAMES = 3
SUSTAINED_DECIBELS = 6.0
SUSTAINED_LOOKBACK_SECONDS = .25
SUSTAINED_FLOOR = .1
SUSTAINED_LAYER_FRACTION = .6
PASSAGE_SECONDS = 2.0
PASSAGE_ONSET_STRENGTH = .35
PASSAGE_DENSITY_REFERENCE = 2.0
LOW_INTENSITY_DENSITY = .5
LOW_INTENSITY_ENERGY_RATIO = .6
PRESETS = {
    "balanced": {"minimum_gap_seconds": .09, "prominence": .10},
    "metal": {"minimum_gap_seconds": .065, "prominence": .12},
    "electronic": {"minimum_gap_seconds": .08, "prominence": .09},
    "vocal": {"minimum_gap_seconds": .12, "prominence": .08},
}


def _signal(path):
    samples, rate, decoder = _decode(path)
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError("Audio must contain finite, nonempty samples")
    # Preserve attacks even in stereo recordings with out-of-phase channels.
    channel = int(np.argmax(np.mean(samples.astype(np.float64) ** 2, axis=0)))
    mono = samples[:, channel]
    if rate != RATE:
        divisor = math.gcd(rate, RATE)
        mono = resample_poly(mono, RATE // divisor, rate // divisor)
    return mono, {"sha256": _hash(Path(path)), "sample_rate": rate,
                  "frames": len(samples), "duration_seconds": len(samples) / rate,
                  "decoder": decoder, "analysis_channel": channel}


def _spectrum(samples):
    padded = np.pad(samples, (0, max(0, WINDOW - len(samples))))
    return stft(padded, fs=RATE, nperseg=WINDOW, noverlap=WINDOW-HOP,
                boundary="zeros", padded=True)


def _normalized(values):
    scale = float(np.max(values)) if len(values) else 0
    return values / scale if scale > 1e-10 else np.zeros_like(values)


def _difference(block):
    """Vectorized cumulative-mean-normalized difference (YIN) for a block of frames."""
    squares = np.concatenate([np.zeros((len(block), 1)), np.cumsum(block ** 2, axis=1)], axis=1)
    head = squares[:, PITCH_WINDOW:PITCH_WINDOW+1]
    lagged = squares[:, PITCH_WINDOW:PITCH_WINDOW+MAXIMUM_LAG+1] - squares[:, :MAXIMUM_LAG+1]
    spectrum = rfft(block, PITCH_FFT, axis=1, workers=-1)
    reference = rfft(block[:, :PITCH_WINDOW], PITCH_FFT, axis=1, workers=-1)
    correlation = irfft(np.conj(reference) * spectrum, PITCH_FFT, axis=1, workers=-1)[:, :MAXIMUM_LAG+1]
    difference = np.maximum(0, head + lagged - 2 * correlation)
    normalized = np.ones_like(difference)
    running = np.cumsum(difference, axis=1)
    np.divide(difference[:, 1:] * LAGS[1:], np.maximum(running[:, 1:], 1e-12), out=normalized[:, 1:])
    normalized[(head[:, 0] < 1e-12) | (running[:, -1] < 1e-12)] = 1
    return normalized, np.sqrt(head[:, 0] / PITCH_WINDOW)


def _frame_candidates(block):
    """Up to four local-minimum lag candidates per frame, refined and confidence ordered."""
    normalized, rms = _difference(block)
    dip = np.zeros(normalized.shape, dtype=bool)
    dip[:, 1:-1] = (normalized[:, 1:-1] < normalized[:, :-2]) & (normalized[:, 1:-1] <= normalized[:, 2:])
    dip[:, :MINIMUM_LAG] = dip[:, MAXIMUM_LAG:] = False
    masked = np.where(dip, normalized, np.inf)
    picks = np.argpartition(masked, 4, axis=1)[:, :4]
    values = np.take_along_axis(masked, picks, axis=1)
    order = np.argsort(values, axis=1)
    picks, values = np.take_along_axis(picks, order, axis=1), np.take_along_axis(values, order, axis=1)
    safe = np.clip(picks, 1, MAXIMUM_LAG - 1)
    left, middle, right = (np.take_along_axis(normalized, safe + offset, axis=1) for offset in (-1, 0, 1))
    curvature = left - 2 * middle + right
    shift = np.clip(np.divide(.5 * (left - right), curvature, out=np.zeros_like(curvature),
                              where=np.abs(curvature) > 1e-12), -1, 1)
    return RATE / np.maximum(safe + shift, 1e-6), np.where(np.isfinite(values), 1 - values, 0).clip(0, 1), rms


def _pitch_track(samples):
    """Monophonic f0 per frame with octave continuity; NaN MIDI where unvoiced."""
    count = max(1, len(samples) // HOP + 1)
    padded = np.pad(np.asarray(samples, dtype=np.float64), (PITCH_WINDOW//2, PITCH_FRAME + HOP))
    frames = sliding_window_view(padded, PITCH_FRAME)[::HOP][:count]
    hertz, scores, rms = [], [], []
    for begin in range(0, count, 512):
        block = _frame_candidates(np.ascontiguousarray(frames[begin:begin+512]))
        hertz.append(block[0]), scores.append(block[1]), rms.append(block[2])
    hertz, scores, rms = (np.concatenate(part) for part in (hertz, scores, rms))
    audible = rms[rms > 0]
    gate = max(.5 * float(np.percentile(audible, 30)), .01 * float(np.max(rms)), 1e-4) if len(audible) else np.inf
    midi, confidence = np.full(count, np.nan), np.zeros(count)
    previous, quiet = None, 0
    for index in range(count):
        options = [(h, c) for h, c in zip(hertz[index].tolist(), scores[index].tolist()) if c > 0]
        choice = options[0] if options else None
        if choice and previous:
            # Octave continuity: stay with the previous pitch whenever a credible candidate is near it.
            near = [o for o in options if o[1] >= VOICED_CONFIDENCE
                    and abs(12 * math.log2(o[0] / previous)) <= CONTINUITY_SEMITONES]
            choice = min(near, key=lambda o: abs(o[0] - previous)) if near else choice
        if not choice or choice[1] < VOICED_CONFIDENCE or rms[index] < gate:
            quiet += 1
            previous = None if quiet > 20 else previous
            continue
        midi[index], confidence[index], previous, quiet = 69 + 12*math.log2(choice[0]/440), choice[1], choice[0], 0
    voiced = ~np.isnan(midi)
    smooth = np.full(count, np.nan)
    if voiced.any():
        windows = sliding_window_view(np.pad(midi, (PITCH_MEDIAN_FRAMES//2,)*2, constant_values=np.nan),
                                      PITCH_MEDIAN_FRAMES)
        smooth[voiced] = np.nanmedian(windows[voiced], axis=1)
    return smooth, confidence, rms, voiced


def _segments(name, track):
    """Contiguous voiced runs with a robust pitch trend; evidence only, never notes."""
    smooth, confidence, rms, voiced = track
    gap = max(1, round(SUSTAIN_GAP_SECONDS * RATE / HOP))
    runs, current, offset = [], [], 0.0
    for index in np.flatnonzero(voiced).tolist():
        value = float(smooth[index]) + offset
        if current and index - current[-1][0] <= gap + 1:
            if abs(abs(value - current[-1][1]) - 12) <= 1:  # fold an octave slip instead of breaking
                offset -= math.copysign(12, value - current[-1][1])
                value = float(smooth[index]) + offset
            if abs(value - current[-1][1]) <= CONTINUITY_SEMITONES:
                current.append((index, value))
                continue
        runs.append(current) if current else None
        current, offset = [(index, float(smooth[index]))], 0.0
    runs.append(current) if current else None
    sustains = []
    for run in runs:
        indices = np.array([frame for frame, _ in run])
        values = np.array([value for _, value in run])
        start, end = indices[0] * HOP / RATE, indices[-1] * HOP / RATE
        if end - start < SUSTAIN_MINIMUM_SECONDS:
            continue
        seconds = (indices - indices[0]) * HOP / RATE
        keep = np.abs(values - median_filter(values, size=min(21, len(values) | 1), mode="nearest")) <= 3
        slope, intercept = np.polyfit(seconds[keep], values[keep], 1) if keep.sum() > 1 else (0.0, values[0])
        residual = float(np.std(values[keep] - (slope * seconds[keep] + intercept))) if keep.sum() > 1 else 0.0
        delta, score = float(slope) * float(end - start), float(np.mean(confidence[indices]))
        shape = ("unstable" if residual > UNSTABLE_RESIDUAL_SEMITONES or score < STABLE_CONFIDENCE else
                 "rise" if delta >= SUSTAIN_SHAPE_SEMITONES else
                 "fall" if delta <= -SUSTAIN_SHAPE_SEMITONES else "flat")
        sustains.append({"id": f"{name}:sustain:{int(indices[0])}",
                         "start_seconds": round(float(start), 6), "end_seconds": round(float(end), 6),
                         "start_hz": round(440 * 2 ** ((float(values[0])-69)/12), 4),
                         "end_hz": round(440 * 2 ** ((float(values[-1])-69)/12), 4),
                         "median_hz": round(440 * 2 ** ((float(np.median(values))-69)/12), 4),
                         "semitone_delta": round(delta, 3), "pitch_shape": shape,
                         "confidence": round(score * len(indices) / float(indices[-1]-indices[0]+1), 4),
                         "strength": float(np.mean(rms[indices]))})
    ceiling = max((s["strength"] for s in sustains), default=0)
    for sustain in sustains:
        sustain["strength"] = round(sustain["strength"] / ceiling, 5) if ceiling > 1e-12 else 0.0
    return sustains


def _pitch_changes(name, track, duration):
    """Settled steps of the smoothed pitch; vibrato stays below the step threshold."""
    smooth, _, _, voiced = track
    hold = max(1, round(CHANGE_HOLD_SECONDS * RATE / HOP))
    events, held, index, quiet = [], None, 0, 0
    while index < len(smooth):
        window = smooth[index:index+hold]
        if not voiced[index] or len(window) < hold or np.isnan(window).any():
            quiet, index = quiet + 1, index + 1
            held = None if quiet > 20 else held
            continue
        quiet = 0
        target = float(np.median(window))
        settled = target if float(np.max(np.abs(window - target))) <= CHANGE_TOLERANCE_SEMITONES else None
        if settled is None or held is None:
            held, index = settled if held is None else held, index + 1
            continue
        # A step, not a glide: most of the move happens inside a few frames.
        start = max(0, index - CHANGE_TRANSITION_FRAMES)
        move = settled - float(smooth[start]) if voiced[start:index+1].all() else 0.0
        if (abs(settled - held) >= CHANGE_SEMITONES and abs(move) >= CHANGE_SEMITONES
                and move * (settled - held) > 0 and start * HOP / RATE < duration):
            events.append({"id": f"{name}:pitch_change:{start}", "seconds": round(start * HOP / RATE, 6),
                           "method": "pitch_change", "strength": round(min(1, abs(settled-held)/12), 5),
                           "from_midi": round(held, 2), "to_midi": round(settled, 2),
                           "semitone_delta": round(settled - held, 2)})
            held, index = settled, index + hold
            continue
        index += 1
    return events


def _attack_profile(power):
    """Fraction of loud frames still holding near their recent peak rather than decaying."""
    if not len(power) or float(np.max(power)) <= 0:
        return {"sustained_fraction": 0.0, "sustained_layer": False}
    span = max(1, round(SUSTAINED_LOOKBACK_SECONDS * RATE / HOP))
    ceiling = sliding_window_view(np.pad(power, (span, 0), mode="edge"), span + 1).max(axis=1)
    loud = power > SUSTAINED_FLOOR * float(np.max(power))
    fraction = float(np.mean(power[loud] >= ceiling[loud] * 10 ** (-SUSTAINED_DECIBELS/20))) if loud.any() else 0.0
    return {"sustained_fraction": round(fraction, 5), "sustained_layer": bool(fraction >= SUSTAINED_LAYER_FRACTION)}


def _passages(layers, duration):
    """Fixed audio-second windows summarising percussive support; classification is auditable."""
    drum = next((name for name in ("drums", "percussive", "low", "mix") if name in layers), None)
    onsets = [e["seconds"] for e in layers.get(drum, {}).get("events", [])
              if e["method"] == "spectral_flux" and e["strength"] >= PASSAGE_ONSET_STRENGTH]
    contour = layers.get("mix", {}).get("energy_contour", [])
    baseline = float(np.median([point["energy"] for point in contour])) if contour else 0.0
    thresholds = {"window_seconds": PASSAGE_SECONDS, "drum_layer": drum,
                  "drum_onset_strength": PASSAGE_ONSET_STRENGTH,
                  "density_reference_per_second": PASSAGE_DENSITY_REFERENCE,
                  "low_intensity_density": LOW_INTENSITY_DENSITY,
                  "low_intensity_energy_ratio": LOW_INTENSITY_ENERGY_RATIO,
                  "mix_energy_median": round(baseline, 6)}
    passages = []
    for step in range(max(1, math.ceil(duration / PASSAGE_SECONDS))):
        start, end = step * PASSAGE_SECONDS, (step + 1) * PASSAGE_SECONDS
        density = sum(1 for second in onsets if start <= second < end) / PASSAGE_SECONDS
        inside = [point["energy"] for point in contour if start <= point["seconds"] < end]
        ratio = float(np.median(inside)) / baseline if inside and baseline > 1e-12 else 0.0
        support = min(1, max(0, .5 * min(1, density / PASSAGE_DENSITY_REFERENCE) + .5 * min(1, ratio)))
        passages.append({"start_seconds": start, "end_seconds": end,
                         "drum_onset_density": round(density, 4), "energy_ratio": round(ratio, 5),
                         "support_score": round(support, 5),
                         "low_intensity": bool(density < LOW_INTENSITY_DENSITY
                                               and ratio < LOW_INTENSITY_ENERGY_RATIO)})
    return passages, thresholds


def _lane(samples, name, settings, band=None):
    frequencies, times, spectrum = _spectrum(samples)
    magnitude = np.abs(spectrum)
    if band:
        magnitude = magnitude[(frequencies >= band[0]) & (frequencies < band[1])]
    power = np.sqrt(np.mean(magnitude ** 2, axis=0))
    flux = np.mean(np.maximum(0, np.diff(magnitude, axis=1, prepend=magnitude[:, :1])), axis=0)
    energy = np.maximum(0, np.diff(power, prepend=power[:1]))
    events = []
    duration = len(samples) / RATE
    for method, values in (("spectral_flux", flux), ("energy_rise", energy)):
        normalized = _normalized(values)
        peaks, _ = find_peaks(normalized, prominence=settings["prominence"],
                             distance=max(1, round(settings["minimum_gap_seconds"] * RATE / HOP)))
        for index in peaks:
            if times[index] < duration:
                events.append({"id": f"{name}:{method}:{index}", "seconds": round(float(times[index]), 6),
                               "method": method, "strength": round(float(normalized[index]), 5)})
    # Compact energy contour exposes sustained phrases and gaps, not just attacks.
    step = max(1, round(.1 * RATE / HOP))
    contour = [{"seconds": round(float(times[i]), 6),
                "energy": round(float(np.max(_power)), 6)}
               for i in range(0, len(times), step) if times[i] < duration
               for _power in [power[i:i+step]]]
    # Frequency bands share the mix time signal, so pitch evidence is published once, on mix.
    track = _pitch_track(samples) if band is None else None
    sustains = [] if track is None else _segments(name, track)
    events += [] if track is None else _pitch_changes(name, track, duration)
    return {"kind": "frequency_band" if band else "audio_layer", "band_hz": band,
            "events": sorted(events, key=lambda e: (e["seconds"], e["method"])),
            "energy_contour": contour, "sustains": sustains,
            "attack_profile": _attack_profile(power),
            "rms": float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))}


def _hpss(samples):
    _, _, spectrum = _spectrum(samples)
    magnitude = np.abs(spectrum)
    harmonic = median_filter(magnitude, size=(1, 31)) ** 2
    percussive = median_filter(magnitude, size=(31, 1)) ** 2
    denominator = harmonic + percussive + 1e-20
    for name, numerator in (("harmonic", harmonic), ("percussive", percussive)):
        _, signal = istft(spectrum * (numerator / denominator), fs=RATE,
                          nperseg=WINDOW, noverlap=WINDOW-HOP, boundary=True)
        yield name, signal[:len(samples)]


def analyze_layers(audio, output, *, backend="bands", preset="balanced", manifest=None,
                   python=None, model="htdemucs", device="cpu"):
    """Write an immutable run, publishing report.json only after full success."""
    if backend not in BACKENDS or preset not in PRESETS:
        raise ValueError("Unknown musical analysis backend or preset")
    if (manifest is not None) != (backend == "import"):
        raise ValueError("Only the import backend requires --manifest")
    audio, output = Path(audio).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new output directory for each evidence run")
    samples, source = _signal(audio)
    imported = None
    if manifest:
        manifest = Path(manifest).resolve()
        imported = read_json(manifest)
        if not isinstance(imported, dict) or imported.get("source_sha256") != source["sha256"]:
            raise ValueError("Stem manifest source_sha256 must match the exact analyzed audio")
        if not isinstance(imported.get("stems"), dict) or not imported["stems"]:
            raise ValueError("Stem manifest needs a nonempty stems object")
        if not isinstance(imported.get("producer"), str) or not imported["producer"].strip():
            raise ValueError("Stem manifest must identify its producer/model")
    if backend == "demucs" and model not in {"htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi"}:
        raise ValueError("Unsupported Demucs model")
    output.mkdir(parents=True)
    report = {"schema_version": "1.1", "created_at": now(), "backend": backend,
              "preset": preset, "settings": PRESETS[preset], "source": source,
              "analysis_sample_rate": RATE, "hop_seconds": HOP/RATE,
              "window_seconds": WINDOW/RATE, "layers": {},
              "limitations": ["Estimated musical events, not notes or instrument transcriptions.",
                              "Strength is normalized within each layer and method; it is not confidence.",
                              "Source seconds are unsnapped. Check attacks, leakage, alignment and rests by listening.",
                              "Sustains and pitch_change come from a single monophonic f0 estimate; layered, choral or "
                              "polyphonic material yields unstable shapes and low confidence.",
                              "Frequency-band layers share the mix time signal, so sustains and pitch_change are "
                              "published on the mix layer only.",
                              "attack_profile.sustained_fraction is the share of frames above 10% of the layer peak "
                              f"still within {SUSTAINED_DECIBELS:g} dB of their preceding {SUSTAINED_LOOKBACK_SECONDS:g} s "
                              "maximum; on a sustained layer energy_rise peaks are envelope wobble, not attacks.",
                              f"Passages are fixed {PASSAGE_SECONDS:g}-second windows in audio seconds, not musical "
                              "phrases; passage_thresholds records every constant used.",
                              "No human timing review or playtest is implied."]}
    settings = PRESETS[preset]
    report["layers"]["mix"] = _lane(samples, "mix", settings)
    if backend == "bands":
        for name, band in (("low", (20, 250)), ("mid", (250, 2000)), ("high", (2000, RATE/2))):
            report["layers"][name] = _lane(samples, name, settings, band)
        report["limitations"].append("Frequency bands are overlapping instruments, not isolated bass/drums/vocals.")
    elif backend == "hpss":
        for name, signal in _hpss(samples):
            sf.write(output / f"{name}.wav", signal, RATE, subtype="FLOAT")
            report["layers"][name] = {**_lane(signal, name, settings), "audio_file": f"{name}.wav"}
        report["limitations"].append("Harmonic/percussive layers are mono estimates, not individual instruments.")
    else:
        if backend == "demucs":
            command = [str(python or sys.executable), "-m", "demucs.separate", "-n", model,
                       "-d", device, "--float32", "-o", str(output / "separated"), str(audio)]
            # shell=False; optional ML dependencies can live in another Python environment.
            with (output / "separation.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            if result.returncode:
                raise ValueError(f"Demucs failed; inspect {output / 'separation.log'}. "
                                 "Install Demucs in a compatible environment and pass --python.")
            folder = output / "separated" / model / audio.stem
            names = ["drums", "bass", "other", "vocals"] + (["guitar", "piano"] if model == "htdemucs_6s" else [])
            stems = {name: folder / f"{name}.wav" for name in names}
            report["producer"] = {"model": model, "command": command}
        else:
            stems = {}
            for name, relative in imported["stems"].items():
                if not isinstance(relative, str):
                    raise ValueError("Each stem path must be a string")
                stems[name] = manifest.parent / relative
            report["producer"] = {"name": imported["producer"], "manifest_sha256": _hash(manifest)}
        for name, path in stems.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name) or name == "mix":
                raise ValueError("Stem names must be lowercase identifiers other than mix")
            signal, identity = _signal(path)
            if abs(identity["duration_seconds"] - source["duration_seconds"]) > .05:
                raise ValueError(f"Stem {name} duration differs by more than 50 ms; provide untrimmed aligned stems")
            # Copy a decoded preview; never alter or trim the supplied stem.
            stereo, rate, _ = _decode(path)
            sf.write(output / f"{name}.wav", stereo, rate, subtype="FLOAT")
            report["layers"][name] = {**_lane(signal, name, settings), "source": identity,
                                      "audio_file": f"{name}.wav",
                                      "alignment": "duration checked; internal delay requires listening review"}
    report["passages"], report["passage_thresholds"] = _passages(report["layers"], len(samples) / RATE)
    write_json(output / "report.json", report)
    return report


def validate_focus(phrases, length):
    """Validate optional section-relative musical focus metadata."""
    def beat(value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Focus beats must be numbers or rational strings")
        return float(Fraction(str(value)))
    if not isinstance(phrases, list):
        raise ValueError("musical_focus must be an array")
    previous_end, ids = 0.0, set()
    for phrase in phrases:
        required = {"id", "start_beat", "end_beat", "lead", "weights", "intent"}
        if not isinstance(phrase, dict) or not required <= phrase.keys() or phrase.keys() - required - {"evidence"}:
            raise ValueError("Focus phrases require id, start_beat, end_beat, lead, weights, intent; evidence is optional")
        identifier = phrase["id"]
        if not isinstance(identifier, str) or not identifier or identifier in ids or "/" in identifier:
            raise ValueError("Focus IDs must be nonempty, unique within the section, and contain no slash")
        ids.add(identifier)
        start, end = beat(phrase["start_beat"]), beat(phrase["end_beat"])
        if not (math.isfinite(start) and math.isfinite(end) and previous_end <= start < end <= float(length)):
            raise ValueError("Focus phrases must be ordered, nonoverlapping, and inside their section")
        previous_end = end
        weights = phrase["weights"]
        if not isinstance(weights, dict) or not weights:
            raise ValueError("Focus weights must name at least one layer")
        for name, weight in weights.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name):
                raise ValueError("Focus layer names must be lowercase identifiers")
            if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not 0 <= weight <= 1:
                raise ValueError("Focus weights must be finite numbers from 0 to 1")
        if not math.isclose(sum(weights.values()), 1, abs_tol=1e-6):
            raise ValueError("Focus weights must sum to 1")
        lead = phrase["lead"]
        if not isinstance(lead, str) or lead not in weights or weights[lead] <= 0:
            raise ValueError("Focus lead must name a positively weighted layer; use mix for the ensemble")
        if not isinstance(phrase["intent"], str) or not phrase["intent"].strip():
            raise ValueError("Focus intent must explain the phrasing or handoff")
        if "evidence" in phrase and (not isinstance(phrase["evidence"], list) or
                                    any(not isinstance(e, str) or not e.strip() for e in phrase["evidence"])):
            raise ValueError("Focus evidence must be an array of nonempty references")


def seconds_to_beat(seconds, arrangement):
    remaining = seconds - arrangement["song"]["audio_offset_seconds"]
    tempo, previous = arrangement["song"]["bpm"], 0.0
    for event in sorted(arrangement.get("tempo_events", []), key=lambda e: float(Fraction(str(e["beat"])))):
        at = float(Fraction(str(event["beat"])))
        duration = (at - previous) * 60 / tempo
        if remaining < duration:
            break
        remaining -= duration
        previous, tempo = at, event["bpm"]
    return previous + remaining * tempo / 60


def evidence_slice(report, arrangement, start, end, layer=None):
    from .arrangement import expanded_notes
    from .revisions import arrangement_revision
    if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
        raise ValueError("Choose a finite increasing beat range")
    if layer is not None and layer not in report["layers"]:
        raise ValueError(f"Unknown layer {layer}; this run has {', '.join(sorted(report['layers']))}")
    def span(item):
        left, right = (seconds_to_beat(item[key], arrangement) for key in ("start_seconds", "end_seconds"))
        return {**item, "start_beat": round(left, 6), "end_beat": round(right, 6)} if left < end and right > start else None
    layers = {}
    for name, evidence in report["layers"].items():
        if layer is not None and name != layer:
            continue
        events = []
        for event in evidence["events"]:
            beat = seconds_to_beat(event["seconds"], arrangement)
            if start <= beat < end:
                events.append({**event, "beat": round(beat, 6)})
        contour = []
        for point in evidence.get("energy_contour", []):
            beat = seconds_to_beat(point["seconds"], arrangement)
            if start <= beat < end:
                contour.append({**point, "beat": round(beat, 6)})
        layers[name] = {"events": events, "kind": evidence["kind"], "energy_contour": contour,
                        "sustains": [s for s in map(span, evidence.get("sustains", [])) if s],
                        "attack_profile": evidence.get("attack_profile", {})}
    focus, missing = [], set()
    for section in arrangement["sections"]:
        base = float(Fraction(str(section["start_beat"])))
        for phrase in section.get("musical_focus", []):
            left, right = (base + float(Fraction(str(phrase[k]))) for k in ("start_beat", "end_beat"))
            if left < end and right > start:
                focus.append({**phrase, "section_id": section["id"], "absolute_start_beat": left, "absolute_end_beat": right})
                missing.update(name for name, weight in phrase["weights"].items() if weight > 0 and name not in layers)
    notes = [{**note, "beat": float(note["beat"])} for note in expanded_notes(arrangement)
             if start <= note["beat"] < end]
    return {"start_beat": start, "end_beat": end, "source": report["source"],
            "revision": arrangement_revision(arrangement), "mapped_notes": notes,
            "grid": {"bpm": arrangement["song"]["bpm"],
                     "audio_offset_seconds": arrangement["song"]["audio_offset_seconds"],
                     "tempo_events": arrangement.get("tempo_events", [])},
            "layers": layers, "musical_focus": focus, "missing_focus_layers": sorted(missing),
            "passages": [p for p in map(span, report.get("passages", [])) if p],
            "passage_thresholds": report.get("passage_thresholds", {}),
            "limitations": report["limitations"],
            "authoring": "Agent selects rhythms and rests, then authors movement. Weights express intent, not note density."}


def project_runs(directory):
    result = []
    for path in sorted((Path(directory) / "musical").glob("*/report.json")):
        report = read_json(path)
        result.append({"id": path.parent.name, "backend": report["backend"], "preset": report["preset"],
                       "created_at": report["created_at"], "layers": list(report["layers"])})
    return result


def analyze_project(store, project_id, **options):
    directory = store.directory(project_id)
    run_id = uuid.uuid4().hex
    report = analyze_layers(directory / "song.ogg", directory / "musical" / run_id, **options)
    return {"id": run_id, "path": str(directory / "musical" / run_id / "report.json"),
            "backend": report["backend"], "layers": list(report["layers"])}
