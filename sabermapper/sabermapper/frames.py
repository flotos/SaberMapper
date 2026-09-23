"""Load in-game frame captures and build contact sheets the agent can read.

Input is the directory written by `game capture`: PNG frames plus `capture.json`. A plain directory
of `tSSSS.mmm.png` frames without a manifest is also accepted. Nothing here judges the frames; see
`frame_metrics.py` for findings.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import json
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCHEMA_VERSION = 1
FRAME_NAME = re.compile(r"^t(\d+(?:\.\d+)?)\.png$", re.IGNORECASE)
ANALYSIS_WIDTH = 192  # metrics run on frames downscaled to this width
MAX_SHEET_WIDTH = 2000
MAX_SHEET_ROWS = 4
LABEL_FONT_SIZE = 15
HEADER_FONT_SIZE = 18
GAP = 8


def _float(value, name, file):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"capture.json frame {file!r} has a non-numeric {name} ({value!r}); "
                         "re-run `game capture` or fix the manifest") from None


def load_capture(directory, arrangement: dict | None = None) -> dict:
    """Normalize a capture directory into {metadata..., frames: [...]} sorted by song time.

    With an arrangement, frames lacking a beat or section get them from the arrangement's timing.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Capture directory {root} does not exist; run `game capture PROJECT --out DIR` first")
    manifest_path = root / "capture.json"
    warnings = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{manifest_path} is not valid JSON ({exc}); re-run `game capture`") from None
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{manifest_path} has schema_version {manifest.get('schema_version')!r}; "
                             f"this SaberMapper reads version {SCHEMA_VERSION}")
        if not isinstance(manifest.get("frames"), list):
            raise ValueError(f"{manifest_path} has no frames list; re-run `game capture`")
        frames, missing = [], []
        for item in manifest["frames"]:
            file = item.get("file")
            if not isinstance(file, str) or Path(file).name != file:
                raise ValueError(f"capture.json frame file {file!r} must be a bare file name inside {root}")
            if not (root / file).is_file():
                missing.append(file)
                continue
            song_time = item.get("song_time", item.get("requested_time"))
            frames.append({"file": file, "path": str(root / file),
                           "song_time": _float(song_time, "song_time", file),
                           "requested_time": (None if item.get("requested_time") is None
                                              else _float(item["requested_time"], "requested_time", file)),
                           "beat": None if item.get("beat") is None else _float(item["beat"], "beat", file),
                           "section_id": item.get("section_id"), "reason": item.get("reason") or "requested"})
        if missing:
            warnings.append({"code": "frame_file_missing", "files": missing[:20], "count": len(missing),
                             "message": f"{len(missing)} manifest frame(s) have no PNG in {root}; they were skipped"})
        meta = {key: manifest.get(key) for key in ("project", "revision", "difficulty", "camera", "width", "height",
                                                    "game_version", "level_path", "created_at")}
        log_diagnostics = manifest.get("log_diagnostics") or []
    else:
        frames, skipped = [], []
        for path in sorted(root.glob("*.png")):
            match = FRAME_NAME.match(path.name)
            if not match:
                skipped.append(path.name)
                continue
            frames.append({"file": path.name, "path": str(path), "song_time": float(match.group(1)),
                           "requested_time": float(match.group(1)), "beat": None, "section_id": None,
                           "reason": "requested"})
        if skipped:
            warnings.append({"code": "frame_name_unparsed", "files": skipped[:20], "count": len(skipped),
                             "message": "PNG names must look like t0012.500.png (song seconds) to be read "
                                        "without capture.json; these were skipped"})
        meta = dict.fromkeys(("project", "revision", "difficulty", "camera", "width", "height", "game_version",
                              "level_path", "created_at"))
        log_diagnostics = []
    if not frames:
        raise ValueError(f"No readable frames in {root}; expected capture.json from `game capture` or "
                         "PNGs named tSSSS.mmm.png")
    frames.sort(key=lambda f: f["song_time"])
    if arrangement is not None:
        annotate_frames(frames, arrangement)
    return {"directory": str(root), "manifest": manifest_path.is_file(), **meta, "frames": frames,
            "log_diagnostics": log_diagnostics, "warnings": warnings}


def section_spans(arrangement: dict) -> list[dict]:
    """[{id, start_seconds, end_seconds, start_beat, end_beat}] for the arrangement's sections."""
    from .critique import beat_to_seconds
    spans = []
    for section in arrangement.get("sections", []):
        start = float(Fraction(str(section["start_beat"])))
        end = start + float(Fraction(str(section.get("length_beats", 0))))
        spans.append({"id": section["id"], "start_beat": start, "end_beat": end,
                      "start_seconds": beat_to_seconds(start, arrangement),
                      "end_seconds": beat_to_seconds(end, arrangement)})
    return spans


def annotate_frames(frames: list[dict], arrangement: dict) -> None:
    from .musical import seconds_to_beat
    spans = section_spans(arrangement)
    for frame in frames:
        if frame["beat"] is None:
            frame["beat"] = round(seconds_to_beat(frame["song_time"], arrangement), 4)
        if frame["section_id"] is None:
            frame["section_id"] = next((s["id"] for s in spans
                                        if s["start_seconds"] <= frame["song_time"] < s["end_seconds"]), None)


