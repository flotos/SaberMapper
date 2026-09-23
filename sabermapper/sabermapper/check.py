"""One read-only report of everything a map breaks or misses (SM-036).

``project check`` merges placement, structural validation, the movement model, audio grounding and the
critique into one list of findings. Each finding has ``code``, ``severity``, ``blocking``, ``source``,
``beats``, ``object_ids``, ``section_id``, ``message`` and ``suggestions``: concrete edits the agent can
apply, each verified to clear the finding. The check never writes anything.

``project save`` refuses exactly the findings this report marks ``blocking``; both use :func:`gate`.
"""

from __future__ import annotations

from .arrangement import expanded_notes
from .movement import analyze_movement, turn_degrees
from .placement import RULE_FIELDS, _clock, _holds, place_arrangement
from .validation import validate_arrangement

# Errors that do not stop a save: an unresolved section is a draft marker that only compile and export refuse.
SAVE_TOLERATED = ("unresolved_section",)
SUGGESTED_CODES = tuple(RULE_FIELDS)
MAX_SUGGESTIONS = 4
WINDOW_SECONDS = 3.0


def is_blocking(finding: dict) -> bool:
    return finding.get("severity") == "error" and finding.get("code") not in SAVE_TOLERATED


def gate(placement_errors: list[dict], diagnostics: list[dict], audio: list[dict]) -> list[dict]:
    """The findings that stop ``project save``, in report order."""
    return [f for f in placement_errors + diagnostics + audio if is_blocking(f)]


def placed_for_check(arrangement: dict) -> tuple[dict, dict, list[dict]]:
    """(placed arrangement, placement report, placement findings) without raising."""
    placed = place_arrangement(arrangement, strict=False)
    findings = [{**error, "section_id": error["object_ids"][-1].split("/")[0] if error["object_ids"] else None,
                 "suggestions": [_from_alternative(a) for a in error["alternatives"]]}
                for error in placed["errors"]]
    return placed["arrangement"], placed["report"], findings


def _from_alternative(alternative):
    if alternative["op"] == "remove":
        return {"op": "remove", "object_id": alternative["object_id"]}
    return {"op": "unpin", "object_id": alternative["object_id"], "fields": alternative["fields"],
            "placer_choice": alternative["placer_choice"]}


def check_arrangement(arrangement: dict, report: dict | None = None, *, run_id: str | None = None,
                      tier_reference: dict | None = None, extra: list[dict] = (), metrics: bool = False,
                      listen: list | None = None) -> dict:
    """The full report for one arrangement; ``report`` is the musical evidence run (None skips the audio).

    ``listen`` is the run's listen section list, whose repetition groups mark recurring parts.
    """
    from .audio_grounding import audio_findings
    from .critique import critique_arrangement
    placed, placement, placement_findings = placed_for_check(arrangement)
    diagnostics = validate_arrangement(placed)
    covered = {tuple(f["object_ids"]) for f in placement_findings}
    diagnostics = [d for d in diagnostics if tuple(d["object_ids"]) not in covered]
    audio, critique = [], {"warnings": [], "metrics": {}}
    if not any(is_blocking(d) and d["code"] != "unresolved_section" for d in diagnostics):
        try:
            audio = audio_findings(placed, report)[1] if report else []
            critique = critique_arrangement(placed, report, tier_reference, listen)
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            pass  # structurally broken input carries its own errors
    seen = {(f["code"], tuple(f["object_ids"]), f["message"]) for f in audio}
    warnings = [w for w in critique["warnings"] if (w["code"], tuple(w["object_ids"]), w["message"]) not in seen]
    if report is None:
        warnings.insert(0, {"severity": "warning", "code": "audio_evidence_missing", "section_id": None,
                            "object_ids": [], "message": "No musical evidence run matches this project's audio, so "
                                                         "nothing was checked against the song; run `music analyze` "
                                                         "before judging the map."})
    beats = _note_beats(placed)
    findings = ([_finding(f, "placement", beats) for f in placement_findings]
                + [_finding(f, "validation", beats) for f in diagnostics]
                + [_finding(f, "audio", beats) for f in audio]
                + [_finding(f, "critique", beats) for f in warnings]
                + [_finding(f, "project", beats) for f in extra])
    _suggest(placed, findings)
    if report:
        from .rhythm_proposal import audio_suggestions
        try:
            audio_suggestions(placed, report, findings)
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            pass  # a broken arrangement already carries its own errors
    result = {"run_id": run_id, "placement": placement,
              "blocking_count": sum(1 for f in findings if f["blocking"]),
              "counts": _counts(findings), "findings": findings}
    if metrics:  # the critique's own view, for the `critique` aliases
        result["metrics"] = critique["metrics"]
        result["warnings"] = warnings[:1] * (report is None) + critique["warnings"]
    return result


