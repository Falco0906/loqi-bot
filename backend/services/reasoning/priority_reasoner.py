"""PriorityReasoner — ranks campaigns by importance.

Input: CampaignSignals list, jobs list, memory dict
Output: sorted CampaignPriority list + CurrentFocus

Deterministic. No LLM. Single responsibility: what deserves attention first.

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
"""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals
from services.reasoning._shared import campaign_status_score


@dataclass
class CampaignPriority:
    campaign_id: str
    name: str
    status: str
    score: float
    rank: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "status": self.status,
            "score": self.score,
            "rank": self.rank,
            "reasons": self.reasons[:2],
            "label": self._label(),
        }

    def _label(self) -> str:
        if self.rank == 1:
            return "Highest priority"
        if self.rank == 2:
            return "Second priority"
        if self.rank == 3:
            return "Third priority"
        return f"Priority {self.rank}"


@dataclass
class CurrentFocus:
    focus: str
    campaign_id: str | None = None
    campaign_name: str | None = None
    action_type: str = "idle"

    def to_dict(self) -> dict:
        return {
            "focus": self.focus,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "action_type": self.action_type,
        }


class PriorityReasoner:
    """Ranks campaigns by urgency/importance and determines current focus."""

    def rank_campaigns(self, campaign_signals: list[CampaignSignals]) -> list[CampaignPriority]:
        scored = []
        for cs in campaign_signals:
            reasons: list[str] = []
            score = campaign_status_score(cs.pipeline_stage)
            status = cs.pipeline_stage

            if status == "ready_to_send":
                reasons.append("All drafts approved — ready to launch")
                score += 20
            elif status == "draft_review":
                pd = cs.pending_reviews
                score += min(pd * 5, 25)
                if pd > 0:
                    reasons.append(f"{pd} draft{'s' if pd > 1 else ''} pending review")
            elif status == "planning":
                score += 5

            if cs.approved_drafts > 0:
                score += min(cs.approved_drafts * 3, 15)
                reasons.append(f"{cs.approved_drafts} draft{'s' if cs.approved_drafts > 1 else ''} approved")

            if cs.lead_count > 0:
                score += min(cs.lead_count * 0.5, 10)

            if cs.recent_activity == "within_hour":
                score += 15
                reasons.append("Recently updated")
            elif cs.recent_activity == "today":
                score += 8
            elif cs.stalled_days > 7 and status not in ("completed", "archived"):
                score -= 15
                reasons.append("No activity for over a week")

            if status in ("completed", "archived"):
                score = max(score, 5)

            scored.append(CampaignPriority(
                campaign_id=cs.id,
                name=cs.name,
                status=status,
                score=round(score, 1),
                rank=0,
                reasons=reasons[:3],
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        for i, cp in enumerate(scored):
            cp.rank = i + 1
        return scored

    def determine_focus(
        self,
        campaigns: list[dict],
        memory: dict,
        jobs: dict,
    ) -> CurrentFocus:
        last_action = memory.get("last_action") or ""
        last_campaign_id = memory.get("last_campaign_id")
        last_campaign_name = memory.get("last_campaign_name")
        running_jobs = jobs.get("running", [])
        searches = [j for j in running_jobs if j.get("type") == "search"]

        if searches:
            return CurrentFocus(
                focus="Searching for leads",
                campaign_id=None,
                campaign_name=None,
                action_type="searching",
            )

        if "launch" in last_action:
            return CurrentFocus(
                focus=f"Launched {last_campaign_name or 'a campaign'}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="launching",
            )

        if "review_draft" in last_action:
            return CurrentFocus(
                focus=f"Reviewing draft for {memory.get('last_draft_name', 'a lead')}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="reviewing",
            )

        if "open_campaign" in last_action and last_campaign_name:
            return CurrentFocus(
                focus=f"Reviewing {last_campaign_name}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="reviewing",
            )

        if "search" in last_action:
            return CurrentFocus(
                focus=f"Searching for {memory.get('last_search', 'leads')}",
                campaign_id=None,
                campaign_name=None,
                action_type="searching",
            )

        if campaigns:
            top = campaigns[0]
            return CurrentFocus(
                focus=f"Campaign overview: {top.get('name', 'No name')}",
                campaign_id=top.get("id"),
                campaign_name=top.get("name"),
                action_type="idle",
            )

        return CurrentFocus(
            focus="Getting started",
            campaign_id=None,
            campaign_name=None,
            action_type="idle",
        )
