"""CampaignSignals — deterministic extraction of per-campaign facts.

Extracts signals from raw campaign dicts.
No LLM. Pure rules. Single responsibility: describe reality.
"""

from dataclasses import dataclass, field
from typing import Any

from services.reasoning._shared import hours_since


@dataclass
class CampaignSignals:
    id: str
    name: str
    pipeline_stage: str
    pending_reviews: int
    approved_drafts: int
    lead_count: int
    stalled_days: float
    recent_activity: str
    launch_ready: bool
    lead_quality_score: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pipeline_stage": self.pipeline_stage,
            "pending_reviews": self.pending_reviews,
            "approved_drafts": self.approved_drafts,
            "lead_count": self.lead_count,
            "stalled_days": self.stalled_days,
            "recent_activity": self.recent_activity,
            "launch_ready": self.launch_ready,
            "lead_quality_score": self.lead_quality_score,
        }


class CampaignSignalsExtractor:
    """Extracts CampaignSignals from raw campaign dicts."""

    def extract(self, campaign: dict) -> CampaignSignals:
        status = campaign.get("status", "planning")
        pending = campaign.get("pending_drafts", 0) or 0
        approved = campaign.get("approved_drafts", 0) or 0
        lead_count = campaign.get("lead_count", 0) or 0
        hs = hours_since(campaign.get("updated_at", ""))

        stalled_days = round(hs / 24, 1) if hs != float("inf") else 0.0

        if hs < 1:
            recent = "within_hour"
        elif hs < 24:
            recent = "today"
        elif hs < 72:
            recent = "this_week"
        else:
            recent = "stalled"

        launch_ready = status in ("ready", "ready_to_send")

        lead_quality_score = min((lead_count / 100) * 0.5 + (approved / max(lead_count, 1)) * 0.5, 1.0)

        return CampaignSignals(
            id=campaign.get("id", ""),
            name=campaign.get("name", ""),
            pipeline_stage=status,
            pending_reviews=pending,
            approved_drafts=approved,
            lead_count=lead_count,
            stalled_days=stalled_days,
            recent_activity=recent,
            launch_ready=launch_ready,
            lead_quality_score=round(lead_quality_score, 2),
        )

    def extract_all(self, campaigns: list[dict]) -> list[CampaignSignals]:
        return [self.extract(c) for c in campaigns]
