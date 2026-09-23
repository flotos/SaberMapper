"""Expand show 0.1 primitives into Vivify, Heck and Chroma v3 ``customData`` for one difficulty.

Every emitted custom event gets a provenance row (same index as ``customData.customEvents``):
the primitive it came from and the audio evidence, lyric word, moment or section boundary it
is grounded in. Provenance stays in a sidecar report, never in the beatmap.
"""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from fractions import Fraction

from .show import (ShowError, beat, evidence_context, primitive_span, resolve_anchor, resolve_driver,
                   section_spans)
from . import vivify

AUTO_TOLERANCE_BEATS = 0.125   # an event within 1/8 beat of an onset is grounded on it
AUTO_MIN_STRENGTH = 0.3
_TRACK_DIMS = {"dissolve": 1, "dissolveArrow": 1, "interactable": 1, "time": 1, "color": 4}
_TYPE_DIMS = {"Float": 1, "Color": 4, "Vector": 4}


def _num(value: Fraction | float) -> float:
    number = round(float(value), 6)
    return int(number) if number == int(number) else number


def _values(value, dims: int) -> list[float]:
    if isinstance(value, list):
        values = [float(v) for v in value]
        if dims == 4 and len(values) == 3:
            values.append(1.0)
        return values
    return [float(value)] * dims


