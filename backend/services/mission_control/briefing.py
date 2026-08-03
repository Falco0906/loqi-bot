from __future__ import annotations

import datetime
from typing import Any

from services.executive_brief import generate_brief
from services.intentions.engine import IntentionEngine
from services.intentions.models import Intention, IntentionType, LifecycleStatus
from services.intentions.priority import order_intentions
from services.narrative_engine import get_engine as get_narrative
from services.recommendation_engine import generate_recommendations
from services.workspace_snapshot import build_snapshot
from services.workspace_timeline import get_events as get_timeline_events

from .types import (
    BriefingResponse,
    BriefingSection,
    HealthSummary,
    IntentionCard,
    TimelineEvent,
)


class MissionControlService:

    def __init__(self) -> None:
        self._intention_engine = IntentionEngine()

    @property
    def intention_engine(self) -> IntentionEngine:
        return self._intention_engine

    def get_briefing(
        self,
        session_token: str,
        campaigns: list[dict],
        drafts: list[dict],
        total_leads: int = 0,
        user_id: str | None = None,
        db_user_id: str | None = None,
    ) -> BriefingResponse:
        snapshot = build_snapshot(session_token, campaigns, drafts, total_leads, user_id=db_user_id)

        analysis = snapshot.get("analysis", {})
        health_raw = analysis.get("workspace_health", {})
        delta = snapshot.get("_delta", {})

        recommendations = generate_recommendations(snapshot)
        brief = generate_brief(snapshot, recommendations)

        signals = self._build_signals(snapshot, analysis, health_raw, delta)

        intentions = self._intention_engine.evaluate(
            workspace_id=session_token,
            signals=signals,
            reasoning=analysis,
            delta=delta,
        )
        active_intentions = [i for i in intentions if i.status == LifecycleStatus.ACTIVE]

        briefing_section = self._build_briefing_section(brief, snapshot, analysis)

        top_priorities = self._filter_intentions(
            active_intentions, priority_filter={"critical", "high"}
        )
        waiting_on_you = self._filter_intentions(
            active_intentions, type_filter={IntentionType.ASK_USER}
        )
        loqi_handled = self._filter_intentions(
            active_intentions, type_filter={IntentionType.AUTO_HANDLE}
        )
        upcoming = self._filter_intentions(
            active_intentions, type_filter={IntentionType.FOLLOW_UP, IntentionType.NOTIFY}
        )

        health = self._build_health_summary(health_raw, snapshot)

        timeline = self._build_timeline(session_token, snapshot, active_intentions)

        return BriefingResponse(
            briefing=briefing_section,
            top_priorities=top_priorities,
            waiting_on_you=waiting_on_you,
            loqi_handled=loqi_handled,
            upcoming=upcoming,
            workspace_health=health,
            timeline=timeline,
            all_intentions=[self._intention_to_card(i) for i in active_intentions],
        )

    def _build_signals(
        self,
        snapshot: dict,
        analysis: dict[str, Any],
        health_raw: dict[str, Any],
        delta: dict[str, Any],
    ) -> dict[str, Any]:
        campaigns = snapshot.get("campaigns", [])
        draft_counts = snapshot.get("drafts", {})
        timeline = snapshot.get("timeline", [])
        jobs = snapshot.get("jobs", {})

        ready_count = sum(
            1 for c in campaigns if c.get("status") in ("ready", "ready_to_send")
        )
        review_count = draft_counts.get("pending", 0)

        return {
            "campaigns_ready_to_launch": ready_count,
            "drafts_pending_review": review_count,
            "unread_replies": delta.get("new_conversations", 0),
            "urgent_replies": health_raw.get("blocked_count", 0),
            "follow_ups_due": health_raw.get("follow_ups_due", 0),
            "pending_meetings": delta.get("pending_meetings", 0),
            "new_leads_count": len(delta.get("new_leads", [])),
            "high_quality_leads": sum(
                1 for _ in delta.get("new_leads", []) if _ and _.get("confidence", 0) > 0.7
            ),
            "failing_providers": health_raw.get("failing_providers", 0),
            "research_jobs_completed": jobs.get("completed", 0),
            "workspace_health_score": health_raw.get("score", 1.0),
            "auto_handle_candidates": health_raw.get("auto_handle_candidates", 0),
            "engagement_signals": analysis.get("engagement_signals", 0),
            "event_count": delta.get("event_count", 0),
        }

    def _build_briefing_section(
        self,
        brief: dict,
        snapshot: dict,
        analysis: dict[str, Any],
    ) -> BriefingSection:
        analysis = snapshot.get("analysis", {}) or {}
        health = analysis.get("workspace_health", {})
        focus = analysis.get("current_focus", {})
        rna = analysis.get("recommended_next_action", {})

        overall = health.get("overall_health", "stable")
        focus_text = focus.get("focus", "") if isinstance(focus, dict) else ""
        top_rec = rna.get("title", "") if isinstance(rna, dict) else ""

        return BriefingSection(
            greeting=brief.get("greeting", "Good morning"),
            lines=brief.get("lines", []),
            suggestion=brief.get("suggestion", ""),
            overall_summary=overall,
            primary_focus=focus_text,
            top_recommendation=top_rec,
        )

    def _build_health_summary(
        self,
        health_raw: dict[str, Any],
        snapshot: dict,
    ) -> HealthSummary:
        campaigns = snapshot.get("campaigns", [])
        draft_counts = snapshot.get("drafts", {})
        jobs = snapshot.get("jobs", {})

        return HealthSummary(
            overall_health=health_raw.get("overall_health", "unknown"),
            pipeline_velocity=health_raw.get("pipeline_velocity", "unknown"),
            bottlenecks=health_raw.get("blocked_workflows", []),
            provider_health=health_raw.get("provider_health", []),
            confidence_score=health_raw.get("score", 0.0),
            campaigns_ready=health_raw.get("campaigns_ready", 0),
            campaigns_waiting=health_raw.get("campaigns_waiting", 0),
            draft_backlog=draft_counts.get("pending", 0),
            details={
                "total_campaigns": len(campaigns),
                "total_drafts": draft_counts.get("total", 0),
                "approved_drafts": draft_counts.get("approved", 0),
                "active_jobs": jobs.get("active", 0),
                "completed_jobs": jobs.get("completed", 0),
            },
        )

    def _build_timeline(
        self,
        session_token: str,
        snapshot: dict,
        intentions: list[Intention],
    ) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []

        timeline_events = get_timeline_events(session_token, limit=15)
        for te in timeline_events:
            events.append(TimelineEvent(
                id=te.get("_id", f"tl-{len(events)}"),
                timestamp=te.get("timestamp", ""),
                type=te.get("type", "event"),
                description=te.get("text", ""),
                category=te.get("type", "event").split("_")[0],
                actor="loqi",
            ))

        delta = snapshot.get("_delta", {})
        if delta:
            for c in delta.get("new_campaigns", []):
                name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                events.append(TimelineEvent(
                    id=f"dc-{len(events)}", timestamp="",
                    type="campaign_created",
                    description=f"Campaign created: {name}",
                    category="campaign", actor="user",
                ))
            for d in delta.get("new_drafts", []):
                subject = d.get("subject", "") if isinstance(d, dict) else getattr(d, "subject", "")
                events.append(TimelineEvent(
                    id=f"dd-{len(events)}", timestamp="",
                    type="draft_generated",
                    description=f"Draft generated: {subject}",
                    category="draft", actor="loqi",
                ))
            for d in delta.get("sent_outreach", []):
                events.append(TimelineEvent(
                    id=f"ds-{len(events)}", timestamp="",
                    type="draft_sent",
                    description="Outreach sent",
                    category="outreach", actor="loqi",
                ))

        now = datetime.datetime.now(datetime.timezone.utc)
        for i in intentions:
            ts = i.updated_at if i.updated_at and i.updated_at != "now" else now.isoformat()
            events.append(TimelineEvent(
                id=f"int-{i.id}",
                timestamp=ts,
                type=f"intention_{i.type.value}",
                description=f"{i.type.value}: {i.reason_code.value}",
                category="intention",
                actor="loqi",
                metadata={"priority": i.priority.value, "confidence": i.confidence},
            ))

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:25]

    def _filter_intentions(
        self,
        intentions: list[Intention],
        priority_filter: set[str] | None = None,
        type_filter: set[IntentionType] | None = None,
    ) -> list[IntentionCard]:
        filtered = list(intentions)
        if priority_filter:
            filtered = [i for i in filtered if i.priority.value in priority_filter]
        if type_filter:
            filtered = [i for i in filtered if i.type in type_filter]
        ordered = order_intentions(filtered)
        return [self._intention_to_card(i) for i in ordered]

    def _intention_to_card(self, intention: Intention) -> IntentionCard:
        evidence_list = [
            {"reason_code": e.reason_code.value, "confidence": e.confidence,
             "source": e.source, "detail": e.detail}
            for e in intention.evidence
        ] if intention.evidence else []

        return IntentionCard(
            id=intention.id,
            title=intention.type.value.replace("_", " ").title(),
            summary=intention.reason_code.value.replace("_", " ").title(),
            priority=intention.priority.value,
            confidence=intention.confidence,
            evidence=evidence_list,
            recommended_action=self._recommended_action(intention),
            related_campaign=intention.related_campaign,
            related_lead=intention.related_lead,
            reason_code=intention.reason_code.value,
        )

    def _recommended_action(self, intention: Intention) -> str:
        actions = {
            "campaign_ready": "Review and launch campaign",
            "draft_review_required": "Review pending drafts",
            "new_reply_received": "Review and reply",
            "follow_up_due": "Send follow-up",
            "meeting_pending": "Confirm meeting",
            "new_leads_found": "Review new prospects",
            "provider_failure": "Check provider status",
            "research_completed": "View research results",
            "engagement_signal": "Review engagement",
            "workspace_health_changed": "Review workspace health",
            "low_confidence": "No action needed",
        }
        return actions.get(intention.reason_code.value, "Review")


_service: MissionControlService | None = None


def get_service() -> MissionControlService:
    global _service
    if _service is None:
        _service = MissionControlService()
    return _service
