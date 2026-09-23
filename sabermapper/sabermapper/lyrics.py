"""Lyrics with word timestamps for an evidence run.

Two sources, both written to ``lyrics.json`` in the run directory:

* ``whisper`` - faster-whisper (preferred) or openai-whisper on the Demucs vocal stem, run in a
  separate interpreter (by default `.venv-separation`, like Demucs) with word timestamps on.
  When neither package is importable the command fails with the structured ``whisper_missing``
  error carrying the exact install command; nothing is installed automatically.
* ``--from-file`` - a user-supplied LRC or plain-text lyric sheet, aligned without any model.
  LRC keeps its line (or enhanced word) timestamps; plain text is aligned line by line to vocal
  phrases found in the vocal stem's energy, so its precision is labelled ``rough``.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np

from .storage import now, read_json, write_json

LYRICS_VERSION = "1.0"
DEFAULT_MODEL = "large-v3"
WHISPER_MODULES = ("faster_whisper", "whisper")
SAMPLE_RATE = 16000
PHRASE_GAP_SECONDS = .35
PHRASE_MIN_SECONDS = .3
VOCAL_ACTIVE_DB = -25.0
SNAP_SECONDS = .15
MAX_GROUP = 6
MAX_SYLLABLE_SECONDS = .6
PRECISION = {
    "whisper": "word timestamps from Whisper's cross-attention alignment on the vocal stem; usually within a few "
               "tenths of a second of the sung onset, worse on melisma, held notes, backing vocals and ad-libs; words "
               "can be misheard",
    "lrc_word": "word timestamps copied from the enhanced LRC file; accuracy is the file author's",
    "lrc_line": "line timestamps copied from the LRC file; word times are interpolated by syllable count inside the "
                "line and snapped to vocal onsets within 0.15 s, so they are approximate",
    "rough": "rough: lines were aligned in order to vocal phrases (vocal-stem energy) by syllable count, with no "
             "speech model; a line can land a phrase early or late and word times are interpolated. Use for "
             "section-level cues, not word-exact effects",
}


class ListenError(ValueError):
    """A failure with a stable ``code`` and an actionable ``fix`` for the agent."""
    def __init__(self, code, message, fix=None, **details):
        super().__init__(message)
        self.code, self.fix, self.details = code, fix, details

    def as_json(self):
        return {"error": {"code": self.code, "message": str(self), "fix": self.fix, **self.details}}


# ---- shared helpers ------------------------------------------------------------------------------

def _beat(seconds, arrangement):
    if not arrangement or seconds is None:
        return None
    from .musical import seconds_to_beat
    return round(seconds_to_beat(seconds, arrangement), 3)


def rebeat_lyrics(lyrics, arrangement):
    """Recompute every beat field from the stored seconds against ``arrangement``'s grid."""
    for segment in lyrics.get("segments", []):
        segment["start_beat"], segment["end_beat"] = _beat(segment["start"], arrangement), _beat(segment["end"], arrangement)
        for word in segment.get("words", []):
            word["beat"] = _beat(word["start"], arrangement)
    lyrics["words"] = flat_words(lyrics.get("segments", []))
    return lyrics


def flat_words(segments):
    """Every word as one driver item (the show compiler reads ``words``): id, start, end, word, confidence."""
    return [{"id": f"{segment['id']}/{index}", "segment_id": segment["id"], "word": word["word"],
             "start": word["start"], "end": word["end"], "beat": word.get("beat"),
             "confidence": 1.0 if word.get("probability") is None else word["probability"]}
            for segment in segments for index, word in enumerate(segment.get("words", []))]


