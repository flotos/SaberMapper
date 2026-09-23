"""Strict structural checks and narrow review warnings for the pilot format."""

from __future__ import annotations

from fractions import Fraction
from math import isfinite

from .movement import analyze_movement


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _beat(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError
    if isinstance(value, float) and not isfinite(value):
        raise ValueError
    beat = Fraction(str(value))
    if beat < 0:
        raise ValueError
    try:
        if not isfinite(float(beat)):
            raise ValueError
    except OverflowError as exc:
        raise ValueError from exc
    return beat


def validate_arrangement(arrangement: dict) -> list[dict]:
    """Return actionable diagnostics; errors prevent compilation.

    Movement warnings come from the shared versioned movement model.
    """
    findings = []

    def add(severity, code, message, section_id=None, object_ids=()):
        findings.append({"severity": severity, "code": code, "message": message,
                         "section_id": section_id, "object_ids": list(object_ids)})

    def keys(obj, expected, where, section_id=None, optional=()):
        if not isinstance(obj, dict):
            add("error", "invalid_type", f"{where} must be an object", section_id)
            return False
        missing = set(expected) - set(obj)
        extra = set(obj) - set(expected) - set(optional)
        for name in sorted(missing):
            add("error", "missing_field", f"{where} requires {name}", section_id)
        for name in sorted(extra):
            add("error", "unsupported_field", f"{where}.{name} is unsupported", section_id)
        return not missing

    if not keys(arrangement, {"schema_version", "song", "difficulty", "motifs", "sections"}, "arrangement",
                optional={"tempo_events", "mapper", "lightshow"}):
        return findings
    if arrangement["schema_version"] != "0.1":
        add("error", "schema_version", "schema_version must be 0.1")
    if "mapper" in arrangement and (not isinstance(arrangement["mapper"], str) or not arrangement["mapper"].strip()):
        add("error", "invalid_metadata", "mapper must be a nonempty string when present")
    song = arrangement["song"]
    if keys(song, {"title", "artist", "bpm", "audio_offset_seconds"}, "song"):
        for field in ("title", "artist"):
            if not isinstance(song[field], str) or not song[field].strip():
                add("error", "invalid_metadata", f"song.{field} must be nonempty")
        if not _finite_number(song["bpm"]) or song["bpm"] <= 0:
            add("error", "invalid_bpm", "song.bpm must be positive and finite")
        if not _finite_number(song["audio_offset_seconds"]) or song["audio_offset_seconds"] < 0:
            add("error", "invalid_offset", "audio_offset_seconds must be finite and nonnegative")
    difficulty = arrangement["difficulty"]
    if keys(difficulty, {"name", "rank", "njs", "spawn_offset_beats"}, "difficulty", optional={"target_tier"}):
        from .star_tiers import TIER_IDS
        if "target_tier" in difficulty and difficulty["target_tier"] not in TIER_IDS:
            add("error", "invalid_target_tier", f"difficulty.target_tier must be one of {', '.join(TIER_IDS)}")
        ranks = {"Easy": 1, "Normal": 3, "Hard": 5, "Expert": 7, "ExpertPlus": 9}
        if not isinstance(difficulty["name"], str) or difficulty["name"] not in ranks or difficulty["rank"] != ranks.get(difficulty["name"]):
            add("error", "invalid_difficulty", "difficulty name/rank must match Easy/1, Normal/3, Hard/5, Expert/7, or ExpertPlus/9")
        if not _finite_number(difficulty["njs"]) or difficulty["njs"] <= 0:
            add("error", "invalid_njs", "difficulty.njs must be positive and finite")
        if not _finite_number(difficulty["spawn_offset_beats"]):
            add("error", "invalid_spawn_offset", "spawn_offset_beats must be finite")
    motifs = arrangement["motifs"]
    sections = arrangement["sections"]
    if not isinstance(motifs, dict) or not isinstance(sections, list):
        add("error", "invalid_type", "motifs must be an object and sections an array")
        return findings
    expanded, held, notes_ok = [], [], [True]

    def note_check(note, where, sid, origin, base):
        before = len(findings)
        _note_check(note, where, sid, origin, base)
        if len(findings) != before:
            notes_ok[0] = False

    def _note_check(note, where, sid, origin, base):
        if not keys(note, {"id", "beat", "x", "y", "color", "direction"}, where, sid, optional={"placed"}):
            return
        nid = note["id"]
        if not isinstance(nid, str) or not nid or "/" in nid:
            add("error", "invalid_id", f"{where}.id must be nonempty and contain no slash", sid)
            return
        oid = f"{origin}/{nid}"
        placed = note.get("placed", [])
        if (not isinstance(placed, list) or any(field not in ("x", "y", "color", "direction") for field in placed)
                or len(set(placed)) != len(placed)):
            add("error", "invalid_placed", f"{oid}.placed must list distinct fields among x, y, color and "
                                           "direction (the ones the placer chose)", sid, [oid])
            return
        try:
            beat = _beat(note["beat"])
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            add("error", "invalid_beat", f"{oid} has invalid beat", sid, [oid])
            return
        for field, allowed in (("x", range(4)), ("y", range(3)), ("color", range(2)), ("direction", range(9))):
            value = note[field]
            if type(value) is not int or value not in allowed:
                add("error", "invalid_note", f"{oid}.{field} is outside supported values", sid, [oid])
                return
        absolute = base + beat
        try:
            exportable = isfinite(float(absolute))
        except OverflowError:
            exportable = False
        if not exportable:
            add("error", "unexportable_beat", f"{oid} absolute beat exceeds v3 numeric range", sid, [oid])
            return
        expanded.append((absolute, note["x"], note["y"], note["color"], note["direction"], sid, oid))

    def object_check(item, kind, sid, start, length):
        common = {"id", "beat", "x", "y"}
        specifics = {"bombs": set(), "obstacles": {"duration_beats", "width", "height"},
                     "arcs": {"color", "direction", "tail_beat", "tail_x", "tail_y", "tail_direction"},
                     "chains": {"color", "direction", "tail_beat", "tail_x", "tail_y", "slice_count"}}
        optional = {"arcs": {"head_multiplier", "tail_multiplier", "mid_anchor"},
                    "chains": {"squish"}}.get(kind, set())
        if not keys(item, common | specifics[kind], kind[:-1], sid, optional=optional):
            return
        oid = item["id"]
        if not isinstance(oid, str) or not oid or "/" in oid:
            add("error", "invalid_id", f"{kind} ID must be nonempty and contain no slash", sid)
            return
        try:
            beat = _beat(item["beat"])
            if beat >= length:
                raise ValueError
            if not isfinite(float(start + beat)):
                raise ValueError
        except (ValueError, TypeError, OverflowError, ZeroDivisionError):
            add("error", "invalid_beat", f"{kind}/{oid} must start within its section", sid, [oid])
            return
        for field, low, high in (("x", 0, 3), ("y", 0, 2)):
            if type(item[field]) is not int or not low <= item[field] <= high:
                add("error", "invalid_object", f"{kind}/{oid}.{field} out of range", sid, [oid])
        if kind == "obstacles":
            for field, low, high in (("width", 1, 4), ("height", 1, 5)):
                if type(item[field]) is not int or not low <= item[field] <= high:
                    add("error", "invalid_object", f"{kind}/{oid}.{field} out of range", sid, [oid])
            if type(item["x"]) is int and type(item["width"]) is int and item["x"] + item["width"] > 4:
                add("error", "outside_grid", f"{kind}/{oid} extends past lane 3", sid, [oid])
            try:
                duration = _beat(item["duration_beats"])
                if duration <= 0 or beat + duration > length or not isfinite(float(start + beat + duration)):
                    raise ValueError
            except (ValueError, TypeError, OverflowError, ZeroDivisionError):
                add("error", "invalid_duration", f"{kind}/{oid} duration must fit section", sid, [oid])
        if kind in ("arcs", "chains"):
            for field, high in (("color", 1), ("direction", 8), ("tail_x", 3), ("tail_y", 2)):
                if type(item[field]) is not int or not 0 <= item[field] <= high:
                    add("error", "invalid_object", f"{kind}/{oid}.{field} out of range", sid, [oid])
            try:
                tail = _beat(item["tail_beat"])
                if tail <= beat or tail >= length or not isfinite(float(start + tail)):
                    raise ValueError
            except (ValueError, TypeError, OverflowError, ZeroDivisionError):
                add("error", "invalid_tail", f"{kind}/{oid} tail must follow head inside section", sid, [oid])
            if kind == "arcs":
                if type(item["tail_direction"]) is not int or not 0 <= item["tail_direction"] <= 8:
                    add("error", "invalid_object", f"{kind}/{oid}.tail_direction out of range", sid, [oid])
                if type(item.get("mid_anchor", 0)) is not int or not 0 <= item.get("mid_anchor", 0) <= 2:
                    add("error", "invalid_object", f"{kind}/{oid}.mid_anchor out of range", sid, [oid])
                for field in ("head_multiplier", "tail_multiplier"):
                    if not _finite_number(item.get(field, 1)) or item.get(field, 1) < 0:
                        add("error", "invalid_object", f"{kind}/{oid}.{field} must be nonnegative", sid, [oid])
            else:
                if type(item["slice_count"]) is not int or not 2 <= item["slice_count"] <= 100:
                    add("error", "invalid_object", f"{kind}/{oid}.slice_count out of range", sid, [oid])
                if not _finite_number(item.get("squish", 0.5)) or not 0 <= item.get("squish", 0.5) <= 1:
                    add("error", "invalid_object", f"{kind}/{oid}.squish must be 0..1", sid, [oid])

    for motif_id, motif in motifs.items():
        if not isinstance(motif_id, str) or not motif_id or "/" in motif_id or not isinstance(motif, list):
            add("error", "invalid_motif", "motif IDs must be nonempty and values arrays")
            continue
        ids = set()
        for note in motif:
            if isinstance(note, dict) and isinstance(note.get("id"), str) and note["id"] in ids:
                add("error", "duplicate_id", f"duplicate note ID in motif {motif_id}")
            if isinstance(note, dict) and isinstance(note.get("id"), str):
                ids.add(note["id"])
            # Validate the motif without adding a standalone map object.
            before = len(expanded)
            note_check(note, f"motif {motif_id} note", None, f"motif/{motif_id}", Fraction(0))
            del expanded[before:]

    section_ids = set()
    for section in sections:
        if not isinstance(section, dict):
            add("error", "invalid_type", "section must be an object")
            continue
        sid = section.get("id")
        if not keys(section, {"id", "start_beat", "length_beats", "intent", "locked", "resolved", "notes", "patterns"}, "section", sid,
                    optional={"bombs", "obstacles", "arcs", "chains", "musical_focus"}):
            continue
        if not isinstance(sid, str) or not sid or "/" in sid or sid in section_ids:
            add("error", "invalid_id", "section ID must be nonempty, unique, and contain no slash", str(sid))
        else:
            section_ids.add(sid)
        if not isinstance(section["intent"], str) or not section["intent"].strip():
            add("error", "invalid_intent", "section intent must be nonempty", sid)
        if type(section["locked"]) is not bool or type(section["resolved"]) is not bool:
            add("error", "invalid_section", "locked and resolved must be booleans", sid)
        elif not section["resolved"]:
            add("error", "unresolved_section", "section must be resolved before compilation", sid)
        try:
            start = _beat(section["start_beat"])
            length = _beat(section["length_beats"])
            if length <= 0:
                raise ValueError
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            add("error", "invalid_section_beat", "section start must be nonnegative and length positive", sid)
            continue
        if "musical_focus" in section:
            from .musical import validate_focus
            try:
                validate_focus(section["musical_focus"], length)
            except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
                add("error", "invalid_musical_focus", str(exc), sid)
        if not isinstance(section["notes"], list) or not isinstance(section["patterns"], list):
            add("error", "invalid_type", "section notes and patterns must be arrays", sid)
            continue
        local_ids = set()
        for note in section["notes"]:
            if isinstance(note, dict) and isinstance(note.get("id"), str) and note["id"] in local_ids:
                add("error", "duplicate_id", "duplicate literal note ID", sid)
            if isinstance(note, dict) and isinstance(note.get("id"), str):
                local_ids.add(note["id"])
            before = len(expanded)
            note_check(note, "literal note", sid, f"{sid}/note", start)
            for item in expanded[before:]:
                if item[0] >= start + length:
                    add("error", "outside_section", "note exceeds section", sid, [item[-1]])
        pattern_ids = set()
        for pattern in section["patterns"]:
            if not keys(pattern, {"id", "motif", "start_beat"}, "pattern", sid, optional={"mirror"}):
                continue
            pid = pattern["id"]
            if not isinstance(pid, str) or not pid or "/" in pid or pid in pattern_ids:
                add("error", "invalid_id", "pattern ID must be nonempty, unique, and contain no slash", sid)
                continue
            pattern_ids.add(pid)
            if type(pattern.get("mirror", False)) is not bool:
                add("error", "invalid_mirror", "pattern mirror must be boolean", sid, [pid])
                continue
            motif_id = pattern["motif"]
            if not isinstance(motif_id, str) or motif_id not in motifs or not isinstance(motifs[motif_id], list):
                add("error", "unknown_motif", f"pattern {pid} references unknown motif", sid, [pid])
                continue
            try:
                pattern_beat = _beat(pattern["start_beat"])
            except (ValueError, TypeError, ZeroDivisionError, OverflowError):
                add("error", "invalid_beat", f"pattern {pid} has invalid start", sid, [pid])
                continue
            for note in motifs[motif_id]:
                before = len(expanded)
                actual_note = dict(note) if isinstance(note, dict) else note
                if isinstance(actual_note, dict) and pattern.get("mirror") is True:
                    if type(actual_note.get("x")) is int and type(actual_note.get("color")) is int and type(actual_note.get("direction")) is int:
                        actual_note["x"] = 3 - actual_note["x"]
                        actual_note["color"] = 1 - actual_note["color"]
                        actual_note["direction"] = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}.get(actual_note["direction"], -1)
                note_check(actual_note, "motif note", sid, f"{sid}/pattern/{pid}", start + pattern_beat)
                for item in expanded[before:]:
                    if item[0] >= start + length:
                        add("error", "outside_section", "pattern note exceeds section", sid, [item[-1]])
        for kind in ("bombs", "obstacles", "arcs", "chains"):
            objects = section.get(kind, [])
            if not isinstance(objects, list):
                add("error", "invalid_type", f"section {kind} must be an array", sid)
                continue
            ids = set()
            for item in objects:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    if item["id"] in ids:
                        add("error", "duplicate_id", f"duplicate {kind} ID", sid, [item["id"]])
                    ids.add(item["id"])
                before = len(findings)
                object_check(item, kind, sid, start, length)
                if kind in ("arcs", "chains") and len(findings) == before:
                    held.append((kind, sid, start, item))

    # Arcs and chains only connect and rescore when a color note sits on the head
    # (and, for arcs, the tail); a dangling arc exports as a cosmetic curve.
    if notes_ok[0] and held:
        index = {}
        for item in expanded:
            index.setdefault(item[:4], item)
        for kind, sid, start, item in held:
            oid = f'{sid}/{kind}/{item["id"]}'
            ends = [("head", item["beat"], item["x"], item["y"], item["direction"])]
            if kind == "arcs":
                ends.append(("tail", item["tail_beat"], item["tail_x"], item["tail_y"], item["tail_direction"]))
            for role, beat, x, y, direction in ends:
                absolute = start + _beat(beat)
                note = index.get((absolute, x, y, item["color"]))
                if note is None:
                    add("error", f"{kind[:-1]}_{role}_without_note",
                        f"{oid} {role} at beat {absolute} has no color note at ({x},{y}) color {item['color']}",
                        sid, [oid])
                elif note[4] != direction:
                    add("error", f"{kind[:-1]}_{role}_direction_mismatch",
                        f"{oid} {role} direction {direction} does not match note {note[-1]} direction {note[4]}",
                        sid, [oid, note[-1]])
        # A held arc or chain occupies its saber from head to tail: a note of the same
        # color strictly between them cannot be cut without abandoning the hold.
        locked_ids = {s.get("id") for s in sections if isinstance(s, dict) and s.get("locked") is True}
        for kind, sid, start, item in held:
            oid = f'{sid}/{kind}/{item["id"]}'
            head, tail = start + _beat(item["beat"]), start + _beat(item["tail_beat"])
            for note in expanded:
                if note[3] != item["color"] or not head < note[0] < tail:
                    continue
                severity, advice = "error", (f"give the note to the other hand, split the {kind[:-1]} at it, "
                                             "or remove it (project repair-swings does this)")
                if sid in locked_ids and note[-2] in locked_ids:
                    severity, advice = "warning", "section is locked, unlock it to repair"
                add(severity, f"{kind[:-1]}_note_conflict",
                    f"{oid} holds color {item['color']} from beat {float(head):g} to {float(tail):g}, but note "
                    f"{note[-1]} of that color sits inside the hold at beat {float(note[0]):g}; {advice}",
                    note[-2], [oid, note[-1]])

    if "tempo_events" in arrangement:
        events = arrangement["tempo_events"]
        if not isinstance(events, list):
            add("error", "invalid_type", "tempo_events must be an array")
        else:
            previous = Fraction(-1)
            for index, event in enumerate(events):
                if not keys(event, {"beat", "bpm"}, f"tempo_events[{index}]"):
                    continue
                try:
                    beat = _beat(event["beat"])
                    if beat <= previous:
                        raise ValueError
                    previous = beat
                except (ValueError, TypeError, OverflowError, ZeroDivisionError):
                    add("error", "invalid_tempo", f"tempo_events[{index}] beats must increase")
                if not _finite_number(event["bpm"]) or event["bpm"] <= 0:
                    add("error", "invalid_tempo", f"tempo_events[{index}].bpm must be positive")

    if "lightshow" in arrangement:
        from .lighting import validate_lightshow
        try:
            validate_lightshow(arrangement, add)
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
            add("error", "invalid_lightshow", f"lightshow cannot be checked: {exc}")

    seen = {}
    for item in expanded:
        cell = item[:3]
        if cell in seen:
            prior = seen[cell]
            add("error", "overlapping_cell", f"notes overlap at beat {item[0]} cell ({item[1]},{item[2]})", item[-2], [prior[-1], item[-1]])
        else:
            seen[cell] = item
    if not any(item["severity"] == "error" for item in findings) and expanded:
        bpm = arrangement["song"]["bpm"]
        changes = [(Fraction(0), float(bpm))] + [( _beat(event["beat"]), float(event["bpm"]))
                                                 for event in arrangement.get("tempo_events", [])]
        def seconds_at(beat):
            seconds, previous, tempo = 0.0, Fraction(0), float(bpm)
            for change, next_tempo in changes[1:]:
                if change > beat:
                    break
                seconds += float(change - previous) * 60 / tempo
                previous, tempo = change, next_tempo
            return seconds + float(beat - previous) * 60 / tempo
        movement_notes = [{"id": item[-1], "beat": float(item[0]), "x": item[1], "y": item[2],
                           "color": item[3], "direction": item[4], "seconds": seconds_at(item[0])}
                          for item in expanded]
        movement = analyze_movement(movement_notes, bpm=float(bpm),
                                    njs=arrangement["difficulty"]["njs"],
                                    spawn_offset_beats=arrangement["difficulty"]["spawn_offset_beats"])
        section_by_id = {item[-1]: item[-2] for item in expanded}
        locked = {section["id"] for section in arrangement["sections"] if section.get("locked") is True}
        for warning in movement["warnings"]:
            ids = warning["note_ids"]
            severity, reason = warning.get("severity", "warning"), warning["reason"]
            if severity == "error" and all(section_by_id.get(oid) in locked for oid in ids):
                # Locked sections are user-approved; report but do not block unrelated edits.
                severity, reason = "warning", reason + "; section is locked, unlock it to repair"
            add(severity, warning["code"], reason, section_by_id.get(ids[-1]), ids)
            findings[-1]["model_version"] = movement["model_version"]
            findings[-1]["confidence"] = warning["confidence"]
        for section in arrangement["sections"]:
            sid = section["id"]
            for kind in ("bombs", "obstacles"):
                for obj in section.get(kind, []):
                    event_beat = _beat(section["start_beat"]) + _beat(obj["beat"])
                    nearby = [item[-1] for item in expanded
                              if abs(item[0] - event_beat) <= Fraction(1, 4)
                              and (kind == "bombs" and item[1] == obj["x"] and item[2] == obj["y"]
                                   or kind == "obstacles" and obj["x"] <= item[1] < obj["x"] + obj["width"])]
                    if nearby:
                        add("warning", "visibility_context", f"{kind} near color notes; review reach and visibility in playtest",
                            sid, [f'{sid}/{kind}/{obj["id"]}', *nearby])
    return findings
