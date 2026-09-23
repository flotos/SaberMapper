"""Per-section mood descriptors: valence/arousal estimates and timbre tags.

The default ``heuristic`` backend is a documented formula over measured features (tempo, loudness,
onset density, spectral centroid, harmonic/percussive balance, major/minor fit, stem balance and
stem timbre). It is not a trained model and not a human judgement; every section records the
features it used so the agent can weigh them itself. The ``external`` backend is the hook for a
local model: it runs ``PYTHON -m MODULE`` (for example in `.venv-separation` on the GPU), sends the
sections and audio paths as JSON on stdin and merges the model's valence/arousal/tags beside the
heuristic features.
"""
from __future__ import annotations

import json
import subprocess

import numpy as np

from .listen import FRAME, decibels, key_estimate

HEURISTIC_VERSION = "1.0"
AROUSAL_WEIGHTS = {"tempo": .2, "loudness": .3, "onset_density": .2, "brightness": .15, "percussive": .15}
VALENCE_WEIGHTS = {"mode": .2, "tempo": .1, "brightness": .1, "harmonic": .05, "noisiness": -.1}
STEM_ACTIVE_DB = -20.0
TAG_THRESHOLD = .2


class MoodBackendError(ValueError):
    def __init__(self, code, message, fix=None):
        super().__init__(message)
        self.code, self.fix = code, fix


def _clip(value, low=0.0, high=1.0):
    return float(min(high, max(low, value)))


def _ramp(value, zero, one):
    """0 at ``zero``, 1 at ``one``, linear between (either direction)."""
    return _clip((value - zero) / (one - zero)) if one != zero else 0.0


def _weighted(values, weights):
    values, weights = np.asarray(values, dtype=float), np.asarray(weights, dtype=float)
    total = float(weights.sum())
    return float((values * weights).sum() / total) if total > 1e-20 else float(np.mean(values)) if len(values) else 0.0


def section_features(frames, section, report, arrangement=None):
    """Measured features of one section; the inputs to every backend."""
    from .moments import section_tempo
    mix, stems = frames["mix"], frames["stems"]
    left, right = int(section["start"] / FRAME), max(int(section["end"] / FRAME), int(section["start"] / FRAME) + 1)
    rms = np.asarray(mix["rms"][left:right], dtype=float)
    power = rms ** 2
    seconds = max(section["end"] - section["start"], 1e-6)
    onsets = [e for e in ((report.get("layers") or {}).get("mix") or {}).get("events", [])
              if e.get("method") == "spectral_flux" and e.get("strength", 0) >= .3
              and section["start"] <= e["seconds"] < section["end"]]
    features = {
        "loudness_dbfs": round(float(10 * np.log10(max(float(power.mean()), 1e-14))), 2),
        "centroid_hz": round(_weighted(mix["centroid_hz"][left:right], power), 1),
        "flatness": round(_weighted(mix["flatness"][left:right], power), 4),
        "harmonic_ratio": round(_weighted(mix["harmonic_ratio"][left:right], power), 3),
        "low_share": round(_weighted(mix["low_share"][left:right], power), 3),
        "high_share": round(_weighted(mix["high_share"][left:right], power), 4),
        "air_share": round(_weighted(mix["air_share"][left:right], power), 4),
        "onset_density": round(len(onsets) / seconds, 3),
    }
    bpm = None
    if arrangement:
        from .listen import seconds_to_beat
        from fractions import Fraction
        bpm = arrangement["song"]["bpm"]
        middle = seconds_to_beat((section["start"] + section["end"]) / 2, arrangement)
        for event in sorted(arrangement.get("tempo_events", []) or [], key=lambda e: float(Fraction(str(e["beat"])))):
            if float(Fraction(str(event["beat"]))) <= middle:
                bpm = event["bpm"]
    audio_tempo = section_tempo(frames, section, arrangement)
    features["tempo_bpm"] = bpm if bpm else (audio_tempo or {}).get("bpm")
    features["tempo_source"] = "arrangement" if bpm else "audio" if audio_tempo else None
    features["audio_tempo"] = audio_tempo
    key = section.get("key")
    features["mode"] = key["mode"] if key else None
    features["major_minus_minor"] = key["major_minus_minor"] if key else None
    if stems:
        mix_db = decibels(rms)
        powers = {name: np.asarray(stem["rms"][left:right], dtype=float) ** 2 for name, stem in stems.items()}
        total = sum(float(p.sum()) for p in powers.values()) or 1e-20
        features["stem_share"] = {name: round(float(p.sum()) / total, 3) for name, p in powers.items()}
        active = {name: decibels(stems[name]["rms"][left:right]) > mix_db + STEM_ACTIVE_DB for name in stems}
        features["stem_active"] = {name: round(float(mask.mean()), 3) for name, mask in active.items()}
        timbre = {}
        for name in ("guitar", "other", "piano", "vocals"):
            if name not in stems or not active[name].any():
                continue
            stem = stems[name]
            mask, weights = active[name], powers[name]
            level = decibels(stem["rms"][left:right])
            steps = np.abs(np.diff(level))[mask[1:]] if mask[1:].any() else np.array([0.0])
            timbre[name] = {"flatness": round(_weighted(np.asarray(stem["flatness"][left:right])[mask], weights[mask]), 4),
                            "centroid_hz": round(_weighted(np.asarray(stem["centroid_hz"][left:right])[mask], weights[mask]), 1),
                            "level_jitter_db": round(float(np.median(steps)), 3)}
        features["stem_timbre"] = timbre
    return features


