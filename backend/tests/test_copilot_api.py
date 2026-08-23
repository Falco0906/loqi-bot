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
    def test_agent_intent_router_distinguishes_action_and_refinements(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent

        decisions = iter([
            '{"intent":"lead_discovery","query":"restaurant leads","reason":"explicit operation"}',
            '{"intent":"lead_discovery","query":"restaurant leads in Hyderabad","reason":"location refinement"}',
            '{"intent":"lead_discovery","query":"restaurant leads in Hyderabad, 100 leads","reason":"quantity refinement"}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        history = [{"role": "user", "text": "I need restaurant leads"}]
        first = decide_copilot_intent("I need restaurant leads", message_history=[])
        second = decide_copilot_intent("Make it Hyderabad", message_history=history)
        third = decide_copilot_intent("Actually give me 100", message_history=history + [{"role": "user", "text": "Make it Hyderabad"}])
        assert [first["intent"], second["intent"], third["intent"]] == ["lead_discovery"] * 3
        assert second["query"] == "restaurant leads in Hyderabad"
        assert "100" in third["query"]

    @pytest.mark.asyncio
    async def test_endpoint_returns_real_discovery_operation_for_explicit_request(self, monkeypatch):
        async def fake_knowledge(*_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"items": [], "sources": []})

        async def fake_create_search_run(user_id, query, session):
            assert user_id == "owner-1"
            assert query == "I need new restaurant leads"
            assert session == "session-1"
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "lead_discovery",
                "query": "I need new restaurant leads",
                "reason": "explicit operation",
            },
        )

        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
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

        async def fake_create_search_run(user_id, query, session):
            calls.append((user_id, query, session))
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "lead_discovery", "query": "I need new restaurant leads", "reason": "explicit operation"},
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