def normalize_segments(raw_segments, arrangement=None):
    """Clean model or parser output into the stored segment schema with ids and beats."""
    segments = []
    for raw in raw_segments:
        words = []
        for word in raw.get("words") or []:
            text = str(word.get("word", "")).strip()
            if not text or word.get("start") is None:
                continue
            start = float(word["start"])
            end = float(word.get("end") if word.get("end") is not None else start)
            probability = word.get("probability")
            words.append({"word": text, "start": round(start, 3), "end": round(max(end, start), 3),
                          "probability": None if probability is None else round(float(probability), 3),
                          "beat": _beat(start, arrangement)})
        text = str(raw.get("text", "")).strip() or " ".join(w["word"] for w in words)
        if not text:
            continue
        start = float(raw["start"]) if raw.get("start") is not None else (words[0]["start"] if words else None)
        end = float(raw["end"]) if raw.get("end") is not None else (words[-1]["end"] if words else start)
        if start is None:
            continue
        segments.append({"id": f"lyr-{len(segments) + 1:03d}", "start": round(start, 3), "end": round(max(end, start), 3),
                         "start_beat": _beat(start, arrangement), "end_beat": _beat(end, arrangement),
                         "text": text, "words": words})
    return segments


# ---- whisper -------------------------------------------------------------------------------------

RUNNER = r'''
import json, os, sys, site
config = json.loads(open(sys.argv[1], encoding="utf-8").read())
# Windows: let CTranslate2 find cuBLAS/cuDNN shipped with torch or the nvidia-* wheels.
if os.name == "nt":
    for root in site.getsitepackages() + [site.getusersitepackages()]:
        for relative in ("torch/lib",) + tuple(f"nvidia/{p}/bin" for p in ("cublas", "cudnn", "cuda_runtime")):
            path = os.path.join(root, relative)
            if os.path.isdir(path):
                os.add_dll_directory(path)
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
import numpy as np
audio = np.load(config["audio"]).astype("float32")
backend, device, language = config["backend"], config["device"], config["language"]
result = {"backend": backend, "model": config["model"], "segments": []}
if backend == "faster_whisper":
    import faster_whisper, ctranslate2
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    # Download into a plain folder: the Hugging Face cache needs symlinks, which Windows refuses
    # without Developer Mode or admin rights (WinError 1314).
    path = config["model"]
    if config.get("model_dir") and not os.path.isdir(path):
        path = os.path.join(config["model_dir"], "faster-whisper-" + config["model"])
        if not os.path.isfile(os.path.join(path, "model.bin")):
            from faster_whisper.utils import download_model
            download_model(config["model"], output_dir=path)
    model = faster_whisper.WhisperModel(path, device=device, compute_type=compute)
    segments, info = model.transcribe(audio, language=language, word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
    for s in segments:
        result["segments"].append({"start": s.start, "end": s.end, "text": s.text, "words": [
            {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability} for w in (s.words or [])]})
    result.update(language=info.language, language_probability=info.language_probability, device=device,
                  compute_type=compute, version=faster_whisper.__version__)
else:
    import whisper, torch
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(config["model"], device=device)
    output = model.transcribe(audio, language=language, word_timestamps=True, condition_on_previous_text=False,
                              fp16=device == "cuda")
    for s in output["segments"]:
        result["segments"].append({"start": s["start"], "end": s["end"], "text": s["text"], "words": [
            {"word": w["word"], "start": w["start"], "end": w["end"], "probability": w.get("probability")}
            for w in s.get("words", [])]})
    result.update(language=output.get("language"), device=device, version=getattr(whisper, "__version__", None))
with open(config["output"], "w", encoding="utf-8") as stream:
    json.dump(result, stream)
'''


def model_directory() -> Path:
    """Where Whisper weights are kept: ``SABERMAPPER_MODEL_DIR``, else %LOCALAPPDATA%/SaberMapper/models."""
    if os.environ.get("SABERMAPPER_MODEL_DIR"):
        return Path(os.environ["SABERMAPPER_MODEL_DIR"])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "SaberMapper" / "models"


