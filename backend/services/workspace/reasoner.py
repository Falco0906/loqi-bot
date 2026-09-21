"""WorkspaceReasoner — thin adapter over the modular reasoning pipeline.

Keeps backward-compatible public API (WorkspaceAnalysis dataclass, .to_dict())
while delegating all business logic to the reasoning/* subpackage.

Legacy dataclass types are re-exported for any external importers.
"""

from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import Any, Optional

from services.reasoning.coordinator import ReasoningCoordinator


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


@dataclass
class AttentionItem:
    campaign_id: Optional[str]
    campaign_name: Optional[str]
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
            "time_waiting": self.time_waiting,
            "action": self.action,
            "link": self.link,
        }


@dataclass
class WorkflowContinuation:
    should_resume: bool
    where: str
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    action: str
    link: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CurrentFocus:
    focus: str
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    action_type: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkspaceAnalysis:
    current_focus: CurrentFocus
    recommended_next_action: RecommendedAction
    campaign_priorities: list[CampaignPriority]
    workspace_health: WorkspaceHealth
    cross_campaign_insights: list[CrossCampaignInsight]
    workflow_continuation: WorkflowContinuation
    attention_items: list[AttentionItem]
    analyzed_at: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["campaign_priorities"] = [cp.to_dict() for cp in self.campaign_priorities]
        result["cross_campaign_insights"] = [ci.to_dict() for ci in self.cross_campaign_insights]
        result["attention_items"] = [ai.to_dict() for ai in self.attention_items]
        return result


def _log(msg: str) -> None:
    print(f"[workspace_reasoner] {msg}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filter_dc(dc_type: type, data: dict) -> dict:
    """Keep only keys that are fields of the dataclass *dc_type*."""
    valid = {f.name for f in fields(dc_type)}
    return {k: v for k, v in data.items() if k in valid}


class WorkspaceReasoner:
    """Thin adapter: delegates all logic to the modular reasoning pipeline.

    Receives the same snapshot dict as before, feeds it to
    ReasoningCoordinator.analyze(), and maps the result back to
    the WorkspaceAnalysis dataclass for full backward compatibility.
    """

    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        self._coordinator = ReasoningCoordinator()

    def analyze(self) -> WorkspaceAnalysis:
        now = _now()
        pipeline_result = self._coordinator.analyze(self.snapshot)

        analysis = pipeline_result

        campaign_priorities = [
            CampaignPriority(**_filter_dc(CampaignPriority, cp))
            for cp in analysis.get("campaign_priorities", [])
        ]

        health_data = analysis.get("workspace_health", {})

        insights_data = analysis.get("cross_campaign_insights", [])

        cf_data = _filter_dc(CurrentFocus, analysis.get("current_focus", {}))
        rna_data = _filter_dc(RecommendedAction, analysis.get("recommended_next_action", {}))
        wc_data = _filter_dc(WorkflowContinuation, analysis.get("workflow_continuation", {}))

        attention_items = [
            AttentionItem(**_filter_dc(AttentionItem, ai))
            for ai in analysis.get("attention_items", [])
        ]

        return WorkspaceAnalysis(
            current_focus=CurrentFocus(**cf_data),
            recommended_next_action=RecommendedAction(**rna_data),
            campaign_priorities=campaign_priorities,
            workspace_health=WorkspaceHealth(**health_data),
            cross_campaign_insights=[CrossCampaignInsight(**_filter_dc(CrossCampaignInsight, ci)) for ci in insights_data],
            workflow_continuation=WorkflowContinuation(**wc_data),
            attention_items=attention_items,
            analyzed_at=now,
        )