def heuristic_mood(features):
    """Valence/arousal (0-1) and timbre tags with confidences from one section's features."""
    tempo = _ramp(features["tempo_bpm"] or 110, 60, 180)
    loudness = _ramp(features["loudness_dbfs"], -30, -8)
    density = _ramp(features["onset_density"], 0, 6)
    brightness = _ramp(np.log2(max(features["centroid_hz"], 1) / 700), 0, np.log2(4000 / 700))
    percussive = _ramp(1 - features["harmonic_ratio"], .2, .7)
    noisiness = _ramp(features["flatness"], .05, .3)
    # Relative major/minor share one pitch set, so a section's mode flips easily: blend it with the song's.
    mode = _clip(.5 * (features["major_minus_minor"] or 0) * 4 + .5 * (features.get("song_major_minus_minor") or 0) * 4,
                 -1, 1)
    parts_a = {"tempo": tempo, "loudness": loudness, "onset_density": density, "brightness": brightness,
               "percussive": percussive}
    arousal = sum(AROUSAL_WEIGHTS[k] * v for k, v in parts_a.items())
    parts_v = {"mode": mode, "tempo": tempo - .5, "brightness": brightness - .5,
               "harmonic": features["harmonic_ratio"] - .5, "noisiness": noisiness - .5}
    valence = _clip(.5 + sum(VALENCE_WEIGHTS[k] * v for k, v in parts_v.items()))
    tags = []

    def tag(name, confidence, because):
        if confidence >= TAG_THRESHOLD:
            tags.append({"tag": name, "confidence": round(_clip(confidence), 2), "because": because})
    share, active, timbre = features.get("stem_share"), features.get("stem_active"), features.get("stem_timbre", {})
    if share:
        tag("vocal_led", _ramp(share.get("vocals", 0), .12, .35) * _ramp(active.get("vocals", 0), .2, .6),
            "vocals stem share and active fraction")
        tag("drum_heavy", _ramp(share.get("drums", 0), .15, .4), "drums stem share")
        tag("bass_heavy", _ramp(share.get("bass", 0), .2, .45), "bass stem share")
        guitar = timbre.get("guitar")
        if guitar:
            tag("distorted_guitar", _ramp(share.get("guitar", 0), .08, .3) * _ramp(guitar["flatness"], .02, .12) *
                _ramp(guitar["centroid_hz"], 700, 1600), "guitar stem share, spectral flatness and centroid")
            tag("clean_guitar", _ramp(share.get("guitar", 0), .08, .3) * (1 - _ramp(guitar["flatness"], .02, .12)),
                "guitar stem share with a tonal (low-flatness) spectrum")
        tag("piano", _ramp(share.get("piano", 0), .06, .25) * _ramp(active.get("piano", 0), .1, .5),
            "piano stem share and active fraction (separator estimate)")
        other = timbre.get("other")
        if other:
            tag("sustained_pad", _ramp(share.get("other", 0), .08, .3) * (1 - _ramp(other["level_jitter_db"], .6, 2.0)),
                "steady 'other' stem (synth pad or strings; not distinguished)")
        count = sum(1 for value in active.values() if value >= .5)
        tag("dense", _ramp(count, 3, 5) * _ramp(features["onset_density"], 2, 5), "active stems and onset density")
        tag("sparse", _ramp(count, 3, 1) * _ramp(features["onset_density"], 3, .5), "few active stems, few onsets")
    else:
        tag("drum_heavy", percussive, "percussive share of the mix (no stems)")
        tag("sparse", _ramp(features["onset_density"], 3, .5) * (1 - loudness), "few onsets at low level (no stems)")
    tag("bright", _ramp(features["centroid_hz"], 1800, 3300), "mix spectral centroid")
    tag("dark", _ramp(features["centroid_hz"], 1500, 800), "mix spectral centroid")
    tag("airy", _ramp(features["air_share"], .005, .04) * _ramp(features["harmonic_ratio"], .5, .75) *
        (1 - _ramp(features["loudness_dbfs"], -16, -9)), "energy above 8 kHz in a harmonic, quiet section")
    tag("noisy", noisiness * loudness, "high spectral flatness at high level (distortion, noise, cymbals)")
    tags.sort(key=lambda t: -t["confidence"])
    return {"valence": round(valence, 3), "arousal": round(_clip(arousal), 3), "tags": tags,
            "components": {"arousal": {k: round(v, 3) for k, v in parts_a.items()},
                           "valence": {k: round(v, 3) for k, v in parts_v.items()}}}


