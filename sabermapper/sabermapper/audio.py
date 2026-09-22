"""Local audio decode, identity, analysis, and Vorbis preparation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from .timing import BeatGrid, estimate_timing, onset_envelope
from .structure import analyze_structure


SUPPORTED_EXTENSIONS = {".wav", ".ogg", ".mp3", ".flac"}
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_DURATION_SECONDS = 12 * 60
MAX_DECODE_BYTES = 512 * 1024 * 1024


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_vorbis(path: Path, samples: np.ndarray, rate: int) -> None:
    # Large single writes can overflow libsndfile's Windows C stack.
    with path.open("xb") as sink:
        with sf.SoundFile(sink, "w", samplerate=rate, channels=samples.shape[1],
                          format="OGG", subtype="VORBIS") as stream:
            for start in range(0, len(samples), 65536):
                stream.write(samples[start:start + 65536])


def _decode(path: str | Path) -> tuple[np.ndarray, int, str]:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.is_file():
        raise ValueError(f"unsupported or missing audio file: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("audio source exceeds 512 MiB local analysis limit")
    try:
        info = sf.info(path)
        if info.duration > MAX_DURATION_SECONDS or info.frames * info.channels * 4 > MAX_DECODE_BYTES:
            raise ValueError("decoded audio exceeds 12-minute or 512 MiB analysis limit")
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        decoder = "libsndfile"
    except (RuntimeError, sf.LibsndfileError):
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "decode.f32"
            command = [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-t", str(MAX_DURATION_SECONDS + 1),
                       "-f", "f32le", "-ac", "2", "-ar", "48000", "-fs", str(MAX_DECODE_BYTES + 1), str(raw)]
            try:
                result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        check=False, timeout=90)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("audio decode exceeded 90-second time limit") from exc
            if result.returncode or not raw.exists() or raw.stat().st_size == 0:
                raise ValueError(f"audio decode failed: {result.stderr.decode('utf-8', errors='replace')[:300]}")
            if raw.stat().st_size > MAX_DECODE_BYTES:
                raise ValueError("decoded audio exceeds 512 MiB analysis limit")
            data = np.fromfile(raw, dtype="<f4").reshape(-1, 2)
        rate = 48000
        decoder = "ffmpeg f32le stereo 48000 Hz"
    if len(data) == 0 or rate <= 0 or not np.isfinite(data).all():
        raise ValueError("audio is empty or contains invalid samples")
    if len(data) / rate > MAX_DURATION_SECONDS:
        raise ValueError("decoded audio exceeds 12-minute analysis limit")
    return data, int(rate), decoder


def inspect_audio(path: str | Path) -> dict:
    source = Path(path)
    samples, rate, decoder = _decode(source)
    peak = float(np.max(np.abs(samples)))
    return {"source_path": str(source.resolve()), "source_sha256": _hash(source),
            "source_bytes": source.stat().st_size, "extension": source.suffix.lower(),
            "sample_rate": rate, "channels": samples.shape[1], "frames": len(samples),
            "duration_seconds": len(samples) / rate, "peak": peak,
            "silent": peak < 1e-5, "decoder": decoder,
            "tags": {}, "identity_status": "unknown; enter title and artist manually"}


def prepare_audio(source: str | Path, destination: str | Path) -> dict:
    """Encode locally to Ogg Vorbis and verify decoded duration and start alignment."""
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError("audio export destination must be new and different from source")
    samples, rate, decoder = _decode(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_vorbis(destination, samples, rate)
        decoded, export_rate, _ = _decode(destination)
        drift = abs(len(decoded) / export_rate - len(samples) / rate)
        if drift > 0.025:
            raise ValueError(f"Vorbis duration drift {drift:.4f}s exceeds 25 ms")
        # Vorbis is lossy; compare low-frequency onset envelopes, not sample equality.
        source_env, source_hop = onset_envelope(samples, rate)
        export_env, export_hop = onset_envelope(decoded, export_rate)
        count = min(len(source_env), len(export_env))
        if count and np.max(source_env) > 1e-6 and np.max(export_env) > 1e-6:
            candidates = []
            for shift in range(-5, 6):
                a = source_env[max(0, -shift):min(count, count - shift)]
                b = export_env[max(0, shift):min(count, count + shift)]
                if len(a) > 10:
                    candidates.append((float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)), shift))
            lag = max(candidates)[1] * max(source_hop, export_hop) if candidates else 0.0
        else:
            lag = 0.0
        if abs(lag) > 0.04:
            raise ValueError(f"Vorbis onset alignment shifted by {lag:.3f}s")
        return {"source_sha256": _hash(source), "export_sha256": _hash(destination),
                "source_path": str(source.resolve()), "export_path": str(destination.resolve()),
                "source_decoder": decoder, "encoder": "libsndfile OGG/VORBIS",
                "source_sample_rate": rate, "export_sample_rate": export_rate,
                "source_frames": len(samples), "export_frames": len(decoded),
                "source_duration_seconds": len(samples) / rate,
                "export_duration_seconds": len(decoded) / export_rate,
                "duration_drift_seconds": drift, "estimated_onset_shift_seconds": lag,
                "trim_seconds": 0, "padding_seconds": 0,
                "note": "Lossy encoding; inspect beginning, middle, and end against beat grid."}
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def generate_demo_audio(destination: str | Path, *, seconds: float = 48.0, bpm: float = 120.0) -> dict:
    """Create an original rhythmic fixture without copyrighted source material."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    if not 8 <= seconds <= 120 or not 40 <= bpm <= 240:
        raise ValueError("demo seconds or bpm outside supported range")
    rate = 44100
    sample_count = round(seconds * rate)
    audio = np.zeros((sample_count, 2), dtype=np.float32)
    beat_length = 60 / bpm
    rng = np.random.default_rng(20260922)
    progression = ((130.81, 164.81, 196.00), (110.00, 130.81, 164.81),
                   (87.31, 130.81, 174.61), (98.00, 146.83, 196.00))
    def add(start_seconds: float, signal: np.ndarray, pan: float = 0.0):
        start = round(start_seconds * rate)
        if start >= sample_count:
            return
        signal = signal[:sample_count - start]
        audio[start:start + len(signal), 0] += signal * (1 - max(0, pan))
        audio[start:start + len(signal), 1] += signal * (1 + min(0, pan))

    total_beats = int(seconds / beat_length)
    for beat in range(total_beats):
        sec = beat * beat_length
        section = min(2, int(sec / (seconds / 3)))
        chord = progression[(beat // 4) % len(progression)]
        if beat % 4 == 0:
            length = min(int(beat_length * 3.8 * rate), sample_count - round(sec * rate))
            t = np.arange(length) / rate
            attack = np.minimum(1, t / 0.025)
            decay = np.exp(-t * (1.1 if section == 0 else 0.75))
            pad = sum(np.sin(2 * np.pi * frequency * t) for frequency in chord) / 3
            pad += 0.12 * sum(np.sin(2 * np.pi * (frequency * 2.003) * t) for frequency in chord) / 3
            add(sec, (0.14 + 0.025 * section) * attack * decay * pad, pan=-0.1)
        if beat % 2 == 0 or section >= 1:
            length = int(0.27 * rate)
            t = np.arange(length) / rate
            bass = 0.19 * np.exp(-11 * t) * np.sin(2 * np.pi * (chord[0] / 2) * t)
            add(sec, bass)
        if beat % 4 in (0, 2) or section == 2:
            length = int(0.18 * rate)
            t = np.arange(length) / rate
            kick = 0.29 * np.exp(-24 * t) * np.sin(2 * np.pi * (55 * t + 45 * (1 - np.exp(-35 * t)) / 35))
            add(sec, kick)
        if beat % 4 in (1, 3) and section >= 1:
            length = int(0.11 * rate)
            t = np.arange(length) / rate
            noise = rng.standard_normal(length)
            noise = noise - np.convolve(noise, np.ones(25) / 25, mode="same")
            add(sec, 0.09 * np.exp(-31 * t) * noise)
        if section >= 1:
            for half in (0, 0.5):
                length = int(0.06 * rate)
                t = np.arange(length) / rate
                noise = rng.standard_normal(length)
                high = noise - np.convolve(noise, np.ones(17) / 17, mode="same")
                add(sec + half * beat_length, 0.028 * np.exp(-65 * t) * high, pan=0.15)
        if section == 2 and beat % 2 == 1:
            length = int(0.24 * rate)
            t = np.arange(length) / rate
            melody = 0.095 * np.exp(-9 * t) * np.sin(2 * np.pi * chord[1] * 2 * t)
            add(sec + 0.25 * beat_length, melody, pan=0.2)
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio *= 0.82 / peak
    fade = min(sample_count, int(0.35 * rate))
    audio[-fade:] *= np.linspace(1, 0, fade)[:, None]
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_vorbis(destination, audio, rate)
    metadata = inspect_audio(destination)
    metadata["fixture"] = {"original_synthesis": True, "bpm": bpm, "offset_seconds": 0,
                           "sections": ["warm intro", "drums enter", "full groove and melody"],
                           "duration_requested_seconds": seconds}
    return metadata


def analyze_audio(path: str | Path, *, bpm: float | None = None,
                  offset_seconds: float | None = None) -> dict:
    samples, rate, _ = _decode(path)
    metadata = inspect_audio(path)
    envelope, hop = onset_envelope(samples, rate)
    timing = estimate_timing(envelope, hop, bpm=bpm, offset_seconds=offset_seconds)
    grid = BeatGrid(timing["bpm"], timing["offset_seconds"] or 0.0) if timing["bpm"] else None
    structure = analyze_structure(samples, rate, envelope, hop, grid)
    mono = samples.mean(axis=1)
    count = min(512, len(mono))
    edges = np.linspace(0, len(mono), count + 1, dtype=int)
    waveform = [{"min": round(float(np.min(mono[edges[i]:edges[i + 1]])), 5),
                 "max": round(float(np.max(mono[edges[i]:edges[i + 1]])), 5)}
                for i in range(count)]
    return {"schema_version": "0.1", "audio": metadata, "timing": timing,
            "structure": structure, "waveform": {"duration_seconds": metadata["duration_seconds"],
                                                  "bins": waveform},
            "evidence": {"automated": ["onsets", "energy", "tempo hypothesis", "recurrence candidates"],
                                                 "manual_review_required": ["BPM and half/double choice", "bar/downbeat anchor", "section names", "alignment at start/middle/end"]}}
