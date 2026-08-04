"""ReasoningCoordinator — orchestrates the deterministic reasoning pipeline.

Pipeline:
    WorkspaceState + WorkspaceDelta
        → SignalFactory (build typed signals from raw state)
        → PriorityReasoner (rank campaigns, determine focus)
        → AttentionReasoner (what needs attention)
        → HealthReasoner (workspace health, cross-campaign insights)
        → RiskReasoner (risks)
        → OpportunityReasoner (opportunities)
        → RecommendationReasoner (next action, workflow continuation)
        → BriefingContext (structured output for NarrativeEngine)

The coordinator owns execution order and data passing between reasoners.
Each reasoner is independently testable.

Since Phase 7: reasoners consume typed signals from the Intelligence Layer
instead of raw campaign dicts.  Signal extraction is the first pipeline step.
"""

from typing import Any

from services.intelligence.signal_factory import SignalFactory
from services.reasoning.attention_reasoner import AttentionReasoner
from services.reasoning.delta_reasoner import DeltaReasoner
from services.reasoning.health_reasoner import HealthReasoner
from services.reasoning.opportunity_reasoner import OpportunityReasoner
from services.reasoning.priority_reasoner import PriorityReasoner
from services.reasoning.recommendation_reasoner import RecommendationReasoner
from services.reasoning.risk_reasoner import RiskReasoner
from services.narrative_engine import BriefingContext


class ReasoningCoordinator:
    """Orchestrates the pipeline from raw state to structured BriefingContext."""

    def __init__(self) -> None:
        self.signals = SignalFactory()
        self.priority = PriorityReasoner()
        self.attention = AttentionReasoner()
        self.health = HealthReasoner()
        self.risk = RiskReasoner()
        self.opportunity = OpportunityReasoner()
        self.recommendation = RecommendationReasoner()
        self.delta = DeltaReasoner()

    def analyze(
        self,
        snapshot: dict,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        """Run the full reasoning pipeline.

        Returns a dict with the same keys as the legacy
        ``WorkspaceAnalysis.to_dict()`` for backwards compatibility,
        plus a ``_briefing_context`` key containing the structured
        BriefingContext for the Narrative Engine.

        Callers that need the old format read the top-level keys.
        Callers that use the Narrative Engine read ``_briefing_context``.
        """
        campaigns: list[dict] = snapshot.get("campaigns", [])
        drafts: dict = snapshot.get("drafts", {})
        jobs: dict = snapshot.get("jobs", {})
        memory: dict = snapshot.get("memory", {})

        # ── 1. Delta ──
        wm_delta: dict = snapshot.get("_delta", {})
        if not wm_delta and session_token:
            wm_delta, _ = self.delta.compute(session_token)

        # ── 1b. Intelligence Layer: extract typed signals from raw state ──
        (
            campaign_signals,
            conversation_signals,
            lead_signals,
            provider_signals,
            workspace_signals,
        ) = self.signals.build_all(campaigns, drafts, wm_delta)

        # ── 2. Priority (campaign ranking + focus) ──
        campaign_priorities = self.priority.rank_campaigns(campaign_signals)
        current_focus = self.priority.determine_focus(campaigns, memory, jobs)

        # ── 3. Attention ──
        attention_items = self.attention.compute(campaign_signals, jobs, campaign_priorities)

        # ── 4. Health + insights ──
        drafts_backlog = drafts.get("pending", 0) if isinstance(drafts, dict) else 0
        workspace_health = self.health.compute_health(
            campaign_signals, workspace_signals, drafts_backlog=drafts_backlog,
        )
        cross_campaign_insights = self.health.compute_insights(campaign_signals)

        # ── 5. Risk ──
        risks = self.risk.compute(
            campaign_signals, workspace_signals,
            delta=wm_delta, drafts_backlog=drafts_backlog,
            health=workspace_health,
        )

        # ── 6. Opportunity ──
        opportunities = self.opportunity.compute(
            campaign_signals, wm_delta,
            campaigns_ready=workspace_health.campaigns_ready,
        )

        # ── 7. Recommendation (next action + workflow continuation) ──
        recent_jobs = jobs.get("recently_completed", []) if isinstance(jobs, dict) else []
        running_jobs = jobs.get("running", []) if isinstance(jobs, dict) else []
        research_available = bool(snapshot.get("total_leads", 0)) or bool(
            wm_delta.get("new_leads", 0)
        ) or any(
            j.get("type") == "search" and j.get("status") == "completed"
            for j in recent_jobs if isinstance(j, dict)
        )
        research_in_progress = any(
            j.get("type") == "search" and j.get("status") in ("queued", "running")
            for j in running_jobs if isinstance(j, dict)
        )
        recommended_next_action = self.recommendation.pick_next_action(
            attention_items,
            campaign_priorities,
            campaign_signals,
            research_available=research_available,
            research_in_progress=research_in_progress,
        )
        workflow_continuation = self.recommendation.workflow_continuation(
            current_focus, campaign_priorities, campaign_signals,
        )

        # ── 8. Build backwards-compatible analysis dict ──
        from services.reasoning._shared import now_iso
        analysis: dict[str, Any] = {
            "current_focus": current_focus.to_dict(),
            "recommended_next_action": recommended_next_action.to_dict(),
            "campaign_priorities": [cp.to_dict() for cp in campaign_priorities],
            "workspace_health": workspace_health.to_dict(),
            "cross_campaign_insights": [i.to_dict() for i in cross_campaign_insights],
            "workflow_continuation": workflow_continuation.to_dict(),
            "attention_items": [a.to_dict() for a in attention_items],
            "analyzed_at": now_iso(),
        }

        # ── 9. Build BriefingContext for NarrativeEngine ──
        import datetime
        h = datetime.datetime.now().hour
        if h < 12:
            greeting = "Good morning"
        elif h < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        briefing_context = BriefingContext(
            greeting=greeting,
            workspace_delta=wm_delta,
            priorities=analysis["campaign_priorities"],
            attention_items=analysis["attention_items"],
            health_summary=analysis["workspace_health"],
            current_focus=analysis["current_focus"],
            recommended_next_action=analysis["recommended_next_action"],
            cross_campaign_insights=analysis["cross_campaign_insights"],
            opportunities=[o.to_dict() for o in opportunities],
            risks=[r.to_dict() for r in risks],
            campaigns=campaigns,
            drafts=drafts,
            jobs=jobs,
            memory=memory,
            timeline=snapshot.get("timeline", []),
        )

        analysis["_briefing_context"] = briefing_context
        return analysis
