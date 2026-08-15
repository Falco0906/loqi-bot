"""Shared fixtures for backend tests."""

import re

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import main as main_module

# Captured BEFORE any test patches, so the security suite can exercise the
# real authentication resolver directly.
REAL_RESOLVE_SESSION_CONTEXT = main_module._resolve_session_context


@pytest.fixture(autouse=True)
def _session_auth_shim(monkeypatch):
    """PR10.8.3.1: route authentication reads the Authorization header only.

    In tests we resolve any present Bearer token to a deterministic owner so
    the rest of the suite does not depend on a live Supabase session. Requests
    WITHOUT a header still fail with 401 (fail closed), preserving the auth
    behavior the security suite asserts. The security suite tests the REAL
    resolver directly via ``_REAL_RESOLVE_SESSION_CONTEXT``.
    """
    import main as main_module

    real_resolve = main_module._resolve_session_context

    async def _test_resolve_session_context(request):
        token = main_module._session_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            return await real_resolve(request)
        except HTTPException:
            # Fake/synthetic test tokens resolve to a deterministic owner.
            return "test-owner", token

    monkeypatch.setattr(
        main_module, "_resolve_session_context", _test_resolve_session_context,
    )
    yield


class _AuthTestClient(TestClient):
    """TestClient that injects Authorization: Bearer from the URL token.

    Test-only shim: the backend ignores URL-path session tokens and reads the
    header. This keeps existing tests that build ``/api/web/session/{token}/...``
    URLs working without reproducing the insecure URL-token auth in the product.
    """

    def request(self, method: str, url: str, **kwargs):
        if "/api/web/session/" in url:
            match = re.search(r"/api/web/session/([^/?]+)", url)
            if match and match.group(1) != "_":
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("Authorization", f"Bearer {match.group(1)}")
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def _isolate_conversation_persistence(monkeypatch, tmp_path):
    """Point conversation persistence at a temp file and reset the store.

    The conversation store persists every mutation to disk; without this
    fixture, tests would write to (and read from) the real dev state file.
    """
    from services.conversations import persistence
    from services.conversations.conversation_store import conversation_store

    monkeypatch.setattr(persistence, "STATE_FILE", str(tmp_path / ".conversations.json"))
    conversation_store.reload()
    yield
    conversation_store.reload()


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
    return _AuthTestClient(app)


@pytest.fixture(scope="module")
def session_token(client):
    resp = client.post("/api/web/session", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    return data["session_token"]
