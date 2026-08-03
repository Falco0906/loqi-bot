"""Shared utilities for deterministic reasoners.

All reasoners import from here to avoid duplicating helper logic.
"""

from datetime import datetime, timezone
from typing import Any


def hours_since(iso_str: str) -> float:
    if not iso_str:
        return float("inf")
    try:
        d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).total_seconds() / 3600
    except (ValueError, TypeError):
        return float("inf")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def time_waiting_label(hours: float) -> str:
    if hours == float("inf"):
        return "Unknown"
    if hours < 1:
        return "Less than an hour"
    if hours < 24:
        return f"{int(hours)} hour{'s' if int(hours) > 1 else ''}"
    days = int(hours / 24)
    return f"{days} day{'s' if days > 1 else ''}"


def priority_label(importance: int) -> str:
    if importance >= 8:
        return "critical"
    if importance >= 6:
        return "high"
    if importance >= 4:
        return "medium"
    return "low"


def confidence_label(score: int | float) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def campaign_status_score(status: str) -> float:
    _scores: dict[str, float] = {
        "ready_to_send": 100,
        "draft_review": 75,
        "ready": 60,
        "generating": 50,
        "planning": 30,
        "completed": 10,
        "archived": 0,
    }
    return _scores.get(status, 10)
