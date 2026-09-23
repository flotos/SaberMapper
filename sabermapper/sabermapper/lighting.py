"""Lightshow: audio-driven Beat Saber basic lighting, generated automatically, tweakable by agents.

An arrangement's optional ``lightshow`` holds three layers:

* inputs the agent may edit: ``environment``, ``style`` (song-wide) and ``sections`` (per section ID:
  mood, primary color, boost, white accents, intensity);
* ``cues``: agent-authored additions and removals (pulse, off, spin, zoom, laser_speed, boost, event,
  clear) at absolute beats, applied on top of the generated layer and never touched by regeneration;
* ``generated``: the materialized output of :func:`generate_lightshow`, rebuilt from the song's musical
  evidence whenever its inputs change (``auto``), so export stays a pure function of the arrangement.

Every generated light sits on a sound: drum hits pulse the back lasers, ring lights and center; the
bar's lead instrument (voice, riff, melody) drives the side lasers and their speed; bass pulses the
center; chord changes swap colors; section energy chooses the mood that sets density, laser speed,
ring motion and color boost. Density targets and safety limits come from the reference corpus study
in ``resources/lighting-reference.json`` (``scripts/lighting_reference.py``).
"""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from statistics import median

GENERATOR_VERSION = "1.0"
DEFAULT_ENVIRONMENT = "BigMirrorEnvironment"
# Environments whose basic events keep the classic meaning of types 0-4, 8, 9, 12 and 13.
ENVIRONMENTS = ("DefaultEnvironment", "BigMirrorEnvironment", "NiceEnvironment", "TriangleEnvironment",
                "OriginsEnvironment", "KDAEnvironment", "MonstercatEnvironment", "CrabRaveEnvironment",
                "DragonsEnvironment", "PanicEnvironment", "RocketEnvironment", "GreenDayEnvironment",
                "GreenDayGrenadeEnvironment", "TimbalandEnvironment", "FitBeatEnvironment")
GROUPS = {"back": 0, "ring": 1, "left": 2, "right": 3, "center": 4}
GROUP_NAMES = {value: name for name, value in GROUPS.items()}
LIGHT_TYPES = (0, 1, 2, 3, 4)
RING_SPIN, RING_ZOOM, LEFT_SPEED, RIGHT_SPEED = 8, 9, 12, 13
EVENT_TYPES = LIGHT_TYPES + (RING_SPIN, RING_ZOOM, LEFT_SPEED, RIGHT_SPEED)
TARGETS = {**GROUPS, "spin": RING_SPIN, "zoom": RING_ZOOM, "left_speed": LEFT_SPEED, "right_speed": RIGHT_SPEED}
COLOR_BASE = {"blue": 0, "red": 4, "white": 8}
STYLE_OFFSET = {"on": 1, "flash": 2, "fade": 3, "transition": 4}
VALUE_NAMES = {0: "off", **{COLOR_BASE[c] + STYLE_OFFSET[s]: f"{c} {s}" for c in COLOR_BASE for s in STYLE_OFFSET}}
PULSE_VALUES = frozenset({1, 2, 3, 5, 6, 7, 9, 10, 11})
WHITE_PULSE_VALUES = frozenset({9, 10, 11})
FADE_VALUES = frozenset({3, 7, 11})
MOODS = ("auto", "off", "calm", "groove", "peak")
MOOD_RANK = {"off": 0, "calm": 1, "groove": 2, "peak": 3}
PALETTES = ("cool_to_warm", "warm_to_cool", "red", "blue")
DEFAULT_STYLE = {"intensity": 1.0, "palette": "cool_to_warm", "white_accents": False, "boost": True}
CUE_ACTIONS = ("pulse", "off", "spin", "zoom", "laser_speed", "boost", "event", "clear")
MAX_SPEED = 20

# Corpus calibration (resources/lighting-reference.json, 132 lit reference maps): light events per
# second of types 0-4 in 4 s windows ranked by note density, low/mid/high tercile medians 12.3/21.2/26.3;
# low-tier p10 4.3 and high-tier p90 50.8 bound the plausible range.
TARGET_RATE = {"calm": 10.0, "groove": 18.0, "peak": 26.0}
DENSITY_LOW = 4.344
DENSITY_HIGH = 50.842
SPEED_RANGE = {"calm": (1, 2), "groove": (2, 4), "peak": (4, 7)}
BRIGHTNESS = {"calm": 0.7, "groove": 0.9, "peak": 1.05}
MOOD_CALM_BELOW = 0.42
MOOD_PEAK_FROM = 0.68
SECTION_ACTIVE_SHARE = 0.25
SECTION_OFF_ONSET_RATE = 1.0  # strong stem onsets per second below which an inactive section stays dark
BAR_BEATS = 4
SNAP = 48
MIN_GROUP_GAP_SECONDS = 0.1
FILL_GAP_SECONDS = 2.0
SWAP_MIN_BEATS = 8
CHORD_SWAP_STRENGTH = 0.5
ONSET_METHODS = ("spectral_flux", "pitch_change", "melody_change")
SUPPORT_METHODS = ONSET_METHODS + ("chord_change",)
DRUM_LAYERS = ("drums", "percussive", "low")
BASS_LAYERS = ("bass", "low")
LEAD_LAYERS = ("vocals", "guitar", "piano", "other", "synth", "harmonic", "mid", "high")

# Safety and review thresholds. A full-field pulse is 4+ of the 5 light groups flashing, fading or
# switching on together (within 20 ms). Human reference maps reach 6 per second at the median of
# their busiest second (p75 7), so blocking starts above 8; the generator itself stays at 4.
FULL_FIELD_GROUPS = 4
WHITE_FIELD_GROUPS = 3
MOMENT_SECONDS = 0.02
STROBE_BLOCK_PER_SECOND = 8
WHITE_BLOCK_PER_SECOND = 3
GENERATOR_FULL_FIELD_PER_SECOND = 4
HEAVY_FLASH_PER_SECOND = 4
HEAVY_FLASH_SECONDS = 4.0
STATIC_WARN_SECONDS = 4.0
STATIC_ONSET_RATE = 1.0
UNSUPPORTED_LIGHT_RUN = 8
SUPPORT_BEATS = 0.13
FADE_LIT_SECONDS = 0.75
BLACKOUT_BEATS = 2.0

DEFINITIONS = {
    "lightshow_missing": "The arrangement has no lightshow; export falls back to one pulse per section. "
                         "Run `project lights ID` (or save with a musical evidence run) to generate one.",
    "lightshow_stale": "The generated lighting was built from other inputs (evidence run, timing, sections, "
                       "style, section overrides or focus) than the arrangement now has, and auto is false. "
                       "Run `project lights ID` to rebuild it.",
    "lightshow_unknown_section": "lightshow.sections names a section ID the arrangement does not have.",
    "light_strobe": f"More than {STROBE_BLOCK_PER_SECOND} full-field pulses ({FULL_FIELD_GROUPS}+ light groups "
                    f"pulsing within {MOMENT_SECONDS * 1000:g} ms) in some 1 s window, or more than "
                    f"{WHITE_BLOCK_PER_SECOND} white pulses on {WHITE_FIELD_GROUPS}+ groups: a photosensitivity "
                    "hazard. Blocking.",
    "light_flash_heavy": f"At least {HEAVY_FLASH_SECONDS:g} s where every 1 s window holds more than "
                         f"{HEAVY_FLASH_PER_SECOND} full-field pulses: sustained heavy flashing.",
    "light_unmapped": f"A stretch of {STATIC_WARN_SECONDS:g} s or more of active audio carrying at least "
                      f"{STATIC_ONSET_RATE:g} onset per second where no light, ring or laser-speed event occurs.",
    "light_without_audio": f"{UNSUPPORTED_LIGHT_RUN} or more consecutive light pulse moments with no onset, pitch, "
                           f"melody or chord change in any layer within {SUPPORT_BEATS:g} beat.",
    "light_density": f"A lit section above {DENSITY_HIGH:g} light events per second (corpus high-tier p90), or below "
                     f"{DENSITY_LOW:g} (low-tier p10) while its audio is active and its stems carry at least "
                     f"{DENSITY_LOW:g} strong onsets (strength 0.3+) per second.",
    "light_blackout_notes": f"All five light groups are dark for {BLACKOUT_BEATS:g} beats or more while notes are "
                            f"in play (a fade counts as lit for {FADE_LIT_SECONDS:g} s; notes within {SUPPORT_BEATS:g} "
                            "beat of either edge do not count).",
}


