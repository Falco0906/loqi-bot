"""Tests for the Mission Control experience (Phase 11)."""

from datetime import datetime, timezone

from services.mission_control.briefing import MissionControlService, get_service
from services.mission_control.types import (
    BriefingResponse,
    BriefingSection,
    HealthSummary,
    IntentionCard,
    TimelineEvent,
)
from services.intentions.models import (
    Intention,
    IntentionType,
    LifecycleStatus,
    PriorityLevel,
    ReasonCode,
)


class TestMissionControlTypes:

    def test_briefing_response_defaults(self):
        r = BriefingResponse()
        assert r.ok is True
        assert r.briefing.greeting == ""
        assert r.top_priorities == []
        assert r.waiting_on_you == []
        assert r.loqi_handled == []
        assert r.upcoming == []
        assert isinstance(r.workspace_health, HealthSummary)
        assert r.timeline == []

    def test_briefing_section_fields(self):
        s = BriefingSection(
            greeting="Good morning",
            lines=["Line 1", "Line 2"],
            suggestion="Launch campaign",
            overall_summary="healthy",
            primary_focus="Campaign review",
            top_recommendation="Launch ready campaign",
        )
        assert s.greeting == "Good morning"
        assert len(s.lines) == 2
        assert s.suggestion == "Launch campaign"

    def test_intention_card_with_evidence(self):
        card = IntentionCard(
            id="i1",
            title="Approve Campaign",
            summary="Campaign is ready to launch",
            priority="high",
            confidence=0.92,
            evidence=[{"reason_code": "campaign_ready", "confidence": 0.95, "source": "policy"}],
            recommended_action="Review and launch",
            reason_code="campaign_ready",
        )
        assert card.id == "i1"
        assert card.priority == "high"
        assert len(card.evidence) == 1
        assert card.evidence[0]["reason_code"] == "campaign_ready"

    def test_health_summary_defaults(self):
        h = HealthSummary()
        assert h.overall_health == "unknown"
        assert h.pipeline_velocity == "unknown"
        assert h.bottlenecks == []
        assert h.confidence_score == 0.0

    def test_timeline_event(self):
        e = TimelineEvent(
            id="e1",
            timestamp="2025-01-01T00:00:00Z",
            type="campaign_created",
            description="Created campaign: Test",
            category="campaign",
            actor="user",
        )
        assert e.type == "campaign_created"
        assert e.description == "Created campaign: Test"
        assert e.actor == "user"