def compile_show(show: dict, arrangement: dict, beatmap: dict, *, bundle: dict | None = None,
                 evidence: dict | None = None) -> dict:
    """Merge the show into ``beatmap`` in place; return provenance, diagnostics and derived facts.

    ``beatmap`` is the vanilla compile of ``arrangement`` (before the audio-offset shift).
    ``evidence`` is ``{"project_dir", "run_id", "report"}`` for drivers and anchors.
    """
    from .critique import beat_to_seconds
    from .musical import seconds_to_beat
    evidence = evidence or {}
    ctx = evidence_context(evidence.get("project_dir"), evidence.get("run_id"), evidence.get("report"), arrangement)
    spans = section_spans(arrangement)
    diagnostics, pending = [], []
    environment, materials = [], {}
    objects = {key: {} for key in ("colorNotes", "bombNotes", "burstSliders")}
    note_jump = {}
    persist_ids, state = set(), {}

    def diag(severity, code, message, index=None, section=None, **extra):
        diagnostics.append({"severity": severity, "code": code, "message": message, "primitive": index,
                            "section_id": section, "difficulty": arrangement["difficulty"]["name"], **extra})

    def emit(at, kind, data, meta, evidence_row=None, role=None, of=None):
        record = {"b": at, "order": len(pending), "event": {"b": _num(at), "t": kind, "d": data},
                  "row": {**meta, "role": role, "evidence": evidence_row}, "of": of}
        pending.append(record)
        return record

    def anchored(item, index, section):
        if not isinstance(item, dict) or "anchor" not in item:
            return None
        try:
            return {**resolve_anchor(item["anchor"], ctx), "explicit": True}
        except ShowError as exc:
            diag("error", exc.code, str(exc), index, section)
            return None

    def prop_type(material, prop, given, index, section):
        info = (bundle or {}).get("materials", {}).get(material.lower())
        if info and prop in info["properties"]:
            kind = info["properties"][prop]["type"]
            if given and given != kind:
                diag("error", "property_type_mismatch", f"{material} property {prop} is {kind} in bundleinfo.json, "
                                                        f"not {given}", index, section)
            return kind
        if given:
            return given
        diag("error", "property_type_unknown", f"type of {material} property {prop} is unknown: "
                                               + ("add the bundle's bundleinfo.json under assets/" if bundle is None else
                                                  "the property is not in bundleinfo.json") + " or give its type",
             index, section)
        return "Float"

    def default(material, prop):
        info = (bundle or {}).get("materials", {}).get(material.lower())
        entry = info["properties"].get(prop) if info else None
        return entry["default"] if entry and entry["type"] in _TYPE_DIMS else None

    def material_event(material, frame, meta, index, section):
        kind = prop_type(material, frame["property"], frame.get("type"), index, section)
        duration = beat(frame.get("duration_beats", 0))
        data = {"asset": material}
        if duration:
            data["duration"] = _num(duration)
        key = (material, frame["property"])
        if "points" in frame:
            value = deepcopy(frame["points"])
            if "easing" in frame:
                data["easing"] = frame["easing"]
            state.pop(key, None)
        else:
            target, previous = frame["value"], state.get(key, default(material, frame["property"]))
            if duration and previous is not None and kind in _TYPE_DIMS:
                dims = _TYPE_DIMS[kind]
                value = [[*_values(previous, dims), 0], [*_values(target, dims), 1]
                         + ([frame["easing"]] if "easing" in frame else [])]
            else:
                value = deepcopy(target)
            state[key] = target
        data["properties"] = [{"id": frame["property"], "type": kind, "value": value}]
        emit(beat(frame["beat"]), "SetMaterialProperty", data, meta, anchored(frame, index, section))

    def timed(item, extra_keys):
        data = {}
        duration = beat(item.get("duration_beats", 0))
        if duration:
            data["duration"] = _num(duration)
        if "easing" in item:
            data["easing"] = item["easing"]
        for key in extra_keys:
            if key in item:
                data[key] = deepcopy(item[key])
        return data

    def assign(group, index_key, span, value):
        start, end = span
        for i, obj in enumerate(beatmap.get(group, [])):
            if start <= Fraction(str(obj["b"])) < end:
                index_key.setdefault(i, []).append(value)

    for index, primitive in enumerate(show.get("primitives", [])):
        kind, pid = primitive["kind"], str(primitive.get("id", index))
        section = primitive.get("section")
        meta = {"primitive": index, "primitive_id": primitive.get("id"), "kind": kind, "section": section}
        try:
            span = primitive_span(primitive, spans)
        except ShowError as exc:
            diag("error", exc.code, str(exc), index, section)
            continue
        start = span[0]
        top = anchored(primitive, index, section)
        if kind == "setup":
            setup = {"source": "setup"}
            for item in primitive.get("screen_textures", []):
                emit(start, "CreateScreenTexture", deepcopy(item), meta, setup)
            for item in primitive.get("cameras", []):
                emit(start, "CreateCamera", deepcopy(item), meta, setup)
            if "camera_properties" in primitive:
                emit(start, "SetCameraProperty", {"properties": deepcopy(primitive["camera_properties"])}, meta, setup)
            if "rendering" in primitive:
                emit(start, "SetRenderingSettings", deepcopy(primitive["rendering"]), meta, setup)
            for target, track in primitive.get("player_tracks", {}).items():
                emit(start, "AssignPlayerToTrack", {"track": track, **({"target": target} if target != "Root" else {})},
                     meta, setup)
        elif kind == "look":
            material, end = primitive["material"], span[1]
            data = {"asset": material, "duration": _num(end - start)}
            for key in ("priority", "pass", "order", "source", "destination", "easing"):
                if key in primitive:
                    data[key] = primitive[key]
            properties = []
            for prop in primitive.get("properties", []):
                properties.append({"id": prop["id"], "type": prop_type(material, prop["id"], prop.get("type"), index,
                                                                       section), "value": deepcopy(prop["value"])})
                state[(material, prop["id"])] = prop["value"]
            if properties:
                data["properties"] = properties
            emit(start, "Blit", data, meta, top, role="blit")
            for frame in primitive.get("keyframes", []):
                material_event(frame.get("material", material), frame, meta, index, section)
        elif kind == "scene":
            object_id = primitive.get("object_id") or f"sm_scene_{pid}"
            track = primitive.get("track") or object_id
            data = {"asset": primitive["prefab"], "id": object_id, "track": track}
            for key in ("position", "localPosition", "rotation", "localRotation", "scale"):
                if key in primitive:
                    data[key] = deepcopy(primitive[key])
            spawn = emit(start, "InstantiatePrefab", data, meta, top, role="spawn")
            for item in primitive.get("animate", []):
                emit(beat(item["beat"]), "AnimateTrack",
                     {"track": track, **timed(item, ["repeat"] + sorted(vivify.NOODLE_TRACK_PROPERTIES | {"color"}))},
                     meta, anchored(item, index, section))
            for frame in primitive.get("keyframes", []):
                material_event(frame["material"], frame, meta, index, section)
            for item in primitive.get("animator", []):
                emit(beat(item["beat"]), "SetAnimatorProperty", {"id": object_id, **timed(item, ["properties"])},
                     meta, anchored(item, index, section))
            if primitive.get("persist"):
                persist_ids.add(object_id)
            else:
                emit(span[1], "DestroyObject", {"id": object_id}, meta, {"source": "lifetime"}, role="destroy", of=spawn)
        elif kind == "skin":
            track = primitive.get("track") or f"sm_skin_{pid}"
            data = {"loadMode": primitive["load_mode"]} if "load_mode" in primitive else {}
            for group in vivify.OBJECT_PREFAB_FIELDS:
                if group in primitive:
                    data[group] = deepcopy(primitive[group]) if group == "saber" else {"track": track,
                                                                                       **deepcopy(primitive[group])}
            emit(start, "AssignObjectPrefab", data, meta, top)
            for group, target in (("colorNotes", "colorNotes"), ("bombNotes", "bombNotes"),
                                  ("burstSliders", "burstSliders"), ("burstSliderElements", "burstSliders")):
                if group in primitive:
                    assign(target, objects[target], span, track)
        elif kind == "pulse":
            _pulse(primitive, span, meta, index, section, ctx, arrangement, emit, diag, prop_type, seconds_to_beat)
        elif kind == "possess":
            target = primitive["target"]
            emit(start, "AssignPlayerToTrack", {"track": primitive["track"],
                                                **({"target": target} if target != "Root" else {})}, meta, top)
            for item in primitive.get("animate", []):
                emit(beat(item["beat"]), "AnimateTrack",
                     {"track": primitive["track"], **timed(item, ["repeat"] + sorted(vivify.NOODLE_TRACK_PROPERTIES))},
                     meta, anchored(item, index, section))
        elif kind == "env":
            environment += deepcopy(primitive.get("environment", []))
            for name, material in primitive.get("materials", {}).items():
                if name in materials and materials[name] != material:
                    diag("error", "duplicate_material", f"environment material {name} is declared twice", index, section)
                materials[name] = deepcopy(material)
            for item in primitive.get("animate", []):
                emit(beat(item["beat"]), "AnimateComponent",
                     {"track": item["track"], **timed(item, []), item["component"]: deepcopy(item["fields"])},
                     meta, anchored(item, index, section))
        elif kind == "path":
            track = primitive.get("track") or f"sm_path_{pid}"
            for item in primitive.get("keyframes", []):
                emit(beat(item["beat"]), "AssignPathAnimation",
                     {"track": track, **timed(item, sorted(vivify.NOODLE_PATH_PROPERTIES | {"color"}))},
                     meta, anchored(item, index, section) or (top if beat(item["beat"]) == start else None))
            colors = set(primitive.get("colors", (0, 1)))
            jump = {"noteJumpMovementSpeed": primitive["njs"], "noteJumpStartBeatOffset": primitive["offset"]}
            if "animation" in primitive:
                jump["animation"] = deepcopy(primitive["animation"])
            if "world_rotation" in primitive:
                jump["worldRotation"] = list(primitive["world_rotation"])
            for i, note in enumerate(beatmap.get("colorNotes", [])):
                if note["c"] in colors and start <= Fraction(str(note["b"])) < span[1]:
                    objects["colorNotes"].setdefault(i, []).append(track)
                    if i in note_jump and note_jump[i] != jump:
                        diag("error", "note_path_conflict", f"note at beat {note['b']} is claimed by two path "
                                                            "primitives with different jump settings", index, section)
                    note_jump[i] = jump
        elif kind == "raw":
            event = primitive["event"]
            if primitive.get("persist"):
                persist_ids.update(_ids(event))
            emit(beat(event["b"]), event["t"], deepcopy(event["d"]), meta, top)

    # Order events by beat (stable), then ground every event without explicit evidence.
    pending.sort(key=lambda r: (r["b"], r["order"]))
    positions = {id(r): i for i, r in enumerate(pending)}
    onsets = _onset_index(ctx, arrangement, seconds_to_beat)
    boundaries = {start: sid for sid, (start, _) in spans.items()}
    provenance, ungrounded = [], {}
    for i, record in enumerate(pending):
        row, at = record["row"], record["b"]
        evidence_row = row["evidence"]
        if record["of"] is not None:
            evidence_row = {"source": "lifetime", "of_event": positions[id(record["of"])]}
        if evidence_row is None:
            evidence_row = _nearest(onsets, float(at))
        if evidence_row is None and at in boundaries:
            evidence_row = {"source": "section_boundary", "id": boundaries[at]}
        if evidence_row is None:
            ungrounded.setdefault(row["primitive"], []).append(_num(at))
        provenance.append({"event_index": i, "type": record["event"]["t"], "beat": _num(at),
                           "seconds": round(beat_to_seconds(float(at), arrangement), 6), **row,
                           "evidence": evidence_row})
    for index, beats in ungrounded.items():
        diag("warning", "visual_without_evidence",
             f"{len(beats)} event(s) of primitive {index} sit on no onset, section boundary, lyric or moment "
             f"(beats {', '.join(f'{b:g}' for b in beats[:8])}); move them onto the sound they illustrate or give "
             "an anchor", index, show["primitives"][index].get("section"), beats=beats)
    events = [record["event"] for record in pending]
    custom = {}
    if events:
        custom["customEvents"] = events
    if environment:
        custom["environment"] = environment
    if materials:
        custom["materials"] = materials
    if custom:
        beatmap["customData"] = custom
    note_data = []
    for group, tracks in objects.items():
        for i in sorted(set(tracks) | (set(note_jump) if group == "colorNotes" else set())):
            data = {}
            names = list(dict.fromkeys(tracks.get(i, [])))
            if names:
                data["track"] = names[0] if len(names) == 1 else names
            if group == "colorNotes" and i in note_jump:
                data.update(deepcopy(note_jump[i]))
            beatmap[group][i]["customData"] = data
            note_data.append(data)
    return {"difficulty": arrangement["difficulty"]["name"], "event_count": len(events),
            "provenance": provenance, "diagnostics": diagnostics,
            "requirements": vivify.requirements(custom, note_data), "persist_ids": sorted(persist_ids),
            "object_custom_data": {group: len(tracks) for group, tracks in objects.items()},
            "evidence_run": ctx["run_id"],
            "assets": sorted({path for e in events for path, _ in vivify.event_assets(e)})}