def load_rgb(path, width: int | None = ANALYSIS_WIDTH) -> np.ndarray:
    """uint8 RGB array, downscaled to `width` (aspect kept) unless width is None."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        if width and image.width > width:
            factor = image.width // (width * 2)
            if factor > 1:
                image = image.reduce(factor)
            image = image.resize((width, max(1, round(image.height * width / image.width))), Image.BILINEAR)
        return np.asarray(image, dtype=np.uint8)


def format_time(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    minutes = int(seconds // 60)
    return f"{sign}{minutes}:{seconds - minutes * 60:06.3f}"


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow without FreeType: fixed bitmap font
        return ImageFont.load_default()


def _groups(frames, per_section, per_sheet):
    """[(section_id or None, [frames])], consecutive frames sharing a section; chunks otherwise."""
    groups = []
    if per_section and any(f["section_id"] is not None for f in frames):
        for frame in frames:
            if groups and groups[-1][0] == frame["section_id"]:
                groups[-1][1].append(frame)
            else:
                groups.append((frame["section_id"], [frame]))
    else:
        groups = [(None, frames[i:i + per_sheet]) for i in range(0, len(frames), per_sheet)]
    pages = []
    for section, items in groups:
        chunks = [items[i:i + per_sheet] for i in range(0, len(items), per_sheet)]
        pages += [(section, chunk, index + 1, len(chunks)) for index, chunk in enumerate(chunks)]
    return pages


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")[:40] or "section"


def contact_sheets(directory, out_dir=None, *, per_section=True, columns=4, thumb_width=420,
                   include_probe=False, arrangement: dict | None = None) -> dict:
    """Write labelled thumbnail sheets (one or more per section) and return what each contains."""
    capture = load_capture(directory, arrangement)
    if columns < 1 or thumb_width < 120:
        raise ValueError("--columns must be at least 1 and --thumb-width at least 120 px")
    columns = max(1, min(columns, (MAX_SHEET_WIDTH - GAP) // (thumb_width + GAP)))
    frames = [f for f in capture["frames"] if include_probe or f["reason"] != "probe"]
    omitted = len(capture["frames"]) - len(frames)
    if not frames:
        raise ValueError("Only probe frames were captured; pass --include-probe to lay them out")
    out = Path(out_dir) if out_dir else Path(directory) / "sheets"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("sheet-*.png"):
        stale.unlink()
    label_font, header_font = _font(LABEL_FONT_SIZE), _font(HEADER_FONT_SIZE)
    line = LABEL_FONT_SIZE + 4
    header_height = HEADER_FONT_SIZE * 2 + 16
    header_bits = [f"project {capture['project'] or '?'}",
                   f"revision {(capture['revision'] or '?')[:12]}", capture["difficulty"] or "difficulty ?",
                   f"camera {capture['camera'] or '?'}"]
    sheets = []
    for number, (section, items, part, parts) in enumerate(_groups(frames, per_section,
                                                                    columns * MAX_SHEET_ROWS), 1):
        thumbs = [load_rgb(f["path"], thumb_width) for f in items]
        thumb_height = max(t.shape[0] for t in thumbs)
        rows = -(-len(items) // columns)
        width = GAP + min(columns, len(items)) * (thumb_width + GAP)
        width = max(width, 640)
        cell = thumb_height + 2 * line + 6
        sheet = Image.new("RGB", (width, header_height + rows * (cell + GAP) + GAP), (24, 24, 28))
        draw = ImageDraw.Draw(sheet)
        span = f"{format_time(items[0]['song_time'])} - {format_time(items[-1]['song_time'])}"
        title = (f"section {section}" if section is not None else "frames") + (
            f" (part {part}/{parts})" if parts > 1 else "") + f"  {span}  ({len(items)} frames)"
        draw.text((GAP, 6), "  |  ".join(header_bits), fill=(235, 235, 235), font=header_font)
        draw.text((GAP, 10 + HEADER_FONT_SIZE), title, fill=(255, 210, 90), font=header_font)
        for index, (frame, thumb) in enumerate(zip(items, thumbs)):
            x = GAP + (index % columns) * (thumb_width + GAP)
            y = header_height + (index // columns) * (cell + GAP)
            sheet.paste(Image.fromarray(thumb), (x, y))
            beat = "?" if frame["beat"] is None else f"{frame['beat']:.2f}"
            first = f"{format_time(frame['song_time'])}  beat {beat}"
            second = f"{frame['section_id'] if frame['section_id'] is not None else '-'}  {frame['reason']}"
            draw.text((x + 2, y + thumb_height + 3), first, fill=(255, 255, 255), font=label_font)
            draw.text((x + 2, y + thumb_height + 3 + line), second, fill=(170, 200, 255), font=label_font)
        name = f"sheet-{number:03d}-{_slug(section) if section is not None else 'frames'}" + (
            f"-p{part}" if parts > 1 else "") + ".png"
        sheet.save(out / name, optimize=True)
        sheets.append({"path": str(out / name), "section_id": section, "part": part, "parts": parts,
                       "width": sheet.width, "height": sheet.height,
                       "start_time": items[0]["song_time"], "end_time": items[-1]["song_time"],
                       "frames": [{"file": f["file"], "song_time": f["song_time"], "beat": f["beat"],
                                   "reason": f["reason"]} for f in items]})
    result = {"directory": capture["directory"], "project": capture["project"], "revision": capture["revision"],
              "difficulty": capture["difficulty"], "camera": capture["camera"], "out_dir": str(out),
              "columns": columns, "thumb_width": thumb_width, "frame_count": len(frames),
              "probe_frames_omitted": omitted, "sheets": sheets, "warnings": capture["warnings"],
              "next": "Read each sheet PNG with the image viewer; frame files are listed per sheet."}
    (out / "sheets.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
