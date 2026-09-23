"""Concept artifact: three candidate visual treatments for a song, scored, with one selected.

The agent writes every creative field. This module validates the structure, checks that every
reference (moment IDs, listen section IDs, lyric line IDs) exists in the project's latest listen
evidence, computes rubric totals, refuses to select a candidate that fails validation, and stores
the document revision-aware in ``<project>/concept.json`` with content-addressed history.
"""
from __future__ import annotations

from pathlib import Path
import re
import uuid

from .storage import digest, now, read_json, write_json

CONCEPT_VERSION = "1.0"
CANDIDATES = 3
POSSESSION = ("none", "player", "head", "hands", "right_hand")
TIERS = {1: "parametric library (standard materials, primitives, particles, post-process presets)",
         2: "agent-written code assets (custom shaders, procedural meshes, particle systems)",
         3: "generative or modelled media (textures, skyboxes, meshes from an image or 3D model)"}
RUBRIC = {"grounded": "Grounded in this song: follows from its lyrics, moments and mood, not a generic show",
          "one_idea": "One strong idea: a single central image or metaphor, not a collage of effects",
          "develops": "Develops: the motifs evolve across sections toward the held-back ending",
          "readable": "Readable while playing: notes and their approach stay legible; spectacle yields to the chart",
          "buildable": "Buildable: achievable with the asset forge tiers it names, within budget"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
CANDIDATE_FIELDS = {"id", "title", "central_idea", "grounding", "palette", "motifs", "key_moments", "possession",
                    "buildability", "rubric"}
OPTIONAL_CANDIDATE_FIELDS = {"notes"}
DOCUMENT_FIELDS = {"schema_version", "candidates", "selected"}
OPTIONAL_DOCUMENT_FIELDS = {"listen_run", "steering", "selection_reason", "notes"}


class ConceptError(ValueError):
    def __init__(self, code, message, fix=None, diagnostics=None):
        super().__init__(message)
        self.code, self.fix, self.details = code, fix, ({"diagnostics": diagnostics} if diagnostics else {})


def _text(value, limit=None):
    return isinstance(value, str) and bool(value.strip()) and (limit is None or len(value) <= limit)


def evidence_index(listen, arrangement=None):
    """IDs a concept may reference, from ``listen.latest_listen`` output."""
    lyrics = listen.get("lyrics")
    return {"run_id": listen.get("run_id"), "available": listen.get("available", False),
            "moments": {m["id"]: m for m in listen.get("moments", [])},
            "sections": {s["id"] for s in listen.get("sections", [])},
            "map_sections": {s.get("id") for s in (arrangement or {}).get("sections", []) if s.get("id")},
            "lyrics": None if not lyrics else {s["id"] for s in lyrics.get("segments", [])}}


def validate_concept(document, evidence):
    """{"valid", "saveable", "candidates": {id: {valid, total, scores}}, "diagnostics": [...]}."""
    diagnostics = []

    def report(code, message, path, candidate=None, severity="error"):
        diagnostics.append({"severity": severity, "code": code, "path": path, "candidate": candidate, "message": message})
    if not isinstance(document, dict):
        report("concept_shape", "The concept must be a JSON object", "$")
        return _result(diagnostics, {}, None)
    missing = DOCUMENT_FIELDS - document.keys()
    unknown = document.keys() - DOCUMENT_FIELDS - OPTIONAL_DOCUMENT_FIELDS
    if missing:
        report("field_missing", f"Missing fields: {', '.join(sorted(missing))}", "$")
    if unknown:
        report("field_unknown", f"Unknown fields: {', '.join(sorted(unknown))}", "$")
    if document.get("schema_version", CONCEPT_VERSION) != CONCEPT_VERSION:
        report("schema_version", f"schema_version must be {CONCEPT_VERSION}", "$.schema_version")
    run = document.get("listen_run")
    if run is not None and evidence.get("run_id") and run != evidence["run_id"]:
        report("listen_run_mismatch", f"Concept was written against listen run {run}; the latest is "
               f"{evidence['run_id']}. Check its references still hold", "$.listen_run", severity="warning")
    steering = document.get("steering", [])
    if not isinstance(steering, list) or any(not isinstance(s, dict) or not _text(s.get("text")) or
                                             s.keys() - {"text", "source", "applied", "at"} for s in steering):
        report("steering_shape", "steering must be a list of {text, source?, applied?, at?} with nonempty text",
               "$.steering")
    candidates = document.get("candidates")
    scores = {}
    if not isinstance(candidates, list):
        report("candidates_shape", "candidates must be a list", "$.candidates")
        candidates = []
    elif len(candidates) != CANDIDATES:
        report("candidate_count", f"Write exactly {CANDIDATES} candidate treatments (found {len(candidates)})",
               "$.candidates")
    seen = set()
    for index, candidate in enumerate(candidates):
        path = f"$.candidates[{index}]"
        if not isinstance(candidate, dict):
            report("candidate_shape", "Each candidate must be an object", path)
            continue
        cid = candidate.get("id")
        if not isinstance(cid, str) or not IDENTIFIER.match(cid):
            report("candidate_id", "Candidate id must be a lowercase slug (a-z, 0-9, _ or -)", path + ".id", None)
            cid = f"#{index}"
        elif cid in seen:
            report("candidate_id", f"Duplicate candidate id {cid}", path + ".id", cid)
        seen.add(cid)
        scores[cid] = _candidate(candidate, cid, path, evidence, report)
    ideas = [c.get("central_idea", "").strip().lower() for c in candidates if isinstance(c, dict)]
    if len(set(ideas)) < len(ideas):
        report("candidates_duplicate", "Two candidates share a central idea; offer three distinct treatments",
               "$.candidates", severity="warning")
    selected = document.get("selected")
    if selected is not None:
        if selected not in scores:
            report("selected_unknown", f"selected {selected!r} is not a candidate id", "$.selected")
        else:
            failed = [d for d in diagnostics if d["candidate"] == selected and d["severity"] == "error"]
            if failed:
                report("selected_invalid", f"Candidate {selected} fails validation ({len(failed)} errors) and cannot be "
                       "selected; fix it or select another", "$.selected")
            best = max((s["total"] for s in scores.values() if s["total"] is not None), default=None)
            if scores[selected]["total"] is not None and best is not None and scores[selected]["total"] < best and \
                    not _text(document.get("selection_reason")):
                report("selected_not_top", "The selected candidate does not have the highest rubric total; explain why "
                       "in selection_reason", "$.selection_reason")
    return _result(diagnostics, scores, selected)


def _candidate(candidate, cid, path, evidence, report):
    missing = CANDIDATE_FIELDS - candidate.keys()
    unknown = candidate.keys() - CANDIDATE_FIELDS - OPTIONAL_CANDIDATE_FIELDS
    if missing:
        report("field_missing", f"Missing fields: {', '.join(sorted(missing))}", path, cid)
    if unknown:
        report("field_unknown", f"Unknown fields: {', '.join(sorted(unknown))}", path, cid)
    for field, limit in (("title", 80), ("central_idea", 600)):
        if field in candidate and not _text(candidate[field], limit):
            report("field_text", f"{field} must be nonempty text of at most {limit} characters", f"{path}.{field}", cid)
    moments, sections = evidence["moments"], evidence["sections"] | evidence["map_sections"]
    grounding = candidate.get("grounding")
    if "grounding" in candidate:
        if not isinstance(grounding, dict) or grounding.keys() - {"moments", "mood", "lyrics", "notes"}:
            report("grounding_shape", "grounding is {moments: [ids], mood: [section ids], lyrics: [lyric ids], notes}",
                   f"{path}.grounding", cid)
        else:
            refs = {key: grounding.get(key, []) for key in ("moments", "mood", "lyrics")}
            if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in refs.values()):
                report("grounding_shape", "grounding moments, mood and lyrics are lists of id strings",
                       f"{path}.grounding", cid)
            else:
                for ref in refs["moments"]:
                    if ref not in moments:
                        report("grounding_unknown_moment", f"Moment {ref} is not in listen run {evidence['run_id']}",
                               f"{path}.grounding.moments", cid)
                for ref in refs["mood"]:
                    if ref not in evidence["sections"]:
                        report("grounding_unknown_section", f"Section {ref} has no mood in the listen evidence",
                               f"{path}.grounding.mood", cid)
                if refs["lyrics"] and evidence["lyrics"] is None:
                    report("lyrics_unavailable", "grounding cites lyrics but this run has no lyrics.json; run "
                           "`music lyrics`", f"{path}.grounding.lyrics", cid)
                for ref in refs["lyrics"] if evidence["lyrics"] is not None else []:
                    if ref not in evidence["lyrics"]:
                        report("grounding_unknown_lyric", f"Lyric line {ref} is not in lyrics.json",
                               f"{path}.grounding.lyrics", cid)
                if not refs["moments"] and not refs["mood"]:
                    report("grounding_audio", "Ground the idea in the audio: cite at least one moment or section mood",
                           f"{path}.grounding", cid)
                if not _text(grounding.get("notes")):
                    report("grounding_notes", "grounding.notes must say how the idea follows from the cited evidence",
                           f"{path}.grounding.notes", cid)
    palette = candidate.get("palette")
    if "palette" in candidate:
        if not isinstance(palette, list) or not 2 <= len(palette) <= 8:
            report("palette_size", "palette lists 2 to 8 colours", f"{path}.palette", cid)
        elif any(not isinstance(c, str) or not HEX.match(c) for c in palette):
            report("palette_hex", "palette colours are #rrggbb hex strings", f"{path}.palette", cid)
    motifs = candidate.get("motifs")
    if "motifs" in candidate:
        if not isinstance(motifs, list) or not 2 <= len(motifs) <= 4:
            report("motif_count", "Write 2 to 4 motifs", f"{path}.motifs", cid)
        for number, motif in enumerate(motifs if isinstance(motifs, list) else []):
            where = f"{path}.motifs[{number}]"
            if not isinstance(motif, dict) or motif.keys() - {"name", "description", "development"} or \
                    not _text(motif.get("name"), 60) or not _text(motif.get("description")):
                report("motif_shape", "A motif is {name, description, development}", where, cid)
                continue
            development = motif.get("development")
            if not isinstance(development, dict) or len(development) < 2 or \
                    any(not _text(v) for v in development.values()):
                report("motif_development", "development maps at least two section ids to how the motif looks there",
                       f"{where}.development", cid)
                continue
            for section in development:
                if section not in sections:
                    report("motif_unknown_section", f"Section {section} is neither a listen section nor a map section",
                           f"{where}.development", cid)
    key_moments = candidate.get("key_moments")
    if "key_moments" in candidate:
        if not isinstance(key_moments, list) or not 1 <= len(key_moments) <= 3:
            report("key_moment_count", "Choose 1 to 3 key moments", f"{path}.key_moments", cid)
            key_moments = key_moments if isinstance(key_moments, list) else []
        held, times, ids = [], [], []
        for number, item in enumerate(key_moments):
            where = f"{path}.key_moments[{number}]"
            if not isinstance(item, dict) or item.keys() - {"moment_id", "treatment", "held_for_end"} or \
                    not isinstance(item.get("held_for_end", False), bool) or not _text(item.get("treatment")):
                report("key_moment_shape", "A key moment is {moment_id, treatment, held_for_end: bool}", where, cid)
                continue
            if item.get("moment_id") not in moments:
                report("key_moment_unknown", f"Moment {item.get('moment_id')} is not in listen run {evidence['run_id']}",
                       where, cid)
                continue
            if item["moment_id"] in ids:
                report("key_moment_duplicate", f"Moment {item['moment_id']} is listed twice", where, cid)
            ids.append(item["moment_id"])
            times.append(moments[item["moment_id"]]["time"])
            if item.get("held_for_end"):
                held.append(moments[item["moment_id"]]["time"])
        if len(held) != 1 and key_moments:
            report("held_for_end_count", "Flag exactly one key moment held_for_end (the reveal saved for the climax)",
                   f"{path}.key_moments", cid)
        elif held and times and held[0] < max(times):
            report("held_for_end_not_last", "The moment held for the end comes before another key moment",
                   f"{path}.key_moments", cid, severity="warning")
    if "possession" in candidate and candidate["possession"] not in POSSESSION:
        report("possession_value", f"possession is one of {', '.join(POSSESSION)}", f"{path}.possession", cid)
    buildability = candidate.get("buildability")
    if "buildability" in candidate:
        tiers = buildability.get("tiers") if isinstance(buildability, dict) else None
        if not isinstance(tiers, list) or not tiers or any(t not in TIERS for t in tiers) or \
                any(isinstance(t, bool) for t in tiers):
            report("buildability_tiers", "buildability.tiers lists the asset tiers needed (1, 2, 3)",
                   f"{path}.buildability", cid)
        if not isinstance(buildability, dict) or not _text(buildability.get("notes")):
            report("buildability_notes", "buildability.notes says which assets each tier must provide",
                   f"{path}.buildability", cid)
    rubric = candidate.get("rubric")
    scores, total = {}, None
    if "rubric" in candidate:
        if not isinstance(rubric, dict) or set(rubric) != set(RUBRIC):
            report("rubric_criteria", f"rubric scores exactly: {', '.join(RUBRIC)}", f"{path}.rubric", cid)
            rubric = rubric if isinstance(rubric, dict) else {}
        for criterion in RUBRIC:
            entry = rubric.get(criterion)
            if not isinstance(entry, dict):
                continue
            score = entry.get("score")
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                report("rubric_score", f"{criterion}.score is an integer from 1 to 5", f"{path}.rubric.{criterion}", cid)
            else:
                scores[criterion] = score
            why = entry.get("why")
            if not _text(why, 200) or "\n" in why:
                report("rubric_why", f"{criterion}.why is a one-line justification (at most 200 characters)",
                       f"{path}.rubric.{criterion}", cid)
        total = sum(scores.values()) if len(scores) == len(RUBRIC) else None
    return {"total": total, "scores": scores}


