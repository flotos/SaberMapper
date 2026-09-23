"""A map's style: one idea per song, decided before drafting, that the draft, the placer and the check follow.

Before drafting, the agent looks at the song (title and lyrics, the spectrogram overview, which stems carry it,
tempo, mood, the recurring themes) and brainstorms three candidate styles. Each is one sentence grounded in that
evidence, plus six settings and optional signature moves tied to the song's themes. The candidates are scored on
a rubric; the selected one goes into every difficulty's arrangement as ``style``:

    "style": {"idea": "...", "grounding": ["..."], "settings": {"flow": "angular", ...},
              "signatures": [{"theme": "gallop-riff", "move": "..."}]}

Settings (the middle value is the default, and a map without a style places exactly as before):

* ``flow`` (round / balanced / angular): how far cuts turn away from clean reversals and how far the hands
  travel. Round keeps swings on clean pendulums with short travel; angular aims each cut about 45 degrees off the
  reversal and travels more.
* ``diagonals`` (few / some / many): how often cuts run diagonally.
* ``top_row`` (low / normal / high): how often the hands lift to the top row.
* ``arcs`` (sparse / normal / lavish): how short a held sound the draft still carries as an arc.
* ``accents`` (sparse / normal / heavy): how many doubles a loud bar's heaviest hits get in the draft.
* ``theme_variation`` (repeat / alternate / mirror): how a returning theme varies (never, every second echo, or
  every echo mirrored; a transposed return is always mirrored).

A style never adds a note without a sound, never relaxes a movement rule and never raises the difficulty past
its target tier: it chooses among the options the audio already supports. ``project check`` reports a map without
a style (``style_missing``) and a measured style that contradicts the declared one (``style_drift``).
"""

from __future__ import annotations

import re
import uuid
from fractions import Fraction
from pathlib import Path

from .storage import digest, now, read_json, write_json

STYLE_VERSION = "1.0"
SETTINGS = {"flow": ("round", "balanced", "angular"),
            "diagonals": ("few", "some", "many"),
            "top_row": ("low", "normal", "high"),
            "arcs": ("sparse", "normal", "lavish"),
            "accents": ("sparse", "normal", "heavy"),
            "theme_variation": ("repeat", "alternate", "mirror")}
DEFAULTS = {name: values[1] for name, values in SETTINGS.items()}
CANDIDATES = 3
RUBRIC = {"grounded": "Follows from this song: its sound (stems, tempo, spectrogram), mood, title or lyrics",
          "one_idea": "One idea a player could name after one run, not a list of effects",
          "serves_audio": "Every setting helps the map follow the audio; none adds notes for their own sake",
          "playable": "Fits the player's tier and recorded preferences (PLAYER.md, player-profile.json)",
          "distinct": "Differs from the other songs' styles in the workspace"}
# Draft parameters per setting.
ARC_SCALE = {"sparse": 1.6, "normal": 1.0, "lavish": 0.7}  # multiplies the held-note length an arc needs
DOUBLES_PER_BAR = {"sparse": 1, "normal": 2, "heavy": 3}
# Measured bands per setting value: (metric, low, high). A value outside its band is style_drift. Bands were set
# from the workspace songs placed under each value (see docs/critique.md, Style).
DRIFT_BANDS = {"flow": ("turn_degrees", {"round": (None, 14.0), "angular": (34.0, None)}),
               "diagonals": ("diagonal_share", {"few": (None, 0.3), "many": (0.55, None)}),
               "top_row": ("top_row_share", {"low": (None, 0.13), "high": (0.23, None)})}
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DEFINITIONS = {
    "turn_degrees": "Mean angle, in degrees, between each cut and the clean reversal of the same hand's previous "
                    "cut, over same-hand swings under 2 s apart (dots skipped): 0 is a pure up-down pendulum.",
    "diagonal_share": "Share of the directional notes (not dots) cut diagonally (directions 4-7).",
    "accent_share": "Share of note times that carry two or more notes (doubles and stacks).",
    "arcs_per_minute": "Arcs per minute between the first and the last note.",
    "style_missing": "The arrangement declares no style: nothing records what makes this map its song's own.",
    "style_drift": "A declared flow, diagonals or top_row setting whose measured metric falls outside its band: "
                   "round flow turns at most 14 degrees on average and angular at least 34 (the default places "
                   "about 20-25); few diagonals at most 30% and many at least 55% (default about 45-50%); a low "
                   "top row at most 13% and a high one at least 23% (default about 18-21%).",
}


