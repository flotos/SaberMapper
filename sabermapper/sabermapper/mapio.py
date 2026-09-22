"""Loss-aware Beat Saber v2/v3 gameplay map normalization.

Unknown collections and mod custom data are retained in ``unsupported`` with
their original values. This parser intentionally does not accept v4 beatmaps.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite


def _number(value, path, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{path} must be a finite number") from exc
    if not isfinite(value) or (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{path} must be {'positive' if positive else 'nonnegative'} and finite")
    return value


def _real(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be finite")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{path} must be finite") from exc
    if not isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _int(value, path, low, high):
    if type(value) is not int or value < low or value > high:
        raise ValueError(f"{path} must be integer {low}..{high}")
    return value


def _signed_int(value, path):
    if type(value) is not int:
        raise ValueError(f"{path} must be an integer")
    return value


def _array(data, key):
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    return value


def parse_map(data: dict, *, bpm=120.0, audio_offset_seconds=0.0, provenance=None) -> dict:
    """Parse v2/v3 gameplay objects and derive piecewise native-tempo seconds.

    ``audio_offset_seconds`` is added to every event timestamp. Custom editor
    BPM data is recorded as unsupported; it never alters native game tempo.
    """
    if not isinstance(data, dict):
        raise ValueError("beatmap must be an object")
    version = data.get("version", data.get("_version"))
    if not isinstance(version, str) or version.split(".")[0] not in ("2", "3"):
        raise ValueError("only v2 and v3 beatmaps are supported")
    major = int(version.split(".")[0])
    base_bpm = _number(bpm, "bpm", positive=True)
    if isinstance(audio_offset_seconds, bool) or not isinstance(audio_offset_seconds, (int, float)):
        raise ValueError("audio_offset_seconds must be finite")
    try:
        offset = float(audio_offset_seconds)
    except OverflowError as exc:
        raise ValueError("audio_offset_seconds must be finite") from exc
    if not isfinite(offset):
        raise ValueError("audio_offset_seconds must be finite")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be an object")
    unsupported = []

    def unknown(path, reason, value):
        unsupported.append({"path": path, "reason": reason, "value": deepcopy(value)})

    known_top = ({"_version", "_notes", "_obstacles", "_events", "_waypoints", "_sliders", "_burstSliders",
                  "_customData", "_specialEventsKeywordFilters", "_BPMChanges"} if major == 2 else
                 {"version", "bpmEvents", "rotationEvents", "colorNotes", "bombNotes", "obstacles", "sliders",
                  "burstSliders", "waypoints", "basicBeatmapEvents", "colorBoostBeatmapEvents",
                  "lightColorEventBoxGroups", "lightRotationEventBoxGroups", "lightTranslationEventBoxGroups",
                  "vfxEventBoxGroups", "fxEventBoxGroups", "customData"})
    for key, value in data.items():
        if key not in known_top:
            unknown(key, "unknown top-level field", value)
    for key in (("_customData", "_specialEventsKeywordFilters", "_BPMChanges", "_waypoints") if major == 2 else
                ("customData", "rotationEvents", "waypoints", "basicBeatmapEvents", "colorBoostBeatmapEvents",
                 "lightColorEventBoxGroups", "lightRotationEventBoxGroups", "lightTranslationEventBoxGroups",
                 "vfxEventBoxGroups", "fxEventBoxGroups")):
        if key in data and data[key]:
            unknown(key, "preserved but not interpreted", data[key])

    raw_tempo = []
    if major == 3:
        for i, item in enumerate(_array(data, "bpmEvents")):
            if not isinstance(item, dict):
                raise ValueError(f"bpmEvents[{i}] must be an object")
            raw_tempo.append((_number(item.get("b"), f"bpmEvents[{i}].b"),
                              _number(item.get("m"), f"bpmEvents[{i}].m", positive=True), i))
            for key in item.keys() - {"b", "m"}:
                unknown(f"bpmEvents[{i}].{key}", "unknown BPM field", item[key])
    else:
        for i, item in enumerate(_array(data, "_events")):
            if not isinstance(item, dict):
                raise ValueError(f"_events[{i}] must be an object")
            if item.get("_type") == 100:
                if "_floatValue" not in item:
                    # Pre-2.5 editors emitted type 100 with other payloads; keep
                    # the evidence instead of failing the whole map.
                    unknown(f"_events[{i}]", "legacy BPM event without _floatValue not interpreted", item)
                    continue
                raw_tempo.append((_number(item.get("_time"), f"_events[{i}]._time"),
                                  _number(item["_floatValue"], f"_events[{i}]._floatValue", positive=True), i))
            else:
                unknown(f"_events[{i}]", "lighting or rotation event not interpreted", item)
    raw_tempo.sort(key=lambda row: (row[0], row[2]))
    tempo = [{"beat": 0.0, "bpm": base_bpm, "seconds": offset}]
    for beat, value, index in raw_tempo:
        previous = tempo[-1]
        seconds = previous["seconds"] + (beat - previous["beat"]) * 60 / previous["bpm"]
        if not isfinite(seconds):
            raise ValueError("tempo event time overflow")
        event = {"beat": beat, "bpm": value, "seconds": seconds}
        if beat == previous["beat"]:
            tempo[-1] = event
        else:
            tempo.append(event)

    def seconds_at(beat):
        previous = tempo[0]
        for event in tempo[1:]:
            if event["beat"] > beat:
                break
            previous = event
        result = previous["seconds"] + (beat - previous["beat"]) * 60 / previous["bpm"]
        if not isfinite(result):
            raise ValueError("object time overflow")
        return result

    result = {"schema_version": "1.0", "format_version": version,
              "notes": [], "bombs": [], "obstacles": [], "arcs": [], "chains": [],
              "tempo_events": tempo, "unsupported": unsupported,
              "source": deepcopy(provenance) if provenance else {}}

    def inspect(item, path, fields):
        if not isinstance(item, dict):
            raise ValueError(f"{path} must be an object")
        for key in item.keys() - fields:
            unknown(f"{path}.{key}", "uninterpreted object field", item[key])

    def spatial(item, path, xkey, ykey):
        return _int(item.get(xkey), f"{path}.{xkey}", 0, 3), _int(item.get(ykey), f"{path}.{ykey}", 0, 2)

    note_key = "_notes" if major == 2 else "colorNotes"
    for i, item in enumerate(_array(data, note_key)):
        path = f"{note_key}[{i}]"
        if major == 2:
            inspect(item, path, {"_time", "_lineIndex", "_lineLayer", "_type", "_cutDirection", "_customData"})
            beat = _number(item.get("_time"), path + "._time")
            x, y = spatial(item, path, "_lineIndex", "_lineLayer")
            kind = item.get("_type")
            if kind == 3:
                result["bombs"].append({"id": f"bomb:{i}", "beat": beat, "seconds": seconds_at(beat), "x": x, "y": y})
            else:
                color = _int(kind, path + "._type", 0, 1)
                direction = _int(item.get("_cutDirection"), path + "._cutDirection", 0, 8)
                result["notes"].append({"id": f"note:{i}", "beat": beat, "seconds": seconds_at(beat),
                                        "x": x, "y": y, "color": color, "direction": direction, "angle": 0.0})
            if item.get("_customData"):
                unknown(path + "._customData", "modded note data", item["_customData"])
        else:
            inspect(item, path, {"b", "x", "y", "c", "d", "a", "customData"})
            if any(key not in item for key in ("b", "x", "y", "c", "d")):
                unknown(path, "incomplete color note preserved without normalization", item)
                continue
            beat = _number(item.get("b"), path + ".b")
            x, y = spatial(item, path, "x", "y")
            angle = item.get("a", 0)
            try:
                angle_ok = not isinstance(angle, bool) and isinstance(angle, (int, float)) and isfinite(float(angle))
            except OverflowError:
                angle_ok = False
            if not angle_ok:
                raise ValueError(path + ".a must be finite")
            result["notes"].append({"id": f"note:{i}", "beat": beat, "seconds": seconds_at(beat),
                                    "x": x, "y": y, "color": _int(item.get("c"), path + ".c", 0, 1),
                                    "direction": _int(item.get("d"), path + ".d", 0, 8), "angle": float(angle)})
            if item.get("customData"):
                unknown(path + ".customData", "modded note data", item["customData"])

    if major == 3:
        for i, item in enumerate(_array(data, "bombNotes")):
            path = f"bombNotes[{i}]"
            inspect(item, path, {"b", "x", "y", "customData"})
            if any(key not in item for key in ("b", "x", "y")):
                unknown(path, "incomplete bomb preserved without normalization", item)
                continue
            beat = _number(item.get("b"), path + ".b")
            x, y = spatial(item, path, "x", "y")
            result["bombs"].append({"id": f"bomb:{i}", "beat": beat, "seconds": seconds_at(beat), "x": x, "y": y})
            if item.get("customData"):
                unknown(path + ".customData", "modded bomb data", item["customData"])

    wall_key = "_obstacles" if major == 2 else "obstacles"
    for i, item in enumerate(_array(data, wall_key)):
        path = f"{wall_key}[{i}]"
        if isinstance(item, dict):
            duration_key, width_key = ("_duration", "_width") if major == 2 else ("d", "w")
            if item.get(duration_key) == 0 or item.get(width_key) == 0:
                unknown(path, "zero-size obstacle preserved without normalization", item)
                continue
        if major == 2:
            inspect(item, path, {"_time", "_duration", "_lineIndex", "_width", "_type", "_lineLayer", "_height", "_customData"})
            kind = _int(item.get("_type"), path + "._type", 0, 2)
            beat = _number(item.get("_time"), path + "._time")
            duration = _number(item.get("_duration"), path + "._duration", positive=True)
            x = _signed_int(item.get("_lineIndex"), path + "._lineIndex")
            width = _int(item.get("_width"), path + "._width", 1, 4)
            y = 0 if kind == 0 else (2 if kind == 1 else _int(item.get("_lineLayer"), path + "._lineLayer", 0, 2))
            height = 5 if kind == 0 else (3 if kind == 1 else _int(item.get("_height"), path + "._height", 1, 5))
            if item.get("_customData"):
                unknown(path + "._customData", "modded obstacle data", item["_customData"])
        else:
            inspect(item, path, {"b", "d", "x", "y", "w", "h", "customData"})
            beat = _number(item.get("b"), path + ".b")
            duration = _number(item.get("d"), path + ".d", positive=True)
            x = _signed_int(item.get("x"), path + ".x")
            y = _int(item.get("y"), path + ".y", 0, 2)
            width = _int(item.get("w"), path + ".w", 1, 4)
            height = _int(item.get("h"), path + ".h", 1, 5)
            if item.get("customData"):
                unknown(path + ".customData", "modded obstacle data", item["customData"])
        # Native wall positions may sit outside the four note lanes for
        # decorative edge walls. Preserve the signed lane without clipping.
        result["obstacles"].append({"id": f"wall:{i}", "beat": beat, "seconds": seconds_at(beat),
                                    "duration_beats": duration, "end_seconds": seconds_at(beat + duration),
                                    "x": x, "y": y, "width": width, "height": height})

    arc_key = "_sliders" if major == 2 else "sliders"
    chain_key = "_burstSliders" if major == 2 else "burstSliders"
    if major == 2:
        for i, item in enumerate(_array(data, arc_key)):
            path = f"{arc_key}[{i}]"
            inspect(item, path, {"_colorType", "_headTime", "_headLineIndex", "_headLineLayer",
                                 "_headCutDirection", "_headControlPointLengthMultiplier", "_tailTime",
                                 "_tailLineIndex", "_tailLineLayer", "_tailCutDirection",
                                 "_tailControlPointLengthMultiplier", "_sliderMidAnchorMode", "_customData"})
            beat = _number(item.get("_headTime"), path + "._headTime")
            tail = _number(item.get("_tailTime"), path + "._tailTime")
            if tail <= beat:
                unknown(path, "degenerate v2 arc preserved without normalization", item)
                continue
            x, y = spatial(item, path, "_headLineIndex", "_headLineLayer")
            tx, ty = spatial(item, path, "_tailLineIndex", "_tailLineLayer")
            result["arcs"].append({"id": f"arc:{i}", "beat": beat, "seconds": seconds_at(beat),
                                   "tail_beat": tail, "tail_seconds": seconds_at(tail),
                                   "x": x, "y": y, "tail_x": tx, "tail_y": ty,
                                   "color": _int(item.get("_colorType"), path + "._colorType", 0, 1),
                                   "direction": _int(item.get("_headCutDirection"), path + "._headCutDirection", 0, 8),
                                   "tail_direction": _int(item.get("_tailCutDirection"), path + "._tailCutDirection", 0, 8),
                                   "head_multiplier": _real(item.get("_headControlPointLengthMultiplier"), path + "._headControlPointLengthMultiplier"),
                                   "tail_multiplier": _real(item.get("_tailControlPointLengthMultiplier"), path + "._tailControlPointLengthMultiplier"),
                                   "mid_anchor": _int(item.get("_sliderMidAnchorMode"), path + "._sliderMidAnchorMode", 0, 2)})
            if item.get("_customData"):
                unknown(path + "._customData", "modded arc data", item["_customData"])
        for i, item in enumerate(_array(data, chain_key)):
            unknown(f"{chain_key}[{i}]", "v2 chain variant not normalized", item)
    else:
        for key, target, fields in ((arc_key, "arcs", {"c", "b", "x", "y", "d", "mu", "tb", "tx", "ty", "tc", "tmu", "m", "customData"}),
                                    (chain_key, "chains", {"c", "b", "x", "y", "d", "tb", "tx", "ty", "sc", "s", "customData"})):
            for i, item in enumerate(_array(data, key)):
                path = f"{key}[{i}]"
                inspect(item, path, fields)
                required = ({"c", "b", "x", "y", "d", "mu", "tb", "tx", "ty", "tc", "tmu", "m"}
                            if target == "arcs" else {"c", "b", "x", "y", "d", "tb", "tx", "ty", "sc", "s"})
                if not required <= item.keys():
                    unknown(path, "incomplete arc/chain preserved without normalization", item)
                    continue
                beat = _number(item.get("b"), path + ".b")
                tail = _number(item.get("tb"), path + ".tb")
                if tail <= beat:
                    unknown(path, "degenerate arc/chain preserved without normalization", item)
                    continue
                x, y = spatial(item, path, "x", "y")
                tx, ty = spatial(item, path, "tx", "ty")
                obj = {"id": f"{'arc' if target == 'arcs' else 'chain'}:{i}", "beat": beat,
                       "seconds": seconds_at(beat), "tail_beat": tail, "tail_seconds": seconds_at(tail),
                       "x": x, "y": y, "tail_x": tx, "tail_y": ty,
                       "color": _int(item.get("c"), path + ".c", 0, 1),
                       "direction": _int(item.get("d"), path + ".d", 0, 8)}
                if target == "arcs":
                    obj.update(tail_direction=_int(item.get("tc"), path + ".tc", 0, 8),
                               head_multiplier=_real(item.get("mu"), path + ".mu"),
                               tail_multiplier=_real(item.get("tmu"), path + ".tmu"),
                               mid_anchor=_int(item.get("m"), path + ".m", 0, 2))
                else:
                    obj.update(slice_count=_int(item.get("sc"), path + ".sc", 2, 100),
                               squish=_number(item.get("s"), path + ".s"))
                result[target].append(obj)
                if item.get("customData"):
                    unknown(path + ".customData", "modded arc/chain data", item["customData"])
    return result
