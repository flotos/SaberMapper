"""Compare an arrangement's intensity with the player's star tiers.

The corpus reference (``corpus analyze`` -> tier-reference.json) holds, per tier,
statistics of 4-beat windows cut from real charts of that star range. The map is
cut into the same windows by the same extractor, so both sides are measured
alike. The closest tier is a descriptive comparison, never a predicted rating.
"""
from __future__ import annotations

import math
from statistics import median

from .arrangement import expanded_notes, beat_fraction
from .patterns import extract_patterns

WINDOW_BEATS = 4
FEATURES = ("median_window_nps", "p90_window_nps", "median_swings_per_second", "median_peak_one_second_swings")
FLOOR = 0.1

DEFINITIONS = {
    "tier_fit": "The map is cut into 4-beat windows exactly as corpus phrases are. Four features (median and 90th-percentile "
                "window notes per second, median swings per second, median peak swings within one second) are compared "
                "with each star tier's reference windows; the closest tier minimises the summed absolute log ratio.",
    "tier_below_target": "difficulty.target_tier is set and the closest reference tier (tier_fit) is an easier one: the map "
                         "plays below the level it aims for. Raise density and movement where the audio supports it.",
    "tier_above_target": "difficulty.target_tier is set and the closest reference tier (tier_fit) is a harder one.",
    "tier_reference_missing": "difficulty.target_tier is set but no tier reference was supplied; run `corpus analyze` "
                              "to write workspace/corpus/tier-reference.json.",
}


def _quantile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def map_windows(arrangement: dict) -> list[dict]:
    """4-beat windows of the arrangement with the corpus phrase metrics."""
    notes = [{"id": n["id"], "beat": float(n["beat"]), "x": n["x"], "y": n["y"], "color": n["color"],
              "direction": n["direction"]} for n in expanded_notes(arrangement)]
    return extract_patterns({"notes": notes, "bpm": float(arrangement["song"]["bpm"])}, version_hash="arrangement",
                            difficulty=arrangement["difficulty"]["name"], window_beats=WINDOW_BEATS)


def features(windows: list[dict]) -> dict:
    nps = [w["nps"] for w in windows]
    swings = [(w.get("movement_metrics") or {}).get("swing_rate_per_second") for w in windows]
    peaks = [(w.get("movement_metrics") or {}).get("peak_one_second_swing_count") for w in windows]
    swings = [v for v in swings if isinstance(v, (int, float))]
    peaks = [v for v in peaks if isinstance(v, (int, float))]
    return {"median_window_nps": round(median(nps), 4) if nps else 0.0,
            "p90_window_nps": round(_quantile(nps, 0.9), 4) if nps else 0.0,
            "median_swings_per_second": round(median(swings), 4) if swings else 0.0,
            "median_peak_one_second_swings": round(median(peaks), 4) if peaks else 0.0}


def reference_features(tier: dict) -> dict:
    movement = tier.get("window_movement", {})
    return {"median_window_nps": tier.get("window_nps", {}).get("median"),
            "p90_window_nps": tier.get("window_nps", {}).get("p90"),
            "median_swings_per_second": movement.get("swing_rate_per_second", {}).get("median"),
            "median_peak_one_second_swings": movement.get("peak_one_second_swing_count", {}).get("median")}


def distance(left: dict, right: dict) -> float:
    return round(sum(abs(math.log(max(left[k], FLOOR) / max(right[k], FLOOR))) for k in FEATURES), 4)


def missing_reference_warning(arrangement: dict) -> dict | None:
    """The tier_reference_missing warning a critique command adds when it has no reference to pass."""
    target = arrangement.get("difficulty", {}).get("target_tier")
    if target is None:
        return None
    return {"severity": "warning", "code": "tier_reference_missing", "section_id": None, "object_ids": [],
            "value": None, "threshold": None,
            "message": f"difficulty.target_tier is {target} but no tier reference was found; run `corpus analyze` "
                       "so critique can compare the map with real charts of that tier."}


def tier_fit(arrangement: dict, reference: dict | None, warn) -> dict:
    target = arrangement.get("difficulty", {}).get("target_tier")
    if target is None:
        return {"checked": False, "reason": "difficulty.target_tier is not set"}
    if reference is None:  # internal callers (repairs) never pass one; the critique commands report it missing
        return {"checked": False, "target_tier": target, "reason": "no tier reference"}
    tiers = [t for t in reference["tiers"] if t.get("windows") and all(reference_features(t)[k] is not None for k in FEATURES)]
    order = [t["id"] for t in reference["tiers"]]
    if target not in [t["id"] for t in tiers]:
        return {"checked": False, "target_tier": target, "reason": "the tier reference has no windows for the target tier"}
    windows = map_windows(arrangement)
    if not windows:
        return {"checked": False, "target_tier": target, "reason": "the map has no notes"}
    mine = features(windows)
    rows = [{"id": t["id"], "label": t.get("label"), "features": reference_features(t),
             "distance": distance(mine, reference_features(t))} for t in tiers]
    closest = min(rows, key=lambda row: row["distance"])["id"]
    target_row = next(t for t in tiers if t["id"] == target)
    target_nps = reference_features(target_row)["median_window_nps"]
    easier = [t for t in tiers if order.index(t["id"]) < order.index(target)]
    # A section sits below the target when its median window is nearer the next easier tier than the target.
    floor = (math.sqrt(target_nps * reference_features(easier[-1])["median_window_nps"]) if easier else target_nps / 2)
    bpm = float(arrangement["song"]["bpm"])
    sections = []
    for section in arrangement["sections"]:
        start = float(beat_fraction(section["start_beat"]))
        end = start + float(beat_fraction(section["length_beats"]))
        inside = [w for w in windows if start <= w["start_beat"] < end]
        if not inside:
            continue
        values = features(inside)
        sections.append({"section_id": section["id"], "start_beat": start, "end_beat": end, "windows": len(inside),
                         **values, "below_target": values["median_window_nps"] < floor})
    result = {"checked": True, "target_tier": target, "target_label": target_row.get("label"), "closest_tier": closest,
              "window_count": len(windows), "map": mine, "tiers": rows, "section_floor_window_nps": round(floor, 4),
              "sections": sections, "note": "Descriptive comparison with real charts of each tier; not a star rating. "
                                             "Quiet passages stay light: audio evidence outranks the tier."}
    step = order.index(closest) - order.index(target)
    if step:
        low = [s["section_id"] for s in sections if s["below_target"]]
        code = "tier_below_target" if step < 0 else "tier_above_target"
        warn(code, f"Target tier {target} ({target_row.get('label')}) but the map's windows are closest to {closest}: "
             f"median {mine['median_window_nps']:g} nps and {mine['median_swings_per_second']:g} swings/s against "
             f"{target_nps:g} nps and {reference_features(target_row)['median_swings_per_second']:g} swings/s for the "
             f"target at {bpm:g} BPM." + (f" Sections under {floor:.2f} median window nps: {', '.join(low)}." if low and step < 0 else ""),
             value=distance(mine, reference_features(target_row)), threshold=min(r["distance"] for r in rows))
    return result