class StyleError(ValueError):
    def __init__(self, code, message, fix, details=None):
        super().__init__(message)
        self.code, self.fix, self.details = code, fix, details or {}


def _text(value, limit=400):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def settings_of(arrangement: dict) -> dict:
    """Every setting of the arrangement's style, defaults filled in."""
    style = arrangement.get("style") if isinstance(arrangement, dict) else None
    settings = style.get("settings") if isinstance(style, dict) else None
    settings = settings if isinstance(settings, dict) else {}
    return {name: settings.get(name) if settings.get(name) in values else DEFAULTS[name]
            for name, values in SETTINGS.items()}


def _check_style(style, where, add, themes=None):
    """Structural problems of one style (an arrangement block or a candidate) through ``add(message)``."""
    if not isinstance(style, dict):
        add(f"{where} must be an object")
        return
    extra = set(style) - {"id", "idea", "grounding", "settings", "signatures", "rubric", "source"}
    if extra:
        add(f"{where} has unsupported fields {sorted(extra)}")
    if not _text(style.get("idea")):
        add(f"{where}.idea must be one sentence naming the map's idea")
    grounding = style.get("grounding")
    if not isinstance(grounding, list) or not grounding or not all(_text(g) for g in grounding):
        add(f"{where}.grounding must list the song evidence the idea follows from (title, lyrics, stems, "
            "spectrogram, mood, tempo)")
    settings = style.get("settings")
    if not isinstance(settings, dict):
        add(f"{where}.settings must be an object")
    else:
        for name, value in settings.items():
            if name not in SETTINGS:
                add(f"{where}.settings.{name} is unknown; settings are {', '.join(SETTINGS)}")
            elif value not in SETTINGS[name]:
                add(f"{where}.settings.{name} must be one of {', '.join(SETTINGS[name])}")
    signatures = style.get("signatures", [])
    if not isinstance(signatures, list):
        add(f"{where}.signatures must be an array")
        signatures = []
    for number, signature in enumerate(signatures):
        if not isinstance(signature, dict) or set(signature) != {"theme", "move"} or not _text(signature.get("move")) \
                or not isinstance(signature.get("theme"), str):
            add(f"{where}.signatures[{number}] must be {{theme, move}}")
        elif themes is not None and signature["theme"] not in themes:
            add(f"{where}.signatures[{number}].theme {signature['theme']!r} names no declared theme")


def validate_style(arrangement: dict, add) -> None:
    """Report a malformed arrangement ``style`` through ``add(severity, code, message)``."""
    themes = {t.get("id") for t in arrangement.get("themes") or [] if isinstance(t, dict)}
    _check_style(arrangement["style"], "style", lambda message: add("error", "invalid_style", message), themes)


# ---------------------------------------------------------------------------------------------------------
# Measured style
# ---------------------------------------------------------------------------------------------------------

