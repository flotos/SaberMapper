"""Vivify, Heck, Noodle and Chroma v3 vocabulary: event fields, requirements, bundles, stripping.

Field names and casing follow the official docs (heck.aeroluna.dev: vivify/events,
animation/*, environment/environment, items/objects) and were checked against the EXSII
difficulty files. The asset bundle manifest is VivifyTemplate's ``bundleinfo.json``
(Swifter1243/VivifyTemplate, BundleInfoProcessor.cs): ``materials`` {name: {path,
properties: {prop: {type: {Float: null}, value}}}}, ``prefabs`` {name: path}, ``bundleFiles``,
``bundleCRCs`` {"_windows2021": crc}, ``isCompressed``.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from pathlib import Path

from .storage import read_json

VIVIFY_EVENTS = {
    "SetMaterialProperty": ({"asset", "properties"}, {"duration", "easing"}),
    "SetGlobalProperty": ({"properties"}, {"duration", "easing"}),
    "Blit": (set(), {"asset", "priority", "pass", "order", "source", "destination", "duration", "easing",
                     "properties"}),
    "CreateCamera": ({"id"}, {"texture", "depthTexture", "properties"}),
    "CreateScreenTexture": ({"id"}, {"xRatio", "yRatio", "width", "height", "colorFormat", "filterMode"}),
    "SetCameraProperty": ({"properties"}, {"id"}),
    "InstantiatePrefab": ({"asset"}, {"id", "track", "position", "localPosition", "rotation", "localRotation",
                                      "scale"}),
    "DestroyObject": ({"id"}, set()),
    "AssignObjectPrefab": (set(), {"loadMode", "colorNotes", "burstSliders", "burstSliderElements", "bombNotes",
                                   "saber"}),
    "SetAnimatorProperty": ({"id", "properties"}, {"duration", "easing"}),
    "SetRenderingSettings": (set(), {"duration", "easing", "renderSettings", "qualitySettings", "xrSettings"}),
}
# Noodle animation properties (animation/properties) plus the GameObject transform properties
# used on prefab, environment and player tracks; Chroma adds color.
NOODLE_TRACK_PROPERTIES = {"offsetPosition", "localRotation", "offsetWorldRotation", "scale", "dissolve",
                           "dissolveArrow", "interactable", "time", "position", "localPosition", "rotation"}
NOODLE_PATH_PROPERTIES = {"offsetPosition", "localRotation", "offsetWorldRotation", "scale", "dissolve",
                          "dissolveArrow", "interactable", "definitePosition"}
HECK_EVENTS = {
    "AnimateTrack": ({"track"}, {"duration", "easing", "repeat", "color"} | NOODLE_TRACK_PROPERTIES),
    "AssignPathAnimation": ({"track"}, {"duration", "easing", "color"} | NOODLE_PATH_PROPERTIES),
    "AssignTrackParent": ({"childrenTracks", "parentTrack"}, {"worldPositionStays"}),
    "AssignPlayerToTrack": ({"track"}, {"target"}),
}
CHROMA_EVENTS = {"AnimateComponent": ({"track"}, {"duration", "easing"})}
CHROMA_COMPONENTS = {"BloomFogEnvironment": {"attenuation", "offset", "startY", "height"},
                     "TubeBloomPrePassLight": {"colorAlphaMultiplier", "bloomFogIntensityMultiplier"}}
EVENT_FIELDS = {**VIVIFY_EVENTS, **HECK_EVENTS, **CHROMA_EVENTS}
EVENT_MOD = {**{t: "vivify" for t in VIVIFY_EVENTS}, "AnimateTrack": "heck", "AssignPathAnimation": "heck",
             "AssignTrackParent": "noodle", "AssignPlayerToTrack": "noodle", "AnimateComponent": "chroma",
             # Legacy names seen in EXSII files; parsed as evidence, never emitted.
             "SetRenderSetting": "vivify", "DeclareCullingTexture": "vivify", "DeclareRenderTexture": "vivify"}
PROPERTY_TYPES = ("Texture", "Float", "Color", "Vector", "Keyword")
ANIMATOR_TYPES = ("Bool", "Float", "Integer", "Trigger")
PLAYER_TARGETS = ("Root", "Head", "LeftHand", "RightHand")
BLIT_ORDERS = ("BeforeMainEffect", "AfterMainEffect")
LOAD_MODES = ("Single", "Additive")
SABER_TYPES = ("Left", "Right", "Both")
CLEAR_FLAGS = ("Skybox", "SolidColor", "Depth", "Nothing")
DEPTH_MODES = ("Depth", "DepthNormals", "MotionVectors")
LOOKUP_METHODS = ("Regex", "Exact", "Contains", "StartsWith", "EndsWith")
ENVIRONMENT_FIELDS = {"id", "lookupMethod", "duplicate", "active", "scale", "position", "localPosition", "rotation",
                      "localRotation", "track", "geometry", "components"}
MATERIAL_FIELDS = {"shader", "color", "track", "shaderKeywords"}
CHROMA_SHADERS = ("Standard", "OpaqueLight", "TransparentLight", "Glowing", "BaseWater", "BTSPillar", "BillieWater",
                  "WaterfallMirror", "InterscopeConcrete", "InterscopeCar")
OBJECT_PREFAB_FIELDS = {"colorNotes": {"track", "asset", "anyDirectionAsset", "debrisAsset"},
                        "burstSliders": {"track", "asset", "debrisAsset"},
                        "burstSliderElements": {"track", "asset", "debrisAsset"},
                        "bombNotes": {"track", "asset"},
                        "saber": {"type", "asset", "trailAsset", "trailTopPos", "trailBottomPos", "trailDuration",
                                  "trailSamplingFrequency", "trailGranularity"}}
_EASING_FAMILIES = ("Sine", "Quad", "Cubic", "Quart", "Quint", "Expo", "Circ", "Back", "Elastic", "Bounce")
EASINGS = frozenset({"easeLinear", "easeStep"} | {f"ease{kind}{family}" for kind in ("In", "Out", "InOut")
                                                  for family in _EASING_FAMILIES})
REQUIREMENTS = ("Vivify", "Noodle Extensions", "Chroma")
# Platform key in Info.dat _assetBundle / bundleCRCs -> bundle file name Vivify loads.
BUNDLE_FILES = {"_windows2019": "bundleWindows2019.vivify", "_windows2021": "bundleWindows2021.vivify",
                "_android2021": "bundleAndroid2021.vivify"}
NOTE_NOODLE_FIELDS = {"noteJumpMovementSpeed", "noteJumpStartBeatOffset", "animation", "worldRotation",
                      "localRotation", "coordinates", "uninteractable", "flip", "disableNoteGravity",
                      "disableNoteLook", "link", "scale"}


def event_assets(event: dict) -> list[tuple[str, str]]:
    """(path, field) of every bundle asset one custom event references."""
    data, kind = event.get("d") or {}, event.get("t")
    found = []
    if kind in ("SetMaterialProperty", "Blit", "InstantiatePrefab") and isinstance(data.get("asset"), str):
        found.append((data["asset"], "asset"))
    if kind == "AssignObjectPrefab":
        for group, fields in OBJECT_PREFAB_FIELDS.items():
            block = data.get(group)
            if isinstance(block, dict):
                found += [(block[f], f"{group}.{f}") for f in ("asset", "anyDirectionAsset", "debrisAsset", "trailAsset")
                          if isinstance(block.get(f), str)]
    return found


def asset_kind(path: str) -> str:
    lower = path.lower()
    return "material" if lower.endswith(".mat") else "prefab" if lower.endswith(".prefab") else "other"


def requirements(custom_data: dict, note_data: list[dict] = ()) -> list[str]:
    """Mods a merged difficulty actually needs, derived from its events and object data."""
    needed = set()
    for event in custom_data.get("customEvents", []):
        kind, data = event.get("t"), event.get("d") or {}
        mod = EVENT_MOD.get(kind)
        if mod == "vivify":
            needed.add("Vivify")
        elif mod == "noodle":
            needed.add("Noodle Extensions")
        elif mod == "chroma":
            needed.add("Chroma")
        if kind in ("AnimateTrack", "AssignPathAnimation"):
            if set(data) & (NOODLE_TRACK_PROPERTIES | NOODLE_PATH_PROPERTIES):
                needed.add("Noodle Extensions")
            if "color" in data:
                needed.add("Chroma")
    if custom_data.get("environment") or custom_data.get("materials"):
        needed.add("Chroma")
    for data in note_data:
        if set(data) & NOTE_NOODLE_FIELDS:
            needed.add("Noodle Extensions")
        if "color" in data:
            needed.add("Chroma")
    return [name for name in REQUIREMENTS if name in needed]


def strip_custom(beatmap: dict) -> dict:
    """Vanilla copy of a v3 beatmap: no top-level or per-object customData."""
    result = {key: deepcopy(value) for key, value in beatmap.items() if key != "customData"}
    for key, value in result.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item.pop("customData", None)
    return result


class BundleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _property_type(entry) -> tuple[str | None, object]:
    """(type, default) of one bundleinfo property in either VivifyTemplate shape."""
    if isinstance(entry, dict) and isinstance(entry.get("type"), dict) and len(entry["type"]) == 1:
        return next(iter(entry["type"])), entry.get("value")
    if isinstance(entry, dict) and len(entry) == 1 and next(iter(entry)) in PROPERTY_TYPES:
        return next(iter(entry)), next(iter(entry.values()))
    return None, None


def read_bundle(directory: str | Path) -> dict | None:
    """Normalized bundle set from ``<dir>/bundleinfo.json`` and the ``bundle*.vivify`` files beside it.

    Returns None when the directory has no bundleinfo.json. The CRCs come from the build
    (Unity's AssetBundle CRC); they are never recomputed here.
    """
    directory = Path(directory)
    info_path = directory / "bundleinfo.json"
    if not info_path.is_file():
        return None
    try:
        raw = read_json(info_path)
    except ValueError as exc:
        raise BundleError("bundleinfo_invalid", f"{info_path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("materials", {}), dict) \
            or not isinstance(raw.get("prefabs", {}), dict) or not isinstance(raw.get("bundleCRCs", {}), dict):
        raise BundleError("bundleinfo_invalid", f"{info_path} must hold materials, prefabs and bundleCRCs objects "
                                                "(VivifyTemplate bundleinfo.json)")
    materials = {}
    for name, material in raw.get("materials", {}).items():
        if not isinstance(material, dict) or not isinstance(material.get("path"), str):
            raise BundleError("bundleinfo_invalid", f"bundleinfo material {name!r} needs a path")
        properties = {}
        for prop, entry in (material.get("properties") or {}).items():
            kind, default = _property_type(entry)
            if kind is None:
                raise BundleError("bundleinfo_invalid", f"bundleinfo {material['path']} property {prop} has no type")
            properties[prop] = {"type": kind, "default": default}
        materials[material["path"].lower()] = {"name": name, "path": material["path"], "properties": properties}
    prefabs = {path.lower(): name for name, path in raw.get("prefabs", {}).items() if isinstance(path, str)}
    crcs = {}
    for key, value in raw.get("bundleCRCs", {}).items():
        if key not in BUNDLE_FILES:
            raise BundleError("bundleinfo_invalid", f"unknown bundle platform {key!r}; use {', '.join(BUNDLE_FILES)}")
        if type(value) is not int or not 0 <= value < 2 ** 32:
            raise BundleError("bundleinfo_invalid", f"bundleCRCs.{key} must be an unsigned 32-bit integer")
        crcs[key] = value
    files = {key: directory / name for key, name in BUNDLE_FILES.items() if (directory / name).is_file()}
    return {"directory": str(directory), "materials": materials, "prefabs": prefabs, "crcs": crcs,
            "files": {key: str(path) for key, path in files.items()},
            "shipped": sorted(set(files) & set(crcs)),
            "missing_files": sorted(set(crcs) - set(files)), "missing_crcs": sorted(set(files) - set(crcs))}


def bundle_summary(bundle: dict | None) -> dict | None:
    if bundle is None:
        return None
    return {"directory": bundle["directory"], "materials": {p: {k: v["type"] for k, v in m["properties"].items()}
                                                            for p, m in bundle["materials"].items()},
            "prefabs": sorted(bundle["prefabs"]), "crcs": bundle["crcs"], "files": bundle["files"],
            "shipped": bundle["shipped"], "missing_files": bundle["missing_files"],
            "missing_crcs": bundle["missing_crcs"]}


def _finite(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


def parse_custom(custom_data: dict, seconds_at) -> dict | None:
    """Normalize v3 ``customData`` custom events, environment and materials; keep raw data as evidence."""
    if not isinstance(custom_data, dict):
        return None
    events = custom_data.get("customEvents") or []
    environment = custom_data.get("environment") or []
    materials = custom_data.get("materials") or {}
    if not (events or environment or materials):
        return None
    parsed, counts, unknown = [], {}, []
    for index, event in enumerate(events if isinstance(events, list) else []):
        # v3 omits "b" when it is 0; a null or non-finite beat stays as unknown evidence.
        if not isinstance(event, dict) or not _finite(event.get("b", 0)) or not isinstance(event.get("t"), str):
            unknown.append({"path": f"customData.customEvents[{index}]", "reason": "malformed custom event",
                            "value": deepcopy(event)})
            continue
        kind, data = event["t"], event.get("d") if isinstance(event.get("d"), dict) else {}
        mod = EVENT_MOD.get(kind, "unknown")
        counts.setdefault(mod, {}).setdefault(kind, 0)
        counts[mod][kind] += 1
        tracks = data.get("track")
        beat = float(event.get("b", 0))
        parsed.append({"index": index, "beat": beat, "seconds": seconds_at(beat),
                       "type": kind, "mod": mod, "data": deepcopy(data),
                       "tracks": [tracks] if isinstance(tracks, str) else list(tracks) if isinstance(tracks, list) else [],
                       "assets": [path for path, _ in event_assets(event)]})
    tracks = sorted({t for e in parsed for t in e["tracks"] if isinstance(t, str)})
    return {"custom_events": parsed, "event_counts": counts, "environment": deepcopy(environment),
            "materials": deepcopy(materials), "tracks": tracks,
            "assets": sorted({a for e in parsed for a in e["assets"]}), "unknown": unknown}
