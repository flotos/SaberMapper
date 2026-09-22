"""Contextual phrase extraction, transparent grouping, and deterministic retrieval."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math


def _signature(notes: list[dict], *, mirror: bool = False) -> tuple:
    first = min(float(n["beat"]) for n in notes)
    return tuple(sorted((round(float(n["beat"]) - first, 5),
                         3 - int(n["x"]) if mirror else int(n["x"]), int(n["y"]),
                         1 - int(n["color"]) if mirror else int(n["color"]),
                         {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6}.get(int(n["direction"]), int(n["direction"]))
                         if mirror else int(n["direction"])) for n in notes))


def _family_key(notes: list[dict]) -> str:
    shape = min(_signature(notes), _signature(notes, mirror=True))
    return hashlib.sha256(json.dumps(shape, separators=(",", ":")).encode()).hexdigest()[:16]


def extract_patterns(map_ir: dict, *, version_hash: str, difficulty: str,
                     song_family_id: str | None = None,
                     window_beats: float = 4, stride_beats: float | None = None,
                     context_beats: float = 1, min_notes: int = 2) -> list[dict]:
    """Extract complete beat windows with neighboring note and movement context."""
    if window_beats <= 0 or context_beats < 0 or (stride_beats is not None and stride_beats <= 0):
        raise ValueError("invalid extraction window")
    stride = stride_beats or window_beats
    notes = sorted(map_ir.get("notes", []), key=lambda n: (float(n["beat"]), n.get("id", "")))
    if not notes:
        return []
    bpm = float(map_ir.get("bpm", (map_ir.get("tempo_events") or [{"bpm": 120}])[0]["bpm"]))
    if bpm <= 0:
        raise ValueError("BPM must be positive")
    movement_model_version = None
    try:
        from .movement import analyze_movement
        movement_model_version = analyze_movement([], bpm=bpm).get("model_version")
    except ImportError:
        pass
    end = max(float(n["beat"]) for n in notes)
    out = []
    start = math.floor(float(notes[0]["beat"]) / stride) * stride
    while start <= end:
        center = [n for n in notes if start <= float(n["beat"]) < start + window_beats]
        if len(center) >= min_notes:
            before = [n for n in notes if start - context_beats <= float(n["beat"]) < start]
            after = [n for n in notes if start + window_beats <= float(n["beat"]) < start + window_beats + context_beats]
            local_movement = analyze_movement(before + center + after, bpm=bpm) if movement_model_version else None
            context_start = start - context_beats
            context_end = start + window_beats + context_beats
            motion_context = {}
            for collection in ("arcs", "chains", "bombs", "obstacles"):
                count = 0
                for item in map_ir.get(collection, []):
                    begin = float(item.get("beat", -1))
                    finish = float(item.get("tail_beat", begin + item.get("duration_beats", 0)))
                    if begin < context_end and finish >= context_start:
                        count += 1
                motion_context[collection] = count
            motion_warnings = local_movement.get("warnings", []) if local_movement else []
            intervals = [round(float(b["beat"]) - float(a["beat"]), 5) for a, b in zip(center, center[1:])]
            active = max(float(center[-1]["beat"]) - float(center[0]["beat"]), 0.5)
            pid = f"{version_hash.upper()}:{difficulty}:{start:g}:{window_beats:g}"
            out.append({"schema_version": "1.0", "id": pid, "source": map_ir.get("source"),
                        "version_hash": version_hash.upper(), "song_family_id": song_family_id or f"version:{version_hash.upper()}",
                        "difficulty": difficulty,
                        "start_beat": start, "length_beats": window_beats, "bpm": bpm,
                        "notes": center, "entry_notes": before[-2:], "exit_notes": after[:2],
                        "rhythm_intervals": intervals, "note_count": len(center),
                        "nps": round(len(center) * bpm / (60 * window_beats), 4),
                        "active_nps": round(len(center) * bpm / (60 * active), 4),
                        "family_key": _family_key(center), "motif_family_id": _family_key(center),
                        "movement_model_version": movement_model_version,
                        "movement_metrics": local_movement.get("metrics") if local_movement else None,
                        "motion_context": motion_context,
                        "movement_warnings": motion_warnings,
                        "unsupported_motion": bool(any(motion_context.values()) or motion_warnings),
                        "entry_hand_state": {str(color): next((n["id"] for n in reversed(before) if n["color"] == color), None)
                                             for color in (0, 1)},
                        "exit_hand_state": {str(color): next((n["id"] for n in after if n["color"] == color), None)
                                            for color in (0, 1)}})
        start += stride
    return out


def group_patterns(patterns: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for pattern in patterns:
        groups[pattern["family_key"]].append(pattern)
    return [{"family_key": key, "count": len(items),
             "source_versions": sorted({x["version_hash"] for x in items}),
             "occurrences": [x["id"] for x in items],
             "exemplar": items[0]["id"]} for key, items in sorted(groups.items())]


def repetition_report(patterns: list[dict]) -> dict:
    by_source = defaultdict(list)
    for p in patterns:
        by_source[p["version_hash"]].append(p)
    return {key: {"windows": len(items), "families": len({p["family_key"] for p in items}),
                  "repeated_windows": sum(c - 1 for c in Counter(p["family_key"] for p in items).values() if c > 1)}
            for key, items in sorted(by_source.items())}


def pattern_distance(left: dict, right: dict) -> dict:
    """Transparent symmetric rhythm and movement distance, without quality claims."""
    a = _signature(left["notes"])
    b = _signature(right["notes"])
    if not a or not b:
        raise ValueError("patterns require notes")
    def compare(seq_a, seq_b):
        paired = min(len(seq_a), len(seq_b))
        rhythm = sum(abs(seq_a[i][0] - seq_b[i][0]) for i in range(paired)) / paired
        placement = sum(abs(seq_a[i][1] - seq_b[i][1]) + abs(seq_a[i][2] - seq_b[i][2])
                        for i in range(paired)) / paired
        hand = sum(seq_a[i][3] != seq_b[i][3] for i in range(paired)) / paired
        direction = sum(seq_a[i][4] != seq_b[i][4] for i in range(paired)) / paired
        count = abs(len(seq_a) - len(seq_b))
        return {"rhythm": rhythm, "placement": placement, "hand": hand,
                "direction": direction, "count": count,
                "total": rhythm + .25 * placement + hand + .5 * direction + count}
    direct = compare(a, b)
    mirrored = compare(a, _signature(right["notes"], mirror=True))
    result = mirrored if mirrored["total"] < direct["total"] else direct
    return {"transform": "mirror" if result is mirrored else "direct", **result}


def near_matches(patterns: list[dict], *, max_distance: float = 1.5,
                 max_pairs: int = 1000) -> list[dict]:
    """List bounded candidate pairs for human similarity inspection."""
    if max_distance < 0 or max_pairs < 0:
        raise ValueError("invalid near-match budget")
    if max_pairs == 0:
        return []
    out = []
    for i, left in enumerate(patterns):
        for right in patterns[i + 1:]:
            if left["family_key"] == right["family_key"]:
                continue
            distance = pattern_distance(left, right)
            if distance["total"] <= max_distance:
                out.append({"left_id": left["id"], "right_id": right["id"], "distance": distance})
                if len(out) >= max_pairs:
                    return out
    return out


def retrieve_patterns(patterns: list[dict], *, bpm: float | None = None,
                      target_nps: float | None = None, length_beats: float | None = None,
                      allowed_families: set[str] | None = None,
                      forbidden_families: set[str] | None = None,
                      forbidden_versions: set[str] | None = None,
                      forbidden_song_families: set[str] | None = None,
                      entry_color: int | None = None, limit: int = 8) -> list[dict]:
    """Return one per family first, with stable reasons and source IDs."""
    forbidden_families = forbidden_families or set()
    forbidden_versions = {v.upper() for v in (forbidden_versions or set())}
    forbidden_song_families = forbidden_song_families or set()
    candidates = []
    for p in patterns:
        if (p["family_key"] in forbidden_families or p["version_hash"].upper() in forbidden_versions
                or p.get("song_family_id") in forbidden_song_families):
            continue
        if allowed_families is not None and p["family_key"] not in allowed_families:
            continue
        if entry_color is not None and p["notes"][0]["color"] != entry_color:
            continue
        score = 0.0
        reasons = []
        for label, actual, target in (("bpm", p["bpm"], bpm), ("nps", p["nps"], target_nps),
                                      ("length", p["length_beats"], length_beats)):
            if target is not None:
                delta = abs(actual - target) / max(abs(target), 1)
                score += delta
                reasons.append(f"{label} delta {delta:.2f}")
        candidates.append((score, p["id"], p, reasons))
    candidates.sort(key=lambda row: (row[0], row[1]))
    result, used = [], set()
    for score, _, pattern, reasons in candidates:
        if pattern["family_key"] in used:
            continue
        result.append({"pattern": pattern, "compatibility_score": round(score, 4),
                       "reason": ", ".join(reasons) or "unfiltered structural match"})
        used.add(pattern["family_key"])
        if len(result) == limit:
            break
    return result