def external_mood(sections, features, options):
    """Run a local model: ``PYTHON -m MODULE`` gets {sections, audio, stems} on stdin, returns
    {"model": {...}, "sections": {id: {"valence", "arousal", "tags": [{"tag", "confidence"}]}}}."""
    python, module = (options or {}).get("python"), (options or {}).get("module")
    if not python or not module:
        raise MoodBackendError("mood_model_unconfigured", "The external mood backend needs --mood-python and "
                               "--mood-module", "Pass the interpreter and module of a local mood model, or use "
                               "--mood-backend heuristic")
    probe = subprocess.run([str(python), "-c", f"import importlib.util,sys;sys.exit(importlib.util.find_spec({module!r}) is None)"],
                           capture_output=True, text=True, check=False)
    if probe.returncode:
        raise MoodBackendError("mood_model_missing", f"Module {module} is not importable in {python}",
                               f"Install the model package into that interpreter ({python} -m pip install ...) "
                               "after the user approves it, or use --mood-backend heuristic")
    payload = {"sections": [{"id": s["id"], "start": s["start"], "end": s["end"]} for s in sections],
               "features": features, "audio": (options or {}).get("audio"), "stems": (options or {}).get("stems", {})}
    result = subprocess.run([str(python), "-m", module], input=json.dumps(payload), capture_output=True,
                            text=True, check=False)
    if result.returncode:
        raise MoodBackendError("mood_model_failed", f"{module} exited with {result.returncode}: {result.stderr[-400:]}",
                               "Run the module by hand with the same interpreter to see the full error")
    try:
        output = json.loads(result.stdout)
        return output.get("model", {"module": module}), output["sections"]
    except (ValueError, KeyError, TypeError) as exc:
        raise MoodBackendError("mood_model_output", f"{module} did not print the expected JSON: {exc}",
                               "The module must print {\"sections\": {id: {valence, arousal, tags}}}") from exc


def section_moods(frames, sections, report, arrangement=None, *, backend="heuristic", options=None):
    """Mood per section plus a duration-weighted song summary."""
    if backend not in ("heuristic", "external"):
        raise MoodBackendError("mood_backend_unknown", f"Unknown mood backend {backend}", "Use heuristic or external")
    from .listen import harmonic_chroma
    song_key = key_estimate(harmonic_chroma(frames).mean(axis=1))
    features = {s["id"]: {**section_features(frames, s, report, arrangement),
                          "song_major_minus_minor": song_key["major_minus_minor"] if song_key else None}
                for s in sections}
    result = {section_id: {**heuristic_mood(values), "features": values} for section_id, values in features.items()}
    model = None
    if backend == "external":
        model, predictions = external_mood(sections, features, options)
        for section_id, prediction in (predictions or {}).items():
            if section_id in result and isinstance(prediction, dict):
                result[section_id]["heuristic"] = {k: result[section_id][k] for k in ("valence", "arousal", "tags")}
                for key in ("valence", "arousal", "tags"):
                    if key in prediction:
                        result[section_id][key] = prediction[key]
    weights = {s["id"]: (s["end"] - s["start"]) * (s.get("level_db", 0) > -45) for s in sections}
    total = sum(weights.values()) or 1.0
    song_tags = {}
    for section_id, mood in result.items():
        for item in mood["tags"]:
            song_tags[item["tag"]] = song_tags.get(item["tag"], 0) + item["confidence"] * weights[section_id] / total
    return {"backend": backend, "version": HEURISTIC_VERSION, "model": model, "song_key": song_key,
            "method": {"arousal": "weighted sum of 0-1 ramps: tempo 60-180 BPM, loudness -30..-8 dBFS, strong mix onsets "
                                  "0-6/s, centroid 700-4000 Hz (log), percussive share 0.2-0.7",
                       "arousal_weights": AROUSAL_WEIGHTS,
                       "valence": "0.5 + weighted terms: major-minus-minor key-profile fit (x4, averaged half-and-half with the "
                                  "whole song's, clipped +-1), tempo, "
                                  "brightness, harmonic share, minus spectral noisiness; clipped 0-1",
                       "valence_weights": VALENCE_WEIGHTS,
                       "tags": f"ramped rules over stem share, stem activity (> mix {STEM_ACTIVE_DB:g} dB), stem timbre and "
                               f"mix spectrum; tags under {TAG_THRESHOLD} confidence are omitted",
                       "basis": "Direction of each term follows the music-emotion literature (mode and tempo for valence; "
                                "tempo, loudness and brightness for arousal; e.g. Gabrielsson & Lindstrom 2010, Eerola & "
                                "Vuoskoski 2013); the weights are hand-set, not fitted."},
            "sections": result,
            "song": {"valence": round(sum(result[k]["valence"] * w for k, w in weights.items()) / total, 3),
                     "arousal": round(sum(result[k]["arousal"] * w for k, w in weights.items()) / total, 3),
                     "tags": [{"tag": t, "weight": round(v, 2)} for t, v in sorted(song_tags.items(), key=lambda x: -x[1])
                              if v >= .15]},
            "honesty": "Heuristic descriptors from measured features, not a trained model or a human judgement."}


__all__ = ["heuristic_mood", "section_features", "section_moods", "MoodBackendError", "key_estimate"]
