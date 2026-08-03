"""HealthReasoner — computes workspace health and cross-campaign insights.

Input: CampaignSignals, WorkspaceSignals
Output: WorkspaceHealth + CrossCampaignInsight list

Consumes signals from the Intelligence Layer — never reads raw campaign dicts.
Deterministic. No LLM."""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals
from services.intelligence.workspace_signals import WorkspaceSignals


@dataclass
class WorkspaceHealth:
    overall_health: str
    pipeline_velocity: str
    blocked_workflows: list[str] = field(default_factory=list)
    idle_campaigns: list[str] = field(default_factory=list)
    campaigns_ready: int = 0
    campaigns_waiting: int = 0
    draft_backlog: int = 0
    searches_in_progress: int = 0

    def to_dict(self) -> dict:
        return {
            "overall_health": self.overall_health,
            "pipeline_velocity": self.pipeline_velocity,
            "blocked_workflows": self.blocked_workflows,
            "idle_campaigns": self.idle_campaigns,
            "campaigns_ready": self.campaigns_ready,
            "campaigns_waiting": self.campaigns_waiting,
            "draft_backlog": self.draft_backlog,
            "searches_in_progress": self.searches_in_progress,
        }


@dataclass
class CrossCampaignInsight:
    insight: str
    insight_type: str
    campaigns_involved: list[str] = field(default_factory=list)
    importance: str = "medium"

    def to_dict(self) -> dict:
        return {
            "insight": self.insight,
            "insight_type": self.insight_type,
            "campaigns_involved": self.campaigns_involved,
        }


class HealthReasoner:
    """Assesses overall workspace health and detects cross-campaign patterns."""

    def compute_health(
        self,
        campaign_signals: list[CampaignSignals],
        workspace_signals: WorkspaceSignals | None = None,
        drafts_backlog: int = 0,
    ) -> WorkspaceHealth:
        total = len(campaign_signals)
        if total == 0:
            return WorkspaceHealth(
                overall_health="empty",
                pipeline_velocity="no_pipeline",
                campaigns_ready=0,
                campaigns_waiting=0,
                draft_backlog=0,
                searches_in_progress=0,
            )

        ready = sum(1 for cs in campaign_signals if cs.launch_ready)
        draft_review = sum(1 for cs in campaign_signals if cs.pipeline_stage == "draft_review")
        planning = sum(1 for cs in campaign_signals if cs.pipeline_stage == "planning")
        archived = sum(1 for cs in campaign_signals if cs.pipeline_stage == "archived")
        backlog = drafts_backlog

        idle = [
            cs.name for cs in campaign_signals
            if cs.pipeline_stage not in ("completed", "archived")
            and cs.recent_activity == "stalled"
        ]

        blocked: list[str] = []
        if workspace_signals:
            blocked = list(workspace_signals.bottlenecks)
        elif planning > 0 and sum(
            cs.lead_count for cs in campaign_signals if cs.pipeline_stage == "planning"
        ) == 0:
            blocked.append("Planning campaigns need leads")

        active_ratio = (ready + draft_review) / max(total - archived, 1)
        if active_ratio > 0.5:
            velocity = "strong"
            overall = "healthy"
        elif active_ratio > 0.2:
            velocity = "moderate"
            overall = "moderate"
        else:
            velocity = "slow"
            overall = "at_risk" if planning > 0 and backlog == 0 else "moderate"

        return WorkspaceHealth(
            overall_health=overall,
            pipeline_velocity=velocity,
            blocked_workflows=blocked,
            idle_campaigns=idle[:5],
            campaigns_ready=ready,
            campaigns_waiting=draft_review + planning,
            draft_backlog=backlog,
            searches_in_progress=0,
        )

    def compute_insights(self, campaign_signals: list[CampaignSignals]) -> list[CrossCampaignInsight]:
        insights: list[CrossCampaignInsight] = []
        active = [cs for cs in campaign_signals if cs.pipeline_stage not in ("completed", "archived")]

        if len(active) >= 2:
            ready = [cs for cs in active if cs.launch_ready]
            review = [
                cs for cs in active
                if cs.pipeline_stage == "draft_review" and cs.pending_reviews > 0
            ]

            if len(ready) >= 2:
                names = [cs.name for cs in ready[:2]]
                insights.append(CrossCampaignInsight(
                    insight=f"Multiple campaigns ready to launch: {' and '.join(names)}",
                    insight_type="ready",
                    campaigns_involved=[cs.id for cs in ready[:2]],
                    importance="high",
                ))

            if len(review) >= 2:
                total_pending = sum(cs.pending_reviews for cs in review)
                insights.append(CrossCampaignInsight(
                    insight=f"{total_pending} drafts across {len(review)} campaigns need review",
                    insight_type="review_backlog",
                    campaigns_involved=[cs.id for cs in review[:3]],
                    importance="high",
                ))

            if len(review) == 1 and len(ready) == 0:
                review_name = review[0].name
                for cs in active:
                    if cs.pipeline_stage == "planning" and cs.id != review[0].id:
                        insights.append(CrossCampaignInsight(
                            insight=f"{review_name} needs review while {cs.name} is waiting in planning",
                            insight_type="pipeline_gap",
                            campaigns_involved=[review[0].id, cs.id],
                            importance="medium",
                        ))
                        break

        idle = [cs for cs in active if cs.recent_activity == "stalled"]
        if idle:
            names = [cs.name for cs in idle[:2]]
            insights.append(CrossCampaignInsight(
                insight=f"{' and '.join(names)} ha{'s' if len(idle) == 1 else 've'} had no activity for over 3 days",
                insight_type="idle",
                campaigns_involved=[cs.id for cs in idle[:2]],
                importance="medium",
            ))

        return insights
