"""Show document 0.1 and arrangement 0.2 presentation: schema, spans, evidence drivers and storage.

The show is project-level and difficulty independent (``<project>/show.json``). It is written in
agent-level primitives that ``show_compile`` expands into Vivify, Heck and Chroma events. Its
revision is the canonical SHA-256 of its JSON (like an arrangement's); ``none`` names the absent
show. ``show.meta.json`` records the arrangement revisions each save was written against.
"""
from __future__ import annotations

from fractions import Fraction
import json
import math
import re
import uuid
from pathlib import Path

from .revisions import arrangement_revision
from .storage import now, read_json, write_json
from . import vivify

SCHEMA_VERSION = "0.1"
FAMILIES = ("post_process", "scene", "none")
NOTE_STYLES = ("plain", "choreographed")
POSSESSIONS = ("none", "player", "head", "hands", "right_hand")
POSSESSION_TARGETS = {"none": set(), "player": {"Root"}, "head": {"Head"}, "hands": {"LeftHand", "RightHand"},
                      "right_hand": {"RightHand"}}
DRIVER_SOURCES = ("onsets", "sustains", "moments", "lyrics")
ANCHOR_SOURCES = DRIVER_SOURCES + ("section",)
SUSTAIN_SHAPES = ("rise", "fall", "flat", "unstable")
NO_SHOW = "none"
_SPAN_KINDS = ("look", "scene", "skin", "pulse", "path")
_COMMON = {"kind", "id", "note", "anchor"}
_SPAN = {"section", "until_section", "start_beat", "end_beat"}
PRIMITIVE_FIELDS = {
    "setup": (set(), {"beat", "screen_textures", "cameras", "camera_properties", "rendering", "player_tracks"}),
    "look": ({"section", "material"}, _SPAN | {"priority", "pass", "order", "source", "destination", "easing",
                                               "properties", "keyframes"}),
    "scene": ({"section", "prefab"}, _SPAN | {"object_id", "track", "position", "localPosition", "rotation",
                                              "localRotation", "scale", "persist", "animate", "keyframes", "animator"}),
    "skin": ({"section"}, _SPAN - {"start_beat", "end_beat"} | {"track", "load_mode"} | set(vivify.OBJECT_PREFAB_FIELDS)),
    "pulse": ({"section", "driver", "property"}, _SPAN | {"material", "global", "track", "type", "envelope",
                                                          "min_gap_beats", "max_events"}),
    "possess": ({"target", "track"}, {"section", "beat", "animate"}),
    "env": (set(), {"section", "beat", "environment", "materials", "animate"}),
    "path": ({"section", "njs", "offset"}, _SPAN - {"start_beat", "end_beat"} | {"track", "colors", "animation",
                                                                              "world_rotation", "keyframes"}),
    "raw": ({"event"}, {"section", "persist"}),
}
# Structural codes block `show save`; every other error blocks export only (bundle, evidence, budgets).
SAVE_BLOCKING = {"invalid_show", "schema_version", "invalid_type", "missing_field", "unsupported_field",
                 "unknown_primitive", "duplicate_id", "invalid_beat", "invalid_value", "unknown_section",
                 "outside_section", "keyframe_outside_span", "invalid_points", "invalid_driver", "invalid_anchor",
                 "raw_unknown_event", "raw_invalid_field", "invalid_presentation"}


class ShowError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def show_revision(show: dict | None) -> str:
    return NO_SHOW if show is None else arrangement_revision(show)


def beat(value) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("beat must be a number or rational string")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("beat must be finite")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid beat {value!r}") from exc
    if result < 0:
        raise ValueError("beat must be nonnegative")
    return result


def section_spans(arrangement: dict) -> dict[str, tuple[Fraction, Fraction]]:
    spans = {}
    for section in arrangement.get("sections", []):
        start = beat(section["start_beat"])
        spans[section["id"]] = (start, start + beat(section["length_beats"]))
    return spans


def primitive_span(primitive: dict, spans: dict) -> tuple[Fraction, Fraction | float]:
    """Absolute [start, end] beats a primitive acts on; float('inf') for map-global environment edits."""
    kind = primitive.get("kind")
    if kind == "setup":
        return Fraction(0), Fraction(0)
    if kind == "raw":
        start = beat((primitive.get("event") or {}).get("b", 0))
        duration = ((primitive.get("event") or {}).get("d") or {}).get("duration", 0)
        return start, start + (beat(duration) if isinstance(duration, (int, float)) and duration > 0 else 0)
    section = primitive.get("section")
    if section is not None and section not in spans:
        raise ShowError("unknown_section", f"section {section!r} does not exist (sections: {', '.join(spans)})")
    if kind in ("possess", "env"):
        if section is None and "beat" not in primitive:
            return (Fraction(0), float("inf")) if kind == "env" else (Fraction(0), Fraction(0))
        start = beat(primitive["beat"]) if "beat" in primitive else spans[section][0]
        end = spans[section][1] if section is not None else start
        for item in primitive.get("animate") or []:
            end = max(end, beat(item["beat"]) + beat(item.get("duration_beats", 0)))
        return start, end
    start, end = spans[section]
    until = primitive.get("until_section")
    if until is not None:
        if until not in spans:
            raise ShowError("unknown_section", f"until_section {until!r} does not exist")
        end = spans[until][1]
    if "start_beat" in primitive:
        start = beat(primitive["start_beat"])
    if "end_beat" in primitive:
        end = beat(primitive["end_beat"])
    return start, end


