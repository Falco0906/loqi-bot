"""Characterization tests for the legacy web lead-card compatibility routes."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main as main_module
from services.conversations import service as conversation_service
from services.world_model import EventType, get_store, publish


def _request(token: str = "session-token"):
    return SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": f"Bearer {token}" if key == "authorization" else default))


def test_select_legacy_workflow_lead_preserves_message_and_side_effect_contract(monkeypatch):
    lead = {"id": "lead-1", "name": "Ada Lovelace", "title": "CTO", "company": "Analytical Engines"}
    recorded_workflow_messages = []
    conversation_logs = []
    select_calls = []
    session_token = "r15-select"
    get_store().clear_session(session_token)
    publish(session_token, EventType.LEAD_DISCOVERED, lead)
    monkeypatch.setattr(conversation_service, "get_session_context", lambda _user_id: {
        "started_at": "2026-01-01T00:00:00+00:00",
        "service": "Outbound automation",
        "target": "CTOs",
        "user_messages": ["Outbound automation", "CTOs"],
        "assistant_messages": ["Reply with a number to pick one"],
    })
    monkeypatch.setattr(
        conversation_service,
        "select_lead",
        lambda *args, **kwargs: select_calls.append((args, kwargs)) or lead,
    )
    monkeypatch.setattr(conversation_service, "get_user_preferences", lambda _user_id: {"tone": "casual"})
    monkeypatch.setattr(conversation_service, "_get_after_draft_variation", lambda *_args: "Approve it when ready.")
    monkeypatch.setattr(conversation_service, "record_workflow_message", lambda **kwargs: recorded_workflow_messages.append(kwargs))
    monkeypatch.setattr(conversation_service, "log_conversation", lambda *args: conversation_logs.append(args))
    workflow_calls = []

    def fake_run_workflow(payload):
        workflow_calls.append(payload)
        return {
            "ok": True,
            "type": "draft_message",
            "message": "Draft ready:\n\n---\nHello Ada\n---",
            "lead": lead,
            "tone": "casual",
            "length": "short",
            "lead_intelligence": {"fit": "high"},
            "company_intelligence": {"industry": "software"},
        }

    monkeypatch.setattr(conversation_service, "run_workflow", fake_run_workflow)

    result = conversation_service.select_legacy_workflow_lead_and_draft(
        user_id="user-1", lead_index=1, workflow_session_id="workflow-1", session_token=session_token,
    )

    assert result["ok"] is True
    assert [message["type"] for message in result["messages"]] == ["lead_selected", "draft_preview", "status"]
    assert result["messages"][0]["data"] == {"lead": lead}
    assert result["messages"][1]["data"]["draft"] == "Hello Ada"
    assert all(set(message) == {"id", "role", "type", "text", "data", "created_at"} for message in result["messages"])
    assert [message["message_type"] for message in recorded_workflow_messages] == ["lead_selected", "draft_preview", "status"]
    assert [entry[2] for entry in conversation_logs] == [message["text"] for message in result["messages"]]
    assert select_calls == [(("user-1", "1"), {"since_timestamp": "2026-01-01T00:00:00+00:00"})]
    assert workflow_calls == [{
        "type": "draft_message", "service": "Outbound automation", "target": "CTOs", "lead": lead,
        "conversation_context": ["Outbound automation", "CTOs", "Reply with a number to pick one"],
    }]
    state = get_store().get_state(session_token)
    assert state.pipeline.leads[0].id == "lead-1"
    assert state.pipeline.leads[0].status == "selected"
    get_store().clear_session(session_token)


def test_select_legacy_workflow_lead_invalid_index_returns_historical_error_envelope(monkeypatch):
    recorded = []
    monkeypatch.setattr(conversation_service, "get_session_context", lambda _user_id: {"started_at": "start"})
    monkeypatch.setattr(conversation_service, "select_lead", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversation_service, "record_workflow_message", lambda **kwargs: recorded.append(kwargs))

    result = conversation_service.select_legacy_workflow_lead_and_draft(
        user_id="user-1", lead_index=9, workflow_session_id="workflow-1", session_token="session-1",
    )

    assert result["ok"] is False
    assert result["messages"][0]["type"] == "error"
    assert result["messages"][0]["text"] == "Could not find that lead. Try searching again."
    assert recorded == []


def test_preview_legacy_workflow_lead_preserves_read_only_intelligence_shape(monkeypatch):
    lead = {"id": "lead-1", "name": "Ada"}
    monkeypatch.setattr(conversation_service, "get_pending_leads", lambda *args, **kwargs: [lead])
    monkeypatch.setattr(conversation_service, "get_enricher", lambda: SimpleNamespace(
        health_check=lambda: {"ok": True}, enrich_lead=lambda value: {"company": value["name"]},
    ))
    monkeypatch.setattr(conversation_service, "generate_lead_intelligence", lambda lead_value, company: {
        "lead_id": lead_value["id"], "company": company["company"],
    })

    result = conversation_service.preview_legacy_workflow_lead_intelligence(user_id="user-1", lead_index=1)

    assert result == {"ok": True, "lead_intelligence": {"lead_id": "lead-1", "company": "Ada"}}
    assert lead == {"id": "lead-1", "name": "Ada"}
    assert conversation_service.preview_legacy_workflow_lead_intelligence(user_id="user-1", lead_index=2) == {
        "ok": False, "error": "Invalid lead index",
    }


def test_select_route_uses_bearer_session_and_translates_invalid_selection(monkeypatch):
    from services.conversations import compatibility

    seen = {}
    def fake_get_web_session(token):
        seen["lookup_token"] = token
        return {"id": "user-1"}

    def fake_ensure_workflow_session(**kwargs):
        seen["workflow"] = kwargs
        return "workflow-1"

    def fake_select_legacy_workflow_lead_and_draft(**kwargs):
        seen["service"] = kwargs
        return {"ok": False, "messages": [{"text": "Could not find that lead. Try searching again."}]}

    monkeypatch.setattr(compatibility, "get_web_session", fake_get_web_session)
    monkeypatch.setattr(compatibility, "ensure_workflow_session", fake_ensure_workflow_session)
    monkeypatch.setattr(conversation_service, "select_legacy_workflow_lead_and_draft", fake_select_legacy_workflow_lead_and_draft)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main_module.select_lead_endpoint("path-token", main_module.SelectLeadRequest(index=8), _request("bearer-token")))

    assert error.value.status_code == 400
    assert error.value.detail == "Could not find that lead. Try searching again."
    assert seen["lookup_token"] == "bearer-token"
    assert seen["workflow"]["session_key"] == "bearer-token"
    assert seen["service"]["user_id"] == "user-1"
    assert seen["service"]["session_token"] == "bearer-token"