class TestMissionControlService:

    def setup_method(self):
        self.svc = MissionControlService()

    def test_service_singleton(self):
        svc1 = get_service()
        svc2 = get_service()
        assert svc1 is svc2

    def test_get_briefing_empty(self):
        result = self.svc.get_briefing("test-token", [], [])
        assert isinstance(result, BriefingResponse)
        assert result.ok is True
        assert isinstance(result.briefing, BriefingSection)
        assert isinstance(result.workspace_health, HealthSummary)
        assert result.top_priorities == []
        assert result.waiting_on_you == []
        assert result.loqi_handled == []
        assert result.upcoming == []
        assert isinstance(result.timeline, list)

    def test_get_briefing_with_campaigns(self):
        campaigns = [
            {"id": "c1", "name": "Campaign A", "status": "ready", "lead_count": 10},
            {"id": "c2", "name": "Campaign B", "status": "draft_review", "lead_count": 5},
        ]
        drafts = [
            {"id": "d1", "campaign_id": "c1", "status": "approved"},
            {"id": "d2", "campaign_id": "c1", "status": "pending"},
            {"id": "d3", "campaign_id": "c2", "status": "pending"},
        ]
        result = self.svc.get_briefing("test-token", campaigns, drafts)
        assert result.ok is True

    def test_signals_from_snapshot(self):
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "campaigns": [
                {"id": "c1", "name": "A", "status": "ready"},
                {"id": "c2", "name": "B", "status": "ready"},
            ],
            "drafts": {"pending": 5, "approved": 2, "total": 7},
            "timeline": [],
            "jobs": {"active": 0, "completed": 1},
        }
        analysis = {
            "workspace_health": {
                "blocked_count": 1,
                "follow_ups_due": 2,
                "score": 0.85,
                "failing_providers": 0,
                "auto_handle_candidates": 0,
            },
            "engagement_signals": 3,
            "current_focus": {"focus": "Review campaigns"},
            "recommended_next_action": {"title": "Launch Campaign A"},
            "campaign_priorities": [],
            "attention_items": [],
            "cross_campaign_insights": [],
        }
        delta = {
            "new_leads": [
                {"name": "Lead1", "confidence": 0.8},
                {"name": "Lead2", "confidence": 0.5},
            ],
            "new_conversations": 3,
            "event_count": 5,
        }
        signals = self.svc._build_signals(snapshot, analysis, analysis["workspace_health"], delta)
        assert signals["campaigns_ready_to_launch"] == 2
        assert signals["drafts_pending_review"] == 5
        assert signals["unread_replies"] == 3
        assert signals["new_leads_count"] == 2
        assert signals["high_quality_leads"] == 1

    def test_signals_accept_persisted_delta_counts(self):
        snapshot = {
            "campaigns": [],
            "drafts": {"pending": 0, "approved": 0, "total": 0},
            "timeline": [],
            "jobs": {},
        }
        signals = self.svc._build_signals(
            snapshot,
            {},
            {},
            {"new_leads": 3, "new_conversations": 0},
        )
        assert signals["new_leads_count"] == 3
        assert signals["high_quality_leads"] == 0

    def test_intention_to_card(self):
        now = datetime.now(timezone.utc).isoformat()
        intention = Intention(
            id="i1",
            workspace_id="w1",
            type=IntentionType.ASK_USER,
            priority=PriorityLevel.HIGH,
            confidence=0.92,
            status=LifecycleStatus.ACTIVE,
            reason_code=ReasonCode.CAMPAIGN_READY,
            blocking=True,
            created_at=now,
            updated_at=now,
            related_campaign="c1",
            evidence=[
                type("Evidence", (), {
                    "reason_code": ReasonCode.CAMPAIGN_READY,
                    "confidence": 0.95,
                    "source": "policy",
                    "detail": "Campaign is ready",
                })()
            ],
        )
        card = self.svc._intention_to_card(intention)
        assert card.id == "i1"
        assert card.priority == "high"
        assert card.reason_code == "campaign_ready"
        assert card.related_campaign == "c1"
        assert len(card.evidence) == 1

    def test_filter_intentions_by_type(self):
        now = datetime.now(timezone.utc).isoformat()
        intentions = [
            Intention(id="a", workspace_id="w", type=IntentionType.ASK_USER,
                      priority=PriorityLevel.HIGH, confidence=0.9,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.CAMPAIGN_READY,
                      blocking=True, created_at=now, updated_at=now),
            Intention(id="b", workspace_id="w", type=IntentionType.AUTO_HANDLE,
                      priority=PriorityLevel.NORMAL, confidence=0.8,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.RESEARCH_COMPLETED,
                      blocking=False, created_at=now, updated_at=now),
            Intention(id="c", workspace_id="w", type=IntentionType.FOLLOW_UP,
                      priority=PriorityLevel.LOW, confidence=0.6,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.FOLLOW_UP_DUE,
                      blocking=False, created_at=now, updated_at=now),
        ]

        ask = self.svc._filter_intentions(intentions, type_filter={IntentionType.ASK_USER})
        assert len(ask) == 1
        assert ask[0].id == "a"

        handled = self.svc._filter_intentions(intentions, type_filter={IntentionType.AUTO_HANDLE})
        assert len(handled) == 1
        assert handled[0].id == "b"

        upcoming = self.svc._filter_intentions(
            intentions, type_filter={IntentionType.FOLLOW_UP, IntentionType.NOTIFY}
        )
        assert len(upcoming) == 1
        assert upcoming[0].id == "c"

    def test_filter_intentions_by_priority(self):
        now = datetime.now(timezone.utc).isoformat()
        intentions = [
            Intention(id="a", workspace_id="w", type=IntentionType.ASK_USER,
                      priority=PriorityLevel.CRITICAL, confidence=0.95,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.CAMPAIGN_READY,
                      blocking=True, created_at=now, updated_at=now),
            Intention(id="b", workspace_id="w", type=IntentionType.NOTIFY,
                      priority=PriorityLevel.HIGH, confidence=0.85,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.NEW_LEADS_FOUND,
                      blocking=False, created_at=now, updated_at=now),
            Intention(id="c", workspace_id="w", type=IntentionType.NOTIFY,
                      priority=PriorityLevel.LOW, confidence=0.5,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.LOW_CONFIDENCE,
                      blocking=False, created_at=now, updated_at=now),
        ]
        high = self.svc._filter_intentions(intentions, priority_filter={"high", "critical"})
        assert len(high) == 2
        assert high[0].id == "a"
        assert high[1].id == "b"

    def test_recommended_action_mapping(self):
        now = datetime.now(timezone.utc).isoformat()
        i = Intention(id="x", workspace_id="w", type=IntentionType.ASK_USER,
                      priority=PriorityLevel.HIGH, confidence=0.9,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.CAMPAIGN_READY,
                      blocking=True, created_at=now, updated_at=now)
        assert self.svc._recommended_action(i) == "Review and launch campaign"

        i2 = Intention(id="y", workspace_id="w", type=IntentionType.RECOMMEND_ACTION,
                       priority=PriorityLevel.NORMAL, confidence=0.7,
                       status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.DRAFT_REVIEW_REQUIRED,
                       blocking=False, created_at=now, updated_at=now)
        assert self.svc._recommended_action(i2) == "Review pending drafts"

        i3 = Intention(id="z", workspace_id="w", type=IntentionType.IGNORE,
                       priority=PriorityLevel.LOW, confidence=0.1,
                       status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.LOW_CONFIDENCE,
                       blocking=False, created_at=now, updated_at=now)
        assert self.svc._recommended_action(i3) == "No action needed"

    def test_health_summary_building(self):
        health_raw = {
            "overall_health": "healthy",
            "pipeline_velocity": "accelerating",
            "blocked_workflows": ["Campaign B"],
            "score": 0.88,
            "campaigns_ready": 2,
            "campaigns_waiting": 1,
            "provider_health": [
                {"provider": "gmail", "status": "healthy"},
            ],
        }
        snapshot = {
            "campaigns": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
            "drafts": {"pending": 4, "approved": 6, "total": 10},
            "jobs": {"active": 1, "completed": 5},
        }
        health = self.svc._build_health_summary(health_raw, snapshot)
        assert health.overall_health == "healthy"
        assert health.pipeline_velocity == "accelerating"
        assert len(health.bottlenecks) == 1
        assert health.confidence_score == 0.88
        assert health.campaigns_ready == 2
        assert health.draft_backlog == 4
        assert len(health.provider_health) == 1

    def test_timeline_building(self):
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "_delta": {
                "new_campaigns": [{"name": "Campaign X"}],
                "new_drafts": [{"subject": "Hello"}],
                "sent_outreach": [{"draft_id": "d1"}],
            }
        }
        intentions = [
            Intention(id="i1", workspace_id="w", type=IntentionType.ASK_USER,
                      priority=PriorityLevel.HIGH, confidence=0.9,
                      status=LifecycleStatus.ACTIVE, reason_code=ReasonCode.CAMPAIGN_READY,
                      blocking=True, created_at=now, updated_at=now),
        ]
        timeline = self.svc._build_timeline("test-token", snapshot, intentions)
        assert len(timeline) >= 4
        types = {e.type for e in timeline}
        assert "campaign_created" in types
        assert "draft_generated" in types
        assert "draft_sent" in types
        assert "intention_ask_user" in types