def touches(span, section_span) -> bool:
    start, end = span
    low, high = section_span
    return start < high and end >= low if end > start else low <= start < high


# ---------------------------------------------------------------- presentation (arrangement 0.2)

def _color(value) -> bool:
    if isinstance(value, str):
        return re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value) is not None
    return (isinstance(value, list) and len(value) in (3, 4)
            and all(not isinstance(v, bool) and isinstance(v, (int, float)) and 0 <= v <= 1 for v in value))


def validate_presentation(arrangement: dict, add) -> None:
    """Check the optional map-level and per-section ``presentation`` blocks of arrangement 0.2."""
    def check(obj, required, optional, where, sid=None):
        if not isinstance(obj, dict):
            add("error", "invalid_presentation", f"{where} must be an object", sid)
            return False
        for name in sorted(set(required) - set(obj)):
            add("error", "invalid_presentation", f"{where} requires {name}", sid)
        for name in sorted(set(obj) - set(required) - set(optional)):
            add("error", "unsupported_field", f"{where}.{name} is unsupported", sid)
        return not set(required) - set(obj)

    top = arrangement.get("presentation")
    if top is not None and check(top, (), ("concept", "palette", "possession"), "presentation"):
        if "concept" in top and (not isinstance(top["concept"], str) or not top["concept"].strip()):
            add("error", "invalid_presentation", "presentation.concept must be a nonempty sentence")
        if "palette" in top and (not isinstance(top["palette"], list) or not 1 <= len(top["palette"]) <= 12
                                 or not all(_color(c) for c in top["palette"])):
            add("error", "invalid_presentation",
                "presentation.palette must list 1-12 colors as #rrggbb[aa] or [r, g, b(, a)] in 0..1")
        if "possession" in top and top["possession"] not in POSSESSIONS:
            add("error", "invalid_presentation", f"presentation.possession must be one of {', '.join(POSSESSIONS)}")
    for section in arrangement.get("sections", []):
        if not isinstance(section, dict) or "presentation" not in section:
            continue
        sid, block = section.get("id"), section["presentation"]
        if not check(block, ("family",), ("concept", "attention", "reveal", "note_style"),
                     "section.presentation", sid):
            continue
        if block["family"] not in FAMILIES:
            add("error", "invalid_presentation", f"presentation.family must be one of {', '.join(FAMILIES)}", sid)
        if "concept" in block and (not isinstance(block["concept"], str) or not block["concept"].strip()):
            add("error", "invalid_presentation", "presentation.concept must be nonempty", sid)
        if "reveal" in block and type(block["reveal"]) is not bool:
            add("error", "invalid_presentation", "presentation.reveal must be a boolean", sid)
        if "note_style" in block and block["note_style"] not in NOTE_STYLES:
            add("error", "invalid_presentation", "presentation.note_style must be plain or choreographed", sid)
        if "attention" in block:
            attention = block["attention"]
            if check(attention, ("notes", "scene"), (), "presentation.attention", sid):
                values = [attention["notes"], attention["scene"]]
                if not all(not isinstance(v, bool) and isinstance(v, (int, float)) and 0 <= v <= 1 for v in values) \
                        or sum(values) > 1.0001:
                    add("error", "invalid_presentation",
                        "presentation.attention notes and scene must be 0..1 and sum to at most 1", sid)


def map_presentation(arrangement: dict) -> dict:
    return arrangement.get("presentation") or {}


def section_presentation(arrangement: dict) -> dict[str, dict]:
    return {s["id"]: s["presentation"] for s in arrangement.get("sections", []) if isinstance(s.get("presentation"), dict)}


def has_presentation(arrangement: dict) -> bool:
    return bool(arrangement.get("presentation")) or bool(section_presentation(arrangement))


# ---------------------------------------------------------------- structural validation

