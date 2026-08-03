"""OpportunityReasoner — identifies opportunities from workspace state and delta.

Opportunities include: new leads to contact, campaigns ready to launch,
new provider connections enabling new channels, completed research tasks.

Input: CampaignSignals, delta
Output: opportunity list

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
Deterministic. No LLM."""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals


@dataclass
class Opportunity:
    category: str
    priority: str  # "high" | "medium" | "low"
    title: str
    detail: str
    campaign_id: str | None = None
    campaign_name: str | None = None
    link: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "priority": self.priority,
            "title": self.title,
            "detail": self.detail,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "link": self.link,
        }


class OpportunityReasoner:
    """Identifies actionable opportunities from state and delta."""

    def compute(
        self,
        campaign_signals: list[CampaignSignals],
        delta: dict,
        campaigns_ready: int = 0,
    ) -> list[Opportunity]:
        opportunities: list[Opportunity] = []

        # ── Campaigns ready to launch ──
        for cs in campaign_signals:
            if cs.launch_ready:
                opportunities.append(Opportunity(
                    category="launch_ready",
                    priority="high",
                    title=f"{cs.name} is ready to launch",
                    detail="All drafts approved and campaign is ready to go live.",
                    campaign_id=cs.id,
                    campaign_name=cs.name,
                    link=f"/campaigns/{cs.id}",
                ))

        # ── New leads from delta ──
        if delta.get("new_leads", 0) > 0:
            nl = delta["new_leads"]
            opportunities.append(Opportunity(
                category="new_leads",
                priority="medium",
                title=f"{nl} new lead{'s' if nl > 1 else ''} discovered",
                detail=f"I found {nl} new prospect{'s' if nl > 1 else ''} matching your criteria since your last visit.",
                link="/discovery",
            ))

        # ── Completed research ──
        if delta.get("completed_jobs", 0) > 0:
            cj = delta["completed_jobs"]
            opportunities.append(Opportunity(
                category="research_complete",
                priority="medium",
                title=f"{cj} research task{'s' if cj > 1 else ''} completed",
                detail="Background research finished. New prospects may be ready for review.",
                link="/discovery",
            ))

        # ── Provider connections ──
        if delta.get("new_providers", 0) > 0:
            np_count = delta["new_providers"]
            opportunities.append(Opportunity(
                category="new_provider",
                priority="low",
                title=f"{np_count} new provider connection{'s' if np_count > 1 else ''}",
                detail="New communication channels are now available for outreach.",
                link="/settings",
            ))

        return opportunities
