"""Regression test suite for the Copilot API.

Exercises the real HTTP endpoints via TestClient.
Mocks only the OpenAI call so tests are deterministic and cost-free.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_openai(monkeypatch):
    """Mock OpenAI calls so the Copilot endpoint returns deterministic text."""

    def mock_send_openai(*args, **kwargs):
        return "I see you're on Mission Control. What would you like to do?"

    import services.conversational_response_generator as crg
    monkeypatch.setattr(crg, "_send_openai_request", mock_send_openai)


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def session_token(client):
    resp = client.post("/api/web/session", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    return data["session_token"]


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_contains_expected_keys(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body
        assert "version" in body


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
            data="not valid json",
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
