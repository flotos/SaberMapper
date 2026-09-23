"""Structured diagnostics from BSIPA game logs (Logs/_latest.log), scoped to the current level.

BSIPA prefixes every physical line, `[LEVEL @ HH:MM:SS | Source] message`; an exception logged through
`Logger.Error(e)` becomes one prefixed line per stack line. Message patterns below are taken from the
Vivify, Heck and SongCore sources (Aeroluna/Vivify, Aeroluna/Heck, Kylemc1413/SongCore) and from Unity's
AssetBundle/shader player messages; anything else falls back to a generic code.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from .errors import GameError

DEFAULT_GAME_DIR = Path("C:/Program Files (x86)/Steam/steamapps/common/Beat Saber")
BRIDGE_SOURCE = "SaberMapperBridge"
RELEVANT_MODS = ("Heck", "Chroma", "NoodleExtensions", "Vivify", "CustomJSONData", "SongCore", "SiraUtil",
                 BRIDGE_SOURCE)
SEVERITY = {"CRITICAL": "error", "ERROR": "error", "WARNING": "warning", "WARN": "warning", "NOTICE": "info",
            "INFO": "info", "DEBUG": "info", "TRACE": "info"}
_LINE = re.compile(r"^\[(?P<level>[A-Z]+) @ (?P<time>\d{1,2}:\d{2}:\d{2}) \| (?P<source>[^\]]*)\] ?(?P<message>.*)$")
_EXCEPTION = re.compile(r"^(?:[A-Za-z_][\w.`]*\.)?[A-Za-z_]\w*(?:Exception|Error)(?::|$)")
_TRACE_LINE = re.compile(r"^(?:\s+|at |--- |Rethrow as |\(wrapper |UnityEngine\.[\w.]+:|[\w.]+:[\w<>]+ ?\()")
_BRIDGE_START = re.compile(r"^level_start\s+(?P<path>.+?)\s*$")
_BRIDGE_END = re.compile(r"^level_end\b")
# Heck logs these (TRACE) from DeserializerManager whenever a level's beatmap data is deserialized.
_FALLBACK_START = (("Heck", re.compile(r"^Deserializing BeatmapData$")),)

_BUNDLE_FIX = ("Rebuild the bundle and re-export so Info.dat _customData._assetBundle._windows2021 holds the CRC "
               "of the bundleWindows2021.vivify shipped next to it")
PATTERNS = (
    ("bundle_checksum_mismatch", None, re.compile(r"CRC Mismatch", re.I), _BUNDLE_FIX),
    ("bundle_checksum_missing", "Vivify", re.compile(r"^Checksum not defined$"),
     "Add the bundle CRC under Info.dat _customData._assetBundle._windows2021 (Vivify refuses unchecked bundles)"),
    ("bundle_missing", "Vivify", re.compile(r"^\[.*\.vivify\] not found$|not found, attempting to download remotely$"),
     "Export the map with its bundleWindows2021.vivify next to Info.dat"),
    ("bundle_load_failed", None, re.compile(
        r"^Failed to load \[.+\]$|Unable to open archive file|can't be loaded because it was not built with the "
        r"right version or build target|AssetBundle .* can't be loaded because another AssetBundle", re.I),
     "Rebuild the bundle with Unity 2021.3.16f1 for StandaloneWindows64 and re-export; check the CRC line above"),
    ("asset_not_found", "Vivify", re.compile(
        r"^Could not find (?:[\w.`+]+ )?\[.+\]$|^Found .+, but was null or not \[.+\]$|^No prefab with id \[.+\] detected$"),
     "Use the exact lowercase asset path from bundleinfo.json (e.g. assets/.../name.mat) and the declared prefab id"),
    ("shader_error", None, re.compile(
        r"Shader Unsupported|is not supported on this GPU|Shader error in|shader compil\w* (?:error|fail)", re.I),
     "Fix the shader (single-pass-instanced stereo macros, a supported target) and rebuild the bundle"),
    ("custom_data_parse_error", None, re.compile(r"^Could not parse custom data for "),
     "Fix the customData of the object or event at the reported beat (types, point definitions, track names)"),
    ("json_parse_error", None, re.compile(
        r"JsonReaderException|JsonSerializationException|Unexpected character encountered while parsing|"
        r"^Error loading beatmap version\.$"),
     "The difficulty or Info.dat JSON does not parse; validate and re-export the map"),
    ("level_load_failed", "SongCore", re.compile(
        r"^Failed to load (?:custom level|song|song folder)\b|^Error in Level |^Error loading beatmap\. Missing or "
        r"unknown characteristic\.$|^Skipping missing or corrupt folder"),
     "SongCore could not load the level folder; check Info.dat, difficulty file names and characteristics"),
    ("custom_event_invalid", None, re.compile(
        r"^\[.+\] (?:debris )?not recognized$|^No track defined$|^Duplicate (?:event|point) defintion name"),
     "Fix the custom event: known keys, a defined track, unique pointDefinition and event names"),
    ("missing_requirement", None, re.compile(r"missing requirement", re.I),
     "Install/enable the mod named in _requirements, or remove the requirement from the map"),
    ("harmony_patch_failed", None, re.compile(r"HarmonyException|Patching exception in method"),
     "A mod failed to patch this game version; update the mod (not a map defect)"),
)
_GENERIC_FIX = {"exception": "A mod threw while running; read the trace (usually a map data problem when it "
                             "names Heck, Vivify, Noodle or Chroma code)"}


def default_game_dir(game_dir: str | Path | None = None) -> Path:
    return Path(game_dir or os.environ.get("SABERMAPPER_GAME_DIR") or DEFAULT_GAME_DIR)


def default_log_path(game_dir: str | Path | None = None) -> Path:
    return default_game_dir(game_dir) / "Logs" / "_latest.log"


def _mod(source: str) -> str:
    return source.split("/", 1)[0].strip()


def parse_records(text: str) -> list[dict]:
    """Group physical log lines into records with continuation/stack lines in `trace`."""
    records: list[dict] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        match = _LINE.match(line)
        if not match:
            if records and line.strip():
                records[-1]["trace"].append(line.rstrip())
            continue
        level, source, message = match["level"], match["source"].strip(), match["message"].rstrip()
        previous = records[-1] if records else None
        if previous and previous["level"] == level and previous["source"] == source:
            if _TRACE_LINE.match(message) or (
                    _EXCEPTION.match(message.strip()) and previous["time"] == match["time"]
                    and not previous["exception"]):
                previous["trace"].append(message)
                if _EXCEPTION.match(message.strip()):
                    previous["exception"] = message.strip()
                continue
        records.append({"line": number, "level": level, "time": match["time"], "source": source,
                        "mod": _mod(source), "message": message,
                        "exception": message.strip() if _EXCEPTION.match(message.strip()) else None, "trace": []})
    return records


def classify(record: dict) -> tuple[str, str | None]:
    text = "\n".join([record["message"], *record["trace"]])
    for code, mod, pattern, fix in PATTERNS:
        if mod and record["mod"].lower() != mod.lower():
            continue
        if pattern.search(record["message"]) or (code in ("json_parse_error", "harmony_patch_failed",
                                                          "bundle_checksum_mismatch") and pattern.search(text)):
            return code, fix
    if record["exception"]:
        return "exception", _GENERIC_FIX["exception"]
    return ("log_error" if SEVERITY.get(record["level"]) == "error" else
            "log_warning" if SEVERITY.get(record["level"]) == "warning" else "log_info"), None


def level_markers(records: list[dict]) -> list[dict]:
    """Level start/end markers; SaberMapperBridge markers are authoritative, Heck's are a fallback."""
    bridge, fallback = [], []
    for index, record in enumerate(records):
        if record["mod"] == BRIDGE_SOURCE:
            start = _BRIDGE_START.match(record["message"])
            if start:
                bridge.append({"index": index, "kind": "start", "path": start["path"], "line": record["line"],
                               "time": record["time"], "source": "bridge"})
            elif _BRIDGE_END.match(record["message"]):
                bridge.append({"index": index, "kind": "end", "path": None, "line": record["line"],
                               "time": record["time"], "source": "bridge"})
        for mod, pattern in _FALLBACK_START:
            if record["mod"] == mod and pattern.match(record["message"]):
                fallback.append({"index": index, "kind": "start", "path": None, "line": record["line"],
                                 "time": record["time"], "source": mod})
    return bridge if bridge else fallback