# ----------------------------------------------------------------------------- time helpers

def _beat(value) -> float:
    return float(Fraction(str(value)))


def _snap(beat: float) -> float:
    return round(round(beat * SNAP) / SNAP, 4)


def _to_seconds(arrangement):
    """Fast beat->seconds for many events: piecewise-linear over tempo changes, beat 0 at the audio offset."""
    bpm = float(arrangement["song"]["bpm"])
    offset = float(arrangement["song"]["audio_offset_seconds"])
    changes = sorted(((_beat(e["beat"]), float(e["bpm"])) for e in arrangement.get("tempo_events") or []))
    anchors, seconds, previous, tempo = [(0.0, offset, bpm)], offset, 0.0, bpm
    for at, next_tempo in changes:
        seconds += (at - previous) * 60 / tempo
        previous, tempo = at, next_tempo
        anchors.append((at, seconds, tempo))
    starts = [a[0] for a in anchors]

    def convert(beat):
        at, base, rate = anchors[max(0, bisect_left(starts, float(beat) + 1e-12) - 1)]
        return base + (float(beat) - at) * 60 / rate
    return convert


def _to_beats(arrangement):
    from .musical import seconds_to_beat
    return lambda seconds: seconds_to_beat(float(seconds), arrangement)


def _spans(arrangement):
    spans = []
    for section in arrangement["sections"]:
        start = _beat(section["start_beat"])
        spans.append({"section": section, "id": section["id"], "start_beat": start,
                      "end_beat": start + _beat(section["length_beats"])})
    return spans


def _value(color: str, style: str) -> int:
    return 0 if style == "off" else COLOR_BASE[color] + STYLE_OFFSET[style]


def _other(color: str) -> str:
    return "red" if color == "blue" else "blue"


# ----------------------------------------------------------------------------- compile

def compile_lightshow(arrangement: dict) -> tuple[list[tuple], list[tuple]]:
    """Return (basic events, boost events) as sorted (beat, type, value, brightness) / (beat, on) tuples."""
    show = arrangement.get("lightshow")
    if not isinstance(show, dict):
        return [], []
    generated = show.get("generated") or {}
    events = [(float(e[0]), int(e[1]), int(e[2]), float(e[3])) for e in generated.get("events") or []]
    boosts = [(float(b[0]), bool(b[1])) for b in generated.get("boosts") or []]
    cues = show.get("cues") or []
    for cue in cues:
        if cue.get("action") != "clear":
            continue
        start, end = _beat(cue["beat"]), _beat(cue["end_beat"])
        targets = cue.get("targets") or list(TARGETS) + ["boost"]
        types = {TARGETS[t] for t in targets if t in TARGETS}
        events = [e for e in events if not (start <= e[0] < end and e[1] in types)]
        if "boost" in targets:
            boosts = [b for b in boosts if not start <= b[0] < end]
    # A cue replaces whatever the generated layer does to the same group at the same beat.
    added = [event for cue in cues for event in _cue_events(cue)]
    replaced = {(round(e[0], 4), e[1]) for e in added}
    events = [e for e in events if (round(e[0], 4), e[1]) not in replaced] + added
    for cue in cues:
        if cue.get("action") == "boost":
            boosts.append((_beat(cue["beat"]), bool(cue["on"])))
    order = {LEFT_SPEED: -2, RIGHT_SPEED: -1}
    events.sort(key=lambda e: (e[0], order.get(e[1], e[1]), e[2]))
    boosts.sort()
    return events, boosts


def _cue_events(cue: dict) -> list[tuple]:
    action, beat = cue.get("action"), _beat(cue["beat"])
    brightness = float(cue.get("brightness", 1.0))
    if action == "pulse":
        value = _value(cue.get("color", "blue"), cue.get("style", "fade"))
        return [(beat, GROUPS[g], value, brightness) for g in cue.get("groups") or list(GROUPS)]
    if action == "off":
        return [(beat, GROUPS[g], 0, 0.0) for g in cue.get("groups") or list(GROUPS)]
    if action == "spin":
        return [(beat, RING_SPIN, 0, 1.0)]
    if action == "zoom":
        return [(beat, RING_ZOOM, 0, 1.0)]
    if action == "laser_speed":
        sides = {"left": [LEFT_SPEED], "right": [RIGHT_SPEED], "both": [LEFT_SPEED, RIGHT_SPEED]}[cue.get("side", "both")]
        return [(beat, side, int(cue["speed"]), 1.0) for side in sides]
    if action == "event":
        return [(beat, int(cue["type"]), int(cue["value"]), brightness)]
    return []


def beatmap_events(arrangement: dict) -> tuple[list[dict], list[dict]]:
    """The v3 ``basicBeatmapEvents`` and ``colorBoostBeatmapEvents`` of an arrangement's lightshow."""
    events, boosts = compile_lightshow(arrangement)
    return ([{"b": b, "et": t, "i": v, "f": f} for b, t, v, f in events],
            [{"b": b, "o": on} for b, on in boosts])


# ----------------------------------------------------------------------------- validation

def validate_lightshow(arrangement: dict, add) -> None:
    """Structural and safety checks; ``add(severity, code, message, section_id=None, object_ids=())``."""
    show = arrangement["lightshow"]
    where = "lightshow"
    errors = [0]
    outer = add

    def add(severity, code, message, section_id=None, object_ids=()):
        errors[0] += severity == "error"
        outer(severity, code, message, section_id, object_ids)

    if not isinstance(show, dict):
        add("error", "invalid_lightshow", "lightshow must be an object")
        return
    allowed = {"environment", "auto", "style", "sections", "cues", "generated"}
    for name in sorted(set(show) - allowed):
        add("error", "unsupported_field", f"{where}.{name} is unsupported")
    if "environment" not in show:
        add("error", "missing_field", f"{where} requires environment")
    elif show["environment"] not in ENVIRONMENTS:
        add("error", "invalid_lightshow", f"lightshow.environment must be one of {', '.join(ENVIRONMENTS)}")
    if "auto" in show and type(show["auto"]) is not bool:
        add("error", "invalid_lightshow", "lightshow.auto must be a boolean")
    _validate_style(show.get("style", {}), "lightshow.style", add, section=False)
    sections = show.get("sections", {})
    if not isinstance(sections, dict):
        add("error", "invalid_lightshow", "lightshow.sections must be an object keyed by section ID")
    else:
        known = {s.get("id") for s in arrangement.get("sections") or [] if isinstance(s, dict)}
        for sid, override in sections.items():
            _validate_style(override, f"lightshow.sections.{sid}", add, section=True)
            if sid not in known:
                add("warning", "lightshow_unknown_section",
                    f"lightshow.sections.{sid} names no section of this arrangement; its overrides are ignored", sid)
    cues = show.get("cues", [])
    if not isinstance(cues, list):
        add("error", "invalid_lightshow", "lightshow.cues must be an array")
    else:
        for index, cue in enumerate(cues):
            _validate_cue(cue, f"lightshow.cues[{index}]", add)
    generated = show.get("generated")
    if generated is not None:
        _validate_generated(generated, add)
    if not errors[0]:
        for code, message in strobe_findings(arrangement):
            add("error", code, message)


def _number(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and low <= value <= high)


def _validate_style(style, where, add, *, section):
    if not isinstance(style, dict):
        add("error", "invalid_lightshow", f"{where} must be an object")
        return
    allowed = {"mood", "primary", "boost", "white_accents", "intensity"} if section else set(DEFAULT_STYLE)
    for name in sorted(set(style) - allowed):
        add("error", "unsupported_field", f"{where}.{name} is unsupported")
    if "intensity" in style and not _number(style["intensity"], 0.25, 2.0):
        add("error", "invalid_lightshow", f"{where}.intensity must be a number from 0.25 to 2")
    for flag in ("boost", "white_accents"):
        if flag in style and type(style[flag]) is not bool:
            add("error", "invalid_lightshow", f"{where}.{flag} must be a boolean")
    if "palette" in style and style["palette"] not in PALETTES:
        add("error", "invalid_lightshow", f"{where}.palette must be one of {', '.join(PALETTES)}")
    if "mood" in style and style["mood"] not in MOODS:
        add("error", "invalid_lightshow", f"{where}.mood must be one of {', '.join(MOODS)}")
    if "primary" in style and style["primary"] not in ("red", "blue"):
        add("error", "invalid_lightshow", f"{where}.primary must be red or blue")


