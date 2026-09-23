"""Exact-chart difficulty coverage and descriptive, unreviewed phrase references."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics

from .corpus import _atomic_json
from .star_tiers import load_profile, player_tiers, tier_by_id, tier_for, tier_label

TIER_WINDOW_METRICS = ("swing_rate_per_second", "peak_one_second_swing_count", "longest_quarter_second_burst",
                       "crossover_demand_count", "maximum_grid_speed_proxy", "mean_grid_distance",
                       "minimum_recovery_seconds")


def positive_rating(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 else None


def chart_records(store, tiers=None):
    """Join only the requested version; never borrow ratings from another revision.

    Each chart carries the player-relative ``star_tier`` of its ScoreSaber rating.
    """
    tiers = tiers or player_tiers(load_profile(store.root.parent))
    charts = {}
    for hash_, provenance, updated, archive_sha in store.db.execute(
            "SELECT version_hash,provenance_json,updated_utc,archive_sha256 FROM maps WHERE status='processed'"):
        metadata = json.loads(provenance).get("metadata", {})
        meta = metadata.get("metadata", {})
        for version in metadata.get("versions", []):
            if version.get("hash", "").upper() != hash_.upper():
                continue
            for diff in version.get("diffs", []):
                if diff.get("characteristic") != "Standard":
                    continue
                label = diff.get("difficulty")
                charts[(hash_.upper(), label)] = {
                    "version_hash": hash_.upper(), "difficulty": label, "characteristic": "Standard",
                    "song": meta.get("songName"), "mapper": meta.get("levelAuthorName"),
                    "map_id": metadata.get("id"), "source_url": f"https://beatsaver.com/maps/{metadata.get('id')}",
                    "exact_metadata_url": f"https://api.beatsaver.com/maps/hash/{hash_}",
                    "stars": positive_rating(diff.get("stars")), "rating_system": "ScoreSaber",
                    "star_tier": tier_for(positive_rating(diff.get("stars")), tiers),
                    "rating_source": "saved BeatSaver exact-version diffs[].stars; not live ScoreSaber",
                    "metadata_record_updated_utc": updated,
                    "archive_sha256": archive_sha,
                    "bpm": meta.get("bpm"), "nps": diff.get("nps"), "njs": diff.get("njs"),
                    "era": metadata.get("uploaded", "")[:4], "source_tags": metadata.get("tags") or [],
                    "requires_gameplay_mods": bool(diff.get("ne") or diff.get("me")),
                    "review_status": "unreviewed", "rights_status": "redistribution_unknown",
                }
    return charts


def rating_summary(charts, min_stars=6.5, max_stars=8):
    rated = [c for c in charts if positive_rating(c.get("stars")) is not None]
    values = [c["stars"] for c in rated]
    target = [c for c in rated if min_stars <= c["stars"] <= max_stars]
    return {"charts": len(charts), "rated_charts": len(rated), "unrated_charts": len(charts)-len(rated),
            "mean_stars": round(statistics.mean(values), 4) if values else None,
            "median_stars": round(statistics.median(values), 4) if values else None,
            "min_stars": min(values) if values else None, "max_stars": max(values) if values else None,
            "below_target": sum(c["stars"] < min_stars for c in rated), "within_target": len(target),
            "above_target": sum(c["stars"] > max_stars for c in rated),
            "versions_with_target_chart": len({c["version_hash"] for c in target})}


def pattern_tags(pattern):
    """Observable note-shape categories, not musical roles or playability verdicts."""
    notes = pattern.get("notes", [])
    if not notes:
        return []
    beats = sorted({round(n["beat"], 5) for n in notes})
    intervals = [round(b-a, 5) for a, b in zip(beats, beats[1:])]
    tags = []
    if len(beats) < len(notes):
        tags.append("simultaneous_notes")
    if any(n["direction"] in (4, 5, 6, 7) for n in notes):
        tags.append("diagonal_cuts")
    if any(n["direction"] == 8 for n in notes):
        tags.append("dot_notes")
    if any((n["color"] == 0 and n["x"] >= 2) or (n["color"] == 1 and n["x"] <= 1) for n in notes):
        tags.append("opposite_half_placement")
    if len({n["y"] for n in notes}) == 3:
        tags.append("three_row_movement")
    if len(set(intervals)) >= 3:
        tags.append("varied_spacing")
    if intervals and min(intervals) <= .25:
        tags.append("quarter_beat_or_faster")
    if intervals and max(intervals) >= 1:
        tags.append("one_beat_gap")
    if len(beats) == len(notes) and all(a["color"] != b["color"] for a, b in zip(notes, notes[1:])):
        tags.append("alternating_hands")
    if any(pattern.get("motion_context", {}).values()):
        tags.append("additional_objects")
    return tags


def filter_patterns(patterns, charts, *, min_stars=None, max_stars=None, tag=None, tier=None):
    if min_stars is not None and max_stars is not None and min_stars > max_stars:
        raise ValueError("minimum stars exceeds maximum stars")
    out = []
    for pattern in patterns:
        chart = charts.get((pattern["version_hash"].upper(), pattern["difficulty"]), {})
        stars = chart.get("stars")
        if tier is not None and (chart.get("star_tier") != tier or chart.get("requires_gameplay_mods")):
            continue
        if min_stars is not None or max_stars is not None:
            if stars is None or chart.get("requires_gameplay_mods"):
                continue
            if min_stars is not None and stars < min_stars or max_stars is not None and stars > max_stars:
                continue
        if tag and tag not in pattern_tags(pattern):
            continue
        out.append(pattern)
    return out


def phrase_record(pattern, chart, audio_hash=None):
    record = {k: pattern.get(k) for k in ("id", "version_hash", "song_family_id", "difficulty", "start_beat",
        "length_beats", "bpm", "nps", "active_nps", "note_count", "family_key", "movement_metrics",
        "movement_warnings", "motion_context", "unsupported_motion")}
    def posture(note):
        return {k: note.get(k) for k in ("id", "beat", "x", "y", "direction", "color")} if note else None
    notes = pattern.get("notes", [])
    boundary = {}
    for color in (0, 1):
        hand = [n for n in notes if n["color"] == color]
        boundary[str(color)] = {"first_note": posture(hand[0]) if hand else None,
                                "last_note": posture(hand[-1]) if hand else None}
    record.update({"chart": chart, "stars": chart.get("stars"), "star_tier": chart.get("star_tier"),
        "tags": pattern_tags(pattern), "audio_sha256": audio_hash,
        "source_pointer": {"catalog": "patterns.json", "pattern_id": pattern["id"], "map_file": pattern.get("source")},
        "end_beat": pattern["start_beat"]+pattern["length_beats"],
        "rhythm_intervals": pattern.get("rhythm_intervals", []),
        "entry_context": pattern.get("entry_hand_state"), "exit_context": pattern.get("exit_hand_state"),
        "boundary_notes_by_hand": boundary,
        "preceding_notes": [posture(n) for n in pattern.get("entry_notes", [])],
        "following_notes": [posture(n) for n in pattern.get("exit_notes", [])],
        "review_status": "unreviewed", "rights_status": "redistribution_unknown; study only, do not copy arrays",
        "timing_status": "declared map BPM/native beats; musical alignment not listened to",
        "musical_role": "unknown_without_audio_review"})
    return record


def numeric_summary(values):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    if not values:
        return {"count": 0}
    def quantile(q):
        index = (len(values)-1)*q
        lo, hi = math.floor(index), math.ceil(index)
        return round(values[lo]+(values[hi]-values[lo])*(index-lo), 4)
    return {"count": len(values), "mean": round(statistics.mean(values), 4),
            "p10": quantile(.1), "median": quantile(.5), "p90": quantile(.9), "max": values[-1]}


def shortlist(target, charts, by_id, limit, *, center_stars, reason):
    """Round-robin observable categories; at most two references per map; warnings stay visible."""
    buckets = defaultdict(list)
    for p in target:
        for tag in pattern_tags(p):
            buckets[tag].append(p)
    for items in buckets.values():
        items.sort(key=lambda p: (bool(p.get("unsupported_motion")),
                                  abs(charts[(p["version_hash"], p["difficulty"])]["stars"]-center_stars), p["id"]))
    chosen, motifs, per_map = [], set(), Counter()
    while len(chosen) < limit:
        advanced = False
        for tag, items in sorted(buckets.items()):
            pick = next((p for p in items if p["family_key"] not in motifs and per_map[p["version_hash"]] < 2), None)
            if pick is None:
                continue
            row = dict(by_id[pick["id"]])
            row["selection_category"] = tag
            row["fit_reason"] = reason(row, tag)
            chosen.append(row)
            motifs.add(pick["family_key"])
            per_map[pick["version_hash"]] += 1
            advanced = True
            if len(chosen) == limit:
                break
        if not advanced:
            break
    return chosen, per_map


def tier_reference(patterns, charts, tiers):
    """Per-tier chart and 4-beat window statistics: what each star level looks like in real maps."""
    windows = defaultdict(list)
    for p in patterns:
        chart = charts.get((p["version_hash"].upper(), p["difficulty"]))
        if chart and chart.get("star_tier") and not chart["requires_gameplay_mods"]:
            windows[chart["star_tier"]].append(p)
    result = []
    for tier in tiers:
        items = windows.get(tier["id"], [])
        tier_charts = list({(p["version_hash"].upper(), p["difficulty"]): charts[(p["version_hash"].upper(), p["difficulty"])]
                            for p in items}.values())
        tags = Counter(tag for p in items for tag in pattern_tags(p))
        result.append({**tier, "label": tier_label(tier), "charts": len(tier_charts), "windows": len(items),
                       "chart_stars": numeric_summary([c["stars"] for c in tier_charts]),
                       "chart_nps": numeric_summary([c["nps"] for c in tier_charts]),
                       "chart_notes_per_beat": numeric_summary([c["nps"] * 60 / c["bpm"] for c in tier_charts
                                                                if c.get("nps") and c.get("bpm")]),
                       "chart_njs": numeric_summary([c["njs"] for c in tier_charts]),
                       "window_nps": numeric_summary([p["nps"] for p in items]),
                       "window_notes_per_beat": numeric_summary([p.get("note_count", len(p.get("notes", []))) / p["length_beats"] for p in items]),
                       "window_movement": {field: numeric_summary([(p.get("movement_metrics") or {}).get(field) for p in items])
                                           for field in TIER_WINDOW_METRICS},
                       "tag_share": {tag: round(count / len(items), 4) for tag, count in sorted(tags.items())} if items else {}})
    return result


def analyze_corpus(store, *, min_stars=6.5, max_stars=8, shortlist_limit=60, tier_shortlist_limit=40):
    if not 0 < min_stars <= max_stars or shortlist_limit < 0:
        raise ValueError("invalid analysis bounds")
    patterns = store.catalog_patterns()
    if not patterns:
        raise ValueError("no current patterns; run corpus process first")
    charts = chart_records(store)
    available = {(p["version_hash"], p["difficulty"]) for p in patterns}
    usable_charts = [c for key, c in charts.items() if key in available and not c["requires_gameplay_mods"]]
    target = filter_patterns(patterns, charts, min_stars=min_stars, max_stars=max_stars)
    audio = dict(store.db.execute("SELECT version_hash,json_extract(processing_json,'$.audio_sha256') FROM maps WHERE status='processed'"))
    compact = [phrase_record(p, charts.get((p["version_hash"], p["difficulty"]), {}), audio.get(p["version_hash"])) for p in patterns]
    by_id = {p["id"]: p for p in compact}
    chosen, per_map = shortlist(target, charts, by_id, shortlist_limit, center_stars=7.43, reason=lambda row, tag: (
        f"Source chart is {row['chart']['stars']:g} stars within {min_stars:g}-{max_stars:g}; illustrates "
        f"{tag.replace('_', ' ')}. Local phrase difficulty and transitions still need review."))
    tiers = player_tiers(load_profile(store.root.parent))
    tier_rows = tier_reference(patterns, charts, tiers)
    tier_lists = {}
    for tier in tiers:
        if tier["id"] in ("below_band", "beyond"):
            continue
        in_tier = filter_patterns(patterns, charts, tier=tier["id"])
        stars = [charts[(p["version_hash"].upper(), p["difficulty"])]["stars"] for p in in_tier]
        tier_lists[tier["id"]] = shortlist(in_tier, charts, by_id, tier_shortlist_limit,
                                           center_stars=statistics.median(stars) if stars else 0,
                                           reason=lambda row, tag, tier=tier: (
            f"Source chart is {row['chart']['stars']:g} stars, tier {tier['id']} ({tier_label(tier)}); illustrates "
            f"{tag.replace('_', ' ')}. The chart rating does not rate this phrase; review its transitions."))[0]
    target_tags = Counter(tag for p in target for tag in pattern_tags(p))
    groups = Counter(p["family_key"] for p in patterns)
    per_chart = Counter((p["version_hash"], p["difficulty"]) for p in patterns)
    for key, c in charts.items():
        c["pattern_count"] = per_chart[key]
    movement_fields = ("swing_rate_per_second", "peak_one_second_swing_count", "mean_grid_distance",
                       "mean_angular_change_degrees", "minimum_recovery_seconds", "crossover_demand_count")
    report = {"schema_version": "1.0", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "target_band": [min_stars, max_stars], "rating_policy": "Chart-weighted positive ScoreSaber ratings from exact-version saved metadata; unrated is unknown, never zero.",
        "status_counts": dict(Counter(r["status"] for r in store.rows())),
        "all_metadata_charts": rating_summary(list(charts.values()), min_stars, max_stars),
        "usable_pattern_charts": rating_summary(usable_charts, min_stars, max_stars),
        "difficulty_labels": dict(Counter(c["difficulty"] for c in usable_charts)),
        "patterns": len(patterns), "motif_groups": len(groups), "repeated_windows": sum(n-1 for n in groups.values()),
        "target_patterns": len(target), "target_motif_groups": len({p["family_key"] for p in target}),
        "target_pattern_tags": dict(target_tags), "shortlist_count": len(chosen),
        "target_phrase_nps": numeric_summary([p["nps"] for p in target]),
        "target_movement_metrics": {field: numeric_summary([(p.get("movement_metrics") or {}).get(field) for p in target])
                                    for field in movement_fields},
        "shortlist_versions": len(per_map), "target_patterns_with_context_warnings": sum(bool(p.get("unsupported_motion")) for p in target),
        "charts_missing_exact_metadata": len(available-set(charts)),
        "eras": dict(Counter(c["era"] for c in {c["version_hash"]: c for c in usable_charts}.values())),
        "mapper_count": len({c["mapper"] for c in usable_charts}),
        "limitations": ["Source-chart stars do not rate individual phrases or generated maps.",
            "Tags describe note geometry and spacing, not musical quality or player enjoyment.",
            "Entry/exit context is limited to the extraction window; inspect the full source transition.",
            "No human review, listening alignment check or VR playtest is implied.",
            "Rights to redistribute or reuse source note arrays are unknown."],
        "star_tiers": [{k: t[k] for k in ("id", "label", "charts", "windows")} for t in tier_rows],
        "charts": list(charts.values())}
    expansion_path = store.root / "player-expansion-seeds.json"
    if expansion_path.exists():
        seeds = json.loads(expansion_path.read_text(encoding="utf-8"))["seeds"]
        report["expansion_selected_difficulties"] = {}
        for cohort in sorted({s["cohort"] for s in seeds}):
            cohort_seeds = [s for s in seeds if s["cohort"] == cohort]
            exact = [charts[(s["hash"], s["difficulty"])] for s in cohort_seeds if (s["hash"], s["difficulty"]) in available and (s["hash"], s["difficulty"]) in charts]
            report["expansion_selected_difficulties"][cohort] = {"requested": len(cohort_seeds), **rating_summary(exact, min_stars, max_stars)}
        report["expansion_unavailable_selections"] = []
        for seed in seeds:
            if (seed["hash"], seed["difficulty"]) in available:
                continue
            row = store.db.execute("SELECT status,error,json_extract(processing_json,'$.failures'),json_extract(processing_json,'$.excluded_difficulties') FROM maps WHERE version_hash=?", (seed["hash"],)).fetchone()
            report["expansion_unavailable_selections"].append({
                "version_hash": seed["hash"], "difficulty": seed["difficulty"], "song": seed["song"],
                "status": row[0] if row else "not_fetched", "error": row[1] if row else None,
                "parser_failures": json.loads(row[2] or "{}") if row else {},
                "excluded_files": json.loads(row[3] or "{}") if row else {}})
    _atomic_json(store.root / "difficulty-analysis.json", report)
    _atomic_json(store.root / "pattern-list.json", {"schema_version": "1.0", "generated_utc": report["generated_utc"], "patterns": compact})
    _atomic_json(store.root / "player-pattern-shortlist.json", {"target_band": [min_stars, max_stars], "review_status": "unreviewed", "patterns": chosen})
    _atomic_json(store.root / "tier-reference.json", {
        "schema_version": "1.0", "generated_utc": report["generated_utc"], "window_beats": 4,
        "source": "player-profile.json star tiers over exact-version ScoreSaber chart ratings",
        "limitations": ["Chart ratings describe whole source charts, not individual windows or generated maps.",
                        "Window statistics mix quiet and dense passages of each source chart."],
        "tiers": tier_rows})
    _atomic_json(store.root / "tier-pattern-shortlist.json", {
        "schema_version": "1.0", "generated_utc": report["generated_utc"], "review_status": "unreviewed",
        "tiers": {tier_id: rows for tier_id, rows in tier_lists.items()}})
    summary = report["usable_pattern_charts"]
    lines = ["# Player reference corpus analysis", "", f"Generated {report['generated_utc']}", "",
        f"{report['status_counts'].get('processed', 0)} processed versions; {summary['charts']} charts with usable phrase records.",
        f"Rated charts: {summary['rated_charts']}; unknown ratings: {summary['unrated_charts']}.",
        f"Mean: {summary['mean_stars']} stars; median: {summary['median_stars']}; range: {summary['min_stars']}-{summary['max_stars']}.",
        f"Target {min_stars}-{max_stars} stars: {summary['within_target']} charts across {summary['versions_with_target_chart']} versions.",
        f"Patterns: {len(patterns):,}; distinct exact/mirrored motifs: {len(groups):,}.",
        f"Target patterns: {len(target):,}; shortlist: {len(chosen)} references across {len(per_map)} versions.", "",
        "Ratings are chart-weighted, from saved exact-version metadata. Unrated charts are excluded from averages.", "",
        "## Target pattern categories", "", "| Category | Windows |", "|---|---:|"]
    lines += [f"| {tag.replace('_', ' ')} | {count:,} |" for tag, count in sorted(target_tags.items())]
    if "expansion_selected_difficulties" in report:
        lines += ["", "## New exact difficulty selections", "", "| Group | Selected | Usable | Mean stars |", "|---|---:|---:|---:|"]
        for cohort, cohort_report in report["expansion_selected_difficulties"].items():
            lines.append(f"| {cohort.replace('_', ' ')} | {cohort_report['requested']} | {cohort_report['charts']} | {cohort_report['mean_stars']} |")
        lines += ["", "Unavailable selections (full parser/exclusion reasons are in difficulty-analysis.json):", ""]
        for missing in report["expansion_unavailable_selections"]:
            reasons = sorted(set(missing["parser_failures"].values()) | {reason for values in missing["excluded_files"].values() for reason in values})
            lines.append(f"- {missing['song']} / {missing['difficulty']}: {'; '.join(reasons) or missing['error'] or missing['status']}")
    lines += ["", "## Star tiers", "", "Player-relative tiers from player-profile.json; every phrase in pattern-list.json carries its source chart's `star_tier`.", "",
              "| Tier | Stars | Charts | Windows | Median window NPS | Median swings/s | Median peak swings in 1 s |", "|---|---|---:|---:|---:|---:|---:|"]
    for t in tier_rows:
        movement = t["window_movement"]
        lines.append(f"| {t['id']} | {t['label']} | {t['charts']} | {t['windows']:,} | {t['window_nps'].get('median', '-')} | "
                     f"{movement['swing_rate_per_second'].get('median', '-')} | {movement['peak_one_second_swing_count'].get('median', '-')} |")
    lines += ["", "Per-tier shortlists are in tier-pattern-shortlist.json; full per-tier statistics in tier-reference.json."]
    lines += ["", "Categories overlap. A source chart's rating is not a local phrase rating.", "", "## Reference shortlist", "",
              "All entries are unreviewed structural candidates. Exact hashes, context, metrics and caveats are in player-pattern-shortlist.json.", "",
              "| Song / mapper | Difficulty | Stars | Beats | Category |", "|---|---|---:|---|---|"]
    for p in chosen:
        c = p["chart"]
        title = f"{c['song']} / {c['mapper']}".replace('|', '/').replace('\n', ' ')
        lines.append(f"| [{title}]({c['source_url']}) | {p['difficulty']} | {c['stars']} | {p['start_beat']:g}-{p['end_beat']:g} | {p['selection_category'].replace('_', ' ')} |")
    lines += ["", "## Limitations", ""] + [f"- {s}" for s in report["limitations"]]
    (store.root / "player-analysis.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return {k: v for k, v in report.items() if k != "charts"}
