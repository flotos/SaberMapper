"""Deterministic constant-tempo timing hypotheses and editable beat grid."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import find_peaks


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    offset_seconds: float = 0.0
    downbeat_anchor: int | None = None
    meter: int = 4

    def __post_init__(self):
        if not math.isfinite(self.bpm) or self.bpm <= 0:
            raise ValueError("bpm must be positive and finite")
        if not math.isfinite(self.offset_seconds):
            raise ValueError("offset_seconds must be finite")
        if self.meter < 1:
            raise ValueError("meter must be positive")

    def beat_to_time(self, beat: float) -> float:
        return self.offset_seconds + float(beat) * 60.0 / self.bpm

    def time_to_beat(self, seconds: float) -> float:
        return (float(seconds) - self.offset_seconds) * self.bpm / 60.0

    def as_dict(self) -> dict:
        return {"bpm": self.bpm, "offset_seconds": self.offset_seconds,
                "downbeat_anchor": self.downbeat_anchor, "meter": self.meter,
                "tempo_mode": "constant", "manual_downbeat_review_required": self.downbeat_anchor is None}


def onset_envelope(samples: np.ndarray, sample_rate: int, hop_seconds: float = 0.02) -> tuple[np.ndarray, float]:
    """Positive frame-energy changes; useful as rhythmic candidates, not note labels."""
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    hop = max(1, int(sample_rate * hop_seconds))
    count = len(mono) // hop
    if count < 2:
        return np.zeros(0), hop / sample_rate
    frames = mono[:count * hop].reshape(count, hop)
    energy = np.sqrt(np.mean(np.square(frames.astype(np.float64)), axis=1))
    novelty = np.maximum(0.0, np.diff(energy, prepend=energy[0]))
    return novelty, hop / sample_rate


def estimate_timing(envelope: np.ndarray, hop_seconds: float, bpm: float | None = None,
                    offset_seconds: float | None = None) -> dict:
    """Find a constant-tempo onset grid with half/double alternatives.

    Scores are relative agreement measures, not calibrated probabilities.
    """
    if envelope.size == 0 or float(np.max(envelope)) < 1e-7:
        return {"status": "silent", "bpm": bpm, "offset_seconds": offset_seconds,
                "confidence": 0.0, "alternatives": [], "manual_review_required": True}
    prominence = max(float(np.max(envelope)) * 0.08, float(np.median(envelope)) * 2)
    peaks, _ = find_peaks(envelope, prominence=prominence, distance=max(1, int(0.09 / hop_seconds)))
    if len(peaks) < 3:
        return {"status": "insufficient_onsets", "bpm": bpm, "offset_seconds": offset_seconds,
                "confidence": 0.0, "alternatives": [], "manual_review_required": True}
    times = peaks * hop_seconds
    strengths = envelope[peaks]
    if bpm is None:
        gaps = np.diff(times)
        gaps = gaps[(gaps >= 0.20) & (gaps <= 1.5)]
        if len(gaps) == 0:
            return {"status": "tempo_uncertain", "bpm": None, "offset_seconds": offset_seconds,
                    "confidence": 0.0, "alternatives": [], "manual_review_required": True}
        candidates = np.arange(60.0, 201.0, 0.5)
    else:
        if not math.isfinite(bpm) or bpm <= 0:
            raise ValueError("bpm must be positive and finite")
        candidates = np.array([float(bpm)])
    weighted = strengths / max(float(np.max(strengths)), 1e-12)
    def score(candidate: float):
        period = 60.0 / candidate
        if offset_seconds is None:
            phases = np.mod(times, period)
            histogram, edges = np.histogram(phases, bins=48, range=(0, period), weights=weighted)
            phase = float((edges[np.argmax(histogram)] + edges[np.argmax(histogram) + 1]) / 2)
        else:
            phase = float(offset_seconds)
        distance = np.abs((times - phase) / period - np.round((times - phase) / period))
        proximity = np.exp(-0.5 * (distance / 0.085) ** 2)
        return float(np.average(proximity, weights=weighted)), phase
    ranked = []
    for candidate in candidates:
        value, phase = score(float(candidate))
        ranked.append((value, float(candidate), phase))
    ranked.sort(reverse=True)
    best_score, best_bpm, best_phase = ranked[0]
    alternatives = []
    for candidate in (best_bpm / 2, best_bpm * 2):
        if 35 <= candidate <= 400:
            value, phase = score(candidate)
            alternatives.append({"bpm": candidate, "offset_seconds": phase, "agreement": round(value, 3)})
    return {"status": "estimated" if bpm is None else "reviewed_bpm", "bpm": best_bpm,
            "offset_seconds": best_phase, "confidence": round(best_score, 3),
            "alternatives": alternatives, "manual_review_required": True,
            "note": "Phase and meter/downbeat must be checked at start, middle, and end."}
