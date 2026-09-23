"""Semantic checks of a compiled show: bundle schema, object lifetimes, possession, photosensitivity,
attention budget, choreography and the EXSII envelope. Errors block export; warnings never do.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

from .show import POSSESSION_TARGETS, map_presentation, section_presentation, section_spans, validate_show
from . import vivify

# WCAG 2.3.1 (three flashes in any one-second period). A static proxy: full-screen transitions
# (Blit on/off, pulses or instant changes on a blitted material, global property changes) per
# second, two transitions per flash. Frame-luminance checks from game captures are separate (M2).
FLASH_HARD_PER_SECOND = 3.0
FLASH_WARN_PER_SECOND = 2.0
HIGH_NPS = 4.0            # section note rate above which scene-heavy attention competes with the chart
CHOREOGRAPHED_MAX_NPS = 3.0   # EXSII median active NPS; paths above it get hard to read
CHOREOGRAPHED_MAX_NJS = 12
ENVELOPE_PATH = Path(__file__).with_name("resources") / "vivify-envelope.json"


def load_envelope() -> dict | None:
    return json.loads(ENVELOPE_PATH.read_text(encoding="utf-8")) if ENVELOPE_PATH.is_file() else None


def _window_max(times: list[float], width: float = 1.0) -> tuple[int, float | None]:
    times = sorted(times)
    best, at, low = 0, None, 0
    for high, value in enumerate(times):
        while value - times[low] >= width:
            low += 1
        if high - low + 1 > best:
            best, at = high - low + 1, times[low]
    return best, at


def _dims_ok(kind: str, value) -> bool:
    dims = {"Float": 1, "Color": (3, 4), "Vector": (3, 4)}.get(kind)
    if dims is None or isinstance(value, str):
        return True
    wanted = dims if isinstance(dims, tuple) else (dims,)
    if not isinstance(value, list):
        return 1 in wanted and isinstance(value, (int, float))
    if value and all(isinstance(v, (int, float)) for v in value):
        return len(value) in wanted
    for point in value:
        if not isinstance(point, list):
            return False
        count = next((i for i, v in enumerate(point) if isinstance(v, str)), len(point))
        if count - 1 not in wanted:
            return False
    return True


def check_compiled(show: dict, arrangement: dict, beatmap: dict, result: dict, bundle: dict | None,
                   envelope: dict | None = None) -> list[dict]:
    from .critique import beat_to_seconds
    name = arrangement["difficulty"]["name"]
    findings = []

    def add(severity, code, message, section=None, events=(), **extra):
        findings.append({"severity": severity, "code": code, "message": message, "primitive": None,
                         "section_id": section, "difficulty": name, "event_indices": list(events)[:20], **extra})

    events = (beatmap.get("customData") or {}).get("customEvents", [])
    provenance = result.get("provenance", [])
    primitives = show.get("primitives", [])

    def persisted(i):
        row = provenance[i] if i < len(provenance) else {}
        index = row.get("primitive")
        return isinstance(index, int) and index < len(primitives) and primitives[index].get("persist") is True

    # Bundle references: paths, existence, property names and types.
    missing_bundle = []
    for i, event in enumerate(events):
        for path, field in vivify.event_assets(event):
            if path != path.lower():
                add("error", "asset_path_case", f"event {i} ({event['t']}) {field} {path!r} must be lowercase; "
                                                "Vivify resolves bundle paths in lower case", events=[i])
            kind = vivify.asset_kind(path)
            if kind == "other":
                add("error", "unknown_asset_kind", f"event {i} {field} {path!r} must end in .mat or .prefab", events=[i])
            elif bundle is None:
                missing_bundle.append(i)
            elif kind == "material" and path.lower() not in bundle["materials"]:
                add("error", "unknown_material", f"material {path} is not in bundleinfo.json (materials: "
                                                 f"{', '.join(sorted(bundle['materials'])[:12]) or 'none'})", events=[i])
            elif kind == "prefab" and path.lower() not in bundle["prefabs"]:
                add("error", "unknown_prefab", f"prefab {path} is not in bundleinfo.json (prefabs: "
                                               f"{', '.join(sorted(bundle['prefabs'])[:12]) or 'none'})", events=[i])
        if bundle is not None and event["t"] in ("SetMaterialProperty", "Blit"):
            material = bundle["materials"].get(str((event["d"] or {}).get("asset", "")).lower())
            for prop in (event["d"] or {}).get("properties", []) if material else []:
                info = material["properties"].get(prop.get("id"))
                if info is None and prop.get("type") != "Keyword":
                    add("error", "unknown_material_property", f"{event['d']['asset']} has no property {prop.get('id')} "
                                                              f"(it has {', '.join(sorted(material['properties']))})",
                        events=[i])
                elif info is not None and prop.get("type") != info["type"]:
                    add("error", "property_type_mismatch", f"{event['d']['asset']} property {prop['id']} is "
                                                           f"{info['type']}, event {i} sends {prop.get('type')}", events=[i])
        for prop in (event.get("d") or {}).get("properties", []) if event["t"] in (
                "SetMaterialProperty", "SetGlobalProperty", "Blit") else []:
            if isinstance(prop, dict) and not _dims_ok(prop.get("type"), prop.get("value")):
                add("error", "property_value_shape", f"event {i} property {prop.get('id')} value does not match "
                                                     f"type {prop.get('type')}", events=[i])
    if missing_bundle:
        add("error", "bundle_missing", f"{len(missing_bundle)} event(s) reference bundle assets but the project has no "
                                       "assets/bundleinfo.json; build the bundle set (asset forge) into "
                                       "<project>/assets/ first", events=missing_bundle)

    # Object lifetimes: every spawn is destroyed, or explicitly persists.
    live = {}
    for i, event in enumerate(events):
        data = event.get("d") or {}
        if event["t"] == "InstantiatePrefab":
            object_id = data.get("id")
            if object_id is None:
                if not persisted(i):
                    add("error", "prefab_without_id", f"event {i} instantiates {data.get('asset')} without an id, so "
                                                      "nothing can destroy it; give an id or persist: true", events=[i])
                continue
            if object_id in live:
                add("error", "duplicate_object_id", f"object id {object_id} is instantiated again at beat "
                                                    f"{event['b']} while still alive", events=[live[object_id], i])
            live[object_id] = i
        elif event["t"] == "DestroyObject":
            ids = data.get("id")
            for object_id in [ids] if isinstance(ids, str) else ids if isinstance(ids, list) else []:
                if live.pop(object_id, None) is None:
                    add("warning", "destroy_unknown_object", f"event {i} destroys {object_id}, which is not alive",
                        events=[i])
    persist = set(result.get("persist_ids", []))
    for object_id, i in live.items():
        if object_id not in persist and not persisted(i):
            add("error", "prefab_not_destroyed", f"object {object_id} (event {i}, beat {events[i]['b']}) is never "
                                                 "destroyed; add a DestroyObject or persist: true", events=[i])

    # One setup; possession only as the map-level decision allows.
    setups = [i for i, p in enumerate(primitives) if p.get("kind") == "setup"]
    if len(setups) > 1:
        add("error", "multiple_setup", f"the show has {len(setups)} setup primitives (indices {setups}); keep one")
    possession = map_presentation(arrangement).get("possession", "none")
    allowed = POSSESSION_TARGETS.get(possession, set())
    player = [i for i, e in enumerate(events) if e["t"] == "AssignPlayerToTrack"]
    for i in player:
        target = (events[i].get("d") or {}).get("target", "Root")
        if target not in allowed:
            add("error", "possession_not_allowed", f"event {i} assigns the player's {target} to a track, but the "
                                                   f"map-level presentation.possession is {possession!r}; possession is "
                                                   "a once-per-map decision, set it in the arrangement first",
                events=[i])
    if possession != "none" and not player:
        add("warning", "possession_unused", f"presentation.possession is {possession!r} but no event assigns the player "
                                            "to a track")

    # Photosensitivity: full-screen transitions per second (static proxy).
    blitted = {str((e.get("d") or {}).get("asset", "")).lower() for e in events if e["t"] == "Blit"}
    transitions = []
    for i, event in enumerate(events):
        data, at = event.get("d") or {}, float(event["b"])
        duration = float(data.get("duration", 0) or 0)
        animated = any(isinstance(p.get("value"), list) and p["value"] and isinstance(p["value"][0], list)
                       for p in data.get("properties", []) if isinstance(p, dict))
        if event["t"] == "Blit":
            transitions += [(at, i), (at + duration, i)]
        elif event["t"] == "SetMaterialProperty" and str(data.get("asset", "")).lower() in blitted \
                or event["t"] == "SetGlobalProperty":
            transitions += [(at, i), (at + duration, i)] if animated and duration else [(at, i)]
    if transitions:
        # Transitions in the same frame (stacked passes, simultaneous property changes) are one change.
        frames = {}
        for at, i in transitions:
            frames.setdefault(round(beat_to_seconds(at, arrangement) * 50), (beat_to_seconds(at, arrangement), at, i))
        seconds = sorted(frames.values())
        count, start = _window_max([s for s, _, _ in seconds])
        rate = count / 2
        if rate > FLASH_WARN_PER_SECOND:
            windows, high = set(), 0
            for low, (s, at, _) in enumerate(seconds):
                while high < len(seconds) and seconds[high][0] < s + 1:
                    high += 1
                if (high - low) / 2 > FLASH_WARN_PER_SECOND:
                    windows.add(round(at, 3))
            windows = sorted(windows)
            severity, code = (("error", "flash_rate_exceeded") if rate > FLASH_HARD_PER_SECOND
                              else ("warning", "flash_rate_high"))
            add(severity, code, f"up to {rate:g} full-screen flashes per second (from {start:.2f} s); the ceiling is "
                                f"{FLASH_HARD_PER_SECOND:g} (WCAG 2.3.1), warning above {FLASH_WARN_PER_SECOND:g}. "
                                "Raise pulse min_gap_beats, lengthen looks or move pulses to scene materials",
                events=sorted({i for _, _, i in seconds}), beats=windows[:20], flashes_per_second=rate)
        # (event_indices lists the first transitions; beats lists where the rate is above the warning line)

    # Attention budget, choreography and family per section.
    spans = section_spans(arrangement)
    presentation = section_presentation(arrangement)
    notes_by = {sid: [] for sid in spans}
    for i, note in enumerate(beatmap.get("colorNotes", [])):
        at = Fraction(str(note["b"]))
        sid = next((s for s, (low, high) in spans.items() if low <= at < high), None)
        if sid:
            notes_by[sid].append(i)
    for sid, block in presentation.items():
        low, high = spans[sid]
        seconds = beat_to_seconds(float(high), arrangement) - beat_to_seconds(float(low), arrangement)
        nps = len(notes_by[sid]) / seconds if seconds > 0 else 0.0
        attention, style = block.get("attention"), block.get("note_style", "plain")
        if attention and attention["scene"] >= 0.5 and nps >= HIGH_NPS:
            add("warning", "attention_over_budget", f"section {sid} runs {nps:.1f} notes/s but declares scene attention "
                                                    f"{attention['scene']:g}; thin the chart here or calm the scene",
                sid, nps=round(nps, 3))
        if style == "choreographed":
            if nps > CHOREOGRAPHED_MAX_NPS:
                add("warning", "choreographed_density", f"choreographed section {sid} runs {nps:.1f} notes/s (EXSII "
                                                        f"choreography stays near {CHOREOGRAPHED_MAX_NPS:g}); pathed notes "
                                                        "get hard to read", sid, nps=round(nps, 3))
            unset = [i for i in notes_by[sid] if not {"noteJumpMovementSpeed", "noteJumpStartBeatOffset"}
                     <= set(beatmap["colorNotes"][i].get("customData", {}))]
            if unset:
                add("error", "choreographed_note_jump_missing",
                    f"{len(unset)} note(s) of choreographed section {sid} have no per-note NJS and offset; cover the "
                    "section with a path primitive (njs, offset)", sid)
            fast = sorted({beatmap["colorNotes"][i]["customData"]["noteJumpMovementSpeed"] for i in notes_by[sid]
                           if beatmap["colorNotes"][i].get("customData", {}).get("noteJumpMovementSpeed", 0)
                           > CHOREOGRAPHED_MAX_NJS})
            if fast:
                add("warning", "choreographed_njs_high", f"choreographed section {sid} uses NJS {fast}; pathed notes "
                                                         f"read best at 8-{CHOREOGRAPHED_MAX_NJS}", sid)
    for index, primitive in enumerate(primitives):
        sid = primitive.get("section")
        if sid not in spans:
            continue
        block = presentation.get(sid)
        if primitive.get("kind") == "path" and (block or {}).get("note_style") != "choreographed":
            add("error", "path_requires_choreographed", f"path primitive {index} targets section {sid}, which is not "
                                                        "presentation.note_style choreographed", sid)
        if block is None:
            continue
        family, kind = block["family"], primitive.get("kind")
        if family == "none" and kind in ("look", "scene", "pulse", "skin"):
            add("warning", "family_mismatch", f"{kind} primitive {index} runs in section {sid}, whose family is none", sid)
        elif family == "scene" and kind == "look" or family == "post_process" and kind == "scene":
            add("warning", "family_mismatch", f"{kind} primitive {index} blends into {family} section {sid}; EXSII keeps "
                                              "one family per section", sid)

    # Event budget against the EXSII envelope (warning only).
    if envelope and events:
        maxima = envelope.get("max", {})
        times = [beat_to_seconds(float(e["b"]), arrangement) for e in events]
        spawns = [t for t, e in zip(times, events) if e["t"] == "InstantiatePrefab"]
        measured = {"custom_events": len(events), "events_per_second": _window_max(times)[0],
                    "spawns_per_second": _window_max(spawns)[0] if spawns else 0}
        for key, value in measured.items():
            if key in maxima and value > maxima[key]:
                add("warning", "outside_exsii_envelope", f"{key} = {value} exceeds the EXSII maximum {maxima[key]}; "
                                                         "no reference map goes this far", measured=value,
                    envelope=maxima[key], metric=key)
    return findings


def compile_difficulty(show: dict, arrangement: dict, *, bundle=None, evidence=None, envelope=None):
    """(beatmap with customData, compile result with checks) for one difficulty, before the audio-offset shift."""
    from .arrangement import compile_arrangement
    from .show_compile import compile_show
    beatmap = compile_arrangement(arrangement)
    result = compile_show(show, arrangement, beatmap, bundle=bundle, evidence=evidence)
    result["diagnostics"] = _dedupe(result["diagnostics"] + check_compiled(show, arrangement, beatmap, result, bundle,
                                                                           envelope))
    return beatmap, result


def _dedupe(findings: list[dict]) -> list[dict]:
    seen, result = set(), []
    for item in findings:
        key = (item["severity"], item["code"], item["message"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def validate_project_show(show: dict, arrangements: dict[str, dict], *, bundle=None, evidence=None) -> dict:
    """Structural, reference and compiled checks of a show against every difficulty."""
    structural = validate_show(show, arrangements)
    report = {"ok": True, "diagnostics": list(structural), "difficulties": {}}
    concepts = {name: deepcopy(map_presentation(a)) for name, a in arrangements.items()}
    if len({json.dumps(c, sort_keys=True) for c in concepts.values()}) > 1:
        report["diagnostics"].append({"severity": "warning", "code": "presentation_mismatch", "primitive": None,
                                      "section_id": None, "difficulty": None,
                                      "message": "difficulties declare different map-level presentation (concept, "
                                                 "palette, possession); the show is shared, so align them"})
    if not any(d["severity"] == "error" for d in structural):
        envelope = load_envelope()
        for name, arrangement in arrangements.items():
            try:
                beatmap, result = compile_difficulty(show, arrangement, bundle=bundle, evidence=evidence,
                                                     envelope=envelope)
            except ValueError as exc:
                report["diagnostics"].append({"severity": "error", "code": "arrangement_invalid", "primitive": None,
                                              "section_id": None, "difficulty": name, "message": str(exc)})
                continue
            report["diagnostics"] += result["diagnostics"]
            report["difficulties"][name] = {"event_count": result["event_count"],
                                            "requirements": result["requirements"],
                                            "assets": result["assets"], "evidence_run": result["evidence_run"],
                                            "object_custom_data": result["object_custom_data"]}
    report["ok"] = not any(d["severity"] == "error" for d in report["diagnostics"])
    return report
