"""ZIP entries for a vivified export: requirements, asset bundle block, bundle files, vanilla twin, sidecar."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .show import note_colors, show_revision
from . import vivify


def _credits(bundle_directory) -> dict | None:
    """The credits of the shipped bundle: credits.json written by `assets build`, else built from assets.json."""
    from .asset_credits import CREDITS_FILE, credits_for_file
    import json
    if not bundle_directory:
        return None
    folder = Path(bundle_directory)
    if (folder / CREDITS_FILE).is_file():
        return json.loads((folder / CREDITS_FILE).read_text(encoding="utf-8"))
    if (folder / "assets.json").is_file():
        return credits_for_file(folder / "assets.json")
    return None


def vivified_entries(info: dict, by_rank: list, report: dict, vivid: dict, destination: Path):
    """(map entries without song/cover/report, vanilla-twin entries, provenance sidecar, credits or None).

    Mutates ``info`` (per-difficulty ``_requirements``, Info-level ``_assetBundle``) and ``report``.
    """
    from .export import ExportError, _json_bytes
    twin_info = deepcopy(info)
    bundle = vivid["bundle"]
    beatmaps = info["_difficultyBeatmapSets"][0]["_difficultyBeatmaps"]
    requirements, provenance = {}, {}
    for entry, (arrangement, (_, row)) in zip(beatmaps, by_rank):
        names = row["vivify"]["requirements"]
        requirements[row["difficulty"]] = names
        if names:
            entry.setdefault("_customData", {})["_requirements"] = names
        colors = note_colors(arrangement) if arrangement.get("schema_version") == "0.2" else None
        if colors:
            entry.setdefault("_customData", {}).update(
                {"_colorLeft": {k: colors["left"][k] for k in "rgb"}, "_colorRight": {k: colors["right"][k] for k in "rgb"}})
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
        info.setdefault("_customData", {})["_assetBundle"] = {key: bundle["crcs"][key] for key in shipped}
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
    credits = _credits(bundle["directory"]) if shipped else None
    credits_path = destination.with_name(destination.name + ".credits.json")
    if credits is not None:
        entries.append(("credits.json", _json_bytes(credits)))
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
        "credits": None if credits is None else {
            "file": str(credits_path), "third_party": len(credits.get("third_party", [])),
            "generated_media": len(credits.get("generated_media", [])), "licenses": credits.get("licenses", []),
            "attribution_text": credits.get("attribution_text"),
            "publish": "Paste attribution_text into the map description: BeatSaver removes files Info.dat does not "
                       "reference, so credits.json only travels with the ZIP when it is shared directly"},
        "checks": "Show structure, bundle schema, object lifetimes, possession, static flash rate, attention "
                  "budget and choreography checked statically; in-game rendering needs a game run."}
    sidecar = {"format": "SaberMapper show provenance 0.1", "map": destination.name,
               "show_revision": report["vivify"]["show_revision"],
               "note": "one row per customData.customEvents entry (same index), per difficulty; beats are "
                       "arrangement beats before the audio-offset shift, seconds are source-audio seconds",
               "difficulties": provenance}
    return entries, twin, sidecar, credits