def whisper_python(python=None):
    """The interpreter that runs Whisper: --python, else `.venv-separation`, else this one."""
    if python is not None:
        return Path(python)
    from .musical import APP_DIRECTORY
    for relative in ("Scripts/python.exe", "bin/python"):
        candidate = APP_DIRECTORY / ".venv-separation" / relative
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def install_fix(python):
    return (f"{python} -m pip install faster-whisper   (needs the user's approval; for CUDA on Windows the runner "
            "loads cuBLAS/cuDNN from the torch install in that environment, else also install nvidia-cublas-cu12 "
            f"nvidia-cudnn-cu12). Alternative reusing torch: {python} -m pip install openai-whisper")


def whisper_backend(python):
    """First importable Whisper package in ``python``, else None."""
    code = ("import importlib.util,sys;print(next((m for m in sys.argv[1:] if importlib.util.find_spec(m)),''))")
    try:
        probe = subprocess.run([str(python), "-c", code, *WHISPER_MODULES], capture_output=True, text=True,
                               check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ListenError("whisper_python_unusable", f"Could not run {python}: {exc}",
                          "Pass --python with a working interpreter") from exc
    name = probe.stdout.strip()
    return name or None


def _vocal_input(run_dir, report, source):
    if source == "mix":
        return None, "mix"
    layer = (report.get("layers") or {}).get("vocals") or {}
    path = Path(run_dir) / layer["audio_file"] if layer.get("audio_file") else None
    if path is None or not path.is_file():
        raise ListenError("vocal_stem_missing", "This evidence run has no separated vocals stem",
                          "Run `music analyze PROJECT --backend ensemble` first, or pass --input mix "
                          "(Whisper on the full mix is less accurate)")
    return path, "vocals"


def transcribe(project_dir, run_id, report, arrangement=None, *, python=None, model=DEFAULT_MODEL, device="auto",
               language=None, source="vocals", runner=subprocess.run):
    """Run Whisper in a separate interpreter and return the lyrics document (not yet written)."""
    from .listen import load_signal
    run_dir = Path(project_dir) / "musical" / run_id
    python = whisper_python(python)
    backend = whisper_backend(python)
    if backend is None:
        raise ListenError("whisper_missing", f"Neither faster-whisper nor openai-whisper is importable in {python}",
                          install_fix(python), python=str(python), install_command=f"{python} -m pip install faster-whisper")
    path, used = _vocal_input(run_dir, report, source)
    signal = load_signal(path if path else Path(project_dir) / "song.ogg")
    from scipy.signal import resample_poly
    audio = resample_poly(signal, SAMPLE_RATE // 50, 22050 // 50).astype(np.float32)
    with tempfile.TemporaryDirectory(prefix="sabermapper-lyrics-") as temp:
        temp = Path(temp)
        np.save(temp / "audio.npy", audio)
        (temp / "runner.py").write_text(RUNNER, encoding="utf-8")
        config = {"audio": str(temp / "audio.npy"), "output": str(temp / "result.json"), "backend": backend,
                  "model": model, "device": device, "language": language, "model_dir": str(model_directory())}
        (temp / "config.json").write_text(json.dumps(config), encoding="utf-8")
        command = [str(python), str(temp / "runner.py"), str(temp / "config.json")]
        log = run_dir / "lyrics.log"
        with log.open("w", encoding="utf-8") as stream:
            result = runner(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
        if result.returncode or not (temp / "result.json").exists():
            raise ListenError("whisper_failed", f"Whisper ({backend}, {model}) exited with {result.returncode}",
                              f"Read {log}; try --device cpu or a smaller --model (medium, small)", log=str(log))
        raw = json.loads((temp / "result.json").read_text(encoding="utf-8"))
    return lyrics_document(raw, report, run_id, arrangement, input_layer=used, command=[str(python), "runner.py"])


def lyrics_document(raw, report, run_id, arrangement=None, *, input_layer="vocals", command=None):
    """Stored lyrics.json from raw Whisper runner output."""
    segments = normalize_segments(raw.get("segments", []), arrangement)
    return {"schema_version": LYRICS_VERSION, "created_at": now(), "run_id": run_id,
            "source_sha256": report["source"]["sha256"], "backend": raw.get("backend"), "model": raw.get("model"),
            "language": raw.get("language"), "language_probability": raw.get("language_probability"),
            "device": raw.get("device"), "compute_type": raw.get("compute_type"), "input": input_layer,
            "precision": "whisper", "precision_note": PRECISION["whisper"], "segments": segments,
            "words": flat_words(segments), "word_count": sum(len(s["words"]) for s in segments),
            "provenance": {"tool": raw.get("backend"), "tool_version": raw.get("version"), "command": command,
                           "word_timestamps": True, "run_id": run_id}}


# ---- lyric sheets without a model --------------------------------------------------------------

TIME_TAG = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
WORD_TAG = re.compile(r"<(\d+):(\d{1,2}(?:[.:]\d{1,3})?)>")
META_TAG = re.compile(r"^\[[a-zA-Z]+:.*\]$")
HEADER = re.compile(r"^[\[(].*[\])]$")


def _clock(minutes, seconds):
    return int(minutes) * 60 + float(seconds.replace(":", "."))


def syllables(text):
    """Vowel-group count (min 1): a language-agnostic proxy for sung duration."""
    groups = re.findall(r"[aeiouyàâäéèêëîïôöùûüœæåáíóúãõ]+", text.lower())
    return max(1, len(groups))


def parse_lyric_sheet(text):
    """(kind, lines): kind is 'lrc' or 'text'; LRC lines carry ``time`` (and ``words`` for enhanced LRC)."""
    lines, timed = [], False
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or META_TAG.match(raw):
            continue
        stamps = TIME_TAG.findall(raw)
        body = TIME_TAG.sub("", raw).strip()
        if stamps:
            timed = True
            words = [(_clock(m, s), w.strip()) for m, s, w in re.findall(r"<(\d+):(\d{1,2}(?:[.:]\d{1,3})?)>([^<]*)", body)]
            clean = WORD_TAG.sub("", body).strip()
            for minutes, seconds in stamps:
                if clean:
                    lines.append({"time": _clock(minutes, seconds), "text": clean,
                                  "words": [{"word": w, "start": t} for t, w in words if w] or None})
            continue
        if HEADER.match(body):
            continue  # [Chorus], (x2) and similar section headers
        lines.append({"time": None, "text": body, "words": None})
    if timed:
        lines = sorted((l for l in lines if l["time"] is not None), key=lambda l: l["time"])
    return ("lrc" if timed else "text"), lines


def vocal_phrases(report):
    """Active vocal runs (seconds) from the vocals stem energy contour, else the mix's."""
    layers = report.get("layers") or {}
    layer = layers.get("vocals") or layers.get("mix") or {}
    contour = layer.get("energy_contour") or []
    if len(contour) < 2:
        return [], "none"
    times = np.array([p["seconds"] for p in contour])
    energy = np.array([p["energy"] for p in contour], dtype=float)
    level = 20 * np.log10(np.maximum(energy, 1e-12))
    active = level > float(np.percentile(level, 90)) + VOCAL_ACTIVE_DB
    if "vocals" in layers and layers.get("mix", {}).get("energy_contour"):
        mix = np.array([p["energy"] for p in layers["mix"]["energy_contour"][:len(energy)]], dtype=float)
        active[:len(mix)] &= level[:len(mix)] > 20 * np.log10(np.maximum(mix, 1e-12)) - 30
    step = float(np.median(np.diff(times)))
    phrases = []
    for index, flag in enumerate(active):
        if not flag:
            continue
        start, end = float(times[index]), float(times[index]) + step
        if phrases and start - phrases[-1][1] <= PHRASE_GAP_SECONDS:
            phrases[-1][1] = end
        else:
            phrases.append([start, end])
    return [p for p in phrases if p[1] - p[0] >= PHRASE_MIN_SECONDS], ("vocals" if "vocals" in layers else "mix")


def _split_to(phrases, count):
    phrases = [list(p) for p in phrases]
    while len(phrases) < count and phrases:
        index = max(range(len(phrases)), key=lambda i: phrases[i][1] - phrases[i][0])
        start, end = phrases[index]
        middle = (start + end) / 2
        phrases[index:index + 1] = [[start, middle], [middle, end]]
    return phrases


def align_lines(lines, phrases):
    """Monotone DP: each line takes a run of consecutive phrases; unused phrases (ad-libs) cost a penalty."""
    phrases = _split_to(phrases, len(lines))
    count, total = len(phrases), sum(p[1] - p[0] for p in phrases)
    weights = [syllables(l["text"]) for l in lines]
    rate = total / max(1, sum(weights))
    inf = float("inf")
    cost = [[inf] * (count + 1) for _ in range(len(lines) + 1)]
    back = [[None] * (count + 1) for _ in range(len(lines) + 1)]
    cost[0][0] = 0.0
    for j in range(1, count + 1):
        cost[0][j] = cost[0][j - 1] + 1.0 + (phrases[j - 1][1] - phrases[j - 1][0]) / max(rate, 1e-6) * .2
        back[0][j] = ("skip", j - 1)
    for i in range(1, len(lines) + 1):
        expected = max(rate * weights[i - 1], .2)
        for j in range(1, count + 1):
            skip = cost[i][j - 1] + 1.0 + (phrases[j - 1][1] - phrases[j - 1][0]) / max(rate, 1e-6) * .2
            best, choice = skip, ("skip", j - 1)
            for first in range(max(0, j - MAX_GROUP), j):
                if cost[i - 1][first] == inf:
                    continue
                span = phrases[j - 1][1] - phrases[first][0]
                value = cost[i - 1][first] + math.log(max(span, .05) / expected) ** 2
                if value < best:
                    best, choice = value, ("take", first)
            cost[i][j], back[i][j] = best, choice
    i, j, spans = len(lines), count, [None] * len(lines)
    while i > 0 and j > 0:
        kind, index = back[i][j]
        if kind == "skip":
            j = index
        else:
            spans[i - 1] = phrases[index:j]
            i, j = i - 1, index
    return spans, rate


def _words_in(text, groups, onsets, start_limit=None):
    """Distribute a line's words over its phrase groups by syllables, snapping starts to vocal onsets."""
    words = text.split()
    if not words or not groups:
        return []
    weights = [syllables(w) for w in words]
    active = sum(end - start for start, end in groups)
    per = active / sum(weights)
    placed, cursor = [], 0.0

    def at(offset):
        for start, end in groups:
            if offset <= end - start:
                return start + offset
            offset -= end - start
        return groups[-1][1]
    for word, weight in zip(words, weights):
        start, end = at(cursor), at(cursor + weight * per)
        near = [o for o in onsets if abs(o - start) <= SNAP_SECONDS]
        if near:
            start = min(near, key=lambda o: abs(o - start))
        placed.append({"word": word, "start": start, "end": max(end, start), "probability": None})
        cursor += weight * per
    for current, following in zip(placed, placed[1:]):
        current["end"] = max(current["start"], min(current["end"], following["start"]))
    return placed


def import_lyric_sheet(text, report, run_id, arrangement=None, *, filename=None):
    """lyrics.json content from an LRC or plain-text sheet (no model)."""
    kind, lines = parse_lyric_sheet(text)
    if not lines:
        raise ListenError("lyrics_empty", "The lyric file has no lyric lines",
                          "Provide plain text (one sung line per line) or an LRC file with [mm:ss.xx] tags")
    vocals = (report.get("layers") or {}).get("vocals") or {}
    onsets = sorted(e["seconds"] for e in vocals.get("events", [])
                    if e.get("method") in ("spectral_flux", "pitch_change") and e.get("strength", 0) >= .2)
    phrases, phrase_source = vocal_phrases(report)
    raw, precision = [], "rough"
    if kind == "lrc":
        precision = "lrc_word" if all(l["words"] for l in lines) else "lrc_line"
        duration = report["source"]["duration_seconds"]
        rate = sum(p[1] - p[0] for p in phrases) / max(1, sum(syllables(l["text"]) for l in lines)) if phrases else .3
        rate = min(max(rate, .15), MAX_SYLLABLE_SECONDS)
        for index, line in enumerate(lines):
            following = lines[index + 1]["time"] if index + 1 < len(lines) else duration
            end = min(following, line["time"] + max(.5, rate * syllables(line["text"]) * 1.5))
            if line["words"]:
                words = [{"word": w["word"], "start": w["start"], "end": None, "probability": None} for w in line["words"]]
                for current, nxt in zip(words, words[1:] + [{"start": end}]):
                    current["end"] = min(nxt["start"], current["start"] + max(.3, rate * syllables(current["word"]) * 2))
                end = max(end, words[-1]["end"])
            else:
                words = _words_in(line["text"], [(line["time"], end)], onsets)
            raw.append({"start": line["time"], "end": end, "text": line["text"], "words": words})
    else:
        if not phrases:
            raise ListenError("vocal_phrases_missing", "No vocal activity found to align the lyric lines to",
                              "Run `music analyze PROJECT --backend ensemble` so a vocals stem exists, or supply an "
                              "LRC file with timestamps")
        spans, _ = align_lines(lines, phrases)
        for line, groups in zip(lines, spans):
            if not groups:
                continue
            raw.append({"start": groups[0][0], "end": groups[-1][1], "text": line["text"],
                        "words": _words_in(line["text"], [tuple(g) for g in groups], onsets)})
    segments = normalize_segments(raw, arrangement)
    return {"schema_version": LYRICS_VERSION, "created_at": now(), "run_id": run_id,
            "source_sha256": report["source"]["sha256"], "backend": "lrc" if kind == "lrc" else "text_alignment",
            "model": None, "language": None, "input": phrase_source if kind == "text" else "file",
            "precision": precision, "precision_note": PRECISION[precision], "segments": segments,
            "words": flat_words(segments), "word_count": sum(len(s["words"]) for s in segments),
            "unaligned_lines": len(lines) - len(segments),
            "provenance": {"tool": "sabermapper lyric-sheet import", "file": filename, "lines": len(lines),
                           "vocal_phrases": len(phrases), "run_id": run_id}}


def lyrics_project(store, project_id, run_id=None, *, python=None, model=DEFAULT_MODEL, device="auto",
                   language=None, source="vocals", from_file=None, runner=subprocess.run):
    """Create lyrics.json for a run of the project's current audio; returns a summary."""
    from .listen import _resolve_run
    directory = store.directory(project_id)
    run_id, report = _resolve_run(directory, project_id, run_id)
    arrangement = read_json(directory / "arrangement.json") if (directory / "arrangement.json").exists() else None
    if from_file is not None:
        path = Path(from_file)
        if not path.is_file():
            raise ListenError("lyrics_file_missing", f"Lyric file {path} was not found", "Pass an existing .txt or .lrc")
        document = import_lyric_sheet(path.read_text(encoding="utf-8-sig"), report, run_id, arrangement,
                                      filename=path.name)
    else:
        document = transcribe(directory, run_id, report, arrangement, python=python, model=model, device=device,
                              language=language, source=source, runner=runner)
    target = directory / "musical" / run_id / "lyrics.json"
    write_json(target, document)
    return {"project": project_id, "run_id": run_id, "path": str(target), "backend": document["backend"],
            "model": document["model"], "language": document["language"], "precision": document["precision"],
            "segments": len(document["segments"]), "words": document["word_count"],
            "lines": [{"id": s["id"], "start": s["start"], "start_beat": s["start_beat"], "text": s["text"]}
                      for s in document["segments"]],
            "precision_note": document["precision_note"]}