def _counts(findings):
    counts = {}
    for finding in findings:
        counts[finding["code"]] = counts.get(finding["code"], 0) + 1
    return dict(sorted(counts.items()))


def _note_beats(arrangement):
    try:
        return {n["id"]: float(n["beat"]) for n in expanded_notes(arrangement)}
    except (ValueError, KeyError, TypeError):
        return {}


def _finding(item, source, beats):
    finding = {"code": item["code"], "severity": item.get("severity", "warning"), "blocking": is_blocking(item),
               "source": source, "section_id": item.get("section_id"), "object_ids": list(item.get("object_ids", [])),
               "beats": list(item["beats"]) if item.get("beats") else [], "message": item["message"],
               "suggestions": list(item.get("suggestions", []))}
    if not finding["beats"]:
        found = [beats[i] for i in finding["object_ids"] if i in beats]
        if found:
            finding["beats"] = [min(found), max(found)]
        elif "beat" in item:
            finding["beats"] = [float(item["beat"])] * 2
    for key in ("rule", "value", "threshold", "confidence", "model_version", "targets"):
        if key in item:
            finding[key] = item[key]
    return finding


# ---------------------------------------------------------------------------------------------------------
# Suggestions for the movement codes
# ---------------------------------------------------------------------------------------------------------

class _Timeline:
    """Expanded notes with seconds, the literal note behind each ID and the arc/chain anchors."""

    def __init__(self, arrangement):
        clock = _clock(arrangement)
        self.arrangement = arrangement
        self.notes = [{**n, "seconds": clock(n["beat"])} for n in expanded_notes(arrangement)]
        self.by_id = {n["id"]: n for n in self.notes}
        self.literal = {f'{s["id"]}/note/{n["id"]}': s for s in arrangement["sections"] for n in s["notes"]}
        self.locked = {s["id"] for s in arrangement["sections"] if s.get("locked")}
        anchors, self.held = _holds(arrangement)
        self.anchors = {(beat, v["x"], v["y"], v["color"]) for beat, v, _ in anchors}
        difficulty = arrangement["difficulty"]
        self.bpm, self.njs = float(arrangement["song"]["bpm"]), difficulty["njs"]
        self.spawn = difficulty["spawn_offset_beats"]

    def editable(self, oid):
        note = self.by_id.get(oid)
        section = self.literal.get(oid)
        return (note is not None and section is not None and section["id"] not in self.locked
                and (note["beat"], note["x"], note["y"], note["color"]) not in self.anchors)

    def violations(self, notes):
        """Rule violations among ``notes`` (a time window of the map, possibly edited)."""
        movement = analyze_movement([{k: (float(v) if k == "beat" else v) for k, v in n.items()
                                      if k in ("id", "beat", "x", "y", "color", "direction", "seconds")}
                                     for n in notes], bpm=self.bpm, njs=self.njs, spawn_offset_beats=self.spawn)
        found = [(w["code"], tuple(w["note_ids"])) for w in movement["warnings"] if w["code"] in RULE_FIELDS]
        for color, spans in self.held.items():
            for head, tail, oid, kind in spans:
                found += [(f"{kind[:-1]}_note_conflict", (oid, n["id"])) for n in notes
                          if n["color"] == color and head < n["beat"] < tail]
        cells = {}
        for note in notes:
            key = (note["beat"], note["x"], note["y"])
            if key in cells:
                found.append(("overlapping_cell", (cells[key], note["id"])))
            cells[key] = note["id"]
        return set(found)