def _norm(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def _level_matches(marker_path: str | None, wanted: str) -> bool:
    if not marker_path:
        return False
    a, b = _norm(marker_path), _norm(wanted)
    return a == b or a.endswith("/" + b) or b.endswith("/" + a) or a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]


def game_version(records: list[dict]) -> str | None:
    found = None
    for record in records:
        if record["mod"] != "IPA":
            continue
        early = re.match(r"^Game version set early to (\S+)", record["message"])
        if early:
            return early[1]
        plain = re.match(r"^Game version (\S+)$", record["message"])
        if plain and not found:
            found = plain[1]
    return found


def diagnose(text: str, *, since_level: bool = False, level: str | None = None, all_mods: bool = False,
             limit: int | None = 200, include_info: bool = False) -> dict:
    records = parse_records(text)
    markers = level_markers(records)
    starts = [m for m in markers if m["kind"] == "start"]
    scope = {"mode": "whole_log", "marker": None, "found": True}
    begin, end = 0, len(records)
    last_start = starts[-1]["index"] if starts else None
    if level is not None:
        matching = [m for m in starts if _level_matches(m["path"], level)]
        scope = {"mode": "level", "level": level, "marker": None, "found": bool(matching)}
        if matching:
            chosen = matching[-1]
            begin = chosen["index"]
            end = next((m["index"] for m in starts if m["index"] > begin), len(records))
            scope["marker"] = {k: chosen[k] for k in ("line", "time", "path", "source")}
        else:
            begin = end = len(records)
    elif since_level:
        scope = {"mode": "since_level", "marker": None, "found": last_start is not None}
        if last_start is not None:
            begin = last_start
            scope["marker"] = {k: starts[-1][k] for k in ("line", "time", "path", "source")}
        else:
            begin = end = len(records)
    relevant = {mod.lower() for mod in RELEVANT_MODS}
    diagnostics = []
    for index in range(begin, end):
        record = records[index]
        severity = SEVERITY.get(record["level"], "info")
        code, fix = classify(record)
        known = code not in ("log_error", "log_warning", "log_info", "exception")
        mod_ok = all_mods or record["mod"].lower() in relevant
        if severity == "info" and not include_info and not (known and mod_ok):
            continue
        if not (mod_ok or known or (record["exception"] and severity == "error")):
            continue
        diagnostics.append({"severity": severity, "source": record["mod"], "logger": record["source"], "code": code,
                            "time": record["time"], "line": record["line"], "message": record["message"],
                            "trace": record["trace"], "fix": fix,
                            "level_scope": last_start is not None and index >= last_start})
    counts = {"error": sum(d["severity"] == "error" for d in diagnostics),
              "warning": sum(d["severity"] == "warning" for d in diagnostics)}
    codes: dict[str, int] = {}
    for item in diagnostics:
        codes[item["code"]] = codes.get(item["code"], 0) + 1
    truncated = limit is not None and limit >= 0 and len(diagnostics) > limit
    level_path = scope["marker"]["path"] if scope.get("marker") else (starts[-1]["path"] if starts else None)
    return {"game_version": game_version(records), "level": level_path, "scope": scope, "counts": counts,
            "codes": codes, "total": len(diagnostics), "truncated": truncated,
            "diagnostics": diagnostics[-limit:] if truncated and limit else ([] if truncated else diagnostics)}


def read_log(path: str | Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise GameError("game_not_found", f"Game log not found: {path}", {"log": str(path)},
                        "Pass --log PATH or --game-dir DIR (or set SABERMAPPER_GAME_DIR); start the game once "
                        "so BSIPA writes Logs/_latest.log")
    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        return stream.read()


def game_logs(log: str | Path | None = None, *, game_dir: str | Path | None = None, **options) -> dict:
    path = Path(log) if log else default_log_path(game_dir)
    return {"log": str(path), **diagnose(read_log(path), **options)}
