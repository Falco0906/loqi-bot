"""Structured output contract from Reasoning to Mission Control narrative."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BriefingContext:
    """Pre-ranked workspace facts that Mission Control may phrase for a user."""

    greeting: str = ""
    workspace_state: dict[str, Any] = field(default_factory=dict)
    workspace_delta: dict[str, Any] = field(default_factory=dict)
    priorities: list[dict] = field(default_factory=list)
    attention_items: list[dict] = field(default_factory=list)
    health_summary: dict[str, Any] = field(default_factory=dict)
    current_focus: dict[str, Any] = field(default_factory=dict)
    recommended_next_action: dict[str, Any] = field(default_factory=dict)
    cross_campaign_insights: list[dict] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    campaigns: list[dict] = field(default_factory=list)
    drafts: dict[str, Any] = field(default_factory=dict)
    jobs: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)

    def is_first_visit(self) -> bool:
        return self.workspace_delta.get("first_visit", True)

    def has_delta(self) -> bool:
        return self.workspace_delta.get("has_delta", False) and not self.is_first_visit()
