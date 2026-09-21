"""Contracts for projecting legacy intelligence events onto durable timelines."""

from services.conversation_intelligence.legacy_models import (
    ConversationMessage,
    TimelineEventType as LegacyTimelineEventType,
)
from services.conversations import compatibility
from services.conversations.conversation_store import conversation_store
from services.conversations.timeline import TimelineEventType
from services.conversation_intelligence.legacy_reply_projection import project_legacy_reply_intelligence


def test_legacy_event_mapping_table_is_explicit_and_complete():
    expected = {
        LegacyTimelineEventType.LEAD_REPLIED: TimelineEventType.REPLY_RECEIVED,
        LegacyTimelineEventType.PRICING_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.MEETING_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.DEMO_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.COMPETITOR_MENTIONED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.POSITIVE_BUYING_SIGNAL: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.STRONG_OBJECTION: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.BUDGET_DISCUSSED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.TIMELINE_DISCUSSED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.DECISION_MAKER_MENTIONED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.FOLLOWUP_RECOMMENDED: TimelineEventType.FOLLOW_UP_SUGGESTED,
        LegacyTimelineEventType.STAGE_CHANGED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.OBJECTION_ANSWERED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.MEETING_SCHEDULED: TimelineEventType.MEETING_BOOKED,
        LegacyTimelineEventType.PROPOSAL_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.CASE_STUDY_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.COMPETITIVE_SITUATION: TimelineEventType.REPLY_CLASSIFIED,
        LegacyTimelineEventType.LOST_OPPORTUNITY: TimelineEventType.CLOSED_LOST,
        LegacyTimelineEventType.WON_DEAL: TimelineEventType.CLOSED_WON,
        LegacyTimelineEventType.DORMANT_PERIOD: TimelineEventType.REPLY_CLASSIFIED,
    }
    assert {
        event_type: compatibility.durable_timeline_type_for_legacy_event(event_type)
        for event_type in LegacyTimelineEventType
    } == expected


def test_canonical_event_round_trips_to_the_legacy_reader_envelope(monkeypatch):
    captured = []
    monkeypatch.setattr(conversation_store, "get_conversation", lambda _id: object())
    monkeypatch.setattr(conversation_store, "add_timeline_event", captured.append)

    assert compatibility.record_legacy_analysis_event(
        "conversation-1",
        LegacyTimelineEventType.PRICING_REQUESTED,
        "Pricing requested",
        {"intent": "pricing_request"},
    ) is True
    assert captured[0].event_type is TimelineEventType.REPLY_CLASSIFIED

    monkeypatch.setattr(conversation_store, "get_timeline", lambda _id: captured)
    legacy_events = compatibility.read_legacy_timeline_events("conversation-1")

    assert [event.model_dump() for event in legacy_events] == [{
        "event_type": LegacyTimelineEventType.PRICING_REQUESTED,
        "message": "Pricing requested",
        "timestamp": captured[0].timestamp.isoformat(),
        "metadata": {"intent": "pricing_request"},
    }]


def test_noncanonical_analysis_keeps_results_but_skips_timeline_persistence(monkeypatch):
    writes = []
    monkeypatch.setattr(conversation_store, "get_conversation", lambda _id: None)
    monkeypatch.setattr(conversation_store, "add_timeline_event", writes.append)

    intelligence, memory = project_legacy_reply_intelligence(
        ConversationMessage(text="How much does this cost?", sender="lead"),
        conversation_id="analysis-only-id",
    )

    assert intelligence.intents
    assert memory.conversation_id == "analysis-only-id"
    assert writes == []
