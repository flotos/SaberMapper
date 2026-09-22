"""Reproducible historical score calibration; never infer taste from scores."""

from __future__ import annotations

from datetime import datetime
import statistics


def summarize_scores(snapshot: dict) -> dict:
    selected = []
    for score in snapshot.get("scores", []):
        if not (score.get("ranked") and score.get("stars", 0) > 0
                and score.get("mode") == "SoloStandard" and not score.get("modifiers")):
            continue
        denominator = score.get("maxScore") or 0
        if denominator <= 0:
            continue
        selected.append({"date": score["timeSet"], "stars": float(score["stars"]),
                         "accuracy": 100 * score["baseScore"] / denominator,
                         "score_id": score["scoreId"]})
    recent = [x for x in selected if x["date"][:10] >= "2024-01-01"]
    def stats(items):
        return {"count": len(items), "mean_stars": round(statistics.mean(x["stars"] for x in items), 4) if items else None,
                "median_stars": statistics.median(x["stars"] for x in items) if items else None,
                "mean_accuracy_percent": round(statistics.mean(x["accuracy"] for x in items), 4) if items else None,
                "min_date": min((x["date"] for x in items), default=None),
                "max_date": max((x["date"] for x in items), default=None)}
    return {"schema_version": "1.0", "snapshot_retrieved_utc": snapshot.get("retrievedAtUtc"),
            "player_id": snapshot.get("player", {}).get("id"), "ranked_standard_unmodified": stats(selected),
            "since_2024": stats(recent), "interpretation": "historical skill context only; preferences require explicit feedback"}


def player_profile(*, player_id: str, score_summary: dict, liked: list[dict] | None = None,
                   disliked: list[dict] | None = None, overrides: dict | None = None) -> dict:
    return {"schema_version": "1.0", "player_id": player_id, "score_evidence": score_summary,
            "liked": liked or [], "disliked": disliked or [], "overrides": overrides or {},
            "uncertainty": "Historical scores do not establish current skill, movement preference, or map quality."}
