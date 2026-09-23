"""The map explained to the player: one paragraph for the whole song, one sentence per section.

The agent writes two plain-language texts beside the evidence it keeps for itself:

* ``style.summary``: one paragraph on the mapping goal and the chosen approach (what the map wants the player to
  feel, and how the style gets there);
* each section's ``summary``: one sentence on what that part of the song is and what the player does there.

A section's ``intent`` keeps the evidence (runs, stems, onsets) for agents; the studio and the viewer show the
summary and fold the evidence away. ``outline`` gives both, with each section's start and end in song seconds, for
the studio, the ArcViewer side panel (``/viewer/``) and ``project outline``. ``project check`` reports a map whose
player-facing texts are missing (``summary_missing``).
"""

from __future__ import annotations

import re
from fractions import Fraction

SUMMARY_LIMIT = 240  # one sentence
STYLE_SUMMARY_LIMIT = 1200  # one paragraph
DEFINITIONS = {
    "summary_missing": "The map has no player-facing explanation: the style has no summary paragraph, or sections "
                       "have no one-sentence summary. The studio then falls back to the first sentence of each "
                       "intent, which is written for agents.",
}
_EVIDENCE = re.compile(r"\s*(?:Evidence\b|Evidence run\b|\(evidence|Run [0-9a-f]{8,}).*$", re.I | re.S)


def _fraction(value):
    return Fraction(str(value))


def fallback_summary(intent: str) -> str:
    """The first sentence of an intent, without its evidence trail (for maps written before summaries)."""
    text = _EVIDENCE.sub("", str(intent or "")).strip()
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0] if text else ""
    return first if len(first) <= SUMMARY_LIMIT else first[:SUMMARY_LIMIT - 1].rstrip() + "…"


def validate_summary(section: dict, add, sid) -> None:
    """A section ``summary`` is one line of at most SUMMARY_LIMIT characters."""
    summary = section.get("summary")
    if not isinstance(summary, str) or not summary.strip() or "\n" in summary or len(summary) > SUMMARY_LIMIT:
        add("error", "invalid_summary", f"section summary must be one sentence on one line, at most "
                                        f"{SUMMARY_LIMIT} characters", sid)


def outline(arrangement: dict, duration_seconds: float | None = None) -> dict:
    """The song's explanation and its sections in song seconds, summary first and evidence apart."""
    from .critique import beat_to_seconds
    style = arrangement.get("style") if isinstance(arrangement.get("style"), dict) else None
    themes = []
    for theme in arrangement.get("themes") or []:
        try:
            spans = [(float(_fraction(s["start_beat"])), float(_fraction(s["end_beat"]))) for s in theme["spans"]]
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        themes.append({"id": theme.get("id"), "intent": theme.get("intent"),
                       "spans": [{"start_beat": a, "end_beat": b, "start_seconds": round(beat_to_seconds(a, arrangement), 3),
                                  "end_seconds": round(beat_to_seconds(b, arrangement), 3),
                                  "role": "statement" if n == 0 else "echo"} for n, (a, b) in enumerate(spans)]})
    sections = []
    for section in arrangement["sections"]:
        start = float(_fraction(section["start_beat"]))
        end = start + float(_fraction(section["length_beats"]))
        written = section.get("summary") if isinstance(section.get("summary"), str) else None
        sections.append({
            "id": section["id"], "start_beat": start, "end_beat": end,
            "start_seconds": round(beat_to_seconds(start, arrangement), 3),
            "end_seconds": round(beat_to_seconds(end, arrangement), 3),
            "summary": written or fallback_summary(section.get("intent")),
            "summary_source": "summary" if written else "intent",
            "evidence": section.get("intent"),
            "locked": section.get("locked") is True,
            "themes": sorted({t["id"] for t in themes for s in t["spans"] if s["start_beat"] < end and start < s["end_beat"]}),
        })
    return {"song": {"title": arrangement["song"]["title"], "artist": arrangement["song"]["artist"],
                     "bpm": arrangement["song"]["bpm"], "duration_seconds": duration_seconds},
            "difficulty": arrangement["difficulty"]["name"],
            "style": None if style is None else {k: style.get(k) for k in ("idea", "summary", "settings", "signatures")},
            "sections": sections, "themes": themes}


def summary_findings(arrangement: dict, warn) -> dict:
    """``summary_missing`` through ``warn``; returns which texts exist."""
    style = arrangement.get("style") if isinstance(arrangement.get("style"), dict) else None
    missing = [s["id"] for s in arrangement["sections"] if not isinstance(s.get("summary"), str)]
    has_paragraph = bool(style and isinstance(style.get("summary"), str) and style["summary"].strip())
    if missing or not has_paragraph:
        parts = []
        if not has_paragraph:
            parts.append("the style has no summary paragraph (the mapping goal and approach, for the player)")
        if missing:
            parts.append(f"{len(missing)} of {len(arrangement['sections'])} sections have no one-sentence summary "
                         f"({', '.join(missing[:6])}{'…' if len(missing) > 6 else ''})")
        warn("summary_missing", "The studio explains the map with its texts, but " + " and ".join(parts)
             + ". Write them in plain language; keep the evidence in each intent.",
             value=len(missing), threshold=0)
    return {"style_summary": has_paragraph, "sections_without_summary": missing}
