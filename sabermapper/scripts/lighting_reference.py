"""Measure how human lighters light the reference corpus; writes the lighting calibration resource.

Usage (from the application directory):
    .venv/Scripts/python scripts/lighting_reference.py --corpus workspace/corpus/archives \
        --output sabermapper/resources/lighting-reference.json

Every map archive contributes its hardest Standard difficulty (lights are usually shared).
Only basic events are measured (v2 ``_events`` / v3 ``basicBeatmapEvents``). The result is a
calibration of density, value mix, static gaps and flash rates, never a pattern to copy.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import zipfile

LIGHT_TYPES = range(0, 5)
FLASH_VALUES = {2, 6, 10}
KINDS = {0: "off", 1: "on", 5: "on", 9: "on", 2: "flash", 6: "flash", 10: "flash",
         3: "fade", 7: "fade", 11: "fade", 4: "transition", 8: "transition", 12: "transition"}
COLOR = {1: "blue", 2: "blue", 3: "blue", 4: "blue", 5: "red", 6: "red", 7: "red", 8: "red",
         9: "white", 10: "white", 11: "white", 12: "white"}
WINDOW = 4.0


def _load(archive: zipfile.ZipFile, names: dict, filename: str):
    return json.loads(archive.read(names[filename.lower().split("/")[-1]]).decode("utf-8-sig"))


def _events(beatmap: dict):
    """(beat, type, value) basic events and boost toggles from a v2 or v3 beatmap."""
    if "basicBeatmapEvents" in beatmap or "colorNotes" in beatmap:
        events = [(float(e.get("b", 0)), int(e.get("et", 0)), int(e.get("i", 0)))
                  for e in beatmap.get("basicBeatmapEvents", [])]
        boosts = [float(e.get("b", 0)) for e in beatmap.get("colorBoostBeatmapEvents", [])]
        notes = [float(n.get("b", 0)) for n in beatmap.get("colorNotes", [])]
    else:
        raw = beatmap.get("_events", [])
        events = [(float(e.get("_time", 0)), int(e.get("_type", 0)), int(e.get("_value", 0))) for e in raw]
        boosts = [b for b, t, _ in events if t == 5]
        notes = [float(n.get("_time", 0)) for n in beatmap.get("_notes", []) if n.get("_type") in (0, 1)]
    return events, boosts, notes


def _quantiles(values, points=(0.1, 0.25, 0.5, 0.75, 0.9)):
    values = sorted(values)
    if not values:
        return None
    return {f"p{int(q * 100)}": round(values[min(len(values) - 1, int(q * len(values)))], 3) for q in points}


def measure(archive_path: Path) -> dict | None:
    archive = zipfile.ZipFile(archive_path)
    names = {n.lower().split("/")[-1]: n for n in archive.namelist()}
    info = _load(archive, names, "info.dat")
    bpm = float(info["_beatsPerMinute"])
    sets = [s for s in info.get("_difficultyBeatmapSets", []) if s.get("_beatmapCharacteristicName") == "Standard"]
    if not sets or not sets[0]["_difficultyBeatmaps"]:
        return None
    chosen = max(sets[0]["_difficultyBeatmaps"], key=lambda d: d.get("_difficultyRank", 0))
    events, boosts, notes = _events(_load(archive, names, chosen["_beatmapFilename"]))
    if len(notes) < 50:
        return None
    seconds = lambda beat: beat * 60 / bpm
    first, last = seconds(min(notes)), seconds(max(notes))
    span = max(last - first, 1.0)
    lights = sorted((seconds(b), t, v) for b, t, v in events if t in LIGHT_TYPES and first <= seconds(b) <= last)
    if not lights:
        return {"id": archive_path.stem, "environment": info.get("_environmentName"), "lit": False}
    light_times = [t for t, _, _ in lights]
    note_times = sorted(seconds(b) for b in notes)
    kinds = Counter(KINDS.get(v, "other") for _, _, v in lights)
    colors = Counter(COLOR[v] for _, _, v in lights if v in COLOR)
    # Density per 4 s window against the window's note density, bucketed into within-map terciles.
    windows = []
    start = first
    while start + WINDOW <= last:
        windows.append((bisect_left(note_times, start + WINDOW) - bisect_left(note_times, start),
                        bisect_left(light_times, start + WINDOW) - bisect_left(light_times, start)))
        start += WINDOW
    ranked = sorted(windows)
    third = max(1, len(ranked) // 3)
    tiers = {"low": ranked[:third], "mid": ranked[third:-third] or ranked, "high": ranked[-third:]}
    tier_rate = {name: round(statistics.mean(l for _, l in rows) / WINDOW, 3) for name, rows in tiers.items() if rows}
    gaps = [b - a for a, b in zip([first] + light_times, light_times + [last])]
    # Moments where three or more ring/laser/center groups flash together, per 1 s window.
    moments = sorted({round(t, 3) for t, _, _ in lights
                      if len({g for tt, g, v in lights if abs(tt - t) < 0.02 and v in FLASH_VALUES}) >= 3})
    burst = max((bisect_left(moments, m + 1.0) - bisect_left(moments, m) for m in moments), default=0)
    groups = Counter(t for _, t, _ in lights)
    same_time = Counter(round(t, 3) for t in light_times)
    speeds = [e for e in events if e[1] in (12, 13)]
    rings = [e for e in events if e[1] in (8, 9)]
    return {
        "id": archive_path.stem, "environment": info.get("_environmentName"), "lit": True,
        "difficulty": chosen["_difficulty"], "seconds": round(span, 1),
        "light_events_per_second": round(len(lights) / span, 3),
        "light_moments_per_second": round(len(same_time) / span, 3),
        "events_per_moment": round(len(lights) / len(same_time), 3),
        "notes_per_second": round(len(note_times) / span, 3),
        "tier_light_events_per_second": tier_rate,
        "value_share": {k: round(v / len(lights), 3) for k, v in kinds.items()},
        "color_share": {k: round(v / sum(colors.values()), 3) for k, v in colors.items()} if colors else {},
        "group_share": {str(k): round(v / len(lights), 3) for k, v in sorted(groups.items())},
        "laser_speed_events_per_second": round(len(speeds) / span, 3),
        "ring_events_per_second": round(len(rings) / span, 3),
        "boost_toggles": len(boosts),
        "longest_static_seconds": round(max(gaps), 2),
        "p95_static_seconds": round(sorted(gaps)[int(0.95 * (len(gaps) - 1))], 3),
        "max_group_flashes_per_second": burst,
    }


def aggregate(rows: list[dict]) -> dict:
    lit = [r for r in rows if r.get("lit")]
    q = lambda key: _quantiles([r[key] for r in lit])
    return {
        "maps": len(rows), "lit_maps": len(lit),
        "environments": Counter(r["environment"] for r in rows).most_common(),
        "light_events_per_second": q("light_events_per_second"),
        "light_moments_per_second": q("light_moments_per_second"),
        "events_per_moment": q("events_per_moment"),
        "tier_light_events_per_second": {tier: _quantiles([r["tier_light_events_per_second"][tier] for r in lit
                                                           if tier in r["tier_light_events_per_second"]])
                                         for tier in ("low", "mid", "high")},
        "value_share": {kind: _quantiles([r["value_share"].get(kind, 0) for r in lit])
                        for kind in ("on", "flash", "fade", "off", "transition")},
        "white_share": _quantiles([r["color_share"].get("white", 0) for r in lit]),
        "laser_speed_events_per_second": q("laser_speed_events_per_second"),
        "ring_events_per_second": q("ring_events_per_second"),
        "maps_using_boost": sum(1 for r in lit if r["boost_toggles"]),
        "longest_static_seconds": q("longest_static_seconds"),
        "p95_static_seconds": q("p95_static_seconds"),
        "max_group_flashes_per_second": q("max_group_flashes_per_second"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True, help="Directory of reference map ZIP archives")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows, skipped = [], []
    for path in sorted(args.corpus.glob("*.zip")):
        try:
            row = measure(path)
        except (KeyError, ValueError, zipfile.BadZipFile) as exc:
            skipped.append({"id": path.stem, "reason": str(exc)[:120]})
            continue
        if row:
            rows.append(row)
    result = {"format": "SaberMapper lighting reference 1.0",
              "method": "Hardest Standard difficulty per archive; basic light events (types 0-4) between first "
                        "and last note; 4 s windows ranked by note count into within-map terciles.",
              "summary": aggregate(rows), "skipped": skipped, "maps": rows}
    args.output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    json.dump(result["summary"], sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
