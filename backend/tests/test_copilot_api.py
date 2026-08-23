"""Regression test suite for the Copilot API.

Exercises the real HTTP endpoints via TestClient.
Mocks only the OpenAI call so tests are deterministic and cost-free.
Fixtures are in conftest.py.
"""

import pytest
import main as main_module
from types import SimpleNamespace


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_contains_expected_keys(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body
        assert "version" in body


class TestCopilotOperationBoundary:
    def test_discovery_title_is_natural_and_separate_from_provider_query(self):
        title = main_module._discovery_title_from_search_context
        assert title({"industry": ["cafe"]}) == "Cafe leads"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"]}) == "Cafe owners"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"], "location": ["Hyderabad"]}) == "Cafe owners in Hyderabad"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"], "location": ["Hyderabad"], "quantity": 100}) == "100 cafe owners in Hyderabad"

    def test_intent_contract_supports_conversation_read_and_unsupported_action(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent

        decisions = iter([
            '{"intent":"conversation","mode":"new","search_context":{},"reason":"greeting"}',
            '{"intent":"read","mode":"new","search_context":{},"reason":"existing results"}',
            '{"intent":"action","mode":"new","search_context":{},"action":"campaign.create","reason":"create campaign"}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        assert decide_copilot_intent("hi")["intent"] == "conversation"
        assert decide_copilot_intent("what did you find?", active_search={"discovery_id": "d-1"})["intent"] == "read"
        action = decide_copilot_intent("create a campaign for these")
        assert action["intent"] == "action"
        assert action["action"] == "campaign.create"

    def test_conversation_response_ignores_active_workspace_operations(self):
        from services.conversational_response_generator import generate_copilot_response

        response = generate_copilot_response(
            "hi",
            copilot_context={
                "intent": "conversation",
                "workspace_context": {
                    "snapshot": {"total_leads": 30},
                    "analysis": {"recommended_next_action": {"title": "Create a campaign"}},
                },
                "active_search": {"discovery_id": "d-1"},
                "available_actions": ["launch_campaign", "generate_drafts"],
            },
        )
        assert response == "I’m here to help with your Loqi workspace. What would you like to work on?"
        assert "campaign" not in response.lower()

    @pytest.mark.asyncio
    async def test_tool_boundary_does_not_execute_for_conversation_or_read(self, monkeypatch):
        from services.copilot_tools import execute_copilot_tool, select_copilot_tool

        assert select_copilot_tool({"intent": "conversation"}) is None
        monkeypatch.setattr(
            "services.discovery.get_discovery",
            lambda _discovery_id, _workspace_id: {
                "id": "d-1", "status": "completed", "title": "Restaurant leads",
                "discovery_leads": [{"rank": 1, "workspace_lead": {"lead": {"name": "A"}}}],
                "discovery_companies": [], "summary": {"lead_count": 1},
            },
        )

        async def must_not_run(*_args, **_kwargs):
            raise AssertionError("Discovery runner must not run for a read")

        result = await execute_copilot_tool(
            "discovery.read",
            user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={"intent": "read", "active_search": {"discovery_id": "d-1"}},
            discovery_runner=must_not_run,
        )
        assert result["ok"] is True
        assert result["result"]["lead_count"] == 1

    @pytest.mark.asyncio
    async def test_discovery_and_refinement_use_executor_runner(self):
        from services.copilot_tools import execute_copilot_tool
        calls = []

        async def runner(user_id, context, session):
            calls.append((user_id, context, session))
            return {"discovery_id": "d-1", "job_id": "j-1", "status": "queued"}

        result = await execute_copilot_tool(
            "discovery.refine",
            user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={"intent": "discovery_refinement", "search_context": {"industry": ["restaurants"]}},
            discovery_runner=runner,
        )
        assert result["ok"] is True
        assert calls == [("u-1", {"industry": ["restaurants"]}, "s-1")]

    @pytest.mark.asyncio
    async def test_endpoint_conversation_and_read_never_create_discovery(self, monkeypatch):
        decisions = iter([
            {"intent": "conversation", "mode": "new", "search_context": {}, "reason": "greeting"},
            {"intent": "read", "mode": "new", "search_context": {}, "reason": "read results"},
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: next(decisions),
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}))
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")
        monkeypatch.setattr(main_module, "_create_search_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("read/conversation must not create Discovery")))
        monkeypatch.setattr("services.discovery.get_discovery", lambda *_args: {"id": "d-1", "status": "completed", "title": "Restaurant leads", "discovery_leads": [], "discovery_companies": [], "summary": {}})
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(text="hi", copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]))
        conversation = await main_module.post_web_session_message("session-1", payload, request)
        assert conversation["intent"] == "conversation"
        assert "operation" not in conversation
        conversation_text = conversation["messages"][0]["text"]
        assert "campaign" not in conversation_text.lower()
        assert "<<action:" not in conversation_text
        payload.text = "what did you find?"
        payload.copilot.active_search = {"discovery_id": "d-1"}
        read = await main_module.post_web_session_message("session-1", payload, request)
        assert read["intent"] == "read"
        assert read["read_result"]["discovery_id"] == "d-1"

    @pytest.mark.asyncio
    async def test_discovery_tool_failure_is_structured(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "discovery", "mode": "new", "search_context": {"industry": ["restaurants"]}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}))
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")
        async def fail_runner(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")
        monkeypatch.setattr(main_module, "_run_copilot_discovery", fail_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(text="I need restaurant leads", copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]))
        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is False
        assert result["operation"]["status"] == "failed"

    def test_agent_intent_router_distinguishes_action_and_refinements(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent

        decisions = iter([
            '{"intent":"lead_discovery","mode":"new","search_context":{"industry":["restaurants"],"location":[],"decision_makers":[],"quantity":null}}',
            '{"intent":"lead_discovery","mode":"refine","search_context":{"industry":["restaurants"],"location":["Hyderabad"],"decision_makers":[],"quantity":null}}',
            '{"intent":"lead_discovery","mode":"refine","search_context":{"industry":["restaurants"],"location":["Hyderabad"],"decision_makers":[],"quantity":100}}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        history = [{"role": "user", "text": "I need restaurant leads"}]
        first = decide_copilot_intent("I need restaurant leads", message_history=[])
        second = decide_copilot_intent("Make it Hyderabad", message_history=history)
        third = decide_copilot_intent("Actually give me 100", message_history=history + [{"role": "user", "text": "Make it Hyderabad"}])
        assert [first["intent"], second["intent"], third["intent"]] == ["discovery"] * 3
        assert second["search_context"]["location"] == ["Hyderabad"]
        assert third["search_context"]["quantity"] == 100

    @pytest.mark.asyncio
    async def test_endpoint_returns_real_discovery_operation_for_explicit_request(self, monkeypatch):
        async def fake_knowledge(*_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"items": [], "sources": []})

        async def fake_create_search_run(user_id, query, session, *, display_title=None):
            assert user_id == "owner-1"
            assert query == "Find leads matching industries: restaurants"
            assert session == "session-1"
            assert display_title == "Restaurant leads"
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "discovery",
                "mode": "new",
                "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None},
                "reason": "explicit operation",
            },
        )

        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(
            main_module.engine,
            "handle_message",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy engine must not receive Copilot requests")),
        )
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", fake_knowledge)
        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)

        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="I need new restaurant leads",
            copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)

        assert result["operation"]["kind"] == "search_discovery"
        assert result["operation"]["discovery_id"] == "discovery-1"
        assert result["operation"]["job_id"] == "job-1"

    @pytest.mark.asyncio
    async def test_copilot_bootstrap_does_not_fall_into_legacy_engine(self, monkeypatch):
        summaries = iter([None, {"user_id": "owner-1", "display_name": "user"}])
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: next(summaries))
        monkeypatch.setattr(main_module.engine, "create_web_session", lambda **_kwargs: {"session_token": "created-session"})
        monkeypatch.setattr(
            main_module.engine,
            "handle_message",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy engine must not receive Copilot bootstrap")),
        )
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "discovery", "mode": "new", "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None}, "reason": "explicit operation"},
        )
        async def empty_knowledge(*_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"items": [], "sources": []})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", empty_knowledge)
        async def fake_create_search_run(_user_id, _query, _session, **_kwargs):
            return {"discovery_id": "discovery-2", "job_id": "job-2", "status": "queued"}
        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)

        request = SimpleNamespace(headers=SimpleNamespace(get=lambda _key, default="": default))
        payload = main_module.SendWebMessageRequest(
            text="I need restaurant leads",
            copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]),
        )
        result = await main_module.post_web_session_message("missing-session", payload, request)
        assert result["operation"]["job_id"] == "job-2"


