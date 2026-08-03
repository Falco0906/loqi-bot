"""RiskReasoner — identifies risks from workspace state and delta.

Risks include: stalled campaigns, blocked workflows,
draft backlogs, unopened conversations, long-idle leads.

Input: CampaignSignals, WorkspaceSignals, delta, health
Output: risk list

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
Deterministic. No LLM."""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals
from services.intelligence.workspace_signals import WorkspaceSignals
from services.reasoning.health_reasoner import WorkspaceHealth


@dataclass
class Risk:
    category: str
    severity: str  # "high" | "medium" | "low"
    title: str
    detail: str
    campaign_id: str | None = None
    campaign_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
        }


class RiskReasoner:
    """Detects risks that could slow or block pipeline progress."""

    def compute(
        self,
        campaign_signals: list[CampaignSignals],
        workspace_signals: WorkspaceSignals | None = None,
        delta: dict | None = None,
        drafts_backlog: int = 0,
        health: WorkspaceHealth | None = None,
    ) -> list[Risk]:
        delta = delta or {}
        risks: list[Risk] = []

        # ── From health (blocked workflows, idle campaigns) ──
        if health:
            for wf in health.blocked_workflows:
                risks.append(Risk(
                    category="blocked_workflow",
                    severity="high",
                    title=wf,
                    detail="Campaigns cannot progress until this is resolved.",
                ))

            for cname in health.idle_campaigns:
                cs = next((cs for cs in campaign_signals if cs.name == cname), None)
                risks.append(Risk(
                    category="idle_campaign",
                    severity="medium" if health.overall_health == "healthy" else "high",
                    title=f"{cname} has been idle",
                    detail="No activity for over 3 days. Progress is stalling.",
                    campaign_id=cs.id if cs else None,
                    campaign_name=cname,
                ))

        # ── From delta: sent outreach with no response ──
        if delta.get("sent_outreach", 0) > 0 and not delta.get("new_conversations", 0):
            risks.append(Risk(
                category="no_response",
                severity="low",
                title="Outreach sent but no replies yet",
                detail=f"{delta['sent_outreach']} message{'s' if delta['sent_outreach'] > 1 else ''} sent since last visit with no response yet. This is normal — replies take time.",
            ))

        # ── Draft backlog ──
        if drafts_backlog > 5:
            risks.append(Risk(
                category="draft_backlog",
                severity="medium",
                title=f"{drafts_backlog} drafts pending review",
                detail="A growing draft backlog slows the entire pipeline. Each day of delay reduces reply probability.",
            ))

        # ── Campaigns in planning with leads for too long ──
        for cs in campaign_signals:
            if cs.pipeline_stage == "planning" and cs.lead_count > 0 and cs.stalled_days > 3:
                risks.append(Risk(
                    category="stalled_planning",
                    severity="medium",
                    title=f"{cs.name} has been in planning for {int(cs.stalled_days)} days",
                    detail="Leads are available but no strategy has been set. Drafts cannot generate until this stage completes.",
                    campaign_id=cs.id,
                    campaign_name=cs.name,
                ))

        return risks
