"""Player-relative ScoreSaber star tiers for reference phrases and difficulty targets.

Tiers come from the player's own score evidence (PLAYER.md, player-profile.json).
They tag every corpus chart, and so every phrase extracted from it, and they name
the level a project difficulty aims for (``difficulty.target_tier``). A source
chart's stars never rate one phrase, and a tier is never a predicted star rating
for a generated map.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

TIER_IDS = ("below_band", "band", "challenge", "stretch", "beyond")
DEFAULT_CEILING = 9.5


def default_tiers(ceiling: float = DEFAULT_CEILING) -> list[dict]:
    """Half-open [min_stars, max_stars) bands; None means unbounded."""
    return [
        {"id": "below_band", "min_stars": None, "max_stars": 6.5,
         "role": "Warm-up, recovery and easier contrast; below the player's provisional band."},
        {"id": "band", "min_stars": 6.5, "max_stars": 8.0,
         "role": "Provisional comfort band from PLAYER.md; the default sustained intensity."},
        {"id": "challenge", "min_stars": 8.0, "max_stars": 9.0,
         "role": "Harder than the band, where the player has many recorded passes; a whole-map target only "
                 "when the user asks for a harder difficulty."},
        {"id": "stretch", "min_stars": 9.0, "max_stars": ceiling,
         "role": "Up to the player's hardest recorded unmodified pass; peaks, not a sustained target, unless asked."},
        {"id": "beyond", "min_stars": ceiling, "max_stars": None,
         "role": "Above every recorded pass; study only, never a target without an explicit request."},
    ]


def _ceiling(profile: dict | None) -> float:
    evidence = ((profile or {}).get("score_evidence") or {}).get("ranked_standard_unmodified") or {}
    hardest = evidence.get("max_stars")
    if isinstance(hardest, (int, float)) and not isinstance(hardest, bool) and math.isfinite(hardest) and hardest > 9:
        return math.ceil(hardest * 2) / 2
    return DEFAULT_CEILING


def player_tiers(profile: dict | None) -> list[dict]:
    """The player's tiers: an explicit ``overrides.star_tiers.tiers`` list, else defaults capped by evidence."""
    override = (((profile or {}).get("overrides") or {}).get("star_tiers") or {}).get("tiers")
    if override is None:
        return default_tiers(_ceiling(profile))
    if not isinstance(override, list) or [t.get("id") for t in override if isinstance(t, dict)] != list(TIER_IDS):
        raise ValueError(f"overrides.star_tiers.tiers must list the tiers {', '.join(TIER_IDS)} in order")
    for left, right in zip(override, override[1:]):
        if left.get("max_stars") != right.get("min_stars"):
            raise ValueError("overrides.star_tiers.tiers must be contiguous: each max_stars equals the next min_stars")
    return override


def load_profile(workspace: str | Path) -> dict | None:
    path = Path(workspace) / "player-profile.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tier_for(stars, tiers: list[dict]) -> str | None:
    """The tier holding a positive star rating; None when the chart is unrated."""
    if isinstance(stars, bool) or not isinstance(stars, (int, float)) or not math.isfinite(stars) or stars <= 0:
        return None
    for tier in tiers:
        if (tier["min_stars"] is None or stars >= tier["min_stars"]) and (tier["max_stars"] is None or stars < tier["max_stars"]):
            return tier["id"]
    return None


def tier_by_id(tiers: list[dict], tier_id: str) -> dict:
    for tier in tiers:
        if tier["id"] == tier_id:
            return tier
    raise ValueError(f"Unknown star tier {tier_id!r}; use one of {', '.join(TIER_IDS)}")


def tier_label(tier: dict) -> str:
    low, high = tier["min_stars"], tier["max_stars"]
    if low is None:
        return f"below {high:g} stars"
    if high is None:
        return f"{low:g}+ stars"
    return f"{low:g}-{high:g} stars"