def style_metrics(arrangement: dict) -> dict:
    """The measured style of a placed arrangement (see ``DEFINITIONS``)."""
    from .arrangement import expanded_notes
    from .critique import beat_to_seconds
    from .movement import _OPPOSITE, turn_degrees
    notes = expanded_notes(arrangement)
    if not notes:
        return {"notes": 0}
    seconds = {n["id"]: beat_to_seconds(float(n["beat"]), arrangement) for n in notes}
    turns, last = [], {}
    for note in notes:
        hand, direction = note["color"], note["direction"]
        previous = last.get(hand)
        if direction != 8 and previous is not None and previous[1] != 8 and \
                0 < seconds[note["id"]] - previous[0] < 2.0 and note["beat"] != previous[2]:
            turns.append(turn_degrees(_OPPOSITE[previous[1]], direction))
        if note["beat"] != (previous or (None, None, None))[2]:
            last[hand] = (seconds[note["id"]], direction, note["beat"])
    directional = [n for n in notes if n["direction"] != 8]
    times = {}
    for note in notes:
        times[note["beat"]] = times.get(note["beat"], 0) + 1
    arcs = sum(len(s.get("arcs", [])) for s in arrangement["sections"])
    minutes = max(1e-9, (max(seconds.values()) - min(seconds.values())) / 60)
    return {"notes": len(notes),
            "turn_degrees": round(sum(turns) / len(turns), 2) if turns else None,
            "diagonal_share": round(sum(1 for n in directional if n["direction"] in (4, 5, 6, 7))
                                    / len(directional), 4) if directional else None,
            "top_row_share": round(sum(1 for n in notes if n["y"] == 2) / len(notes), 4),
            "accent_share": round(sum(1 for c in times.values() if c > 1) / len(times), 4),
            "arcs_per_minute": round(arcs / minutes, 3)}


def style_findings(arrangement: dict, warn) -> dict:
    """``style_missing`` and ``style_drift`` warnings through ``warn``; returns the declared and measured style."""
    measured = style_metrics(arrangement)
    declared = arrangement.get("style") if isinstance(arrangement.get("style"), dict) else None
    result = {"declared": declared, "settings": settings_of(arrangement), "measured": measured}
    if declared is None:
        warn("style_missing", "The map declares no style: brainstorm one from the song (`style template`), save it "
                              "with `style save` and add the selected style to every difficulty's arrangement.",
             value=None, threshold=None)
        return result
    settings = declared.get("settings") if isinstance(declared.get("settings"), dict) else {}
    for name, (metric, bands) in DRIFT_BANDS.items():
        value, band = measured.get(metric), bands.get(settings.get(name))
        if value is None or band is None:
            continue
        low, high = band
        if (low is not None and value < low) or (high is not None and value > high):
            warn("style_drift",
                 f'style declares {name} {settings[name]}, but the map measures {metric} {value:g} '
                 f'(expected {"at least " + format(low, "g") if low is not None else "at most " + format(high, "g")}); '
                 "pinned or stored placements hold the old look. Unpin the placer-chosen fields (drop x, y, color, "
                 "direction and placed) so the placer follows the style, or change the setting.",
                 value=value, threshold=low if low is not None else high)
    return result


# ---------------------------------------------------------------------------------------------------------
# Brainstorm document: three candidates, scored, one selected
# ---------------------------------------------------------------------------------------------------------

def style_file(directory: Path) -> Path:
    return Path(directory) / "style.json"


def _unwrap(document):
    if isinstance(document, dict) and "candidates" not in document and isinstance(document.get("style"), dict):
        return document["style"]
    return document


def _themes(store, directory):
    ids = set()
    for file in store.difficulty_files(directory).values():
        ids |= {t.get("id") for t in read_json(file).get("themes") or [] if isinstance(t, dict)}
    return ids