def _candidates(timeline, finding):
    """Edits that might clear ``finding``, cheapest first: re-cut, move, hand over, then remove."""
    code, ids = finding["code"], [i for i in finding["object_ids"] if i in timeline.by_id]
    targets = [i for i in reversed(ids) if timeline.editable(i)]
    if code == "one_hand_burst":
        targets = [i for i in ids[1:-1] if timeline.editable(i)][::-1] + [i for i in (ids[-1], ids[0])
                                                                          if timeline.editable(i)]
    edits = []
    for oid in targets:
        note = timeline.by_id[oid]
        if code in ("fast_direction_break", "flow_parity_break"):
            for direction in sorted(range(8), key=lambda d: (turn_degrees(note["direction"], d)
                                                            if note["direction"] != 8 else 0, d)):
                if direction != note["direction"]:
                    edits.append({"op": "set", "object_id": oid, "to": {"direction": direction}})
        if code in ("hidden_note", "reach_proxy"):
            cells = sorted(((abs(x - note["x"]) + abs(y - note["y"]), x, y) for x in range(4) for y in range(3)
                            if (x, y) != (note["x"], note["y"])))
            edits += [{"op": "move", "object_id": oid, "to": {"x": x, "y": y}} for _, x, y in cells]
        if code in ("fast_direction_break", "flow_parity_break", "one_hand_burst", "arc_note_conflict",
                    "chain_note_conflict"):
            other = 1 - note["color"]
            for direction in (note["direction"], _MIRROR_CUT.get(note["direction"], note["direction"])):
                for x in (range(2, 4) if other else range(2)):
                    for y in (note["y"], 1, 0, 2):
                        edits.append({"op": "set", "object_id": oid,
                                      "to": {"color": other, "direction": direction, "x": x, "y": y}})
    edits += [{"op": "remove", "object_id": oid} for oid in targets]
    seen, unique = set(), []
    for edit in edits:
        key = repr(edit)
        if key not in seen:
            seen.add(key)
            unique.append(edit)
    return unique


_MIRROR_CUT = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}


def _suggest(arrangement, findings):
    """Attach verified suggestions to every movement finding that has none yet."""
    wanted = [f for f in findings if f["code"] in SUGGESTED_CODES and not f["suggestions"] and f["source"] != "placement"]
    if not wanted:
        return
    try:
        timeline = _Timeline(arrangement)
    except (ValueError, KeyError, TypeError):
        return
    for finding in wanted:
        ids = [i for i in finding["object_ids"] if i in timeline.by_id]
        if not ids:
            continue
        center = timeline.by_id[ids[-1]]["seconds"]
        window = [n for n in timeline.notes if abs(n["seconds"] - center) <= WINDOW_SECONDS]
        before = timeline.violations(window)
        key = (finding["code"], tuple(finding["object_ids"]))
        for edit in _candidates(timeline, finding):
            trial = _apply(window, edit)
            after = timeline.violations(trial)
            if key in after or any(v not in before for v in after):
                continue  # still broken, or the edit breaks something else
            finding["suggestions"].append(edit)
            if len(finding["suggestions"]) >= MAX_SUGGESTIONS:
                break


def _apply(notes, edit):
    if edit["op"] == "remove":
        return [n for n in notes if n["id"] != edit["object_id"]]
    return [{**n, **edit["to"]} if n["id"] == edit["object_id"] else n for n in notes]