def _result(diagnostics, scores, selected):
    candidates = {cid: {**value, "valid": not any(d["candidate"] == cid and d["severity"] == "error"
                                                   for d in diagnostics)} for cid, value in scores.items()}
    document_errors = [d for d in diagnostics if d["severity"] == "error" and d["candidate"] is None
                       and d["code"] not in ("selected_invalid",)]
    blocking = document_errors + [d for d in diagnostics if d["code"] == "selected_invalid"]
    ranking = sorted((cid for cid in candidates if candidates[cid]["total"] is not None),
                     key=lambda cid: -candidates[cid]["total"])
    return {"valid": not any(d["severity"] == "error" for d in diagnostics), "saveable": not blocking,
            "selected": selected, "candidates": candidates, "ranking": ranking,
            "errors": sum(d["severity"] == "error" for d in diagnostics), "diagnostics": diagnostics}


# ---- storage -------------------------------------------------------------------------------------

def concept_file(directory):
    return Path(directory) / "concept.json"


def concept_revision(document):
    return digest(document)


def _unwrap(document):
    """Accept the bare concept, or template/get output that carries it under "concept"."""
    if isinstance(document, dict) and "candidates" not in document and isinstance(document.get("concept"), dict):
        return document["concept"]
    return document


def _evidence(store, directory):
    from .listen import latest_listen
    listen = latest_listen(directory)
    arrangement = read_json(directory / "arrangement.json") if (directory / "arrangement.json").exists() else None
    if not listen["available"]:
        raise ConceptError("listen_missing", "The project has no listen evidence (moments and mood) for its current audio",
                           f"Run `music listen {directory.name}` first")
    return listen, evidence_index(listen, arrangement)


