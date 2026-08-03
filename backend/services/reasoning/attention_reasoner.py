"""AttentionReasoner — determines what needs the user's attention.

Input: CampaignSignals, jobs, priorities (from PriorityReasoner)
Output: sorted AttentionItem list

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
Deterministic. No LLM."""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals
from services.reasoning._shared import time_waiting_label, priority_label
from services.reasoning.priority_reasoner import CampaignPriority


@dataclass
class AttentionItem:
    campaign_id: str | None
    campaign_name: str | None
    title: str
    reason: str
    importance: int
    urgency: int
    blocking_impact: int
    time_waiting: str
    confidence: int
    action: str
    link: str

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "title": self.title,
            "reason": self.reason,
            "importance": self.importance,
            "urgency": self.urgency,
            "blocking_impact": self.blocking_impact,
            "time_waiting": self.time_waiting,
            "confidence": self.confidence,
            "action": self.action,
            "link": self.link,
        }


class AttentionReasoner:
    """Identifies items needing user attention, prioritised by impact."""

    def compute(
        self,
        campaign_signals: list[CampaignSignals],
        jobs: dict,
        priorities: list[CampaignPriority],
    ) -> list[AttentionItem]:
        items: list[AttentionItem] = []

        for cp in priorities:
            cs = next((x for x in campaign_signals if x.id == cp.campaign_id), None)
            if not cs:
                continue
            status = cs.pipeline_stage
            pd = cs.pending_reviews

            if status == "ready_to_send":
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{cp.name} is ready to launch",
                    reason="All drafts have been approved. Launching now gets your outreach in front of leads.",
                    importance=9,
                    urgency=7,
                    blocking_impact=8,
                    time_waiting=time_waiting_label(cs.stalled_days * 24),
                    confidence=95,
                    action="Launch Campaign",
                    link=f"/campaigns/{cp.campaign_id}",
                ))
            elif status == "draft_review" and pd > 0:
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{pd} draft{'s' if pd > 1 else ''} pending in {cp.name}",
                    reason="Pending drafts cannot be sent until reviewed. Each day of delay reduces reply probability.",
                    importance=8,
                    urgency=6,
                    blocking_impact=7,
                    time_waiting=time_waiting_label(cs.stalled_days * 24),
                    confidence=90,
                    action="Review Drafts",
                    link="/draft",
                ))
            elif status == "planning" and cs.lead_count > 0 and cs.stalled_days > 2:
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{cp.name} has been in planning for over 2 days",
                    reason="Leads are waiting. Finalizing the strategy now enables overnight draft generation.",
                    importance=6,
                    urgency=5,
                    blocking_impact=5,
                    time_waiting=time_waiting_label(cs.stalled_days * 24),
                    confidence=75,
                    action="Continue Planning",
                    link=f"/campaigns/{cp.campaign_id}",
                ))

        running_jobs = jobs.get("running", [])
        for j in running_jobs:
            jtype = j.get("type", "job")
            if j.get("status") == "queued":
                items.append(AttentionItem(
                    campaign_id=None,
                    campaign_name=None,
                    title=f"{jtype.replace('_', ' ').title()} is queued",
                    reason="A queued job will start processing when resources are available.",
                    importance=4,
                    urgency=3,
                    blocking_impact=2,
                    time_waiting="Just queued",
                    confidence=80,
                    action="View Jobs",
                    link="/discovery",
                ))

        items.sort(key=lambda x: (x.importance + x.urgency + x.blocking_impact), reverse=True)
        return items[:8]
