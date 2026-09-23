"""Frame metrics over an in-game capture, reported as critique-shaped findings.

Four checks, all numpy/Pillow, thresholds documented in docs/frame-review.md:

1. photosensitive flashes (general and saturated-red) on dense frame runs, blocking above 3 per second;
2. note readability against the background inside the note corridor (player camera);
3. palette drift from the concept palette (CIEDE2000 in CIELAB);
4. large visual changes versus section boundaries and moments.

A 2D desktop capture is evidence about the rendered picture only: it does not show VR scale, comfort
or performance. Findings use the critique shape {severity, code, section_id, object_ids, value,
threshold, message} plus `time` (song seconds) and `frames` (capture file names).
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import json

import numpy as np

from .frames import ANALYSIS_WIDTH, format_time, load_capture, load_rgb, section_spans

# Photosensitivity: WCAG 2.2 "general flash and red flash thresholds" (SC 2.3.1) and ITU-R BT.1702.
FLASH_DELTA = 0.10          # opposing change of >= 10% of the maximum relative luminance (1.0)
FLASH_DARK_MAX = 0.80       # ...where the darker state is below 0.80
FLASH_AREA = 0.25           # ...over >= 25% of the frame (BT.1702 / Ofcom screen-area criterion)
FLASH_LIMIT = 3.0           # more than 3 flashes in any 1 s: blocking
FLASH_WARN = 2.0            # 2 or more per second: warning (inside the limit, little margin)
RED_SATURATION = 0.80       # WCAG red: R / (R + G + B) >= 0.8 (linear components)
RED_DELTA = 20.0            # ...and a change of more than 20 in max(0, R - G - B) * 320
FLASH_GRID = (8, 8)         # tiles for the area criterion
FLASH_MERGE_FRAMES = 2      # tile transitions this close count as concurrent
REQUIRED_FPS = 20.0         # resolves up to 5 flashes/s (10 transitions/s) without aliasing
MIN_DENSE_SECONDS = 1.0

# Note corridor: normalized (x0, y0, x1, y1), y down, player camera. See docs/frame-review.md.
DEFAULT_CORRIDOR = (0.25, 0.35, 0.75, 0.90)
DEFAULT_NOTE_COLORS = {"left": "#c81414", "right": "#288ed2"}  # Beat Saber default scheme saberA / saberB
NON_TEXT_CONTRAST = 3.0     # WCAG 2.2 SC 1.4.11 non-text contrast
NOTE_HUE_DE = 20.0          # CIEDE2000 below this: the note colour does not stand out by hue either
ARROW_LUMINANCE = 0.30      # white arrow vs background < 3:1 once background luminance exceeds 0.30
CAMOUFLAGE_LIMIT = 0.5      # half of the corridor hides a note colour (or washes out the arrow)
EDGE_LIGHTNESS = 10.0       # L* step between neighbouring analysis pixels counted as an edge
BUSY_LIMIT = 0.30           # edge density in the corridor above this: busy background

# Palette.
DARK_LIGHTNESS = 12.0       # L* below this is neutral darkness, not a palette colour
PALETTE_DE = 15.0           # section median CIEDE2000 (kL = 2) to the nearest palette colour
PALETTE_K = 5
MIN_CLUSTER_SHARE = 0.05

# Visual change (mean per-pixel CIE76 difference; 2.3 is one just-noticeable difference).
CHANGE_LARGE = 20.0
CHANGE_STATIC = 2.3
ALIGN_TOLERANCE = 0.5
BOUNDARY_BEFORE = 4.0
BOUNDARY_AFTER = 2.0
REVIEW_PROBE_STEP = 0.5     # probe frames enter palette/corridor/change review at most every 0.5 s


# ---------- colour ----------

def linear(rgb) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luminance(lin) -> np.ndarray:
    return np.asarray(lin) @ np.array([0.2126, 0.7152, 0.0722])


def lab(rgb) -> np.ndarray:
    """sRGB uint8 (..., 3) to CIELAB (D65)."""
    xyz = linear(rgb) @ np.array([[0.4124564, 0.2126729, 0.0193339], [0.3575761, 0.7151522, 0.1191920],
                                  [0.1804375, 0.0721750, 0.9503041]])
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e00(lab1, lab2, k_l=1.0) -> np.ndarray:
    """CIEDE2000 colour difference (Sharma, Wu and Dalal 2005), broadcasting."""
    lab1, lab2 = np.asarray(lab1, dtype=np.float64), np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    c_bar = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_bar ** 7 / (c_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    zero = c1p * c2p == 0
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(zero, 0, dh)
    d_l, d_c = l2 - l1, c2p - c1p
    d_h = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    l_bar, cp_bar, h_sum = (l1 + l2) / 2, (c1p + c2p) / 2, h1p + h2p
    h_bar = np.where(zero, h_sum, np.where(np.abs(h1p - h2p) <= 180, h_sum / 2,
                                           np.where(h_sum < 360, (h_sum + 360) / 2, (h_sum - 360) / 2)))
    t = (1 - 0.17 * np.cos(np.radians(h_bar - 30)) + 0.24 * np.cos(np.radians(2 * h_bar))
         + 0.32 * np.cos(np.radians(3 * h_bar + 6)) - 0.20 * np.cos(np.radians(4 * h_bar - 63)))
    theta = 30 * np.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * np.sqrt(cp_bar ** 7 / (cp_bar ** 7 + 25.0 ** 7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    s_c, s_h = 1 + 0.045 * cp_bar, 1 + 0.015 * cp_bar * t
    r_t = -np.sin(np.radians(2 * theta)) * r_c
    return np.sqrt((d_l / (k_l * s_l)) ** 2 + (d_c / s_c) ** 2 + (d_h / s_h) ** 2 + r_t * (d_c / s_c) * (d_h / s_h))


def contrast_ratio(y1, y2):
    y1, y2 = np.asarray(y1, dtype=np.float64), np.asarray(y2, dtype=np.float64)
    return (np.maximum(y1, y2) + 0.05) / (np.minimum(y1, y2) + 0.05)


def parse_color(value) -> tuple[int, int, int]:
    """'#rrggbb', [r, g, b] (0-1 or 0-255) or {'r','g','b'} (Beat Saber style, 0-1)."""
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) not in (6, 8) or any(ch not in "0123456789abcdefABCDEF" for ch in text):
            raise ValueError(f"Colour {value!r} is not #rrggbb")
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    if isinstance(value, dict):
        value = [value.get("r"), value.get("g"), value.get("b")]
    if isinstance(value, (list, tuple)) and len(value) >= 3 and all(isinstance(v, (int, float)) for v in value[:3]):
        scale = 255 if max(value[:3]) <= 1 else 1
        return tuple(int(round(min(255, max(0, v * scale)))) for v in value[:3])
    raise ValueError(f"Colour {value!r} is not #rrggbb, [r, g, b] or {{r, g, b}}")


def to_hex(rgb) -> str:
    return "#" + "".join(f"{int(round(min(255, max(0, v)))):02x}" for v in rgb)


def lab_to_hex(value) -> str:
    l_, a, b = value
    fy = (l_ + 16) / 116
    f = np.array([fy + a / 500, fy, fy - b / 200])
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * np.array([0.95047, 1.0, 1.08883])
    lin = xyz @ np.array([[3.2404542, -0.9692660, 0.0556434], [-1.5371385, 1.8760108, -0.2040259],
                          [-0.4985314, 0.0415560, 1.0572252]])
    lin = np.clip(lin, 0, 1)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return to_hex(srgb * 255)


def kmeans(points: np.ndarray, k: int, iterations: int = 25, seed: int = 0):
    """Deterministic k-means++; returns (centers, shares) sorted by share, largest first."""
    points = np.asarray(points, dtype=np.float64)
    if len(points) == 0:
        return np.zeros((0, points.shape[-1])), np.zeros(0)
    k = min(k, len(np.unique(points.round(1), axis=0)))
    rng = np.random.default_rng(seed)
    centers = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        distance = np.min(((points[:, None] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        if distance.sum() == 0:
            break
        centers.append(points[rng.choice(len(points), p=distance / distance.sum())])
    centers = np.array(centers)
    for _ in range(iterations):
        labels = np.argmin(((points[:, None] - centers[None]) ** 2).sum(-1), axis=1)
        updated = np.array([points[labels == i].mean(0) if np.any(labels == i) else centers[i]
                            for i in range(len(centers))])
        if np.allclose(updated, centers):
            break
        centers = updated
    labels = np.argmin(((points[:, None] - centers[None]) ** 2).sum(-1), axis=1)
    shares = np.bincount(labels, minlength=len(centers)) / len(points)
    order = np.argsort(-shares)
    return centers[order], shares[order]


# ---------- inputs ----------

def _find_key(value, key, depth=0):
    if depth > 4 or not isinstance(value, dict):
        return None
    if value.get(key) is not None:
        return value[key]
    for nested in ("presentation", "selected", "concept"):
        found = _find_key(value.get(nested), key, depth + 1)
        if found is not None:
            return found
    treatments, selected = value.get("treatments"), value.get("selected_treatment", value.get("selected_id"))
    if isinstance(treatments, list):
        for item in treatments:
            if isinstance(item, dict) and (selected is None and item.get("selected") or
                                           selected is not None and item.get("id") == selected):
                return _find_key(item, key, depth + 1)
    return None


def concept_palette(concept=None, arrangement=None):
    """(palette hex list, source) from the concept, then the arrangement presentation; ([], None) if absent."""
    for source, value in (("concept", concept), ("arrangement", arrangement)):
        palette = _find_key(value, "palette")
        if isinstance(palette, dict):
            palette = palette.get("colors") or list(palette.values())
        if isinstance(palette, list) and palette:
            colours = []
            for item in palette:
                item = item.get("hex", item.get("color")) if isinstance(item, dict) and "r" not in item else item
                colours.append(to_hex(parse_color(item)))
            return colours, source
    return [], None


def note_colors(concept=None, arrangement=None) -> tuple[dict, str]:
    for source, value in (("arrangement", arrangement), ("concept", concept)):
        for key in ("note_colors", "colors", "color_scheme"):
            found = _find_key(value, key)
            if isinstance(found, dict):
                left = found.get("left", found.get("saberA", found.get("_colorLeft")))
                right = found.get("right", found.get("saberB", found.get("_colorRight")))
                if left is not None and right is not None:
                    return {"left": to_hex(parse_color(left)), "right": to_hex(parse_color(right))}, source
    return dict(DEFAULT_NOTE_COLORS), "default"


def concept_moments(concept, arrangement) -> list[float]:
    from .critique import beat_to_seconds
    times = []
    for item in _find_key(concept, "moments") or []:
        if not isinstance(item, dict):
            continue
        for key in ("song_time", "seconds", "time", "start_seconds"):
            if isinstance(item.get(key), (int, float)):
                times.append(float(item[key]))
                break
        else:
            beat = item.get("beat", item.get("start_beat"))
            if beat is not None and arrangement is not None:
                times.append(beat_to_seconds(float(Fraction(str(beat))), arrangement))
    return times


def parse_corridor(text) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(v) for v in str(text).split(","))
    except ValueError:
        values = ()
    if len(values) != 4 or not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
        raise ValueError(f"--corridor {text!r} must be x0,y0,x1,y1 in 0..1 with x0 < x1 and y0 < y1")
    return values


# ---------- per-frame features ----------

def _features(frame, corridor):
    rgb = load_rgb(frame["path"], ANALYSIS_WIDTH)
    lin = linear(rgb)
    y = luminance(lin)
    h, w = y.shape
    rows, cols = FLASH_GRID
    ys, xs = np.linspace(0, h, rows + 1).astype(int), np.linspace(0, w, cols + 1).astype(int)
    tiles_y, tiles_rgb = np.zeros(rows * cols), np.zeros((rows * cols, 3))
    for r in range(rows):
        for c in range(cols):
            block = lin[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            tiles_rgb[r * cols + c] = block.reshape(-1, 3).mean(0)
            tiles_y[r * cols + c] = y[ys[r]:ys[r + 1], xs[c]:xs[c + 1]].mean()
    small = np.asarray(rgb[::4, ::4])
    x0, y0, x1, y1 = corridor
    band = rgb[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
    return {"mean_luminance": float(y.mean()), "tiles_y": tiles_y, "tiles_rgb": tiles_rgb,
            "lab_small": lab(small), "corridor_rgb": band, "sample": rgb[::3, ::3].reshape(-1, 3)}


# ---------- 1. flashes ----------

def _dense_runs(frames):
    runs, current = [], [0]
    step = 1.25 / REQUIRED_FPS
    for i in range(1, len(frames)):
        if frames[i]["song_time"] - frames[i - 1]["song_time"] <= step:
            current.append(i)
        else:
            runs.append(current)
            current = [i]
    runs.append(current)
    return [r for r in runs if len(r) > 2 and frames[r[-1]]["song_time"] - frames[r[0]]["song_time"]
            >= MIN_DENSE_SECONDS - 1e-6]


def _tile_transitions(series, threshold, valid):
    """Per-tile turning-point transitions with hysteresis; returns [(frame_index, tile, +1/-1)]."""
    count, tiles = series.shape
    direction = np.zeros(tiles, dtype=int)
    ref, ref_index = series[0].copy(), np.zeros(tiles, dtype=int)
    low, low_index = series[0].copy(), np.zeros(tiles, dtype=int)
    high, high_index = series[0].copy(), np.zeros(tiles, dtype=int)
    events = []
    for t in range(1, count):
        x = series[t]
        for tile in range(tiles):
            value, d = x[tile], direction[tile]
            if d == 0:
                if value - low[tile] >= threshold and valid(low_index[tile], t, tile):
                    events.append((t, tile, 1)); direction[tile], ref[tile], ref_index[tile] = 1, value, t
                elif high[tile] - value >= threshold and valid(high_index[tile], t, tile):
                    events.append((t, tile, -1)); direction[tile], ref[tile], ref_index[tile] = -1, value, t
                else:
                    if value < low[tile]:
                        low[tile], low_index[tile] = value, t
                    if value > high[tile]:
                        high[tile], high_index[tile] = value, t
            elif d == 1:
                if ref[tile] - value >= threshold and valid(ref_index[tile], t, tile):
                    events.append((t, tile, -1)); direction[tile], ref[tile], ref_index[tile] = -1, value, t
                elif value > ref[tile]:
                    ref[tile], ref_index[tile] = value, t
            else:
                if value - ref[tile] >= threshold and valid(ref_index[tile], t, tile):
                    events.append((t, tile, 1)); direction[tile], ref[tile], ref_index[tile] = 1, value, t
                elif value < ref[tile]:
                    ref[tile], ref_index[tile] = value, t
    return events


def _area_events(events, count, tiles, area):
    """Frame-level transitions: concurrent same-direction tile transitions covering >= area of the frame."""
    by_frame = {}
    for t, tile, d in events:
        by_frame.setdefault(t, []).append((tile, d))
    result, pending = [], {1: {}, -1: {}}
    for t in range(count):
        for tile, d in by_frame.get(t, []):
            pending[d][tile] = t
        for d in (1, -1):
            pending[d] = {tile: at for tile, at in pending[d].items() if t - at <= FLASH_MERGE_FRAMES}
            if len(pending[d]) / tiles >= area:
                result.append((t, d, len(pending[d]) / tiles))
                pending[d] = {}
    alternating = []
    for item in result:  # a same-direction repeat is one transition, not two
        if not alternating or alternating[-1][1] != item[1]:
            alternating.append(item)
    return alternating


def _max_rate(times):
    """(max transitions in any 1 s window, window start index, end index)."""
    best = (0, 0, 0)
    end = 0
    for start in range(len(times)):
        while end < len(times) and times[end] < times[start] + 1.0 - 1e-9:
            end += 1
        best = max(best, (end - start, start, end), key=lambda b: b[0])
    return best


def _flash_analysis(frames, features, area):
    runs, windows, findings = _dense_runs(frames), [], []
    for run in runs:
        items = [frames[i] for i in run]
        tiles_y = np.array([features[i]["tiles_y"] for i in run])
        tiles_rgb = np.array([features[i]["tiles_rgb"] for i in run])
        tiles = tiles_y.shape[1]
        general = _tile_transitions(tiles_y, FLASH_DELTA,
                                    lambda a, b, tile: min(tiles_y[a, tile], tiles_y[b, tile]) < FLASH_DARK_MAX)
        total = tiles_rgb.sum(-1)
        saturated = np.where(total > 0, tiles_rgb[..., 0] / np.maximum(total, 1e-9), 0) >= RED_SATURATION
        redness = np.maximum(0, tiles_rgb[..., 0] - tiles_rgb[..., 1] - tiles_rgb[..., 2]) * 320
        red = _tile_transitions(redness, RED_DELTA + 1e-9,
                                lambda a, b, tile: bool(saturated[a, tile] or saturated[b, tile]))
        duration = items[-1]["song_time"] - items[0]["song_time"]
        window = {"start": items[0]["song_time"], "end": items[-1]["song_time"], "frames": len(items),
                  "fps": round((len(items) - 1) / duration, 2) if duration > 0 else None}
        for kind, transitions in (("general", general), ("red", red)):
            events = _area_events(transitions, len(items), tiles, area)
            times = [items[t]["song_time"] for t, _, _ in events]
            count, first, last = _max_rate(times)
            rate = count / 2
            window[f"max_{kind}_flashes_per_second"] = rate
            window[f"{kind}_transitions"] = len(events)
            if rate >= FLASH_WARN:
                hit = [items[events[i][0]] for i in range(first, last)]
                frames_hit = [f["file"] for f in hit]
                code = ("flash_rate_exceeded" if rate > FLASH_LIMIT else "flash_rate_high")
                code = ("red_" + code) if kind == "red" else code
                what = "saturated-red flashes" if kind == "red" else "flashes"
                limit = ("exceeds the hard limit of 3 per second (WCAG 2.2 SC 2.3.1, ITU-R BT.1702); this blocks "
                         "handover" if rate > FLASH_LIMIT else
                         "is within the 3 per second limit but leaves little margin")
                findings.append(_finding(
                    "error" if rate > FLASH_LIMIT else "warning", code, hit[0]["section_id"], rate, FLASH_LIMIT,
                    f"{rate:g} {what} in 1 s from {format_time(hit[0]['song_time'])} "
                    f"({len(hit)} opposing luminance transitions over >= {area:.0%} of the frame) {limit}. Fix: "
                    "strobe at most every other beat (under 3 Hz), keep the pulse amplitude under 10% of full "
                    "luminance or keep the darker state above 0.8, or confine the flashing to under a quarter of "
                    "the view" + (", and avoid saturated red for pulsing elements" if kind == "red" else "") + ".",
                    time=hit[0]["song_time"], frames=frames_hit))
        windows.append(window)
    fps = [1 / (b["song_time"] - a["song_time"]) for a, b in zip(frames, frames[1:])
           if b["song_time"] > a["song_time"]]
    if not runs:
        findings.append(_finding(
            "info", "flash_check_insufficient_sampling", None, round(max(fps), 2) if fps else 0, REQUIRED_FPS,
            f"No run of frames at >= {REQUIRED_FPS:g} fps lasting >= {MIN_DENSE_SECONDS:g} s, so photosensitive "
            "flashes were not checked (sparse frames alias strobes). Fix: capture a dense probe over the brightest "
            f"or fastest-pulsing passages (e.g. {REQUIRED_FPS:g}-30 fps for 2-4 s, reason 'probe') and rerun."))
    return {"checked": bool(runs), "required_fps": REQUIRED_FPS, "area_fraction": area, "windows": windows,
            "checked_seconds": round(sum(w["end"] - w["start"] for w in windows), 3)}, findings


# ---------- 2. note corridor ----------

def _corridor(feature, colours):
    rgb = feature["corridor_rgb"].reshape(-1, 3)
    pixels_lab = lab(rgb)
    y = luminance(linear(rgb))
    median_y = float(np.median(y))
    result = {"median_luminance": round(median_y, 4), "body_camouflage": {}, "median_contrast": {}}
    for side, hex_value in colours.items():
        rgb_c = np.array(parse_color(hex_value))
        y_c, lab_c = float(luminance(linear(rgb_c))), lab(rgb_c)
        hidden = (contrast_ratio(y_c, y) < NON_TEXT_CONTRAST) & (delta_e00(lab_c, pixels_lab) < NOTE_HUE_DE)
        result["body_camouflage"][side] = round(float(hidden.mean()), 4)
        result["median_contrast"][side] = round(float(contrast_ratio(y_c, median_y)), 3)
    result["arrow_washout"] = round(float((y > ARROW_LUMINANCE).mean()), 4)
    band = feature["corridor_rgb"]
    lightness = lab(band)[..., 0]
    edges = np.zeros(lightness.shape, dtype=bool)
    edges[:, 1:] |= np.abs(np.diff(lightness, axis=1)) > EDGE_LIGHTNESS
    edges[1:, :] |= np.abs(np.diff(lightness, axis=0)) > EDGE_LIGHTNESS
    result["edge_density"] = round(float(edges.mean()), 4)
    reasons = [f"{side} note colour {colours[side]} blends into {value:.0%} of the corridor"
               for side, value in result["body_camouflage"].items() if value >= CAMOUFLAGE_LIMIT]
    if result["arrow_washout"] >= CAMOUFLAGE_LIMIT:
        reasons.append(f"{result['arrow_washout']:.0%} of the corridor is brighter than luminance "
                       f"{ARROW_LUMINANCE} and washes out the white arrows")
    if result["edge_density"] >= BUSY_LIMIT:
        reasons.append(f"busy background: {result['edge_density']:.0%} of corridor pixels are edges")
    result["score"] = max([*result["body_camouflage"].values(), result["arrow_washout"],
                           result["edge_density"] * CAMOUFLAGE_LIMIT / BUSY_LIMIT])
    result["reasons"] = reasons
    return result


def _corridor_findings(frames, review, corridors, corridor, colours):
    findings, current = [], None
    for index in review:
        item = corridors.get(index)
        if item and item["reasons"]:
            section = frames[index]["section_id"]
            if current and current["section_id"] == section:
                current["frames"].append(index)
                continue
            current = {"section_id": section, "frames": [index]}
            findings.append(current)
        else:
            current = None
    result = []
    for group in findings:
        hit = [frames[i] for i in group["frames"]]
        worst = max(group["frames"], key=lambda i: corridors[i]["score"])
        reasons = corridors[worst]["reasons"]
        result.append(_finding(
            "warning", "note_contrast_low", group["section_id"], round(corridors[worst]["score"], 3),
            CAMOUFLAGE_LIMIT,
            f"Notes are hard to read against the background in the note corridor (screen x {corridor[0]:g}-"
            f"{corridor[2]:g}, y {corridor[1]:g}-{corridor[3]:g}) in {len(hit)} frame(s) from "
            f"{format_time(hit[0]['song_time'])} to {format_time(hit[-1]['song_time'])}: {'; '.join(reasons)}. "
            "Fix: darken or desaturate what sits behind the note lanes (lower the look's intensity there, add "
            "a vignette toward the centre), move bright or detailed scene elements out of the corridor, or pick "
            "note colours that differ in hue and lightness from the scene.",
            time=hit[0]["song_time"], frames=[f["file"] for f in hit]))
    return result


# ---------- 3. palette ----------

def _dominant(sample_rgb, k=PALETTE_K):
    points = lab(sample_rgb)
    dark = points[:, 0] < DARK_LIGHTNESS
    lit = points[~dark]
    centers, shares = kmeans(lit, k) if len(lit) >= max(10, 0.05 * len(points)) else (np.zeros((0, 3)), [])
    keep = [(c, s) for c, s in zip(centers, shares) if s >= MIN_CLUSTER_SHARE]
    return keep, float(dark.mean())


def _drift(keep, palette_lab):
    if not keep or len(palette_lab) == 0:
        return None, []
    rows = []
    for center, share in keep:
        distance = delta_e00(center[None], palette_lab, k_l=2.0)
        nearest = int(np.argmin(distance))
        rows.append((float(distance[nearest]), float(share), lab_to_hex(center), nearest))
    order = sorted(rows)
    total, acc, median = sum(r[1] for r in rows), 0.0, order[-1][0]
    for row in order:  # share-weighted median
        acc += row[1]
        if acc >= total / 2:
            median = row[0]
            break
    return median, rows


def _palette_analysis(frames, review, features, palette):
    palette_lab = lab(np.array([parse_color(c) for c in palette])) if palette else np.zeros((0, 3))
    sections, findings, order = {}, [], []
    for index in review:
        key = frames[index]["section_id"]
        if key not in sections:
            sections[key] = []
            order.append(key)
        sections[key].append(index)
    report = {}
    for key in order:
        indices = sections[key]
        rng = np.random.default_rng(0)
        pool = np.concatenate([features[i]["sample"] for i in indices])
        if len(pool) > 6000:
            pool = pool[rng.choice(len(pool), 6000, replace=False)]
        keep, dark = _dominant(pool)
        entry = {"frames": len(indices), "dark_share": round(dark, 3),
                 "observed": [{"hex": lab_to_hex(c), "share": round(float(s), 3)} for c, s in keep]}
        median, rows = _drift(keep, palette_lab)
        if median is not None:
            entry["median_delta_e"] = round(median, 2)
            off = [{"hex": hexv, "share": round(share, 3), "delta_e": round(d, 1), "nearest": palette[n]}
                   for d, share, hexv, n in rows if d > PALETTE_DE and share >= 0.1]
            entry["off_palette"] = off
            if median > PALETTE_DE:
                drifting = []
                for i in indices:
                    frame_median, _ = _drift(_dominant(features[i]["sample"], 4)[0], palette_lab)
                    if frame_median is not None and frame_median > PALETTE_DE:
                        drifting.append(frames[i])
                drifting = drifting or [frames[i] for i in indices]
                colours = ", ".join(f"{o['hex']} ({o['share']:.0%}, nearest {o['nearest']} dE {o['delta_e']})"
                                    for o in off) or "mixed shades"
                findings.append(_finding(
                    "warning", "palette_drift", key, round(median, 2), PALETTE_DE,
                    f"Section {key}: the lit colours drift from the concept palette (median CIEDE2000 "
                    f"{median:.1f} > {PALETTE_DE:g}); off-palette: {colours}. Fix: retint the look/scene "
                    f"materials of this section toward {', '.join(palette)}, or update the concept palette if "
                    "the change is intended.", time=drifting[0]["song_time"], frames=[f["file"] for f in drifting]))
        elif not palette:
            findings.append(_finding(
                "info", "palette_observed", key, len(keep), None,
                f"Section {key} observed palette (no concept palette to compare): "
                + (", ".join(f"{o['hex']} {o['share']:.0%}" for o in entry["observed"]) or "almost all dark")
                + f"; {dark:.0%} of pixels are near-black.", time=frames[indices[0]]["song_time"],
                frames=[frames[i]["file"] for i in indices]))
        report[str(key)] = entry
    return report, findings


# ---------- 4. visual change ----------

def change_score(a, b) -> float:
    """Mean per-pixel CIE76 difference between two analysis frames."""
    return float(np.sqrt(((a - b) ** 2).sum(-1)).mean())


def _boundaries(frames, arrangement):
    if arrangement is not None:
        spans = section_spans(arrangement)
        return [(s["start_seconds"], s["id"]) for s in spans[1:]] + (
            [(spans[0]["start_seconds"], spans[0]["id"])] if spans and spans[0]["start_seconds"] > 0 else [])
    result = []
    for previous, frame in zip(frames, frames[1:]):
        if frame["section_id"] is not None and frame["section_id"] != previous["section_id"]:
            result.append((frame["song_time"], frame["section_id"]))
    return result


def _change_analysis(frames, review, features, arrangement, moments):
    boundaries = sorted(_boundaries(frames, arrangement))
    markers = [b[0] for b in boundaries] + moments + [f["song_time"] for f in frames if f["reason"] == "moment"]
    pairs, findings = [], []
    for a, b in zip(review, review[1:]):
        score = change_score(features[a]["lab_small"], features[b]["lab_small"])
        ta, tb = frames[a]["song_time"], frames[b]["song_time"]
        aligned = any(ta - ALIGN_TOLERANCE <= m <= tb + ALIGN_TOLERANCE for m in markers)
        pairs.append({"from": frames[a]["file"], "to": frames[b]["file"], "start": ta, "end": tb,
                      "score": round(score, 2), "aligned": aligned})
        if score >= CHANGE_LARGE and not aligned:
            findings.append(_finding(
                "info", "visual_change_unaligned", frames[b]["section_id"], round(score, 2), CHANGE_LARGE,
                f"Large visual change (mean dE {score:.1f}) between {format_time(ta)} and {format_time(tb)} with no "
                f"section boundary or moment within {ALIGN_TOLERANCE:g} s. Fix: if no sound drives it, move the "
                "change onto the nearest boundary or audio moment; if a sound does, record that moment in the "
                "concept so it is intended.", time=tb, frames=[frames[a]["file"], frames[b]["file"]]))
    report, unsampled = [], []
    for at, section in boundaries:
        before = [i for i in review if at - BOUNDARY_BEFORE <= frames[i]["song_time"] < at - 0.02]
        after = [i for i in review if at - 0.02 <= frames[i]["song_time"] <= at + BOUNDARY_AFTER]
        if not before or not after:
            unsampled.append(section)
            report.append({"section_id": section, "time": round(at, 3), "sampled": False})
            continue
        score = max(change_score(features[before[-1]]["lab_small"], features[i]["lab_small"]) for i in after)
        report.append({"section_id": section, "time": round(at, 3), "sampled": True, "score": round(score, 2)})
        if score < CHANGE_STATIC:
            findings.append(_finding(
                "warning", "section_boundary_static", section, round(score, 2), CHANGE_STATIC,
                f"Section {section} starts at {format_time(at)} with no visible change (mean dE {score:.2f}, below "
                f"one just-noticeable difference {CHANGE_STATIC}). Fix: mark the boundary with a look, scene or "
                "environment change (colour, intensity or a new element) unless continuity is the intent.",
                time=at, frames=[frames[before[-1]]["file"]] + [frames[i]["file"] for i in after]))
    if unsampled:
        findings.append(_finding(
            "info", "section_boundary_unsampled", None, len(unsampled), None,
            f"{len(unsampled)} section boundar{'y' if len(unsampled) == 1 else 'ies'} "
            f"({', '.join(map(str, unsampled[:8]))}) lack a frame within {BOUNDARY_BEFORE:g} s before and "
            f"{BOUNDARY_AFTER:g} s after, so boundary changes were not checked there. Fix: include section "
            "boundaries in `game capture` times."))
    return {"pairs": pairs, "boundaries": report}, findings


# ---------- orchestration ----------

def _finding(severity, code, section_id, value, threshold, message, *, time=None, frames=None):
    finding = {"severity": severity, "code": code, "section_id": section_id, "object_ids": [],
               "value": value, "threshold": threshold, "message": message}
    if time is not None:
        finding["time"] = round(float(time), 3)
    if frames is not None:
        finding["frames"] = list(frames)
    return finding


def _review_indices(frames):
    review, last_probe = [], None
    for i, frame in enumerate(frames):
        if frame["reason"] != "probe":
            review.append(i)
        elif last_probe is None or frame["song_time"] - last_probe >= REVIEW_PROBE_STEP - 1e-9:
            review.append(i)
            last_probe = frame["song_time"]
    return review


def analyze_frames(capture_dir, arrangement: dict | None = None, concept: dict | None = None, *,
                   corridor=None, colors: dict | None = None, flash_area: float = FLASH_AREA) -> dict:
    """Compute every frame metric; returns {capture, metrics, findings, summary}."""
    capture = load_capture(capture_dir, arrangement)
    frames = capture["frames"]
    corridor = tuple(corridor or DEFAULT_CORRIDOR)
    features = [_features(f, corridor) for f in frames]
    review = _review_indices(frames)
    findings = []
    if arrangement is not None and capture["revision"]:
        from .revisions import arrangement_revision
        current = arrangement_revision(arrangement)
        if current != capture["revision"]:
            findings.append(_finding(
                "warning", "capture_revision_stale", None, capture["revision"], current,
                f"Frames were captured from revision {capture['revision'][:12]} but the arrangement is at "
                f"{current[:12]}; findings may not describe the current map. Fix: rerun `game capture`."))
    flash, found = _flash_analysis(frames, features, flash_area)
    findings += found
    colours, colour_source = (dict(colors), "argument") if colors else note_colors(concept, arrangement)
    corridors = {}
    camera = capture["camera"]
    if camera in (None, "player"):
        corridors = {i: _corridor(features[i], colours) for i in review}
        findings += _corridor_findings(frames, review, corridors, corridor, colours)
    palette, palette_source = concept_palette(concept, arrangement)
    palette_report, found = _palette_analysis(frames, review, features, palette)
    findings += found
    changes, found = _change_analysis(frames, review, features, arrangement, concept_moments(concept, arrangement))
    findings += found
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f.get("time", -1)))
    metrics = {
        "flash": flash,
        "corridor": {"rect": list(corridor), "camera": camera or "unknown (assumed player)",
                     "note_colors": colours, "note_colors_source": colour_source,
                     "checked": bool(corridors),
                     "frames": {frames[i]["file"]: {k: v for k, v in item.items() if k != "reasons"}
                                for i, item in corridors.items()}},
        "palette": {"palette": palette, "source": palette_source, "sections": palette_report},
        "changes": changes,
        "per_frame": [{"file": frames[i]["file"], "song_time": frames[i]["song_time"],
                       "section_id": frames[i]["section_id"],
                       "mean_luminance": round(features[i]["mean_luminance"], 4)} for i in review]}
    counts = {level: sum(1 for f in findings if f["severity"] == level) for level in order}
    return {"capture": {k: capture[k] for k in ("directory", "manifest", "project", "revision", "difficulty",
                                                  "camera", "width", "height", "game_version")}
            | {"frame_count": len(frames), "probe_frames": sum(f["reason"] == "probe" for f in frames),
               "warnings": capture["warnings"]},
            "metrics": metrics, "findings": findings,
            "summary": {**counts, "blocking": counts["error"] > 0,
                        "note": "2D captures show the rendered picture only; they do not establish VR comfort, "
                                "scale or performance."}}


def frame_findings(capture_dir, arrangement=None, concept=None) -> list[dict]:
    """Critique-shaped findings for a capture directory (for `project critique` integration)."""
    return analyze_frames(capture_dir, arrangement, concept)["findings"]


def section_summary(capture_dir, arrangement: dict | None = None, concept: dict | None = None, **options) -> dict:
    """Per-section stats: luminance, corridor contrast, dominant palette, change and flash rate."""
    result = analyze_frames(capture_dir, arrangement, concept, **options)
    metrics = result["metrics"]
    capture = load_capture(capture_dir, arrangement)
    frames = capture["frames"]
    sections, order = {}, []
    for frame in frames:
        key = frame["section_id"]
        if key not in sections:
            sections[key] = []
            order.append(key)
        sections[key].append(frame)
    luminance_by_file = {row["file"]: row["mean_luminance"] for row in metrics["per_frame"]}
    corridor = metrics["corridor"]["frames"]
    rows = []
    for key in order:
        items = sections[key]
        files = {f["file"] for f in items}
        lum = [luminance_by_file[f] for f in files if f in luminance_by_file]
        cor = [corridor[f] for f in files if f in corridor]
        scores = [p["score"] for p in metrics["changes"]["pairs"] if p["to"] in files]
        flashes = [max(w["max_general_flashes_per_second"], w["max_red_flashes_per_second"])
                   for w in metrics["flash"]["windows"]
                   if items[0]["song_time"] - 1 <= w["start"] <= items[-1]["song_time"]]
        palette = metrics["palette"]["sections"].get(str(key), {})
        rows.append({"section_id": key, "frames": len(items),
                     "start_time": items[0]["song_time"], "end_time": items[-1]["song_time"],
                     "mean_luminance": round(float(np.mean(lum)), 4) if lum else None,
                     "corridor_median_luminance": round(float(np.median([c["median_luminance"] for c in cor])), 4)
                     if cor else None,
                     "corridor_min_contrast": round(min(min(c["median_contrast"].values()) for c in cor), 3)
                     if cor else None,
                     "corridor_edge_density": round(float(np.mean([c["edge_density"] for c in cor])), 4)
                     if cor else None,
                     "dominant_palette": palette.get("observed", []), "dark_share": palette.get("dark_share"),
                     "palette_median_delta_e": palette.get("median_delta_e"),
                     "mean_change": round(float(np.mean(scores)), 2) if scores else None,
                     "max_change": round(float(max(scores)), 2) if scores else None,
                     "max_flashes_per_second": max(flashes) if flashes else None,
                     "findings": [f["code"] for f in result["findings"] if f["section_id"] == key]})
    return {"capture": result["capture"], "sections": rows, "summary": result["summary"],
            "log_diagnostics": capture["log_diagnostics"]}


def load_concept(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read concept {path}: {exc}") from None