def validate_document(document: dict, themes: set | None = None) -> dict:
    """Structure, rubric totals and the selected candidate of a style brainstorm."""
    diagnostics = []

    def add(severity, code, message, candidate=None):
        diagnostics.append({"severity": severity, "code": code, "message": message, "candidate": candidate})
    if not isinstance(document, dict):
        add("error", "style_shape", "The style document must be an object {candidates, selected}")
        return {"valid": False, "saveable": False, "errors": 1, "diagnostics": diagnostics, "candidates": {},
                "ranking": [], "selected": None}
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != CANDIDATES:
        add("error", "candidate_count", f"Write exactly {CANDIDATES} candidate styles")
        candidates = candidates if isinstance(candidates, list) else []
    results, seen, shapes = {}, set(), {}
    for number, candidate in enumerate(candidates):
        cid = candidate.get("id") if isinstance(candidate, dict) else None
        where = f"candidates[{number}]"
        errors_before = sum(1 for d in diagnostics if d["severity"] == "error")
        if not isinstance(cid, str) or not IDENTIFIER.match(cid) or cid in seen:
            add("error", "candidate_id", f"{where}.id must be a unique lowercase identifier", cid)
        seen.add(cid)
        _check_style(candidate, where, lambda message: add("error", "candidate_shape", message, cid), themes)
        if isinstance(candidate, dict) and isinstance(candidate.get("settings"), dict):
            missing = [name for name in SETTINGS if name not in candidate["settings"]]
            if missing:
                add("error", "candidate_settings", f"{where}.settings must choose every setting; missing "
                                                   f"{', '.join(missing)}", cid)
            shape = tuple(candidate["settings"].get(name) for name in SETTINGS)
            if shape in shapes:
                add("error", "candidates_alike", f"{where} has the same settings as {shapes[shape]}; each candidate "
                                                 "is a different way to play the song", cid)
            shapes.setdefault(shape, where)
        rubric = candidate.get("rubric") if isinstance(candidate, dict) else None
        total = 0
        if not isinstance(rubric, dict) or set(rubric) != set(RUBRIC):
            add("error", "rubric", f"{where}.rubric scores each of {', '.join(RUBRIC)}", cid)
        else:
            for criterion, entry in rubric.items():
                score = entry.get("score") if isinstance(entry, dict) else None
                if type(score) is not int or not 1 <= score <= 5 or not _text(entry.get("why")):
                    add("error", "rubric", f"{where}.rubric.{criterion} needs an integer score 1-5 and a why", cid)
                else:
                    total += score
        valid = sum(1 for d in diagnostics if d["severity"] == "error") == errors_before
        if isinstance(cid, str):
            results[cid] = {"total": total, "valid": valid}
    ranking = sorted(results, key=lambda c: (-results[c]["total"], c))
    selected = document.get("selected")
    if selected is not None and selected not in results:
        add("error", "selected_unknown", f"selected {selected!r} names no candidate")
    elif selected is not None and not results[selected]["valid"]:
        add("error", "selected_invalid", f"selected candidate {selected} has errors")
    elif selected is not None and ranking and selected != ranking[0] and not _text(document.get("selection_reason")):
        add("warning", "selection_reason", f"{selected} is not the top total ({ranking[0]}); say why in "
                                           "selection_reason")
    if selected is None:
        add("warning", "unselected", "No candidate is selected yet")
    errors = sum(1 for d in diagnostics if d["severity"] == "error")
    return {"valid": errors == 0, "saveable": errors == 0 and selected is not None, "errors": errors,
            "diagnostics": diagnostics, "candidates": results, "ranking": ranking, "selected": selected}


def arrangement_style(document: dict, revision: str | None = None) -> dict | None:
    """The selected candidate as the arrangement's ``style`` block."""
    chosen = next((c for c in document.get("candidates", []) if isinstance(c, dict)
                   and c.get("id") == document.get("selected")), None)
    if chosen is None:
        return None
    block = {"idea": chosen["idea"], "grounding": list(chosen["grounding"]), "settings": dict(chosen["settings"])}
    if chosen.get("signatures"):
        block["signatures"] = [dict(s) for s in chosen["signatures"]]
    if revision:
        block["source"] = {"style_revision": revision, "candidate": chosen["id"]}
    return block


def validate_file(store, project_id, document):
    directory = store.directory(project_id)
    return {"project": project_id, **validate_document(_unwrap(document), _themes(store, directory))}