def apply_suggestion(arrangement: dict, suggestion: dict) -> dict:
    """Apply one suggestion to a copy of ``arrangement``; a set or moved field becomes the agent's pin.

    ``add`` inserts rhythm-only notes (the placer places them), ``remove`` takes ``object_id`` or
    ``object_ids``, ``set_weights`` rewrites a focus phrase's lead and weights, ``stack`` marks the note
    ``object_id`` (or new notes at ``beat``) as a stack of ``size`` notes and removes the notes in ``remove``,
    ``add_theme`` declares a theme and reopens its echo notes for the placer.
    """
    import copy
    from fractions import Fraction
    if suggestion["op"] == "add_theme":
        from .recurrence import add_theme
        return add_theme(arrangement, suggestion["theme"])
    result = copy.deepcopy(arrangement)
    if suggestion["op"] == "stack":
        for oid in suggestion.get("remove", ()):
            result = apply_suggestion(result, {"op": "remove", "object_id": oid})
        if "object_id" in suggestion:
            sid, kind, nid = suggestion["object_id"].split("/", 2)
            if kind != "note":
                raise ValueError(f"{suggestion['object_id']} is not a literal note")
            section = next(s for s in result["sections"] if s["id"] == sid)
            note = next(n for n in section["notes"] if n["id"] == nid)
            note["stack"], relative, count = True, note["beat"], suggestion["size"] - 1
        else:
            beat = Fraction(str(suggestion["beat"]))
            section = next(s for s in result["sections"] if Fraction(str(s["start_beat"])) <= beat
                           < Fraction(str(s["start_beat"])) + Fraction(str(s["length_beats"])))
            offset = beat - Fraction(str(section["start_beat"]))
            relative, count = int(offset) if offset.denominator == 1 else str(offset), suggestion["size"]
        taken = {n["id"] for n in section["notes"]}
        for index in range(count):
            note_id = f"k-{str(relative).replace('/', '_')}-{index}"
            while note_id in taken:
                note_id += "x"
            taken.add(note_id)
            section["notes"].append({"id": note_id, "beat": relative, "stack": True})
        return result
    if suggestion["op"] == "add":
        for item in suggestion["notes"]:
            beat = Fraction(str(item["beat"]))
            section = next(s for s in result["sections"] if Fraction(str(s["start_beat"])) <= beat
                           < Fraction(str(s["start_beat"])) + Fraction(str(s["length_beats"])))
            relative = beat - Fraction(str(section["start_beat"]))
            taken = {n["id"] for n in section["notes"]}
            note_id = "s-" + str(beat).replace("/", "_")
            while note_id in taken:
                note_id += "x"
            section["notes"].append({"id": note_id, "beat": int(relative) if relative.denominator == 1
                                     else str(relative)})
        return result
    if suggestion["op"] == "set_weights":
        section = next(s for s in result["sections"] if s["id"] == suggestion["section_id"])
        phrase = next(p for p in section["musical_focus"] if p["id"] == suggestion["focus_id"])
        phrase.update(lead=suggestion["lead"], weights=dict(suggestion["weights"]))
        return result
    if suggestion["op"] == "remove" and "object_ids" in suggestion:
        for oid in suggestion["object_ids"]:
            result = apply_suggestion(result, {"op": "remove", "object_id": oid})
        return result
    sid, kind, nid = suggestion["object_id"].split("/", 2)
    if kind != "note":
        raise ValueError(f"{suggestion['object_id']} is not a literal note")
    section = next(s for s in result["sections"] if s["id"] == sid)
    note = next(n for n in section["notes"] if n["id"] == nid)
    if suggestion["op"] == "remove":
        section["notes"].remove(note)
    elif suggestion["op"] in ("set", "move"):
        note.update(suggestion["to"])
        if "placed" in note:
            note["placed"] = [f for f in note["placed"] if f not in suggestion["to"]]
            if not note["placed"]:
                del note["placed"]
    elif suggestion["op"] == "unpin":
        for field in suggestion["fields"]:
            note.pop(field, None)
    elif suggestion["op"] == "retime":
        note["beat"] = suggestion["to_beat"]
    else:
        raise ValueError(f"Unknown suggestion op {suggestion['op']!r}")
    return result