def get_concept(store, project_id):
    directory = store.directory(project_id)
    path = concept_file(directory)
    if not path.exists():
        return {"project": project_id, "revision": None, "concept": None,
                "next": f"Run `concept template {project_id}`, write three candidates, then `concept save` with "
                        "--revision none"}
    stored = read_json(path)
    result = {"project": project_id, "revision": stored["revision"], "saved_at": stored.get("saved_at"),
              "concept": stored["concept"], "computed": stored.get("computed")}
    try:
        _, evidence = _evidence(store, directory)
        result["current_validation"] = validate_concept(stored["concept"], evidence)
    except ConceptError as exc:
        result["current_validation"] = {"error": {"code": exc.code, "message": str(exc), "fix": exc.fix}}
    history = directory / "concept-history" / "log"
    result["history"] = [read_json(p) for p in sorted(history.glob("*.json"), reverse=True)] if history.exists() else []
    return result


def validate_file(store, project_id, document):
    directory = store.directory(project_id)
    _, evidence = _evidence(store, directory)
    return {"project": project_id, "run_id": evidence["run_id"], **validate_concept(_unwrap(document), evidence)}


def save_concept(store, project_id, document, expected_revision):
    """Validate and store; ``expected_revision`` is the current revision, or "none" for the first save."""
    from .projects import ConflictError
    document = _unwrap(document)
    with store.lock:
        directory = store.directory(project_id)
        path = concept_file(directory)
        current = read_json(path)["revision"] if path.exists() else None
        if (expected_revision or "none") != (current or "none"):
            raise ConflictError(f"Concept is at revision {current or 'none'}; reread it with `concept get` and "
                                "reconcile before saving")
        _, evidence = _evidence(store, directory)
        result = validate_concept(document, evidence)
        if not result["saveable"]:
            raise ConceptError("concept_invalid", f"Concept not saved: {result['errors']} errors (see diagnostics)",
                               "Fix the listed errors; a candidate with errors cannot be selected",
                               [d for d in result["diagnostics"] if d["severity"] == "error"])
        revision = concept_revision(document)
        computed = {"run_id": evidence["run_id"], "totals": {cid: c["total"] for cid, c in result["candidates"].items()},
                    "valid": {cid: c["valid"] for cid, c in result["candidates"].items()},
                    "ranking": result["ranking"], "selected": result["selected"],
                    "warnings": [d for d in result["diagnostics"] if d["severity"] == "warning"],
                    "errors": [d for d in result["diagnostics"] if d["severity"] == "error"]}
        saved_at = now()
        write_json(directory / "concept-history" / f"{revision}.json", document)
        write_json(directory / "concept-history" / "log" / f"{saved_at.replace(':', '').replace('+', 'Z')[:22]}-"
                   f"{uuid.uuid4().hex[:8]}.json", {"previous": current, "revision": revision, "at": saved_at,
                                                    "selected": result["selected"], "totals": computed["totals"]})
        write_json(path, {"schema_version": CONCEPT_VERSION, "project": project_id, "revision": revision,
                          "saved_at": saved_at, "concept": document, "computed": computed})
    return {"project": project_id, "previous_revision": current, "revision": revision, "selected": result["selected"],
            "totals": computed["totals"], "valid": computed["valid"], "ranking": result["ranking"],
            "warnings": computed["warnings"], "draft_errors": computed["errors"]}


