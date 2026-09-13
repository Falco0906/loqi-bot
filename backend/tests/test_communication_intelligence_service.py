"""Contracts preserved while communication intelligence adapters moved from main."""

from types import SimpleNamespace

import pytest

from services.communication import service


class _Dumpable:
    def __init__(self, **payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def test_analyze_communication_message_preserves_envelope(monkeypatch):
    monkeypatch.setattr(service.memory_store, "get", lambda conversation_id: {"id": conversation_id})
    monkeypatch.setattr(
        service,
        "project_legacy_reply_intelligence",
        lambda **_kwargs: (_Dumpable(score="high"), _Dumpable(stage="engaged")),
    )

    result = service.analyze_communication_message(
        text="Interested in a demo",
        sender="lead",
        subject="Re: Loqi",
        conversation_id="conversation-1",
    )

    assert result == {
        "ok": True,
        "intelligence": {"score": "high"},
        "memory": {"stage": "engaged"},
    }


def test_recommendation_and_summary_preserve_envelopes(monkeypatch):
    monkeypatch.setattr(service, "detect_intents", lambda text: [f"intent:{text}"])
    monkeypatch.setattr(service, "detect_signals", lambda text: [f"signal:{text}"])
    recommendation = _Dumpable(action="follow_up")
    monkeypatch.setattr(service, "recommend_followup", lambda *_args: recommendation)
    monkeypatch.setattr(service, "generate_summary", lambda *_args: "Follow up soon")

    assert service.recommend_communication_follow_up(text="yes") == {
        "ok": True,
        "recommendation": {"action": "follow_up"},
    }
    assert service.summarize_communication_message(text="yes") == {
        "ok": True,
        "summary": "Follow up soon",
    }


def test_timeline_hides_foreign_conversation_and_preserves_event_envelope(monkeypatch):
    foreign = SimpleNamespace(owner_id="other-user")
    monkeypatch.setattr(service.conversation_store, "get_conversation", lambda _id: foreign)
    monkeypatch.setattr(service, "conversation_owned_by", lambda *_args: False)

    with pytest.raises(service.ConversationNotFoundForOwner):
        service.communication_timeline_for_owner(owner_id="owner-a", conversation_id="conversation-1")

    owned = SimpleNamespace(owner_id="owner-a")
    monkeypatch.setattr(service.conversation_store, "get_conversation", lambda _id: owned)
    monkeypatch.setattr(service, "conversation_owned_by", lambda *_args: True)
    monkeypatch.setattr(
        service,
        "read_legacy_timeline_events",
        lambda _id: [_Dumpable(type="message.received")],
    )

    assert service.communication_timeline_for_owner(
        owner_id="owner-a", conversation_id="conversation-1",
    ) == {
        "ok": True,
        "events": [{"type": "message.received"}],
        "total": 1,
    }
