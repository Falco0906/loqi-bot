"""LeadSignals — deterministic extraction of per-campaign lead quality signals.

Extracts signals from campaign lead data and delta.
Signals are campaign-level aggregates.

No LLM. Pure rules.
"""

from dataclasses import dataclass, field
from typing import Any

from services.reasoning._shared import hours_since


@dataclass
class LeadSignals:
    icp_match: float
    enrichment_completeness: float
    confidence: float
    source: str
    freshness: float
    engagement: float

    def to_dict(self) -> dict:
        return {
            "icp_match": self.icp_match,
            "enrichment_completeness": self.enrichment_completeness,
            "confidence": self.confidence,
            "source": self.source,
            "freshness": self.freshness,
            "engagement": self.engagement,
        }


class LeadSignalsExtractor:
    """Extracts lead quality signals from campaign data.

    Today limited by available lead-level data.
    As enrichment improves, these signals become richer.
    """

    def extract(
        self,
        campaign: dict,
        delta: dict | None = None,
    ) -> LeadSignals:
        delta = delta or {}
        lead_count = campaign.get("lead_count", 0) or 0
        approved = campaign.get("approved_drafts", 0) or 0
        hs = hours_since(campaign.get("updated_at", ""))

        icp_match = 0.5
        if lead_count > 0:
            icp_match = min(0.5 + (approved / max(lead_count, 1)) * 0.3, 0.8)

        completeness = 0.3
        if lead_count > 0:
            completeness = min(0.3 + (approved / max(lead_count, 1)) * 0.4, 0.9)

        confidence = round((icp_match + completeness) / 2, 2)

        source = "search"
        if delta.get("new_providers", 0) > 0:
            source = "multi"

        freshness = round(hs / 24, 1) if hs != float("inf") else 0.0

        engagement = 0.0
        if delta.get("new_conversations", 0) > 0:
            engagement = min(delta["new_conversations"] * 0.2, 0.9)

        return LeadSignals(
            icp_match=round(icp_match, 2),
            enrichment_completeness=round(completeness, 2),
            confidence=confidence,
            source=source,
            freshness=freshness,
            engagement=round(engagement, 2),
        )

    def extract_all(
        self,
        campaigns: list[dict],
        delta: dict | None = None,
    ) -> list[LeadSignals]:
        return [self.extract(c, delta) for c in campaigns]
