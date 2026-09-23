"""Small, deterministic v3 Beat Saber ZIP exporter for the first playtest."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import zlib
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from .arrangement import beat_fraction, compile_arrangement
from .audio import inspect_audio
from .validation import validate_arrangement
from .revisions import arrangement_revision


class ExportError(ValueError):
    """An arrangement or asset cannot be exported safely."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _asset(path: str | Path, label: str) -> tuple[Path, bytes]:
    source = Path(path)
    if not source.is_file():
        raise ExportError(f"{label} file does not exist: {source}")
    data = source.read_bytes()
    if not data:
        raise ExportError(f"{label} file is empty: {source}")
    return source, data


def _ogg_vorbis(data: bytes) -> None:
    # Check the first Ogg page and Vorbis identification packet. This does not
    # decode the stream or prove that later pages are playable.
    if len(data) < 58 or data[:4] != b"OggS" or data[4] != 0 or not (data[5] & 2):
        raise ExportError("audio must start with an Ogg Vorbis beginning-of-stream page")
    segments = data[26]
    if not segments or len(data) < 27 + segments:
        raise ExportError("audio has a truncated Ogg page header")
    packet_start = 27 + segments
    page_end = packet_start + sum(data[27:packet_start])
    if page_end > len(data) or data[27] < 30 or page_end < packet_start + 30:
        raise ExportError("audio has a truncated Vorbis identification packet")
    if data[packet_start:packet_start + 7] != b"\x01vorbis":
        raise ExportError("audio must contain a Vorbis identification packet; Opus is unsupported")
    if data[packet_start + 7:packet_start + 11] != bytes(4) or not data[packet_start + 11]:
        raise ExportError("audio has an unsupported Vorbis identification packet")
    if not struct.unpack_from("<I", data, packet_start + 12)[0] or not (data[packet_start + 29] & 1):
        raise ExportError("audio has an invalid Vorbis sample rate or framing bit")


def _cover(data: bytes, suffix: str) -> str:
    from PIL import Image, UnidentifiedImageError
    try:
        if len(data) > 16 * 1024 * 1024:
            raise ExportError("cover exceeds the 16 MB budget")
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"PNG", "JPEG"} or picture.width * picture.height > 16_000_000:
                raise ExportError("cover must be PNG or JPEG with at most 16 million pixels")
            if (picture.format == "PNG") != (suffix == ".png"):
                raise ExportError("cover extension does not match its encoded format")
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            picture.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ExportError("cover image cannot be decoded") from exc
    if suffix == ".png":
        if len(data) < 45 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ExportError("cover must be a valid PNG with an IHDR chunk")
        length = struct.unpack(">I", data[8:12])[0]
        if length != 13 or zlib.crc32(data[12:29]) & 0xffffffff != struct.unpack(">I", data[29:33])[0]:
            raise ExportError("cover PNG has an invalid IHDR chunk")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height or b"IEND" not in data[-16:]:
            raise ExportError("cover PNG is incomplete")
        return "cover.png"
    if suffix in (".jpg", ".jpeg"):
        if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
            raise ExportError("cover must be a JPEG with SOI and EOI markers")
        return "cover.jpg"
    raise ExportError("cover must have a .png, .jpg, or .jpeg extension")


def _zip_entry(name: str, data: bytes, archive: ZipFile) -> None:
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.external_attr = 0o644 << 16
    archive.writestr(entry, data)


def _beat_seconds(beat: float, base_bpm: float, events: list[dict]) -> float:
    elapsed = 0.0
    previous = 0.0
    tempo = base_bpm
    for event in sorted(events, key=lambda item: float(item["b"])):
        at = float(event["b"])
        if at > beat:
            break
        elapsed += (at - previous) * 60 / tempo
        previous = at
        tempo = float(event["m"])
    return elapsed + (beat - previous) * 60 / tempo


STANDARD_RANKS = {"Easy": 1, "Normal": 3, "Hard": 5, "Expert": 7, "ExpertPlus": 9}


