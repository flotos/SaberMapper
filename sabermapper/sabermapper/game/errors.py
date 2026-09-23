"""Typed game errors with stable codes; the CLI prints `to_dict()` as JSON and exits 2."""
from __future__ import annotations

# Stable codes. Other game modules add their own; keep existing meanings unchanged.
CODES = {
    "game_busy": "Another holder (agent or human) has the game, or Beat Saber runs without a lease.",
    "game_preempted": "The user took the game over (studio Play in game). Retry later; this is not a map defect.",
    "lease_not_held": "This session does not hold the game lease.",
    "lease_invalid": "The lease file is unreadable or malformed.",
    "game_not_found": "The Beat Saber install or its log could not be found.",
    "game_not_running": "Beat Saber is not running.",
    "bridge_unreachable": "The SaberMapper Bridge mod did not answer on localhost.",
    "timeout": "The operation did not finish before its deadline.",
}


class GameError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None, fix: str | None = None):
        super().__init__(message)
        self.code, self.message, self.details, self.fix = code, message, dict(details or {}), fix

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details, "fix": self.fix}}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
