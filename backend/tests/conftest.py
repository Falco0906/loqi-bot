"""Shared fixtures for backend tests."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_openai(monkeypatch):
    """Mock OpenAI calls so endpoints return deterministic text.

    Returns context-aware responses so integration tests can verify
    that workspace data actually reaches the LLM prompt.
    """
    import services.ai as ai_mod

    _call_count: int = 0

    def mock_send_openai(system: str, user_text: str, **kwargs) -> str:
        nonlocal _call_count
        _call_count += 1

        context_lower = (system + " " + user_text).lower()

        # For executive brief — return valid JSON
        if "write a brief" in context_lower:
            return (
                '{"greeting": "Good afternoon", '
                '"lines": ["Tech Founders Outreach has 2 drafts pending review.", '
                '"SaaS Pilot Campaign is waiting in planning."], '
                '"suggestion": "Review the pending drafts first."}'
            )

        # For recommendation engine — return JSON array
        if "recommendation" in context_lower:
            return (
                '[{"observation": "Tech Founders Outreach has 2 pending drafts.", '
                '"reason": "Approving them moves the campaign closer to launch.", '
                '"action": "Review Drafts", '
                '"confidence": "high", '
                '"type": "review_drafts", '
                '"link": "/draft"}]'
            )

        # For copilot — reference workspace context
        if "campaign" in context_lower and ("should" in context_lower or "next" in context_lower):
            return (
                "Tech Founders Outreach has 2 drafts pending. "
                "I recommend reviewing those before moving to the next step. "
                "What would you like to do?"
            )

        return "I see you're on Mission Control. What would you like to do?"

    monkeypatch.setattr(ai_mod, "_send_openai_request", mock_send_openai)


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