def _validate_cue(cue, where, add):
    if not isinstance(cue, dict):
        add("error", "invalid_lightshow", f"{where} must be an object")
        return
    action = cue.get("action")
    fields = {"pulse": {"groups", "color", "style", "brightness"}, "off": {"groups"}, "spin": set(), "zoom": set(),
              "laser_speed": {"side", "speed"}, "boost": {"on"}, "event": {"type", "value", "brightness"},
              "clear": {"end_beat", "targets"}}
    if action not in fields:
        add("error", "invalid_lightshow", f"{where}.action must be one of {', '.join(CUE_ACTIONS)}")
        return
    for name in sorted(set(cue) - fields[action] - {"beat", "action", "id", "note"}):
        add("error", "unsupported_field", f"{where}.{name} is unsupported for action {action}")
    try:
        beat = _beat(cue.get("beat"))
        if beat < 0 or not math.isfinite(beat):
            raise ValueError
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        add("error", "invalid_lightshow", f"{where}.beat must be a nonnegative beat")
        return
    for name in ("id", "note"):
        if name in cue and (not isinstance(cue[name], str) or not cue[name].strip()):
            add("error", "invalid_lightshow", f"{where}.{name} must be a nonempty string")
    if "groups" in cue and (not isinstance(cue["groups"], list) or not cue["groups"]
                            or any(g not in GROUPS for g in cue["groups"])):
        add("error", "invalid_lightshow", f"{where}.groups must list light groups from {', '.join(GROUPS)}")
    if "color" in cue and cue["color"] not in COLOR_BASE:
        add("error", "invalid_lightshow", f"{where}.color must be red, blue or white")
    if "style" in cue and cue["style"] not in (*STYLE_OFFSET, "off"):
        add("error", "invalid_lightshow", f"{where}.style must be on, flash, fade, transition or off")
    if "brightness" in cue and not _number(cue["brightness"], 0, 2):
        add("error", "invalid_lightshow", f"{where}.brightness must be a number from 0 to 2")
    if action == "laser_speed":
        if cue.get("side", "both") not in ("left", "right", "both"):
            add("error", "invalid_lightshow", f"{where}.side must be left, right or both")
        if type(cue.get("speed")) is not int or not 0 <= cue["speed"] <= MAX_SPEED:
            add("error", "invalid_lightshow", f"{where}.speed must be an integer from 0 to {MAX_SPEED}")
    if action == "boost" and type(cue.get("on")) is not bool:
        add("error", "invalid_lightshow", f"{where}.on must be a boolean")
    if action == "event":
        problem = _event_problem([beat, cue.get("type"), cue.get("value"), cue.get("brightness", 1.0)])
        if problem:
            add("error", "invalid_lightshow", f"{where}: {problem}")
    if action == "clear":
        try:
            if _beat(cue.get("end_beat")) <= beat:
                raise ValueError
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            add("error", "invalid_lightshow", f"{where}.end_beat must follow beat")
        targets = cue.get("targets", list(TARGETS))
        if not isinstance(targets, list) or not targets or any(t not in (*TARGETS, "boost") for t in targets):
            add("error", "invalid_lightshow", f"{where}.targets must list names from {', '.join((*TARGETS, 'boost'))}")


def _event_problem(event) -> str | None:
    if not isinstance(event, list) or len(event) != 4:
        return "an event must be [beat, type, value, brightness]"
    beat, kind, value, brightness = event
    if not _number(beat, 0, 1e7):
        return "event beat must be a finite nonnegative number"
    if type(kind) is not int or kind not in EVENT_TYPES:
        return f"event type must be one of {EVENT_TYPES}"
    if type(value) is not int:
        return "event value must be an integer"
    if kind in LIGHT_TYPES and not 0 <= value <= 12:
        return "light event value must be 0-12"
    if kind in (LEFT_SPEED, RIGHT_SPEED) and not 0 <= value <= MAX_SPEED:
        return f"laser speed must be 0-{MAX_SPEED}"
    if kind in (RING_SPIN, RING_ZOOM) and value != 0:
        return "ring spin and zoom events take value 0"
    if not _number(brightness, 0, 2):
        return "event brightness must be 0-2"
    return None


def _validate_generated(generated, add):
    if not isinstance(generated, dict):
        add("error", "invalid_lightshow", "lightshow.generated must be an object")
        return
    allowed = {"generator", "inputs", "evidence_run", "events", "boosts", "sections"}
    for name in sorted(set(generated) - allowed):
        add("error", "unsupported_field", f"lightshow.generated.{name} is unsupported")
    events = generated.get("events", [])
    if not isinstance(events, list):
        add("error", "invalid_lightshow", "lightshow.generated.events must be an array")
    else:
        for index, event in enumerate(events):
            problem = _event_problem(event)
            if problem:
                add("error", "invalid_lightshow", f"lightshow.generated.events[{index}]: {problem}")
                break
    boosts = generated.get("boosts", [])
    if not isinstance(boosts, list) or any(not isinstance(b, list) or len(b) != 2 or not _number(b[0], 0, 1e7)
                                           or b[1] not in (0, 1) or isinstance(b[1], bool) for b in boosts):
        add("error", "invalid_lightshow", "lightshow.generated.boosts must be [beat, 0|1] pairs")


# ----------------------------------------------------------------------------- safety

def _moments(events, to_seconds):
    """Cluster light pulses into moments: [(seconds, {group: value}, [event indexes])]."""
    rows = sorted((to_seconds(e[0]), i, e) for i, e in enumerate(events) if e[1] in LIGHT_TYPES and e[2] in PULSE_VALUES)
    moments = []
    for seconds, index, event in rows:
        if moments and seconds - moments[-1][0] <= MOMENT_SECONDS:
            moments[-1][1][event[1]] = event[2]
            moments[-1][2].append(index)
        else:
            moments.append([seconds, {event[1]: event[2]}, [index]])
    return moments


def _window_max(times: list[float], width: float = 1.0) -> tuple[int, float]:
    best, at = 0, 0.0
    for i, t in enumerate(times):
        count = bisect_left(times, t + width) - i
        if count > best:
            best, at = count, t
    return best, at


def _field_times(moments, groups, values=PULSE_VALUES):
    return [m[0] for m in moments if sum(1 for v in m[1].values() if v in values) >= groups]


def strobe_findings(arrangement: dict) -> list[tuple[str, str]]:
    events, _ = compile_lightshow(arrangement)
    if not events:
        return []
    moments = _moments(events, _to_seconds(arrangement))
    found = []
    count, at = _window_max(_field_times(moments, FULL_FIELD_GROUPS))
    if count > STROBE_BLOCK_PER_SECOND:
        found.append(("light_strobe", f"{count} full-field light pulses within 1 s from {at:.2f} s "
                                      f"(limit {STROBE_BLOCK_PER_SECOND}); pulse fewer groups at once or thin the cues there."))
    count, at = _window_max(_field_times(moments, WHITE_FIELD_GROUPS, WHITE_PULSE_VALUES))
    if count > WHITE_BLOCK_PER_SECOND:
        found.append(("light_strobe", f"{count} white pulses on {WHITE_FIELD_GROUPS}+ groups within 1 s from {at:.2f} s "
                                      f"(limit {WHITE_BLOCK_PER_SECOND}); use red/blue or fewer groups."))
    return found


# ----------------------------------------------------------------------------- evidence