def _compile_difficulty(arrangement: dict, audio_duration: float) -> tuple[dict, dict]:
    """Compile one difficulty with the audio offset baked in; return the beatmap and its report row."""
    song, difficulty = arrangement["song"], arrangement["difficulty"]
    name = difficulty.get("name", "Expert")
    if name not in STANDARD_RANKS:
        raise ExportError("difficulty name must be a built-in Standard difficulty")
    offset_seconds = float(song.get("audio_offset_seconds", 0))
    beatmap = compile_arrangement(arrangement)
    if beatmap.get("version") != "3.3.0" or not isinstance(beatmap.get("colorNotes"), list):
        raise ExportError(f"{name}: compiler did not return a v3.3.0 beatmap with colorNotes")
    if not beatmap["colorNotes"]:
        raise ExportError(f"{name}: compiled beatmap has no color notes")
    beat_shift = offset_seconds * float(song["bpm"]) / 60
    if beat_shift:
        for collection in ("bpmEvents", "colorNotes", "bombNotes", "obstacles", "sliders", "burstSliders", "waypoints",
                           "basicBeatmapEvents", "colorBoostBeatmapEvents", "rotationEvents"):
            for item in beatmap.get(collection, []):
                item["b"] = round(float(item["b"]) + beat_shift, 9)
                if collection in ("sliders", "burstSliders"):
                    item["tb"] = round(float(item["tb"]) + beat_shift, 9)
    latest_note = max(float(note["b"]) for note in beatmap["colorNotes"])
    latest_time = _beat_seconds(latest_note, float(song["bpm"]), beatmap.get("bpmEvents", []))
    if latest_time >= audio_duration - 0.05:
        raise ExportError(f"{name}: last note at {latest_time:.3f}s exceeds playable audio duration {audio_duration:.3f}s")
    latest_object = latest_note
    for collection in ("bombNotes", "obstacles", "sliders", "burstSliders"):
        for item in beatmap.get(collection, []):
            latest_object = max(latest_object, float(item.get("tb", item["b"])))
            if collection == "obstacles":
                latest_object = max(latest_object, float(item["b"]) + float(item["d"]))
    if _beat_seconds(latest_object, float(song["bpm"]), beatmap.get("bpmEvents", [])) > audio_duration:
        raise ExportError(f"{name}: compiled gameplay object extends past decoded audio duration")
    # Without a lightshow, a small visible pulse at each section start. Basic events live
    # in the v3 beatmap itself; they do not require a separate v4 lightshow file.
    has_lightshow = isinstance(arrangement.get("lightshow"), dict)
    if not has_lightshow and not beatmap.get("basicBeatmapEvents"):
        beats = sorted({float(beat_fraction(section["start_beat"])) + beat_shift for section in arrangement["sections"]})
        beatmap["basicBeatmapEvents"] = [{"b": b, "et": 0, "i": 1, "f": 1.0} for b in beats]
    row = {"difficulty": name, "rank": STANDARD_RANKS[name], "beatmap_filename": f"{name}.dat",
           "njs": difficulty.get("njs", 16), "target_tier": difficulty.get("target_tier"),
           "arrangement_sha256": arrangement_revision(arrangement), "color_note_count": len(beatmap["colorNotes"]),
           "last_note_seconds": latest_time, "basic_event_count": len(beatmap["basicBeatmapEvents"]),
           "lighting": {"source": "lightshow" if has_lightshow else "section-pulse fallback",
                        "environment": _environment(arrangement),
                        "basic_events": len(beatmap["basicBeatmapEvents"]),
                        "boost_events": len(beatmap.get("colorBoostBeatmapEvents", []))}}
    return beatmap, row


def _environment(arrangement: dict) -> str:
    return (arrangement.get("lightshow") or {}).get("environment") or "DefaultEnvironment"


def export_arrangement(arrangement: dict, audio: str | Path, cover: str | Path, output: str | Path) -> dict:
    """Export one Standard difficulty. Returns the compatibility report."""
    return export_arrangements([arrangement], audio, cover, output)