def save_style(store, project_id, document, expected_revision):
    """Validate and store the brainstorm; returns the selected ``style`` block to put in each arrangement."""
    from .projects import ConflictError
    document = _unwrap(document)
    with store.lock:
        directory = store.directory(project_id)
        path = style_file(directory)
        current = read_json(path)["revision"] if path.exists() else None
        if (expected_revision or "none") != (current or "none"):
            raise ConflictError(f"Style is at revision {current or 'none'}; reread it with `style get` and reconcile "
                                "before saving")
        result = validate_document(document, _themes(store, directory))
        if not result["saveable"]:
            raise StyleError("style_invalid", f"Style not saved: {result['errors']} errors"
                             + ("" if result["selected"] else ", and no candidate is selected"),
                             "Fix the listed errors and select a candidate",
                             {"diagnostics": result["diagnostics"]})
        revision = digest(document)
        saved_at = now()
        write_json(directory / "style-history" / f"{revision}.json", document)
        write_json(directory / "style-history" / "log" / f"{saved_at.replace(':', '').replace('+', 'Z')[:22]}-"
                   f"{uuid.uuid4().hex[:8]}.json", {"previous": current, "revision": revision, "at": saved_at,
                                                    "selected": result["selected"]})
        block = arrangement_style(document, revision)
        write_json(path, {"schema_version": STYLE_VERSION, "project": project_id, "revision": revision,
                          "saved_at": saved_at, "style": document, "selected": block,
                          "totals": {c: r["total"] for c, r in result["candidates"].items()}})
    return {"project": project_id, "previous_revision": current, "revision": revision,
            "selected": result["selected"], "ranking": result["ranking"], "arrangement_style": block,
            "warnings": [d for d in result["diagnostics"] if d["severity"] == "warning"],
            "next": "Add arrangement_style as `style` to every difficulty's arrangement (keep its notes' placer-chosen "
                    "fields open where the new style should apply), then `project check` and `project save`."}


def get_style(store, project_id):
    directory = store.directory(project_id)
    path = style_file(directory)
    if not path.exists():
        return {"project": project_id, "revision": None, "style": None,
                "next": f"Run `style template {project_id}`, write three candidates, then `style save` with "
                        "--revision none"}
    stored = read_json(path)
    history = directory / "style-history" / "log"
    return {"project": project_id, "revision": stored["revision"], "saved_at": stored["saved_at"],
            "style": stored["style"], "selected": stored["selected"], "totals": stored.get("totals"),
            "history": [read_json(p) for p in sorted(history.glob("*.json"), reverse=True)] if history.exists() else []}


def _stems(report):
    """Per stem: strong attacks and their share, busiest first: which instruments carry the song."""
    from .recurrence import ATTACK_STRENGTH, RHYTHM_METHODS
    counts = {}
    for name, layer in (report.get("layers") or {}).items():
        if name == "mix":
            continue
        events = [e for e in layer.get("events", []) if e.get("method") in RHYTHM_METHODS]
        ceiling = max((float(e.get("strength", 0)) for e in events), default=0) or 1.0
        counts[name] = sum(1 for e in events if float(e.get("strength", 0)) / ceiling >= ATTACK_STRENGTH)
    total = sum(counts.values()) or 1
    return [{"stem": name, "strong_attacks": count, "share": round(count / total, 3),
             "sustains": len((report["layers"][name].get("sustains") or []))}
            for name, count in sorted(counts.items(), key=lambda item: -item[1])]


