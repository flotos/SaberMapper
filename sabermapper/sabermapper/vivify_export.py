"""ZIP entries for a vivified export: requirements, asset bundle block, bundle files, vanilla twin, sidecar."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .show import show_revision
from . import vivify


def vivified_entries(info: dict, by_rank: list, report: dict, vivid: dict, destination: Path):
    """(map entries without song/cover/report, vanilla-twin entries, provenance sidecar).

    Mutates ``info`` (per-difficulty ``_requirements``, Info-level ``_assetBundle``) and ``report``.
    """
    from .export import ExportError, _json_bytes
    twin_info = deepcopy(info)
    bundle = vivid["bundle"]
    beatmaps = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"]
    requirements, provenance = {}, {}
    for entry, (_, (_, row)) in zip(beatmaps, by_rank):
        names = row["vivify"]["requirements"]
        requirements[row["difficulty"]] = names
        if names:
            entry["_customData"] = {"_requirements": names}
        provenance[row["difficulty"]] = row.pop("_provenance")
    needs_vivify = any("Vivify" in names for names in requirements.values())
    shipped, warnings = [], []
    if needs_vivify and bundle is not None:
        if bundle["missing_crcs"]:
            raise ExportError(f"bundle_crc_missing: {', '.join(vivify.BUNDLE_FILES[k] for k in bundle['missing_crcs'])} "
                              "has no CRC in bundleinfo.json; rebuild the bundle set so Vivify's checksum matches")
        shipped = bundle["shipped"]
        if not shipped:
            raise ExportError("bundle_files_missing: bundleinfo.json lists CRCs but no bundle*.vivify file sits "
                              f"beside it in {bundle['directory']}")
        info["_customData"] = {"_assetBundle": {key: bundle["crcs"][key] for key in shipped}}
        if bundle["missing_files"]:
            warnings.append({"severity": "warning", "code": "bundle_platform_missing",
                             "message": f"bundleinfo.json has CRCs for {', '.join(bundle['missing_files'])} but no "
                                        "bundle file; those platforms are left out of _assetBundle"})
        if "_windows2021" not in shipped:
            warnings.append({"severity": "warning", "code": "bundle_windows2021_missing",
                             "message": "no bundleWindows2021.vivify; PC Beat Saber 1.30+ loads the 2021 bundle"})
    entries = [("Info.dat", _json_bytes(info))]
    entries += [(row["beatmap_filename"], _json_bytes(beatmap)) for _, (beatmap, row) in by_rank]
    entries += [(vivify.BUNDLE_FILES[key], Path(bundle["files"][key]).read_bytes()) for key in shipped]
    twin = [("Info.dat", _json_bytes(twin_info))]
    twin += [(row["beatmap_filename"], _json_bytes(vivify.strip_custom(beatmap))) for _, (beatmap, row) in by_rank]
    twin_path = destination.with_name(destination.stem + "-vanilla.zip")
    sidecar_path = destination.with_name(destination.name + ".show.json")
    report["vivify"] = {
        "show_revision": show_revision(vivid["show"]) if vivid["show"].get("primitives") else "none",
        "requirements": requirements, "asset_bundle": info.get("_customData", {}).get("_assetBundle", {}),
        "bundle_files": [vivify.BUNDLE_FILES[key] for key in shipped],
        "bundle_directory": bundle["directory"] if bundle else None,
        "vanilla_twin": str(twin_path), "provenance_file": str(sidecar_path), "warnings": warnings,
        "checks": "Show structure, bundle schema, object lifetimes, possession, static flash rate, attention "
                  "budget and choreography checked statically; in-game rendering needs a game run."}
    sidecar = {"format": "SaberMapper show provenance 0.1", "map": destination.name,
               "show_revision": report["vivify"]["show_revision"],
               "note": "one row per customData.customEvents entry (same index), per difficulty; beats are "
                       "arrangement beats before the audio-offset shift, seconds are source-audio seconds",
               "difficulties": provenance}
    return entries, twin, sidecar
