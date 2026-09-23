"""Recurring parts of a song and the note themes that echo them.

A song returns to its hooks: a chorus comes back, a riff repeats after a verse. The map follows: a part that
sounds like an earlier one is played with a recognisably recurring pattern, so each song carries its own
signature figures instead of a new random placement every time.

Two measurements find the recurring parts, both in absolute beats on whole bars:

* **Harmony**: the listen run's section repetition groups (``listen.py`` ``_repetition``: chord sequences with the
  song's mean chroma removed, transposition allowed). A section that repeats an earlier one pairs with the
  earliest section it matches, aligned at their starts, over the shorter length.
* **Rhythm**: the attack grid of the drums and the busiest other instrument (``rhythm_stems``). Each bar
  becomes a vector of its sixteenth cells' strongest attacks per stem (``spectral_flux``, ``pitch_change``,
  ``chord_change``, ``melody_change``; each stem normalised to its strongest attack in the song). Two 16-beat
  phrases at least 32 beats apart whose vectors reach cosine ``RHYTHM_SIMILARITY`` repeat the same figure;
  consecutive phrases at the same lag merge into one span.

A **theme** in the arrangement (``themes``) declares the recurrence the map honours: a statement span and the
echo spans that repeat it (an echo repeats the statement from its start, or from ``from_beat`` inside it, and
may be mirrored). The placer
gives an echo note whose time matches a statement note the statement note's hand, cut and cell (mirrored when
asked), unless a movement rule or a stored value says otherwise (``placement.py``). Notes stay on each
occurrence's own sounds, so the echo varies where the audio does.

``project check`` reports a recurring part mapped as an unrelated pattern (``repeat_unechoed``) and a declared
echo the notes no longer follow (``theme_unechoed``); both are warnings.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

BAR_BEATS = 4
PHRASE_BEATS = 16
CELLS_PER_BEAT = 4
MIN_LAG_BEATS = 32
RHYTHM_SIMILARITY = 0.85
RHYTHM_MIN_ATTACKS = 12  # strong attacks a phrase needs before its figure counts as one
ATTACK_STRENGTH = 0.3
MATCH_BEATS = Fraction(13, 100)  # critique.SALIENCE_MATCH_BEATS
ECHO_RHYTHM_THRESHOLD = 0.5
ECHO_PLACEMENT_THRESHOLD = 0.35
ECHO_MIN_MATCHED = 8
MAX_THEMES = 6
RHYTHM_METHODS = ("spectral_flux", "pitch_change", "chord_change", "melody_change")
MIRROR_DIRECTION = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
THEME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

DEFINITIONS = {
    "audio_repeat": "Two whole-bar spans of the song that sound alike: a listen section and the earliest section it "
                    "repeats (repetition group similarity 0.5 or more, aligned at their starts over the shorter "
                    "length), or two 16-beat phrases at least 32 beats apart whose per-stem sixteenth attack grids "
                    "reach cosine 0.85 (consecutive phrases at one lag merge).",
    "echo_rhythm": "Share of note times in a recurring span that match a note of the earlier span at the same "
                   "relative beat (within 0.13 beat), out of the larger of the two spans' note counts.",
    "echo_placement": "Share of those matched notes whose (x, y, colour, direction) equals the earlier note's, "
                      "directly or mirrored (x to 3 - x, colours swapped, cuts mirrored), whichever is higher.",
    "repeat_unechoed": "An audio repeat covered by no theme, whose notes share at least 50% of their times with the "
                       "earlier span (at least 8 matched notes) but fewer than 35% of those matched notes repeat its "
                       "placement: the returning part reads as a different map.",
    "theme_unechoed": "A declared theme echo whose matched notes (at least 8) repeat fewer than 35% of the "
                      "statement's placements, because pinned or stored values or the flow at its seams override it.",
}


def _fraction(value):
    return Fraction(str(value))


# ---------------------------------------------------------------------------------------------------------
# Declared themes
# ---------------------------------------------------------------------------------------------------------

def validate_themes(arrangement: dict, add) -> None:
    """Report malformed ``themes`` through ``add(severity, code, message)``."""
    themes = arrangement["themes"]
    if not isinstance(themes, list):
        add("error", "invalid_theme", "themes must be an array")
        return
    seen, taken = set(), []
    for index, theme in enumerate(themes):
        where = f"themes[{index}]"
        if not isinstance(theme, dict) or set(theme) - {"id", "intent", "spans", "evidence"} \
                or not {"id", "intent", "spans"} <= set(theme):
            add("error", "invalid_theme", f"{where} must be {{id, intent, spans[, evidence]}}")
            continue
        if not isinstance(theme["id"], str) or not THEME_ID.match(theme["id"]) or theme["id"] in seen:
            add("error", "invalid_theme", f"{where}.id must be a unique lowercase identifier")
        seen.add(theme["id"])
        if not isinstance(theme["intent"], str) or not theme["intent"].strip():
            add("error", "invalid_theme", f"{where}.intent must name the recurring sound")
        if "evidence" in theme and not isinstance(theme["evidence"], dict):
            add("error", "invalid_theme", f"{where}.evidence must be an object")
        spans = theme["spans"]
        if not isinstance(spans, list) or len(spans) < 2:
            add("error", "invalid_theme", f"{where}.spans must list the statement and at least one echo")
            continue
        statement = None
        for number, span in enumerate(spans):
            label = f"{where}.spans[{number}]"
            allowed = {"start_beat", "end_beat"} | ({"mirror", "from_beat"} if number else set())
            if not isinstance(span, dict) or set(span) - allowed or not {"start_beat", "end_beat"} <= set(span):
                add("error", "invalid_theme", f"{label} must be {{start_beat, end_beat"
                                              + (", mirror, from_beat}" if number else
                                                 "} (the statement is never mirrored)"))
                continue
            try:
                start, end = _fraction(span["start_beat"]), _fraction(span["end_beat"])
                source = _fraction(span.get("from_beat", statement[0] if statement else 0))
                if any(isinstance(span.get(k), bool) for k in ("start_beat", "end_beat", "from_beat")) \
                        or not 0 <= start < end:
                    raise ValueError
            except (ValueError, TypeError, ZeroDivisionError, OverflowError):
                add("error", "invalid_theme", f"{label} needs 0 <= start_beat < end_beat and a numeric from_beat")
                continue
            if "mirror" in span and not isinstance(span["mirror"], bool):
                add("error", "invalid_theme", f"{label}.mirror must be true or false")
            if number == 0:
                statement = (start, end)
            elif statement is not None and not (statement[0] <= source and source + (end - start) <= statement[1]):
                add("error", "invalid_theme", f"{label} repeats beats {float(source):g}-{float(source + end - start):g}, "
                                              "which must lie inside the statement (the first span)")
            for other_start, other_end, other in taken:
                if start < other_end and other_start < end:
                    add("error", "invalid_theme", f"{label} overlaps {other}; a beat belongs to one theme span")
            taken.append((start, end, label))


def theme_links(arrangement: dict) -> list[dict]:
    """Every declared echo: ``{"theme", "statement": (start, end), "echo": (start, end), "mirror"}`` in Fractions.

    Malformed themes are skipped (validation reports them).
    """
    links = []
    for theme in arrangement.get("themes") or []:
        try:
            head = (_fraction(theme["spans"][0]["start_beat"]), _fraction(theme["spans"][0]["end_beat"]))
            spans = [(_fraction(s["start_beat"]), _fraction(s["end_beat"]),
                      _fraction(s.get("from_beat", head[0])), s.get("mirror") is True) for s in theme["spans"][1:]]
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            continue
        for start, end, source, mirror in spans:
            if start < end and head[0] <= source and source + (end - start) <= head[1]:
                links.append({"theme": theme.get("id"), "statement": (source, source + (end - start)),
                              "echo": (start, end), "mirror": mirror})
    return links


def mirrored(values: dict) -> dict:
    """A placement seen in the mirror: lanes flipped, hands swapped, cuts mirrored."""
    return {"x": 3 - values["x"], "y": values["y"], "color": 1 - values["color"],
            "direction": MIRROR_DIRECTION[values["direction"]]}


def pair_by_time(statement: list, echo: list, offset: Fraction, *, beat=lambda item: item["beat"],
                 order=lambda item: item["id"], same_size: bool = False) -> list[tuple]:
    """(statement item, echo item) pairs at the same relative beat; ``offset`` = echo start - statement start.

    Items are grouped by beat; an echo group takes the nearest unused statement group within ``MATCH_BEATS``,
    and a double pairs its notes in ``order``. With ``same_size`` a group pairs only with a group of as many
    notes: a double where the statement has a single is a different figure, not an echo.
    """
    def groups(items):
        found = {}
        for item in items:
            found.setdefault(_fraction(beat(item)), []).append(item)
        return sorted(found.items())
    source = groups(statement)
    times = [b + offset for b, _ in source]
    used, pairs = set(), []
    for when, members in groups(echo):
        best = None
        for index, time in enumerate(times):
            distance = abs(time - when)
            if index not in used and distance <= MATCH_BEATS and (best is None or distance < best[0]):
                best = (distance, index)
        if best is None or same_size and len(source[best[1]][1]) != len(members):
            continue
        used.add(best[1])
        pairs += list(zip(sorted(source[best[1]][1], key=order), sorted(members, key=order)))
    return pairs


def echo_score(notes: list[dict], statement: tuple, echo: tuple, mirror: bool | None = None) -> dict:
    """How far the notes in span ``echo`` repeat those in span ``statement`` (see ``DEFINITIONS``).

    ``notes`` are expanded notes with absolute beats. ``mirror`` None takes the better of direct and mirrored.
    """
    length = echo[1] - echo[0]
    first = [n for n in notes if statement[0] <= n["beat"] < statement[0] + length]
    second = [n for n in notes if echo[0] <= n["beat"] < echo[1]]
    order = lambda n: (n["color"], n["x"], n["y"], n["id"])
    pairs = pair_by_time(first, second, echo[0] - statement[0], order=order)
    key = lambda n: (n["x"], n["y"], n["color"], n["direction"])
    direct = sum(1 for a, b in pairs if key(a) == key(b))
    flipped = sum(1 for a, b in pairs if key(mirrored(a)) == key(b))
    if mirror is None:
        mirror = flipped > direct
    agree = flipped if mirror else direct
    return {"statement_notes": len(first), "echo_notes": len(second), "matched": len(pairs),
            "rhythm": round(len(pairs) / max(1, len(first), len(second)), 3),
            "placement": round(agree / len(pairs), 3) if pairs else 0.0, "mirror": bool(mirror)}


# ---------------------------------------------------------------------------------------------------------
# Recurring audio
# ---------------------------------------------------------------------------------------------------------

def bar_vectors(report: dict, arrangement: dict) -> dict[int, list[float]]:
    """{bar start beat: per-stem sixteenth attack strengths}, each stem normalised to its song-wide peak."""
    from .musical import seconds_to_beat
    layers = report.get("layers") or {}
    names = rhythm_stems(report)
    cells = BAR_BEATS * CELLS_PER_BEAT
    vectors = {}
    for position, name in enumerate(names):
        events = [(seconds_to_beat(e["seconds"], arrangement), float(e.get("strength", 0)))
                  for e in layers[name].get("events", []) if e.get("method") in RHYTHM_METHODS]
        ceiling = max((s for _, s in events), default=0) or 1.0
        for beat, strength in events:
            index = math.floor(beat * CELLS_PER_BEAT + .5)
            if index < 0:
                continue
            bar = (index // cells) * BAR_BEATS
            vector = vectors.setdefault(bar, [0.0] * (cells * len(names)))
            slot = position * cells + index % cells
            vector[slot] = max(vector[slot], strength / ceiling)
    return vectors


def rhythm_stems(report: dict) -> list[str]:
    """The stems whose attack grid carries a part's figure: the drums and the busiest other instrument.

    Vocals follow the lyrics (a returning chorus melody may carry new words) and the mix doubles every stem, so
    neither decides whether a part repeats. Without a drum stem the two busiest instruments are used.
    """
    layers = report.get("layers") or {}

    def attacks(name):
        events = [e for e in layers[name].get("events", []) if e.get("method") in RHYTHM_METHODS]
        ceiling = max((float(e.get("strength", 0)) for e in events), default=0) or 1.0
        return sum(1 for e in events if float(e.get("strength", 0)) / ceiling >= ATTACK_STRENGTH)
    instruments = sorted((n for n in layers if n not in ("mix", "vocals", "drums")), key=lambda n: (-attacks(n), n))
    if "drums" in layers:
        return ["drums"] + instruments[:1]
    return instruments[:2] or [n for n in layers if n != "mix"][:2] or list(layers)[:1]


def _phrase(vectors, start):
    phrase = []
    for bar in range(start, start + PHRASE_BEATS, BAR_BEATS):
        phrase += vectors.get(bar) or []
    return phrase


def _cosine(a, b):
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _bar(value) -> int:
    return int(round(float(value) / BAR_BEATS)) * BAR_BEATS


def _listen_repeats(sections, song_end):
    found = []
    by_id = {s.get("id"): s for s in sections}
    for section in sections:
        earlier = [(by_id[r["section_id"]], r) for r in section.get("repeats") or [] if r.get("section_id") in by_id]
        earlier = [(s, r) for s, r in earlier if s.get("start_beat") is not None]
        if not earlier or section.get("start_beat") is None:
            continue
        source, match = min(earlier, key=lambda item: item[0]["start_beat"])
        a0, b0 = _bar(max(0.0, source["start_beat"])), _bar(section["start_beat"])
        a1 = min(_bar(source["end_beat"]), b0)
        b1 = min(_bar(section["end_beat"]), song_end)
        length = min(a1 - a0, b1 - b0) // BAR_BEATS * BAR_BEATS
        if length < PHRASE_BEATS or b0 - a0 < MIN_LAG_BEATS:
            continue
        found.append({"statement": [a0, a0 + length], "echo": [b0, b0 + length], "source": "listen",
                      "similarity": match.get("similarity"),
                      "transposed_semitones": match.get("transposed_semitones") or 0,
                      "sections": [source["id"], section["id"]]})
    return found


def _rhythm_repeats(vectors, song_end):
    starts = [b for b in range(0, song_end - PHRASE_BEATS + 1, BAR_BEATS)]
    phrases = {}
    for start in starts:
        phrase = _phrase(vectors, start)
        if len(phrase) == 4 * len(next(iter(vectors.values()), [])) and \
                sum(1 for v in phrase if v >= ATTACK_STRENGTH) >= RHYTHM_MIN_ATTACKS:
            phrases[start] = phrase
    best = {}
    for later in phrases:
        match = None
        for earlier in phrases:
            if later - earlier < MIN_LAG_BEATS:
                break
            value = _cosine(phrases[earlier], phrases[later])
            if value >= RHYTHM_SIMILARITY and (match is None or value > match[0] + 1e-9):
                match = (value, earlier)
        if match:
            best[later] = match
    runs = []
    for later in sorted(best):
        value, earlier = best[later]
        lag = later - earlier
        if runs and runs[-1]["lag"] == lag and later - runs[-1]["last"] <= BAR_BEATS:
            runs[-1].update(last=later, values=runs[-1]["values"] + [value])
        else:
            runs.append({"lag": lag, "first": later, "last": later, "values": [value]})
    found = []
    for run in runs:
        b0, b1 = run["first"], min(run["last"] + PHRASE_BEATS, song_end)
        a0 = b0 - run["lag"]
        b1 = min(b1, b0 + run["lag"])  # the echo never reaches back into its own statement
        found.append({"statement": [a0, a0 + b1 - b0], "echo": [b0, b1], "source": "rhythm",
                      "similarity": round(sum(run["values"]) / len(run["values"]), 3),
                      "transposed_semitones": 0, "sections": []})
    return found


def audio_repeats(arrangement: dict, report: dict | None, listen_sections: list | None = None) -> list[dict]:
    """Recurring spans of the song (see the module docstring), echo spans never overlapping each other."""
    try:
        song_end = int(max(_fraction(s["start_beat"]) + _fraction(s["length_beats"]) for s in arrangement["sections"]))
    except (KeyError, TypeError, ValueError):
        return []
    found = _listen_repeats(listen_sections or [], song_end)
    if report:
        vectors = bar_vectors(report, arrangement)
        if vectors:
            found += _rhythm_repeats(vectors, song_end)
    kept = []
    for item in sorted(found, key=lambda r: (r["source"] != "listen", -(r["echo"][1] - r["echo"][0]), r["echo"][0])):
        piece = _largest_free(item["echo"], [k["echo"] for k in kept])
        if piece is None:
            continue
        shift = piece[0] - item["echo"][0]
        kept.append({**item, "echo": list(piece),
                     "statement": [item["statement"][0] + shift, item["statement"][0] + shift + piece[1] - piece[0]]})
    return sorted(kept, key=lambda r: r["echo"][0])


def _largest_free(span, taken):
    """The longest part of ``span`` (whole bars, at least a phrase) that overlaps none of ``taken``, else None."""
    pieces = [tuple(span)]
    for a, b in taken:
        pieces = [part for start, end in pieces
                  for part in ((start, min(end, a)), (max(start, b), end)) if part[1] > part[0]]
    pieces = [p for p in pieces if p[1] - p[0] >= PHRASE_BEATS]
    return max(pieces, key=lambda p: (p[1] - p[0], -p[0])) if pieces else None


def propose_themes(arrangement: dict, report: dict | None, listen_sections: list | None = None) -> list[dict]:
    """Themes for the song's recurring parts, for the rhythm draft and ``project check`` suggestions.

    Each theme's statement is the earliest occurrence. A repeat whose earlier span overlaps a theme's statement
    joins that theme as an echo of the overlapping part (``from_beat`` names where in the statement it starts),
    so a riff that returns several times becomes one theme. A transposed repeat, and every second echo, is
    mirrored so a recurring part stays recognisable without the map replaying one figure. Spans already in a
    declared theme are left alone.
    """
    taken = []
    for theme in arrangement.get("themes") or []:
        for span in (theme.get("spans") or []) if isinstance(theme, dict) else []:
            try:
                taken.append((float(_fraction(span["start_beat"])), float(_fraction(span["end_beat"]))))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
    names = {t.get("id") for t in arrangement.get("themes") or [] if isinstance(t, dict)}

    def free(span):
        return not any(span[0] < b and a < span[1] for a, b in taken)
    work = []
    for repeat in sorted(audio_repeats(arrangement, report, listen_sections),
                         key=lambda r: (r["source"] != "listen", r["statement"][0],
                                        -(r["statement"][1] - r["statement"][0]), r["echo"][0])):
        (s0, s1), (e0, e1) = repeat["statement"], repeat["echo"]
        # An earlier span that is itself an echo repeats that echo's statement.
        for theme in work:
            inside = [(echo, source) for echo, source, _ in theme["echoes"] if echo[0] <= s0 and s1 <= echo[1]]
            if inside:
                (echo_start, _), source = inside[0]
                s0, s1 = source + s0 - echo_start, source + s1 - echo_start
                break
        host = next((t for t in work if s0 < t["statement"][1] and t["statement"][0] < s1), None)
        if host is not None and not (host["statement"][0] <= s0 and s1 <= host["statement"][1]):
            # The earlier span runs past the theme's statement: the statement grows to cover it when it can.
            grown = (min(s0, host["statement"][0]), max(s1, host["statement"][1]))
            others = [span for span in taken if span != host["statement"]]
            if any(grown[0] < b and a < grown[1] for a, b in others):
                continue
            taken[taken.index(host["statement"])] = grown
            host["statement"] = grown
        if host is None:
            # A new theme; its statement and echo give way to spans already taken.
            piece = _largest_free((s0, s1), taken + [(e0, e1)])
            if piece is None:
                continue
            e0, e1 = e0 + piece[0] - s0, e0 + piece[1] - s0
            (s0, s1), statement = piece, piece
        else:
            statement = None
        piece = _largest_free((e0, e1), taken + ([statement] if statement else []))
        if piece is None:
            continue
        s0, echo = s0 + piece[0] - e0, piece
        if statement:
            host = {"statement": statement, "echoes": []}
            work.append(host)
            taken.append(statement)
        taken.append(echo)
        host["echoes"].append((echo, s0, repeat))
    themes = []
    for host in work:
        if not host["echoes"]:
            continue
        statement = host["statement"]
        spans = [{"start_beat": statement[0], "end_beat": statement[1]}]
        for number, (echo, source, repeat) in enumerate(sorted(host["echoes"], key=lambda e: e[0]), start=1):
            mirror = bool(repeat["transposed_semitones"]) or number % 2 == 0
            spans.append({"start_beat": echo[0], "end_beat": echo[1],
                          **({"from_beat": source} if source != statement[0] else {}),
                          **({"mirror": True} if mirror else {})})
        repeats = [r for _, _, r in host["echoes"]]
        sources = sorted({r["source"] for r in repeats})
        number = len(themes) + 1
        while f"theme-{number}" in names:
            number += 1
        names.add(f"theme-{number}")
        themes.append({"id": f"theme-{number}",
                       "intent": (f"the part first heard at beats {statement[0]}-{statement[1]} returns "
                                  f"({' and '.join(sources)} repeat)"),
                       "spans": spans,
                       "evidence": {"sources": sources, "sections": sorted({s for r in repeats for s in r["sections"]}),
                                    "similarity": [r["similarity"] for r in repeats]}})
        if len(themes) == MAX_THEMES:
            break
    return themes


# ---------------------------------------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------------------------------------

def recurrence_findings(arrangement: dict, report: dict | None, listen_sections: list | None, warn) -> dict:
    """``repeat_unechoed`` and ``theme_unechoed`` warnings through ``warn``; returns the recurrence metrics."""
    from .arrangement import expanded_notes
    notes = expanded_notes(arrangement)
    links = theme_links(arrangement)
    metrics = {"themes": [], "repeats": []}
    for link in links:
        score = echo_score(notes, link["statement"], link["echo"], link["mirror"])
        entry = {"theme": link["theme"], "statement": [float(v) for v in link["statement"]],
                 "echo": [float(v) for v in link["echo"]], **score}
        metrics["themes"].append(entry)
        if score["matched"] >= ECHO_MIN_MATCHED and score["placement"] < ECHO_PLACEMENT_THRESHOLD:
            warn("theme_unechoed",
                 f'theme {link["theme"]}: beats {entry["echo"][0]:g}-{entry["echo"][1]:g} should echo '
                 f'{entry["statement"][0]:g}-{entry["statement"][1]:g}, but only {score["placement"] * 100:.0f}% of '
                 f'{score["matched"]} matched notes repeat its placement: pinned or stored hands, cuts or cells, or '
                 "the movement rules around it, override the theme there. Unpin the echo's notes (drop x, y, color, "
                 "direction and placed) to let it echo; if it still does not, the flow into it differs from the "
                 "statement's and the echo varies there on purpose.",
                 value=score["placement"], threshold=ECHO_PLACEMENT_THRESHOLD, beats=entry["echo"])

    def covered(repeat):
        return any(float(l["echo"][0]) <= repeat["echo"][0] and repeat["echo"][1] <= float(l["echo"][1])
                   or float(l["echo"][0]) < repeat["echo"][1] and repeat["echo"][0] < float(l["echo"][1])
                   for l in links)
    for repeat in audio_repeats(arrangement, report, listen_sections):
        statement = tuple(Fraction(v) for v in repeat["statement"])
        echo = tuple(Fraction(v) for v in repeat["echo"])
        score = echo_score(notes, statement, echo)
        entry = {**repeat, **score, "themed": covered(repeat)}
        metrics["repeats"].append(entry)
        if entry["themed"] or score["matched"] < ECHO_MIN_MATCHED or score["rhythm"] < ECHO_RHYTHM_THRESHOLD \
                or score["placement"] >= ECHO_PLACEMENT_THRESHOLD:
            continue
        where = (f'listen {" / ".join(reversed(repeat["sections"]))}, similarity {repeat["similarity"]}'
                 if repeat["source"] == "listen" else f'stem rhythm, cosine {repeat["similarity"]}')
        theme = _theme_for(arrangement, repeat)
        warn("repeat_unechoed",
             f'beats {repeat["echo"][0]}-{repeat["echo"][1]} repeat {repeat["statement"][0]}-{repeat["statement"][1]} '
             f'({where}) with {score["rhythm"] * 100:.0f}% of the same note times but '
             f'{score["placement"] * 100:.0f}% of the same placements; the returning part reads as a different map. '
             "Declare a theme so the placer echoes the earlier placement.",
             value=score["placement"], threshold=ECHO_PLACEMENT_THRESHOLD, beats=list(repeat["echo"]),
             suggestions=[{"op": "add_theme", "theme": theme}] if theme else None)
    return metrics


def _theme_for(arrangement, repeat):
    """The theme that declares ``repeat``: a declared theme whose statement covers its earlier span, extended by
    one echo, else a new theme. None when either span would overlap a declared theme span."""
    import copy
    echo = {"start_beat": repeat["echo"][0], "end_beat": repeat["echo"][1],
            **({"mirror": True} if repeat["transposed_semitones"] else {})}
    spans = []
    for theme in arrangement.get("themes") or []:
        try:
            spans += [(float(_fraction(s["start_beat"])), float(_fraction(s["end_beat"])), theme, n)
                      for n, s in enumerate(theme["spans"])]
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
    if any(a < repeat["echo"][1] and repeat["echo"][0] < b for a, b, _, _ in spans):
        return None
    (s0, s1) = repeat["statement"]
    host = [(theme, a, b) for a, b, theme, n in spans if n == 0 and a <= s0 and s1 <= b]
    if host:
        theme, a, _ = host[0]
        extended = copy.deepcopy(theme)
        extended["spans"].append({**echo, **({"from_beat": s0} if s0 != a else {})})
        return extended
    if any(a < s1 and s0 < b for a, b, _, _ in spans):
        return None
    return {"id": f"repeat-{repeat['echo'][0]}", "intent": "the returning part named in this finding",
            "spans": [{"start_beat": s0, "end_beat": s1}, echo]}


def add_theme(arrangement: dict, theme: dict) -> dict:
    """A copy with ``theme`` declared and its new echo spans' unlocked literal notes reopened for the placer.

    A theme with the same ``id`` is replaced (a theme extended by an echo). Reopening removes ``x``, ``y``,
    ``color``, ``direction`` and ``placed`` from every unlocked literal note inside an echo span the theme did not
    have before, so the placer chooses them again with the echo preference. The statement keeps its notes.
    """
    import copy
    result = copy.deepcopy(arrangement)
    themes = result.setdefault("themes", [])
    before = next((t for t in themes if isinstance(t, dict) and t.get("id") == theme.get("id")), None)
    known = [(s.get("start_beat"), s.get("end_beat")) for s in (before or {}).get("spans", [])[1:]]
    if before is not None:
        themes[themes.index(before)] = copy.deepcopy(theme)
    else:
        themes.append(copy.deepcopy(theme))
    echoes = [(_fraction(s["start_beat"]), _fraction(s["end_beat"])) for s in theme["spans"][1:]
              if (s["start_beat"], s["end_beat"]) not in known]
    for section in result["sections"]:
        if section.get("locked") is True:
            continue
        start = _fraction(section["start_beat"])
        for note in section["notes"]:
            beat = start + _fraction(note["beat"])
            if any(a <= beat < b for a, b in echoes):
                for field in ("x", "y", "color", "direction", "placed"):
                    note.pop(field, None)
    return result