def concept_template(store, project_id):
    """Skeleton concept plus the evidence it should follow from."""
    directory = store.directory(project_id)
    listen, evidence = _evidence(store, directory)
    moods = (listen.get("mood") or {}).get("sections", {})
    sections = []
    for section in listen["sections"]:
        mood = moods.get(section["id"], {})
        key = section.get("key")
        sections.append({"id": section["id"], "start": section["start"], "end": section["end"],
                         "start_beat": section.get("start_beat"), "end_beat": section.get("end_beat"),
                         "group": section.get("group"), "level_db": section.get("level_db"),
                         "map_sections": section.get("map_sections"),
                         "key": f"{key['tonic']} {key['mode']}" if key else None,
                         "valence": mood.get("valence"), "arousal": mood.get("arousal"),
                         "tags": [{"tag": t["tag"], "confidence": t["confidence"]} for t in mood.get("tags", [])]})
    moments = [{k: m.get(k) for k in ("id", "kind", "time", "beat", "strength", "duration", "section_id")}
               for m in listen["moments"]]
    last_third = max((s["end"] for s in listen["sections"]), default=0) * 2 / 3
    held = sorted((m for m in listen["moments"] if m["time"] >= last_third and
                   m["kind"] in ("final_chorus", "drop", "key_change", "build", "ending", "big_hit")),
                  key=lambda m: -m["strength"])[:5]
    lyrics = listen.get("lyrics")
    skeleton = {"id": "", "title": "", "central_idea": "",
                "grounding": {"moments": [], "mood": [], "lyrics": [], "notes": ""},
                "palette": ["#000000", "#ffffff"],
                "motifs": [{"name": "", "description": "", "development": {}}, {"name": "", "description": "",
                                                                             "development": {}}],
                "key_moments": [{"moment_id": "", "treatment": "", "held_for_end": True}],
                "possession": "none", "buildability": {"tiers": [1], "notes": ""},
                "rubric": {criterion: {"score": None, "why": ""} for criterion in RUBRIC}}
    current = concept_file(directory)
    return {"project": project_id, "run_id": listen["run_id"],
            "current_revision": read_json(current)["revision"] if current.exists() else None,
            "evidence": {"song_mood": (listen.get("mood") or {}).get("song"), "sections": sections, "moments": moments,
                         "held_for_end_suggestions": [m["id"] for m in held],
                         "lyrics": None if not lyrics else {
                             "backend": lyrics.get("backend"), "precision": lyrics.get("precision"),
                             "lines": [{"id": s["id"], "start": s["start"], "start_beat": s.get("start_beat"),
                                        "text": s["text"]} for s in lyrics.get("segments", [])]},
                         "lyrics_hint": None if lyrics else f"No lyrics yet: `music lyrics {project_id}` (Whisper) or "
                                                            "`--from-file` a lyric sheet"},
            "concept": {"schema_version": CONCEPT_VERSION, "listen_run": listen["run_id"], "steering": [],
                        "candidates": [dict(skeleton, id=cid) for cid in ("a", "b", "c")], "selected": None},
            "rubric": RUBRIC, "tiers": TIERS, "possession": POSSESSION,
            "rules": ["Exactly three distinct candidates; each follows from cited moments/section mood (and lyrics "
                      "when present), explained in grounding.notes.",
                      "Palette: 2-8 #rrggbb colours. Motifs: 2-4, each developing across >= 2 sections (listen or map "
                      "section ids).",
                      "Key moments: 1-3 moment ids, exactly one held_for_end (the reveal saved for the climax).",
                      "Rubric: integer 1-5 per criterion with a one-line why; totals are computed.",
                      "selected must name a valid candidate; explain in selection_reason when it is not the top total.",
                      "Record the user's steering text in steering[] with how it was applied, before assets are built."],
            "next": f"Fill `concept`, write it to a file, `concept validate --project {project_id} --file F`, then "
                    f"`concept save {project_id} --file F --revision "
                    f"{read_json(current)['revision'] if current.exists() else 'none'}`"}
