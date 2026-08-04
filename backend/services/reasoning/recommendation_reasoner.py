"""RecommendationReasoner — picks the single next action and determines workflow continuation.

Input: attention_items, priorities, current_focus, CampaignSignals
Output: RecommendedAction + WorkflowContinuation

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
Deterministic. No LLM."""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals
from services.reasoning._shared import priority_label
from services.reasoning.priority_reasoner import CampaignPriority, CurrentFocus
from services.reasoning.attention_reasoner import AttentionItem


@dataclass
class RecommendedAction:
    title: str
    reason: str
    confidence: int
    priority: str
    link: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "reason": self.reason,
            "confidence": self._confidence_label(),
            "priority": self.priority,
            "link": self.link,
        }

    def _confidence_label(self) -> str:
        if self.confidence >= 85:
            return "high"
        if self.confidence >= 60:
            return "medium"
        return "low"


@dataclass
class WorkflowContinuation:
    should_resume: bool
    where: str
    campaign_id: str | None = None
    campaign_name: str | None = None
    action: str = ""
    link: str = ""

    def to_dict(self) -> dict:
        return {
            "should_resume": self.should_resume,
            "where": self.where,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "action": self.action,
            "link": self.link,
        }


class RecommendationReasoner:
    """Determines the single most important next action and workflow continuation."""

    def pick_next_action(
        self,
        attention_items: list[AttentionItem],
        priorities: list[CampaignPriority],
        campaign_signals: list[CampaignSignals],
        research_available: bool = False,
        research_in_progress: bool = False,
    ) -> RecommendedAction:
        if attention_items:
            top = attention_items[0]
            return RecommendedAction(
                title=top.title,
                reason=top.reason,
                confidence=top.confidence,
                priority=priority_label(top.importance),
                link=top.link,
            )

        if priorities:
            top_cp = priorities[0]
            cs = next((x for x in campaign_signals if x.id == top_cp.campaign_id), None)
            if cs and cs.pipeline_stage == "planning" and cs.lead_count > 0:
                return RecommendedAction(
                    title=f"Continue planning {top_cp.name}",
                    reason="Planning stage has leads ready to be structured into outreach.",
                    confidence=65,
                    priority="medium",
                    link=f"/campaigns/{top_cp.campaign_id}",
                )
            if cs and cs.pipeline_stage == "planning":
                return RecommendedAction(
                    title="Find leads for a new campaign",
                    reason="No campaigns have leads yet. Starting with lead discovery builds pipeline momentum.",
                    confidence=70,
                    priority="medium",
                    link="/discovery",
                )

        if research_in_progress:
            return RecommendedAction(
                title="Researching your ideal prospects",
                reason="Loqi is using your onboarding context to find and qualify the right leads.",
                confidence=95,
                priority="high",
                link="/discovery",
            )

        if research_available:
            return RecommendedAction(
                title="Review your researched leads",
                reason="Your first prospect research is ready. Review the matches before creating a campaign.",
                confidence=95,
                priority="high",
                link="/discovery",
            )

        return RecommendedAction(
            title="Research your ideal prospects",
            reason="Loqi needs to find the right leads from your onboarding context before a campaign can be created.",
            confidence=90,
            priority="high",
            link="/discovery",
        )

    def workflow_continuation(
        self,
        focus: CurrentFocus,
        priorities: list[CampaignPriority],
        campaign_signals: list[CampaignSignals],
    ) -> WorkflowContinuation:
        if focus.action_type in ("reviewing", "searching", "launching", "editing"):
            if focus.campaign_id:
                cs = next((x for x in campaign_signals if x.id == focus.campaign_id), None)
                if cs and cs.pipeline_stage not in ("completed", "archived"):
                    return WorkflowContinuation(
                        should_resume=True,
                        where=f"Continue in {focus.campaign_name or 'your campaign'}",
                        campaign_id=focus.campaign_id,
                        campaign_name=focus.campaign_name,
                        action=focus.focus,
                        link=f"/campaigns/{focus.campaign_id}",
                    )

        if priorities:
            top = priorities[0]
            cs = next((x for x in campaign_signals if x.id == top.campaign_id), None)
            if cs and cs.launch_ready:
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Launch {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Launch campaign",
                    link=f"/campaigns/{top.campaign_id}",
                )
            if cs and cs.pipeline_stage == "draft_review" and cs.pending_reviews > 0:
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Review {cs.pending_reviews} draft{'s' if cs.pending_reviews > 1 else ''} in {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Review drafts",
                    link="/draft",
                )
            if cs:
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Continue working on {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Continue planning",
                    link=f"/campaigns/{top.campaign_id}",
                )

        return WorkflowContinuation(
            should_resume=False,
            where="Start a new campaign",
            campaign_id=None,
            campaign_name=None,
            action="Find leads",
            link="/discovery",
        )