def style_template(store, project_id):
    """Skeleton brainstorm plus the song evidence a style should follow from."""
    from .listen import latest_listen
    from .musical import latest_run
    from .placement import place_arrangement
    directory = store.directory(project_id)
    project = read_json(directory / "project.json")
    arrangement = read_json(directory / "arrangement.json")
    run_id, report = latest_run(directory)
    listen = latest_listen(directory)
    song = arrangement["song"]
    lyrics = listen.get("lyrics")
    moods = (listen.get("mood") or {}).get("sections", {})
    difficulties = {name: read_json(file) for name, file in store.difficulty_files(directory).items()}
    others = []
    for other in store.list():
        if other["id"] == project_id:
            continue
        file = style_file(store.directory(other["id"]))
        if file.exists():
            selected = read_json(file).get("selected") or {}
            others.append({"project": other["id"], "title": other.get("title"), "idea": selected.get("idea"),
                           "settings": selected.get("settings")})
    overview = None
    if run_id:
        view = (report.get("views") or {}).get("overview")
        overview = str(directory / "musical" / run_id / view) if view else None
    measured = {}
    for name, current in difficulties.items():
        try:
            measured[name] = style_metrics(place_arrangement(current, strict=False)["arrangement"])
        except (KeyError, TypeError, ValueError):
            measured[name] = None
    skeleton = {"id": "", "idea": "", "grounding": [""], "settings": dict(DEFAULTS), "signatures": [],
                "rubric": {criterion: {"score": None, "why": ""} for criterion in RUBRIC}}
    current = style_file(directory)
    revision = read_json(current)["revision"] if current.exists() else None
    return {"project": project_id, "current_revision": revision,
            "evidence": {
                "song": {"title": song["title"], "artist": song["artist"], "album": project.get("album"),
                         "bpm": song["bpm"], "duration_seconds": project.get("duration_seconds")},
                "overview_image": overview,
                "overview_hint": None if overview else f"Run `music analyze {project_id} --backend ensemble` first",
                "stems": _stems(report) if report else [],
                "song_mood": (listen.get("mood") or {}).get("song"),
                "sections": [{"id": s["id"], "start_beat": s.get("start_beat"), "end_beat": s.get("end_beat"),
                              "group": s.get("group"), "level_db": s.get("level_db"),
                              "tags": [t["tag"] for t in moods.get(s["id"], {}).get("tags", [])
                                       if t.get("confidence", 0) >= .5]} for s in listen.get("sections", [])],
                "moments": [{k: m.get(k) for k in ("id", "kind", "beat", "strength")} for m in listen.get("moments", [])],
                "listen_hint": None if listen.get("available") else f"Run `music listen {project_id}` for mood, "
                                                                    "sections and moments",
                "lyrics": [s["text"] for s in (lyrics or {}).get("segments", [])][:40] if lyrics else None,
                "themes": {name: [{"id": t.get("id"), "intent": t.get("intent")} for t in a.get("themes") or []]
                           for name, a in difficulties.items()},
                "difficulties": {name: {"target_tier": a["difficulty"].get("target_tier"),
                                        "style": a.get("style")} for name, a in difficulties.items()},
                "measured_style": measured,
                "other_songs": others},
            "style": {"schema_version": STYLE_VERSION,
                      "candidates": [dict(skeleton, id=cid) for cid in ("a", "b", "c")], "selected": None},
            "settings": {name: list(values) for name, values in SETTINGS.items()},
            "rubric": RUBRIC,
            "rules": ["Look before writing: read overview_image and a spectrogram of the song's defining passage "
                      "(`music spectrogram`), the title and the lyrics.",
                      "Exactly three candidates, each a different way to play this song: one sentence (idea), the "
                      "evidence it follows from (grounding), every setting, and signature moves tied to the song's "
                      "themes.",
                      "A style chooses among what the audio supports: it never adds notes, relaxes a movement rule "
                      "or raises the difficulty past the target tier.",
                      "Differ from other_songs where this song differs; the same settings for every song is no style.",
                      "Rubric: integer 1-5 per criterion with a one-line why; say why in selection_reason when the "
                      "selected candidate is not the top total."],
            "next": f"Fill `style`, write it to a file, `style validate --project {project_id} --file F`, then "
                    f"`style save {project_id} --file F --revision {revision or 'none'}`"}
