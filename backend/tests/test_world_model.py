"""Tests for the World Model foundation (Phase 1).

These tests verify:
- Event creation and serialization
- Event append and retrieval (incremental read)
- State projection from events
- Delta computation
- Store isolation between sessions
- Thread safety of the in-memory store
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from services.world_model import (
    EventType,
    InMemoryWorldModelStore,
    WorkspaceEvent,
    WorkspaceState,
)


def _make_event(
    session_id: str = "test-session",
    event_type: EventType = EventType.CAMPAIGN_CREATED,
    data: dict | None = None,
    actor: str = "test",
) -> WorkspaceEvent:
    return WorkspaceEvent(
        id=uuid4().hex[:16],
        type=event_type,
        timestamp=datetime.now(timezone.utc),
        session_id=session_id,
        actor=actor,
        data=data or {},
    )


# ── Event basics ──


def test_event_has_default_id():
    event = WorkspaceEvent(session_id="s1")
    assert len(event.id) == 16


def test_event_to_dict():
    event = _make_event(data={"name": "Test Campaign"})
    d = event.to_dict()
    assert d["type"] == event.type.value
    assert d["data"]["name"] == "Test Campaign"
    assert d["session_id"] == "test-session"
    assert d["sequence"] == 0  # set by store, not constructor


# ── Append and read ──


def test_append_increments_sequence():
    store = InMemoryWorldModelStore()
    e1 = _make_event()
    e2 = _make_event()

    store.append_event(e1)
    store.append_event(e2)

    assert e1.sequence == 1
    assert e2.sequence == 2


def test_get_events_returns_all():
    store = InMemoryWorldModelStore()
    for _ in range(5):
        store.append_event(_make_event())

    events = store.get_events("test-session")
    assert len(events) == 5


def test_get_events_after_sequence():
    store = InMemoryWorldModelStore()
    ids = []
    for _ in range(5):
        e = _make_event()
        store.append_event(e)
        ids.append(e.id)

    events = store.get_events("test-session", after_sequence=2)
    assert len(events) == 3
    assert events[0].id == ids[2]


def test_get_events_unknown_session():
    store = InMemoryWorldModelStore()
    events = store.get_events("nonexistent")
    assert events == []


def test_get_last_sequence():
    store = InMemoryWorldModelStore()
    assert store.get_last_sequence("test-session") == 0

    for _ in range(3):
        store.append_event(_make_event())
    assert store.get_last_sequence("test-session") == 3


# ── Session isolation ──


def test_sessions_are_isolated():
    store = InMemoryWorldModelStore()
    for _ in range(3):
        store.append_event(_make_event(session_id="s1"))
    for _ in range(5):
        store.append_event(_make_event(session_id="s2"))

    assert len(store.get_events("s1")) == 3
    assert len(store.get_events("s2")) == 5
    assert store.get_last_sequence("s1") == 3
    assert store.get_last_sequence("s2") == 5


# ── State projection ──


def test_empty_state():
    store = InMemoryWorldModelStore()
    state = store.get_state("empty-session")
    assert isinstance(state, WorkspaceState)
    assert state.session_id == "empty-session"
    assert state.pipeline.campaigns == []


def test_state_project_campaign_created():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "Test Campaign", "status": "planning"},
    ))

    state = store.get_state("test-session")
    assert len(state.pipeline.campaigns) == 1
    assert state.pipeline.campaigns[0].name == "Test Campaign"
    assert state.pipeline.campaigns[0].status == "planning"


def test_state_project_campaign_status_change():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "Campaign 1"},
    ))
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_STATUS_CHANGED,
        data={"campaign_id": "c1", "status": "ready_to_send"},
    ))

    state = store.get_state("test-session")
    assert state.pipeline.campaigns[0].status == "ready_to_send"


def test_state_project_draft_lifecycle():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.DRAFT_GENERATED,
        data={"id": "d1", "campaign_id": "c1", "subject": "Hello"},
    ))
    state = store.get_state("test-session")
    assert state.pipeline.drafts[0].status == "pending"

    store.append_event(_make_event(
        event_type=EventType.DRAFT_APPROVED,
        data={"draft_id": "d1"},
    ))
    state = store.get_state("test-session")
    assert state.pipeline.drafts[0].status == "approved"

    store.append_event(_make_event(
        event_type=EventType.DRAFT_SENT,
        data={"draft_id": "d1"},
    ))
    state = store.get_state("test-session")
    assert state.pipeline.drafts[0].status == "sent"


def test_state_project_conversation():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.MESSAGE_RECEIVED,
        data={"conversation_id": "conv1", "from_name": "John", "subject": "Re: outreach"},
    ))
    state = store.get_state("test-session")
    assert len(state.relationships.conversations) == 1
    assert state.relationships.conversations[0].contact_name == "John"

    # Second message in same thread
    store.append_event(_make_event(
        event_type=EventType.MESSAGE_RECEIVED,
        data={"conversation_id": "conv1", "from_name": "John", "subject": "Re: outreach"},
    ))
    state = store.get_state("test-session")
    assert state.relationships.conversations[0].message_count == 2


def test_state_project_escalation():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.MESSAGE_RECEIVED,
        data={"conversation_id": "conv1", "from_name": "Jane"},
    ))
    store.append_event(_make_event(
        event_type=EventType.CONVERSATION_ESCALATED,
        data={"conversation_id": "conv1", "summary": "Asked about pricing"},
    ))
    state = store.get_state("test-session")
    conv = state.relationships.conversations[0]
    assert conv.needs_attention is True
    assert "pricing" in conv.summary


def test_state_project_preferences():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.PREFERENCE_LEARNED,
        data={"key": "tone", "value": "casual", "confidence": 0.8},
    ))
    state = store.get_state("test-session")
    assert len(state.business_context.preferences) == 1
    assert state.business_context.preferences[0].value == "casual"


# ── State cache invalidation ──


def test_state_cache_invalidates_on_new_event():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "First"},
    ))
    state1 = store.get_state("test-session")
    assert len(state1.pipeline.campaigns) == 1

    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c2", "name": "Second"},
    ))
    state2 = store.get_state("test-session")
    assert len(state2.pipeline.campaigns) == 2


# ── Delta computation ──


def test_delta_empty_when_no_events():
    store = InMemoryWorldModelStore()
    delta = store.get_delta("test-session")
    assert delta.is_empty()


def test_delta_returns_new_campaigns():
    store = InMemoryWorldModelStore()
    # Create a briefing view as baseline
    store.append_event(_make_event(
        event_type=EventType.BRIEFING_VIEWED,
    ))
    # Now create something new
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "After Briefing"},
    ))

    delta = store.get_delta("test-session")
    assert len(delta.new_campaigns) == 1
    assert delta.new_campaigns[0].name == "After Briefing"


def test_delta_excludes_events_before_baseline():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "Before Briefing"},
    ))
    store.append_event(_make_event(
        event_type=EventType.BRIEFING_VIEWED,
    ))
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c2", "name": "After Briefing"},
    ))

    delta = store.get_delta("test-session")
    assert len(delta.new_campaigns) == 1
    assert delta.new_campaigns[0].name == "After Briefing"


def test_delta_respects_explicit_timestamp():
    store = InMemoryWorldModelStore()
    from datetime import timedelta

    early = _make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "Early"},
    )
    early.timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
    store.append_event(early)

    late = _make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c2", "name": "Late"},
    )
    late.timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    store.append_event(late)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).isoformat()
    delta = store.get_delta("test-session", since=cutoff)
    assert len(delta.new_campaigns) == 1
    assert delta.new_campaigns[0].name == "Late"


def test_delta_aggregates_multiple_event_types():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event(event_type=EventType.BRIEFING_VIEWED))
    store.append_event(_make_event(
        event_type=EventType.CAMPAIGN_CREATED,
        data={"id": "c1", "name": "C1"},
    ))
    store.append_event(_make_event(
        event_type=EventType.DRAFT_GENERATED,
        data={"id": "d1", "campaign_id": "c1"},
    ))
    store.append_event(_make_event(
        event_type=EventType.LEAD_DISCOVERED,
        data={"id": "l1", "name": "Acme", "company": "Acme Inc"},
    ))

    delta = store.get_delta("test-session")
    assert len(delta.new_campaigns) == 1
    assert len(delta.new_drafts) == 1
    assert len(delta.new_leads) == 1
    assert delta.event_count == 3


# ── Clear ──


def test_clear_session():
    store = InMemoryWorldModelStore()
    store.append_event(_make_event())
    store.clear_session("test-session")
    assert store.get_events("test-session") == []
    assert store.get_last_sequence("test-session") == 0


# ── Thread safety ──


def test_concurrent_append():
    import threading

    store = InMemoryWorldModelStore()
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        for _ in range(10):
            store.append_event(_make_event())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = store.get_events("test-session")
    assert len(events) == 100
    # Sequence numbers must be unique and monotonic
    sequences = [e.sequence for e in events]
    assert sequences == list(range(1, 101))