def _ids(event: dict) -> list[str]:
    value = (event.get("d") or {}).get("id")
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _onset_index(ctx, arrangement, seconds_to_beat):
    report = ctx["report"]
    rows = []
    for name, layer in ((report or {}).get("layers") or {}).items():
        for event in layer.get("events", []):
            if event.get("strength", 0) >= AUTO_MIN_STRENGTH and event.get("method") in ("spectral_flux", "energy_rise"):
                rows.append((seconds_to_beat(float(event["seconds"]), arrangement), event["id"], name,
                             float(event["strength"]), float(event["seconds"])))
    rows.sort()
    return rows


def _nearest(rows, at: float) -> dict | None:
    if not rows:
        return None
    position = bisect_left(rows, (at - AUTO_TOLERANCE_BEATS,))
    best = None
    while position < len(rows) and rows[position][0] <= at + AUTO_TOLERANCE_BEATS:
        if best is None or rows[position][3] > best[3]:
            best = rows[position]
        position += 1
    if best is None:
        return None
    return {"source": "onsets", "id": best[1], "layer": best[2], "strength": best[3], "seconds": best[4],
            "auto": True}


def _pulse(primitive, span, meta, index, section, ctx, arrangement, emit, diag, prop_type, seconds_to_beat):
    driver, envelope = primitive["driver"], primitive.get("envelope", {})
    try:
        items = resolve_driver(driver, ctx)
    except ShowError as exc:
        diag("error", exc.code, str(exc), index, section)
        return
    start, end = span
    prop = primitive["property"]
    if "material" in primitive:
        kind = prop_type(primitive["material"], prop, primitive.get("type"), index, section)
        dims = _TYPE_DIMS.get(kind, 1)
    elif "global" in primitive:
        kind, dims = primitive["type"], _TYPE_DIMS.get(primitive["type"], 1)
    else:
        kind, dims = None, _TYPE_DIMS.get(prop, 3)
    peak = _values(envelope.get("peak", 1), dims)
    base = _values(envelope.get("base", 0), dims)
    attack = float(beat(envelope.get("attack_beats", 0)))
    decay = float(beat(envelope.get("decay_beats", "1/2")))
    release = float(beat(envelope.get("release_beats", "1/2")))
    easing = envelope.get("easing", "easeOutQuad")
    scale = envelope.get("scale_by_strength", True)
    placed = []
    for item in items:
        at = seconds_to_beat(item["seconds"], arrangement)
        if not float(start) <= at < float(end):
            continue
        tail = seconds_to_beat(item["end_seconds"], arrangement) if "end_seconds" in item else None
        placed.append((at, tail, item))
    gap = float(beat(primitive.get("min_gap_beats", "1/4")))
    kept = []
    for row in sorted(placed, key=lambda r: r[0]):
        if kept and row[0] - kept[-1][0] < gap:
            if row[2]["strength"] > kept[-1][2]["strength"]:
                kept[-1] = row
            continue
        kept.append(row)
    if primitive.get("max_events") and len(kept) > primitive["max_events"]:
        kept = sorted(sorted(kept, key=lambda r: -r[2]["strength"])[:primitive["max_events"]], key=lambda r: r[0])
    if not kept:
        diag("warning", "pulse_without_events", f"pulse driver {driver} matches no evidence inside beats "
                                                f"{float(start):g}-{float(end):g}; lower min_strength or pick another "
                                                "layer", index, section)
    for at, tail, item in kept:
        level = max(0.0, min(1.0, item["strength"])) if scale else 1.0
        top = [round(b + (p - b) * level, 6) for p, b in zip(peak, base)]
        if tail is not None and tail > at:
            duration = min(tail, float(end)) - at
            rise, fall = min(attack, duration / 2) / duration, min(release, duration / 2) / duration
            points = ([[*base, 0]] if rise else []) + [[*top, round(rise, 6)], [*top, round(1 - fall, 6)],
                                                       [*base, 1, easing]]
            begin = at
        else:
            duration = attack + decay
            points = ([[*base, 0], [*top, round(attack / duration, 6)]] if attack else [[*top, 0]]) \
                + [[*base, 1, easing]]
            begin = max(float(start), at - attack)
        row_evidence = {k: v for k, v in item.items() if k in ("source", "id", "seconds", "end_seconds", "strength",
                                                                 "label", "run")}
        if "material" in primitive:
            data = {"asset": primitive["material"], "duration": _num(duration),
                    "properties": [{"id": prop, "type": kind, "value": points}]}
            emit(Fraction(str(round(begin, 6))), "SetMaterialProperty", data, meta, row_evidence, role="pulse")
        elif "global" in primitive:
            data = {"duration": _num(duration), "properties": [{"id": prop, "type": kind, "value": points}]}
            emit(Fraction(str(round(begin, 6))), "SetGlobalProperty", data, meta, row_evidence, role="pulse")
        else:
            data = {"track": primitive["track"], "duration": _num(duration), prop: points}
            emit(Fraction(str(round(begin, 6))), "AnimateTrack", data, meta, row_evidence, role="pulse")
