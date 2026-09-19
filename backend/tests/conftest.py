"""Shared fixtures for backend tests."""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import main as main_module
import services.identity.dependencies as identity_dependencies


# This row is intentionally durable across test runs.  Cleanup below may only
# delete rows tied to this exact UUID; it never deletes an identity user.
SHARED_TEST_USER_ID = "00000000-0000-4000-8000-000000000001"
SHARED_TEST_EMAIL = "test-fixture@loqi.internal"


def _rows(client, table: str, column: str, value: str) -> list[dict]:
    response = client.table(table).select("id").eq(column, value).execute()
    return list(getattr(response, "data", None) or [])


def _delete_owned_test_data(client, user_id: str = SHARED_TEST_USER_ID) -> None:
    """Delete only data attributable to the fixed integration-test identity.

    Workspace deletion relies on the database's workspace-owned cascades.
    Session/message rows are removed explicitly because they predate that
    workspace graph.  The identity row is deliberately never deleted.
    """
    if user_id != SHARED_TEST_USER_ID:
        raise AssertionError("test cleanup may only target the shared test identity")

    session_ids = [row["id"] for row in _rows(client, "workflow_sessions", "user_id", user_id)]
    for session_id in session_ids:
        client.table("workflow_messages").delete().eq("workflow_session_id", session_id).execute()
        client.table("workflow_events").delete().eq("workflow_session_id", session_id).execute()

    # These predicates are deliberately exact, never prefix/pattern based.
    client.table("web_session_bindings").delete().eq("canonical_user_id", user_id).execute()
    client.table("sessions").delete().eq("user_id", user_id).execute()
    client.table("password_reset_requests").delete().eq("user_id", user_id).execute()
    client.table("notifications").delete().eq("user_id", user_id).execute()
    client.table("workflow_sessions").delete().eq("user_id", user_id).execute()
    client.table("workspaces").delete().eq("owner_user_id", user_id).execute()
    client.table("workspace_members").delete().eq("user_id", user_id).execute()
    # The legacy bridge is test-owned state. Deleting it cascades its jobs.
    client.table("users").delete().eq("id", user_id).execute()


def _ensure_shared_test_identity(client) -> str:
    rows = _rows(client, "identity_users", "id", SHARED_TEST_USER_ID)
    if not rows:
        client.table("identity_users").insert({
            "id": SHARED_TEST_USER_ID,
            "display_name": "Loqi Test Fixture",
            "email": SHARED_TEST_EMAIL,
        }).execute()
    return SHARED_TEST_USER_ID


@pytest.fixture(scope="session")
def durable_test_identity():
    """One reusable live-Supabase identity, reset without changing its ID."""
    from services.platform.supabase import get_supabase_client

    client = get_supabase_client()
    if client is None:
        pytest.skip("live Supabase integration fixture requires configured Supabase")
    user_id = _ensure_shared_test_identity(client)
    _delete_owned_test_data(client, user_id)
    yield user_id
    _delete_owned_test_data(client, user_id)


@pytest.fixture()
def shared_test_identity(durable_test_identity):
    """Provide an empty owned-data graph for one live integration test."""
    from services.platform.supabase import get_supabase_client

    client = get_supabase_client()
    assert client is not None
    _delete_owned_test_data(client, durable_test_identity)
    yield durable_test_identity
    _delete_owned_test_data(client, durable_test_identity)


@pytest.fixture()
def shared_authenticated_session(client, monkeypatch, shared_test_identity):
    """Create one authenticated web session bound to the stable test user."""
    async def current_auth(_request):
        return SimpleNamespace(user_id=shared_test_identity, session_id="shared-test-session")

    monkeypatch.setattr(identity_dependencies, "get_current_auth", current_auth)
    response = client.post(
        "/api/web/session",
        json={"display_name": "Loqi Test Fixture"},
        headers={"Authorization": "Bearer shared-test-token"},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]

# Captured BEFORE any test patches, so the security suite can exercise the
# real authentication resolver directly.
REAL_RESOLVE_WEB_SESSION = identity_dependencies.resolve_web_session


@pytest.fixture(autouse=True)
def _session_auth_shim(monkeypatch):
    """PR10.8.3.1: route authentication reads the Authorization header only.

    In tests we resolve any present Bearer token to a deterministic owner so
    the rest of the suite does not depend on a live Supabase session. Requests
    WITHOUT a header still fail with 401 (fail closed), preserving the auth
    behavior the security suite asserts. The security suite tests the real
    canonical resolver directly via ``REAL_RESOLVE_WEB_SESSION``.
    """
    import main as main_module

    real_resolve = identity_dependencies.resolve_web_session

    async def _test_resolve_web_session(request):
        token = identity_dependencies.web_session_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            return await real_resolve(request)
        except HTTPException:
            # Fake/synthetic test tokens resolve to a deterministic owner.
            return "test-owner", token

    monkeypatch.setattr(
        identity_dependencies, "resolve_web_session", _test_resolve_web_session,
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
    # Some security tests deliberately set APP_ENV=production. Their isolated
    # temp snapshot must remain available; this test-only override does not
    # change production's fail-closed persistence behavior.
    monkeypatch.setenv("LOQI_ALLOW_LOCAL_CONVERSATION_SNAPSHOTS", "true")
    # Unit and route tests must not probe the configured Supabase project just
    # to reset their local conversation fixture. Tests for the durable adapter
    # explicitly replace this seam with their own fake client.
    monkeypatch.setattr(persistence, "_client", lambda: None)
    conversation_store.reload()
    yield
    conversation_store.reload()


@pytest.fixture(autouse=True)
def _mock_openai(monkeypatch):
    """Mock OpenAI calls so endpoints return deterministic text.

    Returns context-aware responses so integration tests can verify
    that workspace data actually reaches the LLM prompt.
    """
    import services.intelligence.ai as ai_mod

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
    monkeypatch.setattr(ai_mod, "try_send_openai_request", mock_send_openai)


@pytest.fixture(scope="module")
def client():
    from main import app
    return _AuthTestClient(app)


@pytest.fixture(scope="module")
def session_token(client):
    """Local compatibility session for unit/route tests without live DB setup."""
    resp = client.post("/api/web/session", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    return data["session_token"]
