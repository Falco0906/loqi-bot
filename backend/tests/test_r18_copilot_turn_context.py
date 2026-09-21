"""R18-C1 characterization for Copilot turn preparation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_prepare_turn_uses_authenticated_workspace_memory_and_local_intent(monkeypatch):
    from services.copilot import service as copilot_service

    captured: dict[str, object] = {}

    async def resolve_session(_request):
        return "owner-1", "canonical-session-1"

    async def resolve_workspace(_request, user_id):
        assert user_id == "owner-1"
        return SimpleNamespace(workspace_id="workspace-1")

    class Memory:
        async def retrieve(self, **kwargs):
            captured["retrieve"] = kwargs
            return {"conversation_turns": [{"role": "user", "text": "Earlier turn"}]}

        async def record_turn(self, **kwargs):
            captured["record_turn"] = kwargs

    monkeypatch.setattr(copilot_service.identity_dependencies, "resolve_web_session", resolve_session)
    monkeypatch.setattr(copilot_service.workspace_access, "resolve_selected_workspace_context", resolve_workspace)
    monkeypatch.setattr(copilot_service, "CopilotMemoryService", lambda: Memory())
    monkeypatch.setattr(copilot_service, "get_user_preferences", lambda _user_id: {"tone": "concise"})
    def build_workspace_context(*args, **kwargs):
        captured["workspace_context_args"] = (args, kwargs)
        return {"snapshot": {}, "analysis": {}}

    monkeypatch.setattr(
        copilot_service.workspace_context_service,
        "build_workspace_context",
        build_workspace_context,
    )
    monkeypatch.setattr(
        copilot_service,
        "classify_copilot_read_question",
        lambda *_args, **_kwargs: {"intent": "read", "action": "analytics.workspace.summary"},
    )

    prepared = await copilot_service.prepare_copilot_turn(
        request=object(),
        session_token="web-token",
        text="How is my workspace doing?",
        current_page="Mission Control",
        page_context={"workspace_id": "untrusted"},
        message_history=[{"role": "assistant", "text": "How can I help?"}],
        conversation_id="chat-1",
        active_search={"discovery_id": "discovery-1"},
    )

    assert prepared.user_id == "owner-1"
    assert prepared.workspace_id == "workspace-1"
    assert prepared.conversation_key == "chat-1"
    assert captured["retrieve"] == {
        "user_id": "owner-1", "workspace_id": "workspace-1", "conversation_key": "chat-1",
    }
    assert prepared.workspace_context["copilot_memory"]["user_preferences"] == {"tone": "concise"}
    assert prepared.decision == {
        "intent": "read",
        "action": "analytics.workspace.summary",
        "user_message": "How is my workspace doing?",
        "message_history": [
            {"role": "user", "text": "Earlier turn"},
            {"role": "assistant", "text": "How can I help?"},
        ],
        "active_search": {"discovery_id": "discovery-1"},
        "page_context": {"workspace_id": "untrusted"},
        "current_page": "Mission Control",
    }
    assert captured["record_turn"] == {
        "user_id": "owner-1",
        "workspace_id": "workspace-1",
        "conversation_key": "chat-1",
        "user_text": "How is my workspace doing?",
        "intent": "read",
        "tool": "analytics.workspace.summary",
    }


@pytest.mark.asyncio
async def test_prepare_turn_falls_back_to_model_intent_and_hashes_legacy_conversation_key(monkeypatch):
    from services.copilot import service as copilot_service

    async def resolve_session(_request):
        return "owner-1", "canonical-session-1"

    async def resolve_workspace(_request, _user_id):
        return SimpleNamespace(workspace_id="workspace-1")

    class Memory:
        async def retrieve(self, **_kwargs):
            return {}

        async def record_turn(self, **_kwargs):
            return None

    captured: dict[str, object] = {}

    def decide(text, **kwargs):
        captured["decision"] = (text, kwargs)
        return {"intent": "conversation", "action": "", "search_context": {}}

    monkeypatch.setattr(copilot_service.identity_dependencies, "resolve_web_session", resolve_session)
    monkeypatch.setattr(copilot_service.workspace_access, "resolve_selected_workspace_context", resolve_workspace)
    monkeypatch.setattr(copilot_service, "CopilotMemoryService", lambda: Memory())
    monkeypatch.setattr(copilot_service, "get_user_preferences", lambda _user_id: None)
    monkeypatch.setattr(copilot_service.workspace_context_service, "build_workspace_context", lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}})
    monkeypatch.setattr(copilot_service, "classify_copilot_read_question", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(copilot_service, "decide_copilot_intent", decide)

    prepared = await copilot_service.prepare_copilot_turn(
        request=object(), session_token="web-token", text="Hello", current_page="", page_context=None,
        message_history=None, conversation_id="", active_search=None,
    )

    assert prepared.conversation_key.startswith("legacy-")
    assert "web-token" not in prepared.conversation_key
    assert captured["decision"][0] == "Hello"
    assert captured["decision"][1]["active_search"] is None


def test_direct_mutation_gate_requires_explicit_confirmation():
    from services.copilot import service as copilot_service

    pending = copilot_service.gate_direct_tool_execution(
        tool_name="campaign.refine",
        decision={"campaign_id": "campaign-1"},
        user_text="Change the objective",
    )
    confirmed = copilot_service.gate_direct_tool_execution(
        tool_name="campaign.refine",
        decision={"campaign_id": "campaign-1"},
        user_text="Confirm campaign refine",
    )

    assert pending.status == "confirmation_required"
    assert pending.decision.get("confirmed") is None
    assert confirmed.status == "execute"
    assert confirmed.decision["confirmed"] is True


@pytest.mark.asyncio
async def test_execute_boundary_passes_authenticated_scope_to_read_tool(monkeypatch):
    from services.copilot import service as copilot_service

    captured: dict[str, object] = {}

    async def execute_tool(tool_name, **kwargs):
        captured["tool_name"] = tool_name
        captured.update(kwargs)
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {"metrics": {}}}

    monkeypatch.setattr(copilot_service, "execute_copilot_tool", execute_tool)

    result = await copilot_service.execute_tool_at_boundary(
        tool_name="analytics.workspace.summary",
        decision={"action": "analytics.workspace.summary"},
        user_id="owner-1",
        workspace_id="workspace-1",
        session_token="web-session-1",
        request_id="request-1234",
        conversation_key="chat-1",
        request=object(),
    )

    assert result["ok"] is True
    assert captured["tool_name"] == "analytics.workspace.summary"
    assert captured["user_id"] == "owner-1"
    assert captured["workspace_id"] == "workspace-1"
    assert captured["session_token"] == "web-session-1"


@pytest.mark.asyncio
async def test_plan_turn_records_the_orchestration_outcome_once(monkeypatch):
    from services.copilot import service as copilot_service

    captured: dict[str, object] = {}

    class Memory:
        async def record_outcome(self, **kwargs):
            captured["outcome"] = kwargs

    monkeypatch.setattr(copilot_service, "has_multi_step_plan", lambda _decision: True)

    async def execute_plan(_decision, _execute):
        return {
            "ok": True,
            "status": "completed",
            "result": {"campaigns": []},
            "operation": {"id": "operation-1"},
        }

    monkeypatch.setattr(copilot_service, "execute_copilot_plan", execute_plan)

    orchestration = await copilot_service.execute_copilot_plan_turn(
        decision={"intent": "read", "plan": [{"action": "campaign.list"}]},
        user_text="Show campaigns",
        user_id="owner-1",
        workspace_id="workspace-1",
        session_token="web-session-1",
        request_id="request-1234",
        conversation_key="chat-1",
        memory=Memory(),
        request=object(),
    )

    assert orchestration["status"] == "completed"
    assert captured["outcome"] == {
        "user_id": "owner-1",
        "workspace_id": "workspace-1",
        "conversation_key": "chat-1",
        "tool": "copilot.orchestration",
        "status": "completed",
        "operation": {"id": "operation-1"},
    }


@pytest.mark.asyncio
async def test_prepared_turn_keeps_the_generic_response_envelope(monkeypatch):
    """C4: response translation stays at the Copilot application boundary."""
    from services.copilot import service as copilot_service

    class Memory:
        async def record_outcome(self, **_kwargs):
            raise AssertionError("a conversational turn must not record a tool outcome")

    prepared = copilot_service.PreparedCopilotTurn(
        user_id="owner-1",
        workspace_id="workspace-1",
        session_token="web-session-1",
        conversation_key="chat-1",
        memory=Memory(),
        workspace_context={"snapshot": {}, "analysis": {}},
        decision={"intent": "conversation", "action": "", "message_history": []},
        message_history=[],
    )
    monkeypatch.setattr(copilot_service, "has_multi_step_plan", lambda _decision: False)
    monkeypatch.setattr(copilot_service, "select_copilot_tool", lambda _decision: None)
    monkeypatch.setattr(copilot_service, "generate_copilot_response", lambda **_kwargs: "Grounded response.")

    response = await copilot_service.execute_prepared_copilot_turn(
        prepared=prepared,
        user_text="What should I do next?",
        copilot_context={"current_page": "Mission Control", "message_history": []},
        legacy_user_id="legacy-user-1",
        request_id="request-1",
        request=object(),
    )

    assert response["ok"] is True
    assert response["intent"] == "conversation"
    assert response["events"] == []
    assert response["messages"][0]["role"] == "assistant"
    assert response["messages"][0]["type"] == "text"
    assert response["messages"][0]["text"] == "Grounded response."
