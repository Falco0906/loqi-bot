"""Characterization for the legacy communication memory-update endpoint."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from services.communication import api as communication_api
from services.communication import service as communication_service


def test_memory_update_preserves_intelligence_memory_and_event_contract(monkeypatch):
    calls: dict[str, object] = {}
    message = SimpleNamespace(id="generated-message", text="Interested in a demo")
    memory = SimpleNamespace(model_dump=lambda: {"conversation_id": "generated-message", "stage": "engaged"})
    intent = SimpleNamespace(value="demo_request")
    signal = SimpleNamespace(signal=SimpleNamespace(value="buying_intent"))
    stage = SimpleNamespace(value="engaged")
    recommendation = SimpleNamespace(action=SimpleNamespace(value="follow_up"))

    monkeypatch.setattr(
        communication_api.identity_dependencies,
        "web_session_token",
        lambda request: "bound-session",
    )
    monkeypatch.setattr(communication_service, "ConversationMessage", lambda **_kwargs: message)
    monkeypatch.setattr(communication_service, "detect_intents", lambda text: [intent])
    monkeypatch.setattr(communication_service, "detect_signals", lambda text: [signal])
    monkeypatch.setattr(communication_service, "classify_stage", lambda history, text: (stage, "interested"))
    monkeypatch.setattr(communication_service, "recommend_followup", lambda *args: recommendation)
    monkeypatch.setattr(
        communication_service.memory_store,
        "get",
        lambda conversation_id: calls.setdefault("existing", conversation_id),
    )

    def create_memory(**kwargs):
        calls["memory"] = kwargs
        return memory

    monkeypatch.setattr(communication_service, "create_or_update_memory", create_memory)
    monkeypatch.setattr(
        communication_service,
        "publish",
        lambda *args, **kwargs: calls.setdefault("event", (args, kwargs)),
    )

    result = asyncio.run(
        communication_api.communication_memory_update(
            "path-token",
            communication_api.AnalyzeMessageRequest(text="Interested in a demo"),
            SimpleNamespace(),
        )
    )

    assert result == {"ok": True, "memory": {"conversation_id": "generated-message", "stage": "engaged"}}
    assert calls["existing"] == "generated-message"
    assert calls["memory"] == {
        "conversation_id": "generated-message",
        "message": message,
        "intents": [intent],
        "buying_signals": [signal],
        "stage": stage,
        "stage_reasoning": "interested",
        "followup_action": "follow_up",
        "existing_memory": "generated-message",
    }
    event_args, event_kwargs = calls["event"]
    assert event_args == (
        "bound-session",
        communication_service.WMEventType.PREFERENCE_LEARNED,
        {
            "conversation_id": "generated-message",
            "intents": ["demo_request"],
            "signals": ["buying_intent"],
            "stage": "engaged",
            "followup_action": "follow_up",
        },
    )
    assert event_kwargs == {"actor": "system"}
