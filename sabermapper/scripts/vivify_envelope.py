"""Measure the EXSII custom-event envelope; writes the show-validation warning resource.

Usage (from the application directory):
    .venv/Scripts/python scripts/vivify_envelope.py \
        --extracted workspace/corpus/extrasensory/extracted \
        --index docs/references/extrasensory/map-index.json \
        --output sabermapper/resources/vivify-envelope.json

Only counts and rates are stored (never event arrays), so the resource carries no EXSII content.
The show validator warns when a compiled show goes beyond the pack's maximum.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sabermapper.mapio import parse_map  # noqa: E402
from sabermapper.show_validation import _window_max  # noqa: E402
from sabermapper.vivify import parse_custom  # noqa: E402


def measure(beatmap: dict, bpm: float) -> dict:
    try:
        custom = parse_map(beatmap, bpm=bpm).get("custom")
    except ValueError:  # a few EXSII files carry off-grid gameplay objects; the events still parse
        custom = parse_custom(beatmap.get("customData") or {}, lambda b: b * 60 / bpm)
    events = (custom or {}).get("custom_events", [])
    times = [e["seconds"] for e in events]
    spawns = [e["seconds"] for e in events if e["type"] == "InstantiatePrefab"]
    blits = [e["seconds"] for e in events if e["type"] == "Blit"]
    return {"custom_events": len(events), "events_per_second": _window_max(times)[0] if times else 0,
            "spawns_per_second": _window_max(spawns)[0] if spawns else 0,
            "blits_per_second": _window_max(blits)[0] if blits else 0,
            "instantiate": len(spawns), "blit": len(blits), "tracks": len((custom or {}).get("tracks", []))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    rows = []
    for entry in index["maps"]:
        folder = args.extracted / Path(entry["extracted"]).name
        info = json.loads((folder / "Info.dat").read_text(encoding="utf-8-sig"))
        for group in info.get("_difficultyBeatmapSets", []):
            for item in group.get("_difficultyBeatmaps", []):
                path = folder / item["_beatmapFilename"]
                beatmap = json.loads(path.read_text(encoding="utf-8-sig"))
                rows.append({"map": entry["songName"], "beatsaver_id": entry["beatsaverId"],
                             "map_hash": entry["mapHash"], "characteristic": group["_beatmapCharacteristicName"],
                             "difficulty": item["_difficulty"], **measure(beatmap, float(info["_beatsPerMinute"]))})
    metrics = ("custom_events", "events_per_second", "spawns_per_second", "blits_per_second")
    result = {"schema_version": "1.0", "source": "Extra Sensory II (10 maps, every difficulty)",
              "retrieved": index.get("retrieved"), "computed": date.today().isoformat(),
              "method": "scripts/vivify_envelope.py: counts of v3 customData.customEvents per difficulty; "
                        "*_per_second = most events of that kind in any one-second window (song seconds "
                        "from Info.dat BPM and bpmEvents)",
              "rights": "counts only; no EXSII event data is stored (see docs/references/extrasensory/README.md)",
              "max": {m: max(r[m] for r in rows) for m in metrics},
              "median": {m: statistics.median(r[m] for r in rows) for m in metrics},
              "difficulties": rows}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "difficulties": len(rows), "max": result["max"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