def _number(value, low=None, high=None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def _points(value) -> str | None:
    """Reason a point definition is malformed, else None."""
    if isinstance(value, str):
        return None  # named point definition or base provider, e.g. "baseHeadPosition"
    if _number(value):
        return None
    if not isinstance(value, list) or not value:
        return "must be a number, a list of numbers or a list of points"
    if all(_number(v) for v in value):
        return None
    previous = -1.0
    for point in value:
        if not isinstance(point, list) or not point:
            return "each point must be a list [values..., time, easing?]"
        provider = isinstance(point[0], str)  # e.g. ["baseHeadPosition", 0]
        items = point[1:] if provider else point
        count = next((i for i, v in enumerate(items) if not _number(v)), len(items))
        numbers, words = items[:count], items[count:]
        if len(numbers) < (1 if provider else 2):
            return "each point needs values followed by a time"
        for word in words:
            if not isinstance(word, str) or word not in vivify.EASINGS and word != "splineCatmullRom":
                return f"unknown easing or trailing value {word!r}"
        time = numbers[-1]
        if not 0 <= time <= 1 or time < previous:
            return "point times must lie in 0..1 and never decrease"
        previous = time
    return None


def validate_show(show: dict, arrangements: dict[str, dict]) -> list[dict]:
    """Structural and reference diagnostics for one show against every difficulty's sections."""
    findings = []

    def add(severity, code, message, primitive=None, section=None, difficulty=None, **extra):
        findings.append({"severity": severity, "code": code, "message": message, "primitive": primitive,
                         "section_id": section, "difficulty": difficulty, **extra})

    def fields(obj, required, optional, where, pid):
        if not isinstance(obj, dict):
            add("error", "invalid_type", f"{where} must be an object", pid)
            return False
        for name in sorted(set(required) - set(obj)):
            add("error", "missing_field", f"{where} requires {name}", pid)
        for name in sorted(set(obj) - set(required) - set(optional)):
            add("error", "unsupported_field", f"{where}.{name} is unsupported", pid)
        return not set(required) - set(obj)

    def beat_ok(value, where, pid):
        try:
            beat(value)
            return True
        except ValueError as exc:
            add("error", "invalid_beat", f"{where}: {exc}", pid)
            return False

    def points_ok(value, where, pid):
        reason = _points(value)
        if reason:
            add("error", "invalid_points", f"{where} {reason}", pid)

    def anchor_ok(anchor, where, pid):
        if not fields(anchor, ("source",), ("id", "word"), where, pid):
            return
        if anchor["source"] not in ANCHOR_SOURCES:
            add("error", "invalid_anchor", f"{where}.source must be one of {', '.join(ANCHOR_SOURCES)}", pid)
        elif "id" not in anchor and "word" not in anchor:
            add("error", "invalid_anchor", f"{where} needs an id (or a word for lyrics)", pid)

    def keyframes(items, where, pid, required, optional, props=(), need_prop=False):
        if not isinstance(items, list):
            add("error", "invalid_type", f"{where} must be an array", pid)
            return
        for index, item in enumerate(items):
            here = f"{where}[{index}]"
            if not fields(item, required, set(optional) | set(props) | {"duration_beats", "easing", "anchor"}, here, pid):
                continue
            beat_ok(item["beat"], here + ".beat", pid)
            if "duration_beats" in item:
                beat_ok(item["duration_beats"], here + ".duration_beats", pid)
            if "easing" in item and item["easing"] not in vivify.EASINGS:
                add("error", "invalid_value", f"{here}.easing {item['easing']!r} is not an easing name", pid)
            if "anchor" in item:
                anchor_ok(item["anchor"], here + ".anchor", pid)
            present = [p for p in props if p in item]
            if need_prop and not present:
                add("error", "missing_field", f"{here} animates nothing; give one of {', '.join(sorted(props))}", pid)
            for prop in present:
                points_ok(item[prop], f"{here}.{prop}", pid)

    def material_keyframes(items, where, pid, need_material):
        keyframes(items, where, pid, {"beat", "property"} | ({"material"} if need_material else set()),
                  {"value", "points", "type", "material"})
        for index, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict):
                if ("value" in item) == ("points" in item):
                    add("error", "invalid_value", f"{where}[{index}] needs exactly one of value or points", pid)
                if "points" in item:
                    points_ok(item["points"], f"{where}[{index}].points", pid)
                if "type" in item and item["type"] not in vivify.PROPERTY_TYPES:
                    add("error", "invalid_value", f"{where}[{index}].type must be one of "
                                                  f"{', '.join(vivify.PROPERTY_TYPES)}", pid)

    if not isinstance(show, dict):
        add("error", "invalid_show", "show must be a JSON object")
        return findings
    if not fields(show, ("schema_version", "primitives"), ("description",), "show", None):
        return findings
    if show["schema_version"] != SCHEMA_VERSION:
        add("error", "schema_version", f"show schema_version must be {SCHEMA_VERSION}")
    if not isinstance(show["primitives"], list):
        add("error", "invalid_type", "show.primitives must be an array")
        return findings
    ids = set()
    spans_by = {}
    for name, arrangement in arrangements.items():
        try:
            spans_by[name] = section_spans(arrangement)
        except (ValueError, KeyError, TypeError):
            spans_by[name] = {}
    for index, primitive in enumerate(show["primitives"]):
        where = f"primitives[{index}]"
        if not isinstance(primitive, dict) or primitive.get("kind") not in PRIMITIVE_FIELDS:
            add("error", "unknown_primitive", f"{where}.kind must be one of {', '.join(PRIMITIVE_FIELDS)}", index)
            continue
        kind = primitive["kind"]
        pid = primitive.get("id", index)
        if "id" in primitive:
            if not isinstance(pid, str) or not re.fullmatch(r"[a-z0-9_\-]{1,48}", pid) or pid in ids:
                add("error", "duplicate_id" if pid in ids else "invalid_value",
                    f"{where}.id must be unique, lowercase [a-z0-9_-]{{1,48}}", index)
            ids.add(pid)
        required, optional = PRIMITIVE_FIELDS[kind]
        if not fields(primitive, required | {"kind"}, optional | _COMMON, f"{where} ({kind})", pid):
            continue
        if "anchor" in primitive:
            anchor_ok(primitive["anchor"], where + ".anchor", pid)
        for key in ("start_beat", "end_beat", "beat"):
            if key in primitive:
                beat_ok(primitive[key], f"{where}.{key}", pid)
        for key in ("track", "object_id"):
            if key in primitive and (not isinstance(primitive[key], str) or not primitive[key].strip()):
                add("error", "invalid_value", f"{where}.{key} must be a nonempty string", pid)
        for key in ("material", "prefab"):
            if key in primitive and not isinstance(primitive[key], str):
                add("error", "invalid_value", f"{where}.{key} must be an asset path string", pid)
        if kind == "setup":
            if "beat" in primitive and primitive["beat"] not in (0, "0"):
                add("error", "invalid_value", "setup runs at beat 0 only", pid)
            for key, event in (("screen_textures", "CreateScreenTexture"), ("cameras", "CreateCamera")):
                items = primitive.get(key, [])
                if not isinstance(items, list):
                    add("error", "invalid_type", f"{where}.{key} must be an array", pid)
                    continue
                for n, item in enumerate(items):
                    fields(item, *vivify.EVENT_FIELDS[event], f"{where}.{key}[{n}]", pid)
            if "rendering" in primitive:
                fields(primitive["rendering"], (), ("renderSettings", "qualitySettings", "xrSettings", "duration",
                                                    "easing"), f"{where}.rendering", pid)
            if "camera_properties" in primitive:
                fields(primitive["camera_properties"], (), ("depthTextureMode", "clearFlags", "backgroundColor",
                                                            "culling", "bloomPrePass", "mainEffect"),
                       f"{where}.camera_properties", pid)
            if "player_tracks" in primitive:
                tracks = primitive["player_tracks"]
                if not isinstance(tracks, dict) or not all(k in vivify.PLAYER_TARGETS and isinstance(v, str) and v
                                                           for k, v in tracks.items()):
                    add("error", "invalid_value", f"{where}.player_tracks maps {'/'.join(vivify.PLAYER_TARGETS)} "
                                                  "to track names", pid)
        if kind == "look":
            if "order" in primitive and primitive["order"] not in vivify.BLIT_ORDERS:
                add("error", "invalid_value", f"{where}.order must be one of {', '.join(vivify.BLIT_ORDERS)}", pid)
            for key in ("priority", "pass"):
                if key in primitive and type(primitive[key]) is not int:
                    add("error", "invalid_value", f"{where}.{key} must be an integer", pid)
            if "easing" in primitive and primitive["easing"] not in vivify.EASINGS:
                add("error", "invalid_value", f"{where}.easing is not an easing name", pid)
            for n, prop in enumerate(primitive.get("properties", []) if isinstance(primitive.get("properties", []), list) else [None]):
                if fields(prop, ("id", "value"), ("type",), f"{where}.properties[{n}]", pid):
                    points_ok(prop["value"], f"{where}.properties[{n}].value", pid)
            material_keyframes(primitive.get("keyframes", []), where + ".keyframes", pid, False)
        if kind == "scene":
            for key in ("position", "localPosition", "rotation", "localRotation", "scale"):
                if key in primitive and not (isinstance(primitive[key], list) and len(primitive[key]) == 3
                                             and all(_number(v) for v in primitive[key])):
                    add("error", "invalid_value", f"{where}.{key} must be [x, y, z]", pid)
            if "persist" in primitive and type(primitive["persist"]) is not bool:
                add("error", "invalid_value", f"{where}.persist must be a boolean", pid)
            keyframes(primitive.get("animate", []), where + ".animate", pid, {"beat"}, {"repeat"},
                      vivify.NOODLE_TRACK_PROPERTIES | {"color"}, need_prop=True)
            material_keyframes(primitive.get("keyframes", []), where + ".keyframes", pid, True)
            keyframes(primitive.get("animator", []), where + ".animator", pid, {"beat", "properties"}, set())
            for n, item in enumerate(primitive.get("animator", []) if isinstance(primitive.get("animator", []), list) else []):
                for m, prop in enumerate(item.get("properties", []) if isinstance(item, dict) and isinstance(item.get("properties"), list) else []):
                    if fields(prop, ("id", "type", "value"), (), f"{where}.animator[{n}].properties[{m}]", pid) \
                            and prop["type"] not in vivify.ANIMATOR_TYPES:
                        add("error", "invalid_value", f"animator property type must be one of "
                                                      f"{', '.join(vivify.ANIMATOR_TYPES)}", pid)
        if kind == "skin":
            groups = [g for g in vivify.OBJECT_PREFAB_FIELDS if g in primitive]
            if not groups:
                add("error", "missing_field", f"{where} assigns nothing; give colorNotes, bombNotes, burstSliders, "
                                              "burstSliderElements or saber", pid)
            for group in groups:
                allowed = vivify.OBJECT_PREFAB_FIELDS[group] - {"track"}
                fields(primitive[group], (), allowed, f"{where}.{group}", pid)
            if "load_mode" in primitive and primitive["load_mode"] not in vivify.LOAD_MODES:
                add("error", "invalid_value", f"{where}.load_mode must be Single or Additive", pid)
            saber = primitive.get("saber")
            if isinstance(saber, dict) and "type" in saber and saber["type"] not in vivify.SABER_TYPES:
                add("error", "invalid_value", f"{where}.saber.type must be Left, Right or Both", pid)
        if kind == "pulse":
            targets = [k for k in ("material", "global", "track") if k in primitive]
            if len(targets) != 1:
                add("error", "invalid_value", f"{where} targets exactly one of material, global or track", pid)
            if "global" in primitive and (primitive["global"] is not True or "type" not in primitive):
                add("error", "invalid_value", f"{where}: a global pulse is \"global\": true plus the property type", pid)
            if "type" in primitive and primitive["type"] not in vivify.PROPERTY_TYPES:
                add("error", "invalid_value", f"{where}.type must be one of {', '.join(vivify.PROPERTY_TYPES)}", pid)
            if "track" in primitive and primitive.get("property") not in vivify.NOODLE_TRACK_PROPERTIES | {"color"}:
                add("error", "invalid_value", f"{where}.property must be a track property for a track pulse", pid)
            _driver(primitive["driver"], where + ".driver", pid, add, fields)
            envelope = primitive.get("envelope", {})
            if fields(envelope, (), ("peak", "base", "attack_beats", "decay_beats", "release_beats", "easing",
                                     "scale_by_strength"), where + ".envelope", pid):
                for key in ("peak", "base"):
                    if key in envelope and not (_number(envelope[key]) or isinstance(envelope[key], list)
                                                and all(_number(v) for v in envelope[key])):
                        add("error", "invalid_value", f"{where}.envelope.{key} must be a number or a list", pid)
                for key in ("attack_beats", "decay_beats", "release_beats"):
                    if key in envelope:
                        beat_ok(envelope[key], f"{where}.envelope.{key}", pid)
                if "easing" in envelope and envelope["easing"] not in vivify.EASINGS:
                    add("error", "invalid_value", f"{where}.envelope.easing is not an easing name", pid)
            if "min_gap_beats" in primitive:
                beat_ok(primitive["min_gap_beats"], where + ".min_gap_beats", pid)
            if "max_events" in primitive and (type(primitive["max_events"]) is not int or primitive["max_events"] < 1):
                add("error", "invalid_value", f"{where}.max_events must be a positive integer", pid)
        if kind == "possess":
            if primitive["target"] not in vivify.PLAYER_TARGETS:
                add("error", "invalid_value", f"{where}.target must be one of {', '.join(vivify.PLAYER_TARGETS)}", pid)
            keyframes(primitive.get("animate", []), where + ".animate", pid, {"beat"}, {"repeat"},
                      vivify.NOODLE_TRACK_PROPERTIES, need_prop=True)
        if kind == "env":
            if not any(k in primitive for k in ("environment", "materials", "animate")):
                add("error", "missing_field", f"{where} changes nothing; give environment, materials or animate", pid)
            for n, entry in enumerate(primitive.get("environment", []) if isinstance(primitive.get("environment", []), list) else [None]):
                if fields(entry, (), vivify.ENVIRONMENT_FIELDS, f"{where}.environment[{n}]", pid):
                    if "id" in entry and entry.get("lookupMethod") not in vivify.LOOKUP_METHODS:
                        add("error", "invalid_value", f"{where}.environment[{n}] with an id needs lookupMethod "
                                                      f"{'/'.join(vivify.LOOKUP_METHODS)}", pid)
                    if "id" not in entry and "geometry" not in entry:
                        add("error", "missing_field", f"{where}.environment[{n}] needs an id or a geometry", pid)
            materials = primitive.get("materials", {})
            if not isinstance(materials, dict):
                add("error", "invalid_type", f"{where}.materials must be an object", pid)
            for name, material in (materials.items() if isinstance(materials, dict) else []):
                if fields(material, ("shader",), vivify.MATERIAL_FIELDS - {"shader"}, f"{where}.materials.{name}", pid) \
                        and material["shader"] not in vivify.CHROMA_SHADERS:
                    add("error", "invalid_value", f"{where}.materials.{name}.shader must be one of "
                                                  f"{', '.join(vivify.CHROMA_SHADERS)}", pid)
            keyframes(primitive.get("animate", []), where + ".animate", pid, {"beat", "track", "component", "fields"}, set())
            for n, item in enumerate(primitive.get("animate", []) if isinstance(primitive.get("animate", []), list) else []):
                if isinstance(item, dict) and "component" in item:
                    allowed = vivify.CHROMA_COMPONENTS.get(item["component"])
                    if allowed is None:
                        add("error", "invalid_value", f"{where}.animate[{n}].component must be one of "
                                                      f"{', '.join(vivify.CHROMA_COMPONENTS)}", pid)
                    elif not isinstance(item.get("fields"), dict) or not item["fields"] or set(item["fields"]) - allowed:
                        add("error", "invalid_value", f"{where}.animate[{n}].fields must animate some of "
                                                      f"{', '.join(sorted(allowed))}", pid)
                    else:
                        for field, value in item["fields"].items():
                            points_ok(value, f"{where}.animate[{n}].fields.{field}", pid)
        if kind == "path":
            if not _number(primitive["njs"], 1, 40):
                add("error", "invalid_value", f"{where}.njs must be a number in 1..40", pid)
            if not _number(primitive["offset"], -4, 16):
                add("error", "invalid_value", f"{where}.offset must be a number in -4..16 beats", pid)
            if "colors" in primitive and (not isinstance(primitive["colors"], list) or not primitive["colors"]
                                          or any(c not in (0, 1) for c in primitive["colors"])):
                add("error", "invalid_value", f"{where}.colors must list 0 and/or 1", pid)
            if "world_rotation" in primitive and not (isinstance(primitive["world_rotation"], list)
                                                      and len(primitive["world_rotation"]) == 3
                                                      and all(_number(v) for v in primitive["world_rotation"])):
                add("error", "invalid_value", f"{where}.world_rotation must be [x, y, z] degrees", pid)
            if "animation" in primitive:
                animation = primitive["animation"]
                if fields(animation, (), vivify.NOODLE_PATH_PROPERTIES | {"color"}, where + ".animation", pid):
                    for prop, value in animation.items():
                        points_ok(value, f"{where}.animation.{prop}", pid)
            keyframes(primitive.get("keyframes", []), where + ".keyframes", pid, {"beat"}, set(),
                      vivify.NOODLE_PATH_PROPERTIES | {"color"}, need_prop=True)
        if kind == "raw":
            event = primitive["event"]
            if fields(event, ("b", "t", "d"), (), where + ".event", pid):
                beat_ok(event["b"], where + ".event.b", pid)
                spec = vivify.EVENT_FIELDS.get(event["t"])
                if spec is None:
                    add("error", "raw_unknown_event", f"{where}.event.t {event['t']!r} is not a known Vivify, Heck or "
                                                      "Chroma event", pid)
                elif event["t"] == "AnimateComponent":
                    if not isinstance(event["d"], dict) or "track" not in event["d"] or \
                            set(event["d"]) - {"track", "duration", "easing"} - set(vivify.CHROMA_COMPONENTS):
                        add("error", "raw_invalid_field", f"{where}.event.d needs a track and known components", pid)
                elif not isinstance(event["d"], dict) or set(spec[0]) - set(event["d"]) \
                        or set(event["d"]) - set(spec[0]) - set(spec[1]):
                    add("error", "raw_invalid_field", f"{where}.event.d for {event['t']} requires "
                                                      f"{sorted(spec[0])} and allows {sorted(spec[1])}", pid)
            if "persist" in primitive and type(primitive["persist"]) is not bool:
                add("error", "invalid_value", f"{where}.persist must be a boolean", pid)
        # Section references and spans hold for every difficulty the show compiles into.
        for name, spans in spans_by.items():
            try:
                start, end = primitive_span(primitive, spans)
            except ShowError as exc:
                add("error", exc.code, f"{where}: {exc} in {name}", pid, primitive.get("section"), name)
                continue
            except (ValueError, TypeError, KeyError):
                continue
            section = primitive.get("section")
            if section is not None and kind in _SPAN_KINDS:
                low, high = spans[section]
                limit = spans[primitive["until_section"]][1] if primitive.get("until_section") in spans else high
                if not low <= start < high or end > limit or end <= start:
                    add("error", "outside_section", f"{where} spans beats {float(start):g}-{float(end):g}, outside "
                                                    f"section {section} ({float(low):g}-{float(limit):g}) in {name}",
                        pid, section, name)
                    continue
            for key in ("keyframes", "animate", "animator"):
                for n, item in enumerate(primitive.get(key, []) if isinstance(primitive.get(key), list) else []):
                    try:
                        at = beat(item["beat"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    if kind in _SPAN_KINDS and not start <= at <= end:
                        add("error", "keyframe_outside_span", f"{where}.{key}[{n}] at beat {float(at):g} lies outside "
                                                              f"the primitive's beats {float(start):g}-{float(end):g}",
                            pid, section, name)
    return findings


def _driver(driver, where, pid, add, fields):
    if not isinstance(driver, dict) or driver.get("source") not in DRIVER_SOURCES:
        add("error", "invalid_driver", f"{where}.source must be one of {', '.join(DRIVER_SOURCES)}", pid)
        return
    source = driver["source"]
    optional = {"onsets": {"layer", "detector", "min_strength", "run"},
                "sustains": {"layer", "min_strength", "min_seconds", "shapes", "run"},
                "moments": {"kinds", "min_strength", "run"},
                "lyrics": {"words", "min_strength", "run"}}[source]
    required = {"layer"} if source in ("onsets", "sustains") else set()
    if not fields(driver, required | {"source"}, optional, where, pid):
        return
    if "min_strength" in driver and not _number(driver["min_strength"], 0, 1):
        add("error", "invalid_driver", f"{where}.min_strength must be 0..1", pid)
    if "min_seconds" in driver and not _number(driver["min_seconds"], 0):
        add("error", "invalid_driver", f"{where}.min_seconds must be nonnegative", pid)
    if "shapes" in driver and (not isinstance(driver["shapes"], list) or set(driver["shapes"]) - set(SUSTAIN_SHAPES)):
        add("error", "invalid_driver", f"{where}.shapes must list {', '.join(SUSTAIN_SHAPES)}", pid)
    for key in ("kinds", "words"):
        if key in driver and (not isinstance(driver[key], list) or not all(isinstance(v, str) and v for v in driver[key])):
            add("error", "invalid_driver", f"{where}.{key} must list nonempty strings", pid)
    if "run" in driver and (not isinstance(driver["run"], str) or not re.fullmatch(r"[a-f0-9]{32}", driver["run"])):
        add("error", "invalid_driver", f"{where}.run must be a musical evidence run ID", pid)


# ---------------------------------------------------------------- evidence (drivers and anchors)

def evidence_context(project_dir: str | Path | None, run_id: str | None, report: dict | None,
                     arrangement: dict) -> dict:
    return {"project_dir": Path(project_dir) if project_dir else None, "run_id": run_id, "report": report,
            "arrangement": arrangement, "_reports": {run_id: report} if run_id else {}}


def _report(ctx: dict, run_id: str | None) -> tuple[str | None, dict | None]:
    if run_id is None or run_id == ctx["run_id"]:
        return ctx["run_id"], ctx["report"]
    if run_id not in ctx["_reports"]:
        path = ctx["project_dir"] / "musical" / run_id / "report.json" if ctx["project_dir"] else None
        if path is None or not path.is_file():
            raise ShowError("evidence_run_missing", f"musical evidence run {run_id} does not exist; list runs with "
                                                    "`music list PROJECT`")
        ctx["_reports"][run_id] = read_json(path)
    return run_id, ctx["_reports"][run_id]


def _external(source: str, ctx: dict, run_id: str | None, report: dict | None) -> list[dict]:
    """Moments or lyrics: ``report[source]``, else ``<run>/<source>.json``, else ``<project>/<source>.json``.

    Accepted item shape: {id?, seconds|start_seconds|start|time, end_seconds|end?, strength|confidence?,
    kind|type|word|text?}; the container may be a list or an object with items/<source>/words.
    """
    data = (report or {}).get(source)
    base = ctx["project_dir"]
    if data is None and base is not None:
        for path in ([base / "musical" / run_id / f"{source}.json"] if run_id else []) + [base / f"{source}.json"]:
            if path.is_file():
                data = read_json(path)
                break
    if isinstance(data, dict):
        data = data.get("items") or data.get(source) or data.get("words")
    if not isinstance(data, list):
        raise ShowError("driver_source_unavailable",
                        f"no {source} evidence exists for this project yet (looked in the musical run report, "
                        f"musical/<run>/{source}.json and {source}.json); analyze {source} first or drive the "
                        "primitive from onsets or sustains")
    items = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        seconds = next((item[k] for k in ("seconds", "start_seconds", "start", "time") if _number(item.get(k))), None)
        if seconds is None:
            continue
        end = next((item[k] for k in ("end_seconds", "end") if _number(item.get(k))), None)
        label = next((item[k] for k in ("kind", "type", "word", "text", "label") if isinstance(item.get(k), str)), None)
        strength = item.get("strength", item.get("confidence", 1.0))
        items.append({"source": source, "id": str(item.get("id") or f"{source}:{index}"), "seconds": float(seconds),
                      **({"end_seconds": float(end)} if end is not None and end > seconds else {}),
                      "strength": float(strength) if _number(strength) else 1.0, "label": label})
    return items


def resolve_driver(driver: dict, ctx: dict) -> list[dict]:
    """Evidence items a driver binds to: {source, id, seconds, end_seconds?, strength, label?}."""
    source = driver["source"]
    run_id, report = _report(ctx, driver.get("run"))
    minimum = driver.get("min_strength", 0)
    if source in ("onsets", "sustains"):
        if report is None:
            raise ShowError("evidence_missing", "no musical evidence run matches this project's audio; run "
                                                "`music analyze PROJECT` before compiling evidence-driven pulses")
        layers = report.get("layers") or {}
        layer = driver["layer"]
        if layer not in layers:
            raise ShowError("unknown_layer", f"layer {layer!r} is not in run {run_id} (layers: {', '.join(layers)})")
        if source == "onsets":
            detector = driver.get("detector")
            return [{"source": "onsets", "id": e["id"], "seconds": float(e["seconds"]),
                     "strength": float(e.get("strength", 1.0)), "label": e.get("method"), "run": run_id}
                    for e in layers[layer].get("events", [])
                    if (detector is None or e.get("method") == detector) and e.get("strength", 1.0) >= minimum]
        shapes = set(driver.get("shapes") or SUSTAIN_SHAPES)
        return [{"source": "sustains", "id": s["id"], "seconds": float(s["start_seconds"]),
                 "end_seconds": float(s["end_seconds"]), "strength": float(s.get("strength", 1.0)),
                 "label": s.get("pitch_shape"), "run": run_id}
                for s in layers[layer].get("sustains", [])
                if s.get("strength", 1.0) >= minimum and s.get("pitch_shape", "flat") in shapes
                and s["end_seconds"] - s["start_seconds"] >= driver.get("min_seconds", 0)]
    items = [i for i in _external(source, ctx, run_id, report) if i["strength"] >= minimum]
    if source == "moments" and driver.get("kinds"):
        kinds = set(driver["kinds"])
        items = [i for i in items if i["label"] in kinds]
    if source == "lyrics" and driver.get("words"):
        words = {w.casefold() for w in driver["words"]}
        items = [i for i in items if re.sub(r"[^\w']", "", (i["label"] or "").casefold()) in words]
    return items


def resolve_anchor(anchor: dict, ctx: dict) -> dict:
    """The evidence item an explicit anchor names; raises ShowError when it does not exist."""
    source = anchor["source"]
    if source == "section":
        spans = section_spans(ctx["arrangement"])
        if anchor.get("id") not in spans:
            raise ShowError("invalid_anchor", f"anchor section {anchor.get('id')!r} does not exist")
        return {"source": "section_boundary", "id": anchor["id"]}
    if source in ("onsets", "sustains"):
        report = ctx["report"]
        if report is None:
            raise ShowError("evidence_missing", "no musical evidence run matches this project's audio; run "
                                                "`music analyze PROJECT` first")
        for name, layer in (report.get("layers") or {}).items():
            pool = layer.get("events", []) if source == "onsets" else layer.get("sustains", [])
            for item in pool:
                if item.get("id") == anchor.get("id"):
                    return {"source": source, "id": item["id"], "run": ctx["run_id"],
                            "seconds": float(item.get("seconds", item.get("start_seconds", 0))),
                            "strength": item.get("strength")}
        raise ShowError("invalid_anchor", f"{source} evidence {anchor.get('id')!r} is not in run {ctx['run_id']}")
    items = _external(source, ctx, ctx["run_id"], ctx["report"])
    for item in items:
        if item["id"] == anchor.get("id") or (source == "lyrics" and anchor.get("word")
                                             and (item["label"] or "").casefold() == anchor["word"].casefold()):
            return item
    raise ShowError("invalid_anchor", f"{source} item {anchor.get('id') or anchor.get('word')!r} does not exist")


# ---------------------------------------------------------------- storage

def show_path(project_dir: Path) -> Path:
    return project_dir / "show.json"


def load_show(project_dir: Path) -> dict | None:
    path = show_path(project_dir)
    return read_json(path) if path.is_file() else None


def bundle_directory(project_dir: Path) -> Path:
    """Where a project's Vivify bundle set lives: bundleinfo.json + bundle*.vivify."""
    return project_dir / "assets"


def show_record(project_dir: Path, arrangements: dict[str, dict]) -> dict:
    """The stored show, its revision, what it was written against and its structural diagnostics."""
    show = load_show(project_dir)
    meta_path = project_dir / "show.meta.json"
    meta = read_json(meta_path) if meta_path.is_file() else {}
    revision = show_revision(show)
    written = meta.get("written_against", {}) if meta.get("revision") == revision else {}
    current = {name: arrangement_revision(a) for name, a in arrangements.items()}
    try:
        bundle = vivify.bundle_summary(vivify.read_bundle(bundle_directory(project_dir)))
        bundle_error = None
    except vivify.BundleError as exc:
        bundle, bundle_error = None, {"code": exc.code, "message": str(exc)}
    return {"document": show, "revision": revision, "written_against": written,
            "stale_difficulties": sorted(name for name, sha in current.items() if written.get(name) not in (None, sha)),
            "saved_at": meta.get("saved_at") if written else None,
            "bundle": bundle, "bundle_error": bundle_error,
            "diagnostics": validate_show(show, arrangements) if show is not None else []}


def save_show(store, project_id: str, show: dict, expected_revision: str) -> dict:
    """Revision-aware show write; refuses stale revisions, structural errors and edits over locked sections."""
    from .projects import ConflictError
    with store.lock:
        path = store.directory(project_id)
        arrangements = {name: read_json(file) for name, file in store.difficulty_files(path).items()}
        original = load_show(path)
        old_revision = show_revision(original)
        if expected_revision != old_revision:
            raise ConflictError(f"The show changed since you read it (it is now at {old_revision}); reread it with "
                                "`show get` and reapply your edit")
        blocking = [d for d in validate_show(show, arrangements)
                    if d["severity"] == "error" and d["code"] in SAVE_BLOCKING]
        if blocking:
            raise ShowError("show_invalid", "; ".join(f"{d['code']}: {d['message']}" for d in blocking[:10]))
        changed = _changed_primitives(original, show)
        for name, arrangement in arrangements.items():
            spans = section_spans(arrangement)
            locked = [s["id"] for s in arrangement["sections"] if s.get("locked")]
            for primitive in changed:
                try:
                    span = primitive_span(primitive, spans)
                except (ShowError, ValueError, TypeError, KeyError):
                    continue
                hit = [sid for sid in locked if touches(span, spans[sid])]
                if hit:
                    raise ConflictError(f"A show edit ({primitive.get('kind')} {primitive.get('id', '')}".rstrip()
                                        + f") touches locked section(s) {', '.join(hit)} of {name}. Unlock them first.")
        revision = show_revision(show)
        written = {name: arrangement_revision(a) for name, a in arrangements.items()}
        if original is not None:
            write_json(path / "show-history" / (old_revision + ".json"), original)
        write_json(path / "show-history" / (revision + ".json"), show)
        write_json(show_path(path), show)
        write_json(path / "show.meta.json", {"schema_version": "1.0", "revision": revision,
                                             "written_against": written, "saved_at": now()})
        write_json(path / "revisions" / (uuid.uuid4().hex + ".json"),
                   {"schema_version": "1.0", "operation": "save_show", "previous": old_revision,
                    "revision": revision, "written_against": written, "at": now()})
        meta = read_json(path / "project.json")
        meta.update(updated_at=now(), playtested=False)
        write_json(path / "project.json", meta)
        return show_record(path, arrangements)


def _changed_primitives(before: dict | None, after: dict) -> list[dict]:
    def canon(p):
        return json.dumps(p, sort_keys=True, separators=(",", ":"))
    old = [canon(p) for p in (before or {}).get("primitives", [])]
    new = [canon(p) for p in after.get("primitives", [])]
    remaining = list(old)
    added = []
    for text in new:
        if text in remaining:
            remaining.remove(text)
        else:
            added.append(text)
    return [json.loads(text) for text in added + remaining]