class _Evidence:
    """Musical evidence converted to absolute arrangement beats for lighting."""

    def __init__(self, arrangement: dict, report: dict):
        from .audio_grounding import _activity
        to_beat = _to_beats(arrangement)
        self.layers = report.get("layers") or {}
        self.onsets, self.beats, self.support = {}, {}, []
        for name, layer in self.layers.items():
            rows = []
            for event in layer.get("events", []):
                method = event.get("method")
                if method in SUPPORT_METHODS and event.get("strength", 0) >= 0.2:
                    self.support.append(to_beat(event["seconds"]))
                if method not in ONSET_METHODS:
                    continue
                delta = event.get("semitone_delta")
                if delta is None and event.get("to_midi") is not None and event.get("from_midi") is not None:
                    delta = event["to_midi"] - event["from_midi"]
                rows.append((to_beat(event["seconds"]), float(event.get("strength", 0)), delta))
            rows.sort(key=lambda r: (r[0], r[1]))
            self.onsets[name], self.beats[name] = rows, [r[0] for r in rows]
        self.support.sort()
        self.chords = sorted((to_beat(e["seconds"]), float(e.get("strength", 0)))
                             for e in (self.layers.get("mix") or {}).get("events", []) if e.get("method") == "chord_change")
        self.sustains = {name: sorted((to_beat(s["start_seconds"]), to_beat(s["end_seconds"]), float(s.get("strength", 0)))
                                      for s in layer.get("sustains") or [])
                         for name, layer in self.layers.items()}
        self.frames, self.active = _activity(report)
        contour = (self.layers.get("mix") or {}).get("energy_contour") or []
        self.energy = [float(c["energy"]) for c in contour]
        active_energy = [e for e, a in zip(self.energy, self.active) if a]
        self.median_active = median(active_energy) if active_energy else 1.0
        self.drum = next((n for n in DRUM_LAYERS if n in self.layers), "mix")
        self.bass = next((n for n in BASS_LAYERS if n in self.layers and n != self.drum), None)
        self.leads = [n for n in LEAD_LAYERS if n in self.layers and n not in (self.drum, self.bass)] or ["mix"]
        self.all_beats = sorted(b for rows in self.beats.values() for b in rows)

    def between(self, name, start, end, strength=0.0):
        rows = self.onsets.get(name) or []
        beats = self.beats.get(name) or []
        return [r for r in rows[bisect_left(beats, start):bisect_left(beats, end)] if r[1] >= strength]

    def frame_stats(self, start_seconds, end_seconds):
        lo, hi = bisect_left(self.frames, start_seconds), bisect_left(self.frames, end_seconds)
        if hi <= lo:
            return 0.0, 0.0
        return sum(self.active[lo:hi]) / (hi - lo), sum(self.energy[lo:hi]) / (hi - lo)

    def nearest_onset(self, beat, reach, names=None):
        """The strongest onset within ``reach`` beats of ``beat`` (any of ``names``), as a beat, else None.

        Onsets before beat 0 (inside the audio offset) are not on the map's timeline and never qualify.
        """
        best = None
        for name in names or self.onsets:
            for row in self.between(name, max(0.0, beat - reach), beat + reach + 1e-9):
                key = (row[1], -abs(row[0] - beat))
                if best is None or key > best[0]:
                    best = (key, row[0])
        return best[1] if best else None


def _bar_lead(evidence, spans, start, stop):
    """The layer leading a bar: articulated singing, else a declared focus lead, else the busiest pitched stem."""
    from .critique import focus_lead
    if "vocals" in evidence.layers:
        sung = evidence.between("vocals", start, stop, 0.25)
        covered = sum(max(0.0, min(e, stop) - max(s, start)) for s, e, _ in evidence.sustains.get("vocals", []))
        if len(sung) >= 2 and covered / (stop - start) >= 0.25:
            return "vocals"
    declared = focus_lead(spans, (start + stop) / 2, evidence.layers)
    if declared and declared != evidence.drum:
        return declared
    counts = [(len(evidence.between(n, start, stop, 0.3)), n) for n in evidence.leads]
    count, name = max(counts) if counts else (0, None)
    if count >= 2:
        return name
    if "mix" in evidence.layers and evidence.between("mix", start, stop, 0.3):
        return "mix"
    return None


# ----------------------------------------------------------------------------- generation

def lightshow_inputs(arrangement: dict, report: dict | None) -> str:
    """Fingerprint of everything the generated layer depends on."""
    show = arrangement.get("lightshow") or {}
    source = (report or {}).get("source") or {}
    payload = {"generator": GENERATOR_VERSION,
               "evidence": [source.get("sha256"), (report or {}).get("created_at")],
               "song": [arrangement["song"]["bpm"], arrangement["song"]["audio_offset_seconds"]],
               "tempo": arrangement.get("tempo_events") or [],
               "sections": [[s["id"], str(s["start_beat"]), str(s["length_beats"]), s.get("musical_focus") or []]
                            for s in arrangement["sections"]],
               "style": {**DEFAULT_STYLE, **(show.get("style") or {})},
               "overrides": show.get("sections") or {}}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_lightshow() -> dict:
    return {"environment": DEFAULT_ENVIRONMENT, "auto": True, "style": dict(DEFAULT_STYLE), "sections": {}, "cues": []}


class _Builder:
    def __init__(self, arrangement, evidence, style):
        self.arrangement, self.evidence, self.style = arrangement, evidence, style
        self.to_seconds = _to_seconds(arrangement)
        self.bpm = float(arrangement["song"]["bpm"])
        self.gap_beats = MIN_GROUP_GAP_SECONDS * self.bpm / 60
        self.events = []  # (beat, type, value, brightness, priority)
        self.boosts = []
        self.taken = {g: [] for g in LIGHT_TYPES}

    def free(self, beat, group):
        times = self.taken[group]
        index = bisect_left(times, beat - self.gap_beats + 1e-9)
        return not (index < len(times) and times[index] < beat + self.gap_beats - 1e-9)

    def take(self, candidate, force=False):
        lights = [e for e in candidate["lights"] if force or self.free(e[0], e[1])]
        if not lights:
            return 0
        for beat, group, value, brightness in lights:
            times = self.taken[group]
            times.insert(bisect_left(times, beat), beat)
            self.events.append((beat, group, value, brightness, candidate["priority"]))
        for beat, kind, value, brightness in candidate.get("extras", []):
            self.events.append((beat, kind, value, brightness, candidate["priority"]))
        return len(lights)


def _bars(spans):
    for span in spans:
        start = span["start_beat"]
        while start < span["end_beat"] - 1e-9:
            yield span, start, min(start + BAR_BEATS, span["end_beat"])
            start += BAR_BEATS


def _bar_levels(arrangement, evidence, spans):
    to_seconds = _to_seconds(arrangement)
    rows = []
    for span, start, stop in _bars(spans):
        seconds = max(1e-6, to_seconds(stop) - to_seconds(start))
        share, energy = evidence.frame_stats(to_seconds(start), to_seconds(stop))
        hits = len(evidence.between(evidence.drum, start, stop, 0.3))
        onsets = sum(len(evidence.between(n, start, stop, 0.3)) for n in evidence.onsets if n != "mix")
        intensity = 0.55 * min(1.0, energy / (1.5 * evidence.median_active)) + 0.45 * min(1.0, hits / seconds / 4)
        rows.append({"span": span, "start": start, "stop": stop, "seconds": seconds, "active": share,
                     "intensity": intensity, "onsets": onsets})
    ranked = sorted(r["intensity"] for r in rows if r["active"] >= 0.2) or [0.0]
    for row in rows:
        rank = bisect_left(ranked, row["intensity"] + 1e-12) / len(ranked)
        row["level"] = 0.6 * row["intensity"] + 0.4 * rank
    return rows


