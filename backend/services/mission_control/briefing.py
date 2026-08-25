from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

from services.executive_brief import generate_brief
from services.intentions.engine import IntentionEngine
from services.intentions.lifecycle import activate
from services.intentions.models import Intention, IntentionType, LifecycleStatus
from services.intentions.priority import order_intentions
from services.narrative_engine import get_engine as get_narrative
from services.recommendation_engine import generate_recommendations
from services.workspace_snapshot import build_snapshot
from services.workspace_timeline import (
    get_events as get_timeline_events,
    get_grouped_events as get_grouped_timeline_events,
)

from .types import (
    BriefingResponse,
    BriefingSection,
    HealthSummary,
    IntentionCard,
    TimelineEvent,
)


def _delta_count(value: Any) -> int:
    """Normalize both current count fields and older list-shaped deltas."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def _delta_items(value: Any) -> list[Any]:
    """Return iterable delta items without treating persisted counts as lists."""
    return list(value) if isinstance(value, (list, tuple, set)) else []


def _delta_value(delta: Any, name: str, default: Any = None) -> Any:
    """Read the in-memory WorldModel delta or its serialized snapshot form."""
    if isinstance(delta, dict):
        return delta.get(name, default)
    return getattr(delta, name, default)


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _tokens(*values: Any) -> set[str]:
    return {
        token
        for value in values
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if token not in {"the", "and", "for", "your", "with", "review"}
    }


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
        prebuilt: dict | None = None,
    ) -> BriefingResponse:
        def _phase(name: str) -> None:
            logger.debug(
                "briefing_phase name=%s elapsed_ms=%.0f",
                name, (time.monotonic() - _t0) * 1000,
            )

        _t0 = time.monotonic()
        if prebuilt is not None:
            snapshot = prebuilt["snapshot"]
            analysis = prebuilt["analysis"]
            recommendations = prebuilt["recommendations"]
            brief = prebuilt["brief"]
            raw_delta = prebuilt.get("delta", snapshot.get("_delta", {}))
        else:
            snapshot = build_snapshot(session_token, campaigns, drafts, total_leads, user_id=db_user_id)
            _phase("snapshot")
            analysis = snapshot.get("analysis", {})
            _phase("analysis")
            recommendations = generate_recommendations(snapshot)
            _phase("recommendations")
            brief = generate_brief(snapshot, recommendations)
            _phase("brief")
            raw_delta = snapshot.get("_delta", {})

        health_raw = analysis.get("workspace_health", {})
        delta = snapshot.get("_delta", {})

        signals = self._build_signals(snapshot, analysis, health_raw, delta)

        intentions = self._intention_engine.evaluate(
            workspace_id=session_token,
            signals=signals,
            reasoning=analysis,
            delta=delta,
        )
        _phase("intentions")
        # ``evaluate`` deliberately returns newly-created intentions. This
        # request is the lifecycle boundary that exposes them to the user, so
        # activate the current evaluation before filtering the response. Do
        # not use the process-local queue here: it can retain stale intentions
        # after the underlying workspace state has changed.
        for intention in intentions:
            if intention.status == LifecycleStatus.CREATED:
                activate(intention)
        active_intentions = [i for i in intentions if i.status == LifecycleStatus.ACTIVE]

        briefing_section = self._build_briefing_section(brief, snapshot, analysis)

        # ``RECOMMEND_ACTION`` is the non-blocking work Loqi has identified
        # for the user.  It still needs a visible home in the briefing even
        # when its policy priority is ``normal``; otherwise it appears only
        # as an opaque timeline event and the primary briefing sections are
        # empty despite an actionable workspace signal.
        top_priority_intentions = [
            intention
            for intention in active_intentions
            if intention.priority.value in {"critical", "high"}
            or intention.type == IntentionType.RECOMMEND_ACTION
        ]
        top_priorities = self._build_attention_cards(
            analysis.get("attention_items", []),
            recommendations,
            top_priority_intentions,
        )
        waiting_on_you = self._filter_intentions(
            active_intentions, type_filter={IntentionType.ASK_USER}
        )
        # An AUTO_HANDLE intention is a policy recommendation, not evidence
        # that an operation actually completed.  Only real activity belongs
        # in the historical "Loqi handled" section.
        loqi_handled = self._build_completed_activity_cards(
            session_token, snapshot, raw_delta
        )
        upcoming = self._filter_intentions(
            active_intentions, type_filter={IntentionType.FOLLOW_UP, IntentionType.NOTIFY}
        )

        health = self._build_health_summary(health_raw, snapshot)

        timeline = self._build_timeline(session_token, snapshot, raw_delta)
        what_changed = self._build_activity(session_token, snapshot, raw_delta)
        _phase("timeline")

        return BriefingResponse(
            briefing=briefing_section,
            top_priorities=top_priorities,
            waiting_on_you=waiting_on_you,
            loqi_handled=loqi_handled,
            upcoming=upcoming,
            workspace_health=health,
            timeline=timeline,
            what_changed=what_changed,
            live_activity=what_changed,
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
            1 for c in campaigns if c.get("current_step") == "sending"
        )
        review_count = draft_counts.get("pending", 0)

        return {
            "campaigns_ready_to_launch": ready_count,
            "drafts_pending_review": review_count,
            "unread_replies": _delta_value(delta, "new_conversations", 0),
            "urgent_replies": health_raw.get("blocked_count", 0),
            "follow_ups_due": health_raw.get("follow_ups_due", 0),
            "pending_meetings": _delta_value(delta, "pending_meetings", 0),
            "new_leads_count": _delta_count(_delta_value(delta, "new_leads", 0)),
            "high_quality_leads": sum(
                1 for _ in _delta_items(_delta_value(delta, "new_leads", []))
                if isinstance(_, dict) and _.get("confidence", 0) > 0.7
            ),
            "failing_providers": health_raw.get("failing_providers", 0),
            "research_jobs_completed": jobs.get("completed", 0),
            "workspace_health_score": health_raw.get("score", 1.0),
            "auto_handle_candidates": health_raw.get("auto_handle_candidates", 0),
            "engagement_signals": analysis.get("engagement_signals", 0),
            "event_count": _delta_value(delta, "event_count", 0),
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

        # NarrativeEngine is already the grounded, generated briefing.  The
        # health label is useful in workspace_health, but is not a synthesis.
        lines = [line for line in brief.get("lines", []) if isinstance(line, str) and line.strip()]
        overall = (
            brief.get("overall_summary")
            or brief.get("summary")
            or (lines[0] if lines else "")
        )
        focus_text = focus.get("focus", "") if isinstance(focus, dict) else ""
        top_rec = rna.get("title", "") if isinstance(rna, dict) else ""

        return BriefingSection(
            greeting=brief.get("greeting", "Good morning"),
            lines=lines,
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
        delta: Any,
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

        if delta:
            for c in _delta_items(_delta_value(delta, "new_campaigns", [])):
                name = _item_value(c, "name")
                events.append(TimelineEvent(
                    id=f"dc-{len(events)}", timestamp="",
                    type="campaign_created",
                    description=f"Campaign created: {name}",
                    category="campaign", actor="user",
                ))
            for d in _delta_items(_delta_value(delta, "new_drafts", [])):
                subject = _item_value(d, "subject")
                events.append(TimelineEvent(
                    id=f"dd-{len(events)}", timestamp="",
                    type="draft_generated",
                    description=f"Draft generated: {subject}",
                    category="draft", actor="loqi",
                ))
            for _d in _delta_items(_delta_value(delta, "sent_outreach", [])):
                events.append(TimelineEvent(
                    id=f"ds-{len(events)}", timestamp="",
                    type="draft_sent",
                    description="Outreach sent",
                    category="outreach", actor="loqi",
                ))

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:25]

    def _build_attention_cards(
        self,
        attention_items: list[dict],
        recommendations: list[dict],
        intentions: list[Intention],
    ) -> list[IntentionCard]:
        """Build user-facing attention from detailed reasoner output first.

        IntentionEngine still supplies policy priority/confidence when it can
        be matched, but never replaces the detailed reason/action copy.
        """
        cards: list[IntentionCard] = []
        seen: set[tuple[str, str]] = set()

        for index, item in enumerate(attention_items):
            if not isinstance(item, dict):
                continue
            campaign_id = item.get("campaign_id") or None
            action = str(item.get("action", "Review"))
            key = self._attention_key(campaign_id, action, item.get("title"), item.get("reason"))
            if key in seen:
                continue
            seen.add(key)
            matching = next((i for i in intentions if self._intention_matches_attention(i, item)), None)
            importance = int(item.get("importance", 0) or 0)
            priority = matching.priority.value if matching else (
                "high" if importance >= 8 else "normal" if importance >= 5 else "low"
            )
            raw_confidence = item.get("confidence", 0)
            confidence = float(raw_confidence or 0)
            if confidence > 1:
                confidence /= 100
            if matching:
                confidence = max(confidence, matching.confidence)
            evidence = [{
                "source": "workspace_reasoner",
                "campaign_name": item.get("campaign_name", ""),
                "importance": importance,
                "urgency": item.get("urgency", 0),
                "blocking_impact": item.get("blocking_impact", 0),
            }]
            if matching:
                evidence.extend(self._intention_to_card(matching).evidence)
            cards.append(IntentionCard(
                id=f"attention:{campaign_id or index}:{self._slug(action)}",
                title=str(item.get("title") or action),
                summary=str(item.get("reason") or ""),
                priority=priority,
                confidence=confidence,
                evidence=evidence,
                recommended_action=action,
                related_campaign=campaign_id,
                reason_code=matching.reason_code.value if matching else "workspace_attention",
                link=str(item.get("link") or ""),
                time_waiting=str(item.get("time_waiting") or ""),
                source="workspace_reasoner",
            ))

        for index, recommendation in enumerate(recommendations):
            if not isinstance(recommendation, dict):
                continue
            action = str(recommendation.get("action") or "Review")
            campaign_id = self._campaign_id_from_link(recommendation.get("link", ""))
            # A generic recommendation such as "research your ideal
            # prospects" is useful elsewhere, but it is not an evidenced
            # Mission Control attention card.  Keep empty workspaces empty.
            if not campaign_id and not attention_items and not intentions:
                continue
            key = self._attention_key(
                campaign_id,
                action,
                recommendation.get("observation"),
                recommendation.get("reason"),
            )
            if key in seen:
                continue
            seen.add(key)
            cards.append(IntentionCard(
                id=f"recommendation:{index}:{self._slug(action)}",
                title=str(recommendation.get("observation") or action),
                summary=str(recommendation.get("reason") or ""),
                priority=str(recommendation.get("priority") or "normal"),
                confidence=self._confidence_value(recommendation.get("confidence")),
                evidence=[{"source": "recommendations"}],
                recommended_action=action,
                related_campaign=campaign_id,
                reason_code=str(recommendation.get("type") or "recommendation"),
                link=str(recommendation.get("link") or ""),
                source="recommendations",
            ))

        # Policies remain a truthful fallback for a signal that has no richer
        # reasoner/recommendation counterpart.
        for intention in order_intentions(intentions):
            policy_card = self._intention_to_card(intention)
            # A policy tied to a resource already represented by a detailed
            # attention item is metadata for that card, not a second problem.
            if policy_card.related_campaign and any(
                card.related_campaign == policy_card.related_campaign for card in cards
            ):
                continue
            key = self._attention_key(
                policy_card.related_campaign,
                policy_card.recommended_action,
                policy_card.title,
                policy_card.summary,
            )
            if key not in seen:
                seen.add(key)
                cards.append(policy_card)
        return cards

    def _build_completed_activity_cards(
        self, session_token: str, snapshot: dict, delta: Any
    ) -> list[IntentionCard]:
        cards: list[IntentionCard] = []
        seen: set[tuple[str, str]] = set()
        completed_types = {"search_completed", "drafts_generated", "draft_approved", "campaign_launched"}
        # Grouping is a presentation optimisation over real recorded events;
        # it does not manufacture historical completion.
        for event in get_grouped_timeline_events(session_token, limit=20):
            event_type = str(event.get("type", ""))
            if event_type not in completed_types:
                continue
            key = (event_type, str(event.get("text", "")).strip().lower())
            if key in seen:
                continue
            seen.add(key)
            cards.append(IntentionCard(
                id=str(event.get("_id") or f"handled:{len(cards)}"),
                title=str(event.get("text") or event_type.replace("_", " ").title()),
                summary="Completed activity recorded in this workspace.",
                priority="normal", confidence=1.0,
                evidence=[{"source": "workspace_timeline", "type": event_type}],
                reason_code=event_type, source="workspace_timeline",
            ))
        for job in snapshot.get("jobs", {}).get("recently_completed", []):
            status = str(_item_value(job, "status", "")).lower()
            if status and status != "completed":
                continue
            job_type = str(_item_value(job, "type", "job"))
            query = str(_item_value(job, "query", ""))
            key = (f"job:{job_type}", query.lower())
            if key in seen:
                continue
            seen.add(key)
            cards.append(IntentionCard(
                id=str(_item_value(job, "id", f"job:{len(cards)}")),
                title=f"{job_type.replace('_', ' ').title()} completed",
                summary=query or "A background task completed successfully.",
                priority="normal", confidence=1.0,
                evidence=[{"source": "durable_job", "status": "completed"}],
                reason_code="job_completed", source="durable_job",
            ))
        return cards

    def _build_activity(
        self, session_token: str, snapshot: dict, delta: Any
    ) -> list[TimelineEvent]:
        """Recent real activity/deltas for What Changed; no policy events."""
        events = self._build_timeline(session_token, snapshot, delta)
        seen = {(event.type, event.description) for event in events}
        for job in snapshot.get("jobs", {}).get("recently_completed", []):
            status = str(_item_value(job, "status", "")).lower()
            if status and status != "completed":
                continue
            job_type = str(_item_value(job, "type", "job"))
            query = str(_item_value(job, "query", ""))
            description = f"{job_type.replace('_', ' ').title()} completed"
            if query:
                description = f"{description}: {query}"
            key = ("job_completed", description)
            if key not in seen:
                seen.add(key)
                events.append(TimelineEvent(
                    id=str(_item_value(job, "id", f"job-{len(events)}")),
                    timestamp=str(_item_value(job, "completed_at", "")),
                    type="job_completed", description=description,
                    category="job", actor="loqi", metadata={"source": "durable_job"},
                ))
        events.sort(key=lambda event: event.timestamp, reverse=True)
        return events[:25]

    @staticmethod
    def _slug(value: Any) -> str:
        return "-".join(re.findall(r"[a-z0-9]+", str(value).lower())) or "item"

    @staticmethod
    def _campaign_id_from_link(link: Any) -> str | None:
        match = re.search(r"/campaigns/([^/?#]+)", str(link or ""))
        return match.group(1) if match else None

    def _attention_key(self, campaign_id: Any, action: Any, title: Any, reason: Any) -> tuple[str, str]:
        resource = str(campaign_id or "")
        if resource:
            return resource, " ".join(sorted(_tokens(action)))
        return "", " ".join(sorted(_tokens(action, title, reason)))

    def _intention_matches_attention(self, intention: Intention, item: dict) -> bool:
        campaign_id = str(item.get("campaign_id") or "")
        if campaign_id and intention.related_campaign:
            return campaign_id == intention.related_campaign
        policy_tokens = _tokens(self._recommended_action(intention), intention.reason_code.value)
        attention_tokens = _tokens(item.get("action"), item.get("title"), item.get("reason"))
        return bool(policy_tokens and attention_tokens and policy_tokens.intersection(attention_tokens))

    @staticmethod
    def _confidence_value(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value / 100 if value > 1 else value)
        return {"high": 0.9, "medium": 0.7, "low": 0.4}.get(str(value).lower(), 0.0)

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