class TestSessionCreation:
    def test_session_token_exists(self, client):
        resp = client.post("/api/web/session", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_token" in data

    def test_session_token_non_empty(self, client):
        resp = client.post("/api/web/session", json={})
        data = resp.json()
        assert len(data["session_token"]) > 0


class TestCopilotMessage:
    def test_copilot_message_returns_200(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        assert resp.status_code == 200

    def test_copilot_message_ok_true(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert data["ok"] is True

    def test_copilot_messages_is_array(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert isinstance(data["messages"], list)

    def test_copilot_messages_non_empty(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert len(data["messages"]) > 0

    def test_copilot_last_message_role_assistant(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        last = data["messages"][-1]
        assert last["role"] == "assistant"

    def test_copilot_last_message_text_non_empty(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        last = data["messages"][-1]
        assert len(last["text"]) > 0


class TestStructuredContext:
    def test_structured_context_returns_200(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Show restaurant leads",
                "copilot": {
                    "current_page": "Discovery",
                    "page_context": {"selected_count": 3},
                    "available_actions": ["select_all"],
                },
            },
        )
        assert resp.status_code == 200

    def test_structured_context_valid_response(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Show restaurant leads",
                "copilot": {
                    "current_page": "Discovery",
                    "page_context": {"selected_count": 3},
                    "available_actions": ["select_all"],
                },
            },
        )
        data = resp.json()
        assert data["ok"] is True
        assert len(data["messages"]) > 0
        assert data["messages"][-1]["role"] == "assistant"

    def test_explicit_lead_request_starts_canonical_discovery_job(self, client, session_token, monkeypatch):
        calls = []

        async def fake_create_search_run(user_id, query, session, **_kwargs):
            calls.append((user_id, query, session))
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "discovery",
                "mode": "new",
                "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None},
                "reason": "explicit operation",
            },
        )

        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "I need new restaurant leads",
                "copilot": {
                    "current_page": "Mission Control",
                    "message_history": [],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["operation"] == {
            "kind": "search_discovery",
            "discovery_id": "discovery-1",
            "job_id": "job-1",
            "status": "queued",
        }
        assert calls and calls[0][1] == "I need new restaurant leads"

class TestUnknownSession:
    def test_unknown_session_returns_valid_response(self, client):
        token = "nonexistent-session-token-12345"
        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is True

    def test_unknown_session_produces_messages(self, client):
        token = "nonexistent-session-token-12345"
        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) > 0


class TestInvalidPayload:
    def test_missing_text_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={},
        )
        assert resp.status_code == 422

    def test_invalid_json_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


COPILOT_PAYLOADS = [
    {
        "text": "Hello",
        "copilot": {
            "current_page": "Mission Control",
            "page_context": {},
            "available_actions": [],
        },
    },
    {
        "text": "Show leads",
        "copilot": {
            "current_page": "Discovery",
            "page_context": {"count": 5},
            "available_actions": ["select_all", "export"],
        },
    },
    {
        "text": "Help me",
        "copilot": {
            "current_page": "Compose",
            "page_context": {"draft_id": "abc"},
            "available_actions": [],
        },
    },
]


@pytest.fixture(scope="module")
def _schema_responses(client, session_token):
    return [
        client.post(
            f"/api/web/session/{session_token}/messages",
            json=p,
        )
        for p in COPILOT_PAYLOADS
    ]


class TestResponseSchema:
    """Assert every successful copilot response has the required schema."""

    def test_ok_field_present(self, _schema_responses):
        for resp in _schema_responses:
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    def test_messages_field_present(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            assert "messages" in data
            assert isinstance(data["messages"], list)

    def test_events_field_present(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            assert "events" in data
            assert isinstance(data["events"], list)

    def test_each_message_has_required_fields(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            for msg in data["messages"]:
                assert "role" in msg
                assert "type" in msg
                assert "text" in msg
                assert msg["role"] == "assistant"
                assert len(msg["text"]) > 0