def _section_plan(spans, bars, show, style):
    overrides = show.get("sections") or {}
    plan, previous = {}, None
    for index, span in enumerate(spans):
        rows = [b for b in bars if b["span"] is span]
        weight = sum(b["seconds"] for b in rows) or 1.0
        active = sum(b["active"] * b["seconds"] for b in rows) / weight
        lit = [b for b in rows if b["active"] >= 0.2]
        level = sum(b["level"] * b["seconds"] for b in lit) / (sum(b["seconds"] for b in lit) or 1.0)
        onsets = sum(b["onsets"] for b in rows) / weight
        mood = ("off" if active < SECTION_ACTIVE_SHARE and onsets < SECTION_OFF_ONSET_RATE
                else "calm" if level < MOOD_CALM_BELOW
                else "peak" if level >= MOOD_PEAK_FROM else "groove")
        override = overrides.get(span["id"]) or {}
        auto = override.get("mood", "auto") == "auto"
        mood = mood if auto else override["mood"]
        palette = style["palette"]
        if palette in ("red", "blue"):
            primary = palette
        else:
            warm, cool = ("red", "blue") if palette == "cool_to_warm" else ("blue", "red")
            primary = {"calm": cool, "peak": warm}.get(mood, cool if index % 2 else warm)
        primary = override.get("primary", primary)
        plan[span["id"]] = {"mood": mood, "auto_mood": auto, "primary": primary, "level": round(level, 3),
                            "active": round(active, 3),
                            "boost": override.get("boost", style["boost"] and mood == "peak"),
                            "white": override.get("white_accents", style["white_accents"]),
                            "intensity": float(override.get("intensity", 1.0)) * float(style["intensity"]),
                            "previous": previous}
        previous = mood
    return plan


def _speed(mood, strength):
    low, high = SPEED_RANGE.get(mood, (1, 2))
    return int(round(low + (high - low) * max(0.0, min(1.0, strength))))


def _bright(mood, strength, scale=1.0):
    return round(max(0.25, min(1.2, BRIGHTNESS.get(mood, 0.8) * (0.55 + 0.5 * strength) * scale)), 2)


def _section_accent(builder, span, info, evidence):
    """Section entry: rise, fall or phrase marker, snapped onto the nearest sound."""
    mood, previous, start = info["mood"], info["previous"], span["start_beat"]
    primary, secondary = info["primary"], _other(info["primary"])
    if mood == "off":
        lights = [(start, g, 0, 0.0) for g in LIGHT_TYPES]
        extras = [(start, LEFT_SPEED, 0, 1.0), (start, RIGHT_SPEED, 0, 1.0)]
        builder.take({"priority": 200, "lights": lights, "extras": extras}, force=True)
        return
    beat = evidence.nearest_onset(start, 0.25)
    beat = _snap(start if beat is None else beat)
    rising = previous is None or MOOD_RANK[mood] > MOOD_RANK.get(previous, 0)
    falling = previous is not None and MOOD_RANK[mood] < MOOD_RANK[previous]
    extras = []
    if rising and mood in ("groove", "peak"):
        scale = 1.15 if mood == "peak" else 1.0
        accent = "white" if info["white"] and mood == "peak" else primary
        lights = [(beat, 0, _value(accent, "fade"), _bright(mood, 1.0, scale)),
                  (beat, 4, _value(accent, "fade"), _bright(mood, 1.0, scale)),
                  (beat, 1, _value(secondary, "fade"), _bright(mood, 0.9)),
                  (beat, 2, _value(secondary, "fade"), _bright(mood, 0.9)),
                  (beat, 3, _value(secondary, "fade"), _bright(mood, 0.9))]
        speed = _speed(mood, 1.0)
        extras = [(beat, LEFT_SPEED, speed, 1.0), (beat, RIGHT_SPEED, speed, 1.0), (beat, RING_ZOOM, 0, 1.0),
                  (beat, RING_SPIN, 0, 1.0)]
    elif falling or mood == "calm":
        lights = [(beat, 0, _value(primary, "fade"), _bright(mood, 0.6)),
                  (beat, 2, _value(primary, "fade"), _bright(mood, 0.6)),
                  (beat, 3, _value(primary, "fade"), _bright(mood, 0.6)),
                  (beat, 1, 0, 0.0)]
        speed = _speed(mood, 0.3)
        extras = [(beat, LEFT_SPEED, speed, 1.0), (beat, RIGHT_SPEED, speed, 1.0)]
    else:
        lights = [(beat, 0, _value(primary, "fade"), _bright(mood, 0.9)),
                  (beat, 4, _value(primary, "fade"), _bright(mood, 0.9))]
        extras = [(beat, RING_SPIN, 0, 1.0)]
    if mood == "calm":
        # Calm passages keep the center softly lit as a steady base; pulses go to the other groups.
        lights.append((beat, 4, _value(primary, "on"), 0.35))
    builder.take({"priority": 150, "lights": lights, "extras": extras}, force=True)


def _bar_candidates(builder, bar, info, evidence, spans, colors, state):
    mood, start, stop = info["mood"], bar["start"], bar["stop"]
    primary, secondary = colors
    candidates = []
    slot = 2 if mood == "calm" else 4
    # Drums: strong beats (kick) pulse back lasers and center; back beats (snare) pulse and spin the rings;
    # off-beat hits (hats, ghosts) alternate softly between rings and back lasers.
    strongest = {}
    for beat, strength, _ in evidence.between(evidence.drum, start, stop, 0.2):
        key = math.floor(beat * slot + 0.5)
        if key not in strongest or strongest[key][1] < strength:
            strongest[key] = (beat, strength)
    for beat, strength in strongest.values():
        position = beat - bar["span"]["start_beat"]
        on_beat = abs(position - round(position)) < 0.12
        snapped = _snap(beat)
        if mood == "calm":
            if strength >= 0.3:
                group = 0 if on_beat else 1
                candidates.append({"priority": 50 + 10 * strength,
                                   "lights": [(snapped, group, _value(primary if group == 0 else secondary, "fade"),
                                               _bright(mood, strength, 0.8))]})
            continue
        if on_beat and round(position) % 2 == 0:
            lights = [(snapped, 0, _value(primary, "fade"), _bright(mood, strength))]
            if mood == "peak" or strength >= 0.4:
                lights.append((snapped, 4, _value(primary, "fade"), _bright(mood, strength)))
            candidates.append({"priority": 80 + 10 * strength, "lights": lights})
        elif on_beat:
            extras = [(snapped, RING_SPIN, 0, 1.0)] if mood == "peak" or strength >= 0.5 else []
            lights = [(snapped, 1, _value(secondary, "fade"), _bright(mood, strength))]
            if mood == "peak" and strength >= 0.5:
                lights.append((snapped, 0, _value(secondary, "fade"), _bright(mood, strength, 0.8)))
            candidates.append({"priority": 75 + 10 * strength, "lights": lights, "extras": extras})
        elif strength >= 0.25:
            state["hat"] = 1 - state.get("hat", 0)
            group = (1, 0)[state["hat"]]
            candidates.append({"priority": 35 + 10 * strength,
                               "lights": [(snapped, group, _value(secondary, "fade"), _bright(mood, strength, 0.7))]})
    # Bass: center pulses under the groove; in calm passages the rings breathe with it (the center is the base).
    if evidence.bass:
        for beat, strength, _ in evidence.between(evidence.bass, start, stop, 0.3):
            group = 1 if mood == "calm" else 4
            candidates.append({"priority": 40 + 10 * strength,
                               "lights": [(_snap(beat), group, _value(primary, "fade"), _bright(mood, strength, 0.7))]})
    # Lead: side lasers follow the voice, riff or melody; pitch direction picks the side, speed follows energy.
    lead = _bar_lead(evidence, spans, start, stop)
    if lead:
        state["leads"][lead] = state["leads"].get(lead, 0) + 1
        color = primary if mood == "calm" else secondary
        held = [s for s in evidence.sustains.get(lead, []) if start <= s[0] < stop and s[1] - s[0] >= 1.0]
        sustain_starts = {round(s[0], 2): s for s in held}
        rows = evidence.between(lead, start, stop, 0.25 if mood == "calm" else 0.2)
        per_slot = {}
        for row in rows:
            key = math.floor(row[0] * 4 + 0.5)
            if key not in per_slot or per_slot[key][1] < row[1]:
                per_slot[key] = row
        for beat, strength, delta in sorted(per_slot.values(), key=lambda r: r[0]):
            if delta is not None and abs(delta) >= 0.8:
                side = 3 if delta > 0 else 2
            else:
                side = 2 if state["side"] == 3 else 3
            state["side"] = side
            snapped = _snap(beat)
            speed_type = LEFT_SPEED if side == 2 else RIGHT_SPEED
            speed = _speed(mood, 0.5 * strength + 0.5 * bar["level"])
            sustain = next((s for key, s in sustain_starts.items() if abs(key - beat) <= 0.15), None)
            if sustain and mood != "peak":
                end = _snap(min(sustain[1], stop + BAR_BEATS))
                lights = [(snapped, side, _value(color, "on"), _bright(mood, strength)),
                          (end, side, _value(color, "fade"), _bright(mood, strength, 0.8))]
            else:
                lights = [(snapped, side, _value(color, "fade"), _bright(mood, strength))]
                if mood == "peak" or (mood == "groove" and strength >= 0.35):
                    lights.append((snapped, 5 - side, _value(color, "fade"), _bright(mood, strength)))
            extras = [(snapped, speed_type, speed, 1.0)]
            if len(lights) > 1 and lights[1][1] != side:
                extras.append((snapped, LEFT_SPEED + RIGHT_SPEED - speed_type, speed, 1.0))
            candidates.append({"priority": 60 + 20 * strength, "lights": lights, "extras": extras})
    # Accompaniment: the busiest other pitched stem (a riff under the voice, chords under a solo) breathes
    # softly on the rings, and on the back lasers between drum hits.
    others = [(len(evidence.between(n, start, stop, 0.3)), n) for n in evidence.leads if n not in (lead, "mix")]
    count, second = max(others) if others else (0, None)
    if second and count >= 2:
        for n, (beat, strength, _) in enumerate(evidence.between(second, start, stop, 0.3)):
            group = 1 if mood == "calm" or n % 2 == 0 else 0
            candidates.append({"priority": 30 + 10 * strength,
                               "lights": [(_snap(beat), group, _value(secondary if group == 1 else primary, "fade"),
                                           _bright(mood, strength, 0.6))]})
    # Ring motion: phrase starts and drum fills, always on a sound.
    index = int(round((start - bar["span"]["start_beat"]) / BAR_BEATS))
    spin_every = {"peak": 1, "groove": 2, "calm": 4}.get(mood)
    if spin_every and index % spin_every == 0 and index:
        at = evidence.nearest_onset(start, 0.25, [evidence.drum] + ([lead] if lead else []))
        if at is not None:
            candidates.append({"priority": 90, "lights": [], "extras": [(_snap(at), RING_SPIN, 0, 1.0)]})
    if mood in ("groove", "peak") and index % 4 == 3:
        fill = evidence.between(evidence.drum, stop - 1, stop, 0.3)
        if len(fill) >= 3:
            candidates.append({"priority": 90, "lights": [], "extras": [(_snap(fill[0][0]), RING_SPIN, 0, 1.0)]})
    return candidates