def export_arrangements(arrangements: list[dict], audio: str | Path, cover: str | Path, output: str | Path) -> dict:
    """Export several Standard difficulties of one song into a single map ZIP.

    The first arrangement is the primary one: it supplies the song metadata. Every
    difficulty shares the audio, so song BPM, offset and tempo events must match.
    """
    if not arrangements:
        raise ExportError("no difficulty to export")
    for arrangement in arrangements:
        diagnostics = validate_arrangement(arrangement)
        errors = [item for item in diagnostics if item.get("severity") == "error"]
        if errors:
            label = (arrangement.get("difficulty") or {}).get("name", "arrangement") if isinstance(arrangement, dict) else "arrangement"
            raise ExportError(f"{label} validation failed: " + "; ".join(str(x.get("message", x)) for x in errors))
    primary = arrangements[0]
    song = primary["song"]
    names = [a["difficulty"]["name"] for a in arrangements]
    if len(set(names)) != len(names):
        raise ExportError("each difficulty may appear only once: " + ", ".join(names))
    for other in arrangements[1:]:
        if (other["song"]["bpm"] != song["bpm"] or other["song"]["audio_offset_seconds"] != song["audio_offset_seconds"]
                or other.get("tempo_events", []) != primary.get("tempo_events", [])):
            raise ExportError(f"{other['difficulty']['name']} song timing differs from {names[0]}; every difficulty "
                              "shares the audio, so save matching song.bpm, audio_offset_seconds and tempo_events")
    offset_seconds = float(song.get("audio_offset_seconds", 0))
    if offset_seconds < 0:
        raise ExportError("negative audio_offset_seconds is unsupported; trim or pad source audio")
    audio_path, audio_bytes = _asset(audio, "audio")
    cover_path, cover_bytes = _asset(cover, "cover")
    if audio_path.suffix.lower() != ".ogg":
        raise ExportError("audio filename must end in .ogg")
    _ogg_vorbis(audio_bytes)
    try:
        audio_metadata = inspect_audio(audio_path)
    except ValueError as exc:
        raise ExportError(f"audio cannot be decoded: {exc}") from exc
    cover_name = _cover(cover_bytes, cover_path.suffix.lower())
    destination = Path(output)
    if destination.resolve() in (audio_path.resolve(), cover_path.resolve()):
        raise ExportError("output must differ from input assets")
    if destination.exists():
        raise ExportError(f"output already exists: {destination}")
    compiled = [_compile_difficulty(arrangement, audio_metadata["duration_seconds"]) for arrangement in arrangements]
    by_rank = sorted(zip(arrangements, compiled), key=lambda item: item[1][1]["rank"])
    # Each difficulty names its lightshow's environment; Info.dat lists them once and indexes them.
    environments = list(dict.fromkeys([_environment(primary)] + [_environment(a) for a in arrangements]))
    info = {
        "_version": "2.1.0", "_songName": song["title"], "_songSubName": "",
        "_songAuthorName": song["artist"], "_levelAuthorName": str(primary.get("mapper") or "SaberMapper").strip(),
        "_beatsPerMinute": song["bpm"], "_songTimeOffset": 0, "_shuffle": 0,
        "_shufflePeriod": 0, "_previewStartTime": 0, "_previewDuration": 10,
        "_songFilename": "song.ogg", "_coverImageFilename": cover_name,
        "_environmentName": environments[0], "_allDirectionsEnvironmentName": "GlassDesertEnvironment",
        # Info 2.1.0 introduced these collections; declare them explicitly so the
        # file matches the schema version it claims.
        "_environmentNames": environments, "_colorSchemes": [],
        "_difficultyBeatmapSets": [{"_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": [{
            "_difficulty": row["difficulty"], "_difficultyRank": row["rank"],
            "_beatmapFilename": row["beatmap_filename"], "_noteJumpMovementSpeed": arrangement["difficulty"].get("njs", 16),
            "_noteJumpStartBeatOffset": arrangement["difficulty"].get("spawn_offset_beats", 0),
            "_beatmapColorSchemeIdx": 0, "_environmentNameIdx": environments.index(_environment(arrangement)),
        } for arrangement, (_, row) in by_rank]}],
    }
    rows = [row for _, row in compiled]
    report = {
        "format": "SaberMapper SM-029 export report 0.2", "beatmap_schema": "3.3.0",
        "info_schema": "2.1.0", "characteristic": "Standard", "difficulty": names[0],
        "difficulties": [row for _, (_, row) in by_rank],
        "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "cover_sha256": hashlib.sha256(cover_bytes).hexdigest(),
        "arrangement_sha256": rows[0]["arrangement_sha256"],
        "arrangement_hash_encoding": "canonical UTF-8 JSON; sorted keys, compact separators, no trailing newline",
        "color_note_count": rows[0]["color_note_count"],
        "audio_duration_seconds": audio_metadata["duration_seconds"],
        "last_note_seconds": max(row["last_note_seconds"] for row in rows),
        "baked_audio_offset_seconds": offset_seconds,
        "audio_decoder": audio_metadata["decoder"],
        "basic_event_count": rows[0]["basic_event_count"],
        "lighting": rows[0]["lighting"],
        "checks": "Vorbis and cover decoded; gameplay duration and structure checked for every difficulty. Musical timing, editor import and in-game playback require separate review.",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream:
            with ZipFile(stream, "w") as archive:
                entries = [("Info.dat", _json_bytes(info))]
                entries += [(row["beatmap_filename"], _json_bytes(beatmap)) for _, (beatmap, row) in by_rank]
                entries += [("song.ogg", audio_bytes), (cover_name, cover_bytes),
                            ("SaberMapper-report.json", _json_bytes(report))]
                for filename, data in entries:
                    _zip_entry(filename, data, archive)
    except FileExistsError:
        raise ExportError(f"output already exists: {destination}")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return report
