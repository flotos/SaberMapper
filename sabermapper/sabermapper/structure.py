"""Compact beat-aligned energy, onset, and recurrence candidates."""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

from .timing import BeatGrid


def analyze_structure(samples: np.ndarray, sample_rate: int, envelope: np.ndarray,
                      hop_seconds: float, grid: BeatGrid | None) -> dict:
    if grid is None:
        return {"status": "timing_required", "sections": [], "accent_candidates": [], "rests": []}
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    duration = len(mono) / sample_rate
    max_beat = max(0, int(grid.time_to_beat(duration)))
    beat_energy = []
    beat_onsets = []
    for beat in range(max_beat):
        start = max(0, round(grid.beat_to_time(beat) * sample_rate))
        end = min(len(mono), round(grid.beat_to_time(beat + 1) * sample_rate))
        segment = mono[start:end]
        beat_energy.append(float(np.sqrt(np.mean(np.square(segment.astype(np.float64))))) if len(segment) else 0.0)
        left = max(0, round(grid.beat_to_time(beat) / hop_seconds))
        right = min(len(envelope), round(grid.beat_to_time(beat + 1) / hop_seconds))
        beat_onsets.append(float(np.sum(envelope[left:right])))
    peaks, _ = find_peaks(envelope, prominence=max(float(np.max(envelope)) * 0.1, 1e-6),
                          distance=max(1, int(0.1 / hop_seconds))) if len(envelope) else ([], {})
    strongest = sorted(peaks, key=lambda p: float(envelope[p]), reverse=True)[:64]
    accents = sorted([{"time_seconds": round(float(p * hop_seconds), 3),
                       "beat": round(grid.time_to_beat(p * hop_seconds), 3),
                       "strength": round(float(envelope[p]), 5)} for p in strongest], key=lambda x: x["time_seconds"])
    energies = np.asarray(beat_energy)
    median = float(np.median(energies)) if len(energies) else 0.0
    rests = [{"start_beat": i, "end_beat": i + 1} for i, value in enumerate(energies)
             if value < max(median * 0.15, 1e-5)]
    sections = []
    # Anonymous 8-bar windows are a review scaffold. Correlation is a cue only.
    window = 32
    feature = np.column_stack((np.log1p(np.asarray(beat_energy) * 100),
                               np.log1p(np.asarray(beat_onsets) * 100))) if beat_energy else np.zeros((0, 2))
    for start in range(0, max_beat, window):
        end = min(max_beat, start + window)
        section = {"id": f"section-{len(sections) + 1}", "start_beat": start,
                   "end_beat": end, "label": "unreviewed", "mean_energy": round(float(np.mean(energies[start:end])), 5),
                   "repeat_candidates": []}
        for prior in sections:
            prior_start = prior["start_beat"]
            if end - start != prior["end_beat"] - prior_start or end - start < 4:
                continue
            first = feature[start:end].flatten()
            second = feature[prior_start:prior["end_beat"]].flatten()
            if np.std(first) > 1e-6 and np.std(second) > 1e-6:
                similarity = float(np.corrcoef(first, second)[0, 1])
                if similarity > 0.7:
                    section["repeat_candidates"].append({"section_id": prior["id"], "similarity": round(similarity, 3)})
        sections.append(section)
    return {"status": "candidates", "sections": sections, "accent_candidates": accents,
            "rests": rests, "beat_energy": [round(v, 5) for v in beat_energy],
            "note": "Section windows and similarity are unlabeled candidates; review musical boundaries and meter."}