def _select(builder, bar, info, candidates):
    target = TARGET_RATE.get(info["mood"], 0) * info["intensity"] * (0.7 + 0.6 * bar["level"]) * bar["seconds"]
    if bar["active"] < 0.2:
        target *= 0.5
    count = 0
    for candidate in sorted(candidates, key=lambda c: (-c["priority"], c["lights"][0][0] if c["lights"] else 0)):
        if not candidate["lights"]:
            builder.take(candidate)
            continue
        if count >= target:
            continue
        count += builder.take(candidate)


def _fill_gaps(builder, evidence, plan, spans):
    """Keep the lights answering the song: pulse the strongest sounds in any lit gap longer than FILL_GAP_SECONDS."""
    times = sorted(builder.to_seconds(e[0]) for e in builder.events if e[1] in LIGHT_TYPES and e[2] != 0)
    to_beat = _to_beats(builder.arrangement)
    for span in spans:
        info = plan[span["id"]]
        if info["mood"] == "off":
            continue
        lo, hi = builder.to_seconds(span["start_beat"]), builder.to_seconds(span["end_beat"])
        inside = [t for t in times if lo <= t < hi]
        edges = [lo] + inside + [hi]
        for left, right in zip(edges, edges[1:]):
            if right - left <= FILL_GAP_SECONDS:
                continue
            share, _ = evidence.frame_stats(left, right)
            if share < 0.5:
                continue
            first, last = to_beat(left) + 0.5, to_beat(right) - 0.25
            chosen = sorted((r for name in evidence.onsets for r in evidence.between(name, first, last, 0.1)),
                            key=lambda r: -r[1])
            picked = []
            for beat, strength, _ in chosen:
                if all(abs(beat - p) >= 1.0 for p in picked):
                    picked.append(beat)
            color = info["primary"]
            for n, beat in enumerate(sorted(picked)):
                group = (0, 1)[n % 2] if info["mood"] == "calm" else (0, 1, 4)[n % 3]
                builder.take({"priority": 20, "lights": [(_snap(beat), group, _value(color, "fade"),
                                                          _bright(info["mood"], 0.5))]})


def _limit_strobe(builder):
    """Strip the lowest-priority groups from full-field moments until at most 4 fall in any 1 s window."""
    for _ in range(1000):
        events = [e[:4] for e in builder.events]
        moments = _moments(events, builder.to_seconds)
        full = [m for m in moments if len(m[1]) >= FULL_FIELD_GROUPS]
        times = [m[0] for m in full]
        count, at = _window_max(times)
        if count <= GENERATOR_FULL_FIELD_PER_SECOND:
            return
        window = [m for m in full if at <= m[0] < at + 1.0]
        victim = min(window, key=lambda m: (max(builder.events[i][4] for i in m[2]), m[0]))
        ranked = sorted(victim[2], key=lambda i: builder.events[i][4])
        drop = set(ranked[:len(ranked) - (FULL_FIELD_GROUPS - 1)])
        builder.events = [e for i, e in enumerate(builder.events) if i not in drop]


def generate_lightshow(arrangement: dict, report: dict, run_id: str | None = None,
                       previous: dict | None = None) -> dict:
    """Build the arrangement's lightshow from musical evidence; keeps inputs, cues and locked sections' lights.

    ``previous`` is the stored lightshow whose generated events stay unchanged inside locked sections.
    """
    show = deepcopy(arrangement.get("lightshow")) if isinstance(arrangement.get("lightshow"), dict) else default_lightshow()
    style = {**DEFAULT_STYLE, **(show.get("style") or {})}
    evidence = _Evidence(arrangement, report)
    spans = _spans(arrangement)
    bars = _bar_levels(arrangement, evidence, spans)
    plan = _section_plan(spans, bars, show, style)
    builder = _Builder(arrangement, evidence, style)
    first = min((s["start_beat"] for s in spans), default=0.0)
    # The song starts dark; the lowest priority lets a section entry on beat 0 set its own state.
    builder.take({"priority": 0, "lights": [(0.0, g, 0, 0.0) for g in LIGHT_TYPES]}, force=True)
    state = {"side": 3, "leads": {}}
    boost_on = False
    for span in spans:
        info = plan[span["id"]]
        state["leads"] = {}
        _section_accent(builder, span, info, evidence)
        want = bool(info["boost"]) and info["mood"] != "off"
        if want != boost_on:
            builder.boosts.append((_snap(span["start_beat"]), 1 if want else 0))
            boost_on = want
        if info["mood"] == "off":
            info["leads"] = []
            continue
        swapped, last_swap = False, -1e9
        for bar in (b for b in bars if b["span"] is span):
            chord = next((c for c in evidence.chords if abs(c[0] - bar["start"]) <= 0.5 and c[1] >= CHORD_SWAP_STRENGTH),
                         None)
            if chord and info["mood"] in ("groove", "peak") and bar["start"] - last_swap >= SWAP_MIN_BEATS \
                    and bar["start"] > span["start_beat"]:
                swapped, last_swap = not swapped, bar["start"]
            colors = (_other(info["primary"]), info["primary"]) if swapped else (info["primary"], _other(info["primary"]))
            _select(builder, bar, info, _bar_candidates(builder, bar, info, evidence, spans, colors, state))
        info["leads"] = [name for name, _ in sorted(state["leads"].items(), key=lambda i: -i[1]) if name][:2]
    _fill_gaps(builder, evidence, plan, spans)
    last = max((s["end_beat"] for s in spans), default=first)
    builder.take({"priority": 300, "lights": [(_snap(last), g, 0, 0.0) for g in LIGHT_TYPES]}, force=True)
    _limit_strobe(builder)
    # One event per group and beat: two values at the same instant leave the group's state to sort order,
    # so the higher-priority one (a section entry over a bar pulse) wins.
    chosen = {}
    for beat, kind, value, brightness, priority in builder.events:
        key = (round(beat, 4), kind)
        if key not in chosen or priority > chosen[key][4]:
            chosen[key] = (key[0], kind, value, round(brightness, 2), priority)
    events = sorted((e[:4] for e in chosen.values()),
                    key=lambda e: (e[0], {LEFT_SPEED: -2, RIGHT_SPEED: -1}.get(e[1], e[1]), e[2]))
    boosts = [(round(b, 4), on) for b, on in builder.boosts]
    # Locked sections keep the lights they were approved with.
    locked = [(s["start_beat"], s["end_beat"]) for s in spans if s["section"].get("locked")]
    old = (previous or {}).get("generated") if isinstance(previous, dict) else None
    if locked and old:
        inside = lambda beat: any(a <= beat < b for a, b in locked)
        events = [e for e in events if not inside(e[0])] + [tuple(e) for e in old.get("events", []) if inside(e[0])]
        boosts = [b for b in boosts if not inside(b[0])] + [tuple(b) for b in old.get("boosts", []) if inside(b[0])]
        events.sort(key=lambda e: (e[0], {LEFT_SPEED: -2, RIGHT_SPEED: -1}.get(e[1], e[1]), e[2]))
        boosts.sort()
    to_seconds = builder.to_seconds
    summary = []
    for span in spans:
        info = plan[span["id"]]
        seconds = max(1e-6, to_seconds(span["end_beat"]) - to_seconds(span["start_beat"]))
        count = sum(1 for e in events if span["start_beat"] <= e[0] < span["end_beat"] and e[1] in LIGHT_TYPES)
        summary.append({"id": span["id"], "mood": info["mood"], "auto_mood": info["auto_mood"],
                        "primary": info["primary"], "level": info["level"], "boost": bool(info["boost"]),
                        "leads": info.get("leads", []), "light_events_per_second": round(count / seconds, 2)})
    show.setdefault("environment", DEFAULT_ENVIRONMENT)
    show.setdefault("auto", True)
    show.setdefault("cues", [])
    show["generated"] = {"generator": GENERATOR_VERSION, "inputs": lightshow_inputs({**arrangement, "lightshow": show}, report),
                         "evidence_run": run_id, "sections": summary,
                         "events": [[e[0], e[1], e[2], e[3]] for e in events],
                         "boosts": [[b[0], b[1]] for b in boosts]}
    return show


# ----------------------------------------------------------------------------- project integration

def lightshow_state(arrangement: dict, report: dict | None) -> str:
    show = arrangement.get("lightshow")
    if not isinstance(show, dict):
        return "missing"
    if report is None:
        return "no_evidence"
    generated = show.get("generated") or {}
    return "current" if generated.get("inputs") == lightshow_inputs(arrangement, report) else "stale"


def refresh_lightshow(arrangement: dict, original: dict | None, run_id: str | None, report: dict | None,
                      *, force: bool = False) -> tuple[dict, dict]:
    """The arrangement to store: lights carried over when omitted, regenerated when missing or stale.

    Returns (arrangement, {"action": ..., "reason": ...}). Nothing changes without an evidence run.
    """
    result = arrangement
    if "lightshow" not in arrangement and isinstance((original or {}).get("lightshow"), dict):
        result = {**arrangement, "lightshow": deepcopy(original["lightshow"])}
    if report is None:
        return result, {"action": "none", "reason": "no musical evidence run for the current audio"}
    state = lightshow_state(result, report)
    show = result.get("lightshow")
    if not force and state == "current":
        return result, {"action": "kept", "reason": "generated lights match their inputs"}
    if not force and state == "stale" and show.get("auto") is False:
        return result, {"action": "kept", "reason": "inputs changed but lightshow.auto is false"}
    regenerated = generate_lightshow(result, report, run_id, (original or {}).get("lightshow"))
    return {**result, "lightshow": regenerated}, {"action": "generated", "reason": "forced" if force else state}


def locked_light_changes(original: dict, arrangement: dict) -> list[str]:
    """Locked sections whose compiled lights differ between the stored and the new arrangement."""
    if not isinstance(original.get("lightshow"), dict):
        return []
    before, before_boosts = compile_lightshow(original)
    after, after_boosts = compile_lightshow(arrangement)
    changed = []
    for span in _spans(original):
        if not span["section"].get("locked"):
            continue
        inside = lambda rows: [r for r in rows if span["start_beat"] <= r[0] < span["end_beat"]]
        if inside(before) != inside(after) or inside(before_boosts) != inside(after_boosts):
            changed.append(span["id"])
    return changed


# ----------------------------------------------------------------------------- review

def _lit_intervals(events, to_seconds):
    """Per light group, the (start, end) seconds when it is lit, from its event sequence."""
    lit = {g: [] for g in LIGHT_TYPES}
    for group in LIGHT_TYPES:
        rows = [(to_seconds(e[0]), e[2]) for e in events if e[1] == group]
        on_since = 0.0  # environments start lit until a group's first event
        for seconds, value in rows:
            if on_since is not None:
                lit[group].append((on_since, seconds))
                on_since = None
            if value in FADE_VALUES:
                lit[group].append((seconds, seconds + FADE_LIT_SECONDS))
            elif value != 0:
                on_since = seconds
        if on_since is not None:
            lit[group].append((on_since, float("inf")))
    return lit


def _dark_spans(events, to_seconds, end):
    intervals = sorted(i for rows in _lit_intervals(events, to_seconds).values() for i in rows)
    dark, reach = [], 0.0
    for start, stop in intervals:
        if start > reach:
            dark.append((reach, start))
        reach = max(reach, stop)
    if reach < end:
        dark.append((reach, end))
    return dark


def lighting_findings(arrangement: dict, report: dict | None) -> tuple[dict, list[dict]]:
    """(metrics, warnings) for the lightshow against the song's evidence and the notes."""
    findings = []

    def add(code, message, *, value=None, threshold=None, section_id=None, beats=None):
        findings.append({"severity": "warning", "code": code, "message": message, "section_id": section_id,
                         "object_ids": [], "value": value, "threshold": threshold})
        if beats is not None:
            findings[-1]["beats"] = beats

    show = arrangement.get("lightshow")
    if not isinstance(show, dict):
        if report is None:  # nothing to generate from; the audio checks report the missing evidence
            return {"checked": False, "state": "missing"}, findings
        add("lightshow_missing", "No lightshow: the export only pulses once per section. Run `project lights ID` "
                                 "(or save with a musical evidence run) to generate one.")
        return {"checked": False, "state": "missing"}, findings
    state = lightshow_state(arrangement, report)
    if state == "stale":
        add("lightshow_stale", "The generated lights were built from other inputs than this arrangement has "
                               "(evidence, timing, sections, style or overrides). Run `project lights ID`.")
    events, boosts = compile_lightshow(arrangement)
    to_seconds = _to_seconds(arrangement)
    to_beat = _to_beats(arrangement)
    spans = _spans(arrangement)
    light_rows = [e for e in events if e[1] in LIGHT_TYPES]
    moments = _moments(events, to_seconds)
    full_times = _field_times(moments, FULL_FIELD_GROUPS)
    per_section = []
    generated = {s["id"]: s for s in (show.get("generated") or {}).get("sections") or []}
    for span in spans:
        seconds = max(1e-6, to_seconds(span["end_beat"]) - to_seconds(span["start_beat"]))
        count = sum(1 for e in light_rows if span["start_beat"] <= e[0] < span["end_beat"])
        row = {"id": span["id"], "mood": (generated.get(span["id"]) or {}).get("mood"),
               "light_events_per_second": round(count / seconds, 2)}
        per_section.append(row)
    metrics = {"checked": True, "state": state, "environment": show.get("environment"),
               "light_events": len(light_rows), "other_events": len(events) - len(light_rows),
               "boost_events": len(boosts), "cues": len(show.get("cues") or []),
               "max_full_field_per_second": _window_max(full_times)[0], "sections": per_section}
    # Sustained heavy flashing.
    heavy = [t for t in full_times
             if bisect_left(full_times, t + 1.0) - bisect_left(full_times, t) > HEAVY_FLASH_PER_SECOND]
    if heavy:
        runs, current = [], [heavy[0], heavy[0] + 1.0]
        for t in heavy[1:]:
            if t <= current[1]:
                current[1] = t + 1.0
            else:
                runs.append(current)
                current = [t, t + 1.0]
        runs.append(current)
        for first, last in runs:
            if last - first >= HEAVY_FLASH_SECONDS:
                add("light_flash_heavy", f"{first:.1f}-{last:.1f} s: more than {HEAVY_FLASH_PER_SECOND} full-field "
                                         "pulses every second; spread the hits over fewer groups.",
                    value=round(last - first, 2), threshold=HEAVY_FLASH_SECONDS,
                    beats=[round(to_beat(first), 3), round(to_beat(last), 3)])
    if report is None:
        return metrics, findings
    evidence_onsets = sorted(float(e["seconds"]) for layer in (report.get("layers") or {}).values()
                             for e in layer.get("events", [])
                             if e.get("method") in SUPPORT_METHODS and e.get("strength", 0) >= 0.2)
    # Static lights over active, articulated audio.
    from .audio_grounding import _activity
    frames, active = _activity(report)
    change_times = sorted(to_seconds(e[0]) for e in events if not (e[1] in LIGHT_TYPES and e[2] == 0))
    duration = float((report.get("source") or {}).get("duration_seconds") or (frames[-1] if frames else 0))
    song_end = min(duration, to_seconds(max((s["end_beat"] for s in spans), default=0)))
    edges = [0.0] + [t for t in change_times if 0 <= t <= song_end] + [song_end]
    for left, right in zip(edges, edges[1:]):
        if right - left < STATIC_WARN_SECONDS:
            continue
        lo, hi = bisect_left(frames, left), bisect_left(frames, right)
        share = sum(active[lo:hi]) / (hi - lo) if hi > lo else 0.0
        onsets = bisect_left(evidence_onsets, right) - bisect_left(evidence_onsets, left)
        if share >= 0.6 and onsets >= STATIC_ONSET_RATE * (right - left):
            start_beat = round(to_beat(left), 3)
            add("light_unmapped", f"{left:.1f}-{right:.1f} s (beats {start_beat:g}-{to_beat(right):.3f}): the song plays "
                                  f"with {onsets} onsets but no light changes for {right - left:.1f} s.",
                value=round(right - left, 2), threshold=STATIC_WARN_SECONDS,
                section_id=next((s["id"] for s in spans if s["start_beat"] <= start_beat < s["end_beat"]), None),
                beats=[start_beat, round(to_beat(right), 3)])
    # Pulses on the grid rather than on sounds.
    tolerance = SUPPORT_BEATS * 60 / float(arrangement["song"]["bpm"])
    run = []
    for moment in moments + [None]:
        supported = True
        if moment is not None:
            index = bisect_left(evidence_onsets, moment[0] - tolerance)
            supported = index < len(evidence_onsets) and evidence_onsets[index] <= moment[0] + tolerance
        if not supported:
            run.append(moment[0])
            continue
        if len(run) >= UNSUPPORTED_LIGHT_RUN:
            first, last = round(to_beat(run[0]), 3), round(to_beat(run[-1]), 3)
            add("light_without_audio", f"Beats {first:g}-{last:g}: {len(run)} consecutive light pulses with no sound "
                                       "under them; move them onto onsets or remove them.",
                value=len(run), threshold=UNSUPPORTED_LIGHT_RUN, beats=[first, last],
                section_id=next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None))
        run = []
    # Density against the reference band: too sparse only where the stems carry enough strong onsets.
    layers = report.get("layers") or {}
    stem_onsets = {name: sorted(float(e["seconds"]) for e in layer.get("events", [])
                                if e.get("method") in ONSET_METHODS and e.get("strength", 0) >= 0.3)
                   for name, layer in layers.items() if name != "mix" or len(layers) == 1}
    for span, row in zip(spans, per_section):
        if row["mood"] == "off":
            continue
        lo, hi = to_seconds(span["start_beat"]), to_seconds(span["end_beat"])
        a, b = bisect_left(frames, lo), bisect_left(frames, hi)
        share = sum(active[a:b]) / (b - a) if b > a else 0.0
        rate = row["light_events_per_second"]
        strong = sum(bisect_left(t, hi) - bisect_left(t, lo) for t in stem_onsets.values()) / max(1e-6, hi - lo)
        if (share >= 0.6 and strong >= DENSITY_LOW and rate < DENSITY_LOW) or rate > DENSITY_HIGH:
            add("light_density", f"Section {span['id']}: {rate:g} light events per second, outside the reference range "
                                 f"{DENSITY_LOW:g}-{DENSITY_HIGH:g}.",
                value=rate, threshold=DENSITY_LOW if rate < DENSITY_LOW else DENSITY_HIGH, section_id=span["id"],
                beats=[span["start_beat"], span["end_beat"]])
    # Darkness while notes are in play.
    from .arrangement import expanded_notes
    note_seconds = sorted(to_seconds(n["beat"]) for n in expanded_notes(arrangement))
    bpm = float(arrangement["song"]["bpm"])
    for start, stop in _dark_spans(events, to_seconds, song_end):
        if (stop - start) * bpm / 60 < BLACKOUT_BEATS:
            continue
        edge = SUPPORT_BEATS * 60 / bpm  # a note on the pulse that ends the darkness is lit
        inside = bisect_left(note_seconds, stop - edge) - bisect_left(note_seconds, start + edge)
        if inside:
            first, last = round(to_beat(start), 3), round(to_beat(stop), 3)
            add("light_blackout_notes", f"Beats {first:g}-{last:g}: every light is dark for {stop - start:.1f} s while "
                                        f"{inside} note(s) are played.",
                value=round((stop - start) * bpm / 60, 2), threshold=BLACKOUT_BEATS, beats=[first, last],
                section_id=next((s["id"] for s in spans if s["start_beat"] <= first < s["end_beat"]), None))
    return metrics, findings


def inspect_lights(arrangement: dict, report: dict | None, start: float, end: float) -> dict:
    """Readable lighting timeline for [start, end) beats: events by moment, with the sounds under them."""
    events, boosts = compile_lightshow(arrangement)
    to_seconds = _to_seconds(arrangement)
    show = arrangement.get("lightshow") or {}
    onsets = []
    if report:
        to_beat = _to_beats(arrangement)
        for name, layer in (report.get("layers") or {}).items():
            for e in layer.get("events", []):
                if e.get("method") in SUPPORT_METHODS and e.get("strength", 0) >= 0.3:
                    beat = to_beat(e["seconds"])
                    if start - 0.2 <= beat < end + 0.2:
                        onsets.append((beat, name, e["method"], round(float(e["strength"]), 2)))
    onsets.sort()
    rows = {}
    for beat, kind, value, brightness in events:
        if not start <= beat < end:
            continue
        if kind in LIGHT_TYPES:
            text = f"{GROUP_NAMES[kind]} {VALUE_NAMES.get(value, value)}" + (f" x{brightness:g}" if value else "")
        elif kind in (LEFT_SPEED, RIGHT_SPEED):
            text = f"{'left' if kind == LEFT_SPEED else 'right'} speed {value}"
        else:
            text = "ring spin" if kind == RING_SPIN else "ring zoom"
        rows.setdefault(round(beat, 4), []).append(text)
    for beat, on in boosts:
        if start <= beat < end:
            rows.setdefault(round(beat, 4), []).append("boost on" if on else "boost off")
    timeline = []
    for beat in sorted(rows):
        near = [f"{name}:{method}:{strength}" for b, name, method, strength in onsets if abs(b - beat) <= SUPPORT_BEATS]
        timeline.append({"beat": beat, "seconds": round(to_seconds(beat), 3), "events": rows[beat], "sounds": near})
    sections = [s for s in (show.get("generated") or {}).get("sections") or []]
    spans = {s["id"]: s for s in _spans(arrangement)}
    sections = [s for s in sections if s["id"] in spans and spans[s["id"]]["start_beat"] < end
                and spans[s["id"]]["end_beat"] > start]
    cues = [c for c in show.get("cues") or [] if start <= _beat(c["beat"]) < end]
    return {"start_beat": start, "end_beat": end, "environment": show.get("environment"),
            "state": lightshow_state(arrangement, report) if show else "missing",
            "sections": sections, "cues": cues, "timeline": timeline}
