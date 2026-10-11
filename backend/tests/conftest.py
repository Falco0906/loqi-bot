"""Shared fixtures for backend tests."""

import os
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

# Establish process-owned test mode before importing main/services. Mutating
# LOQI_TEST_MODE later cannot disable the shared runtime guard.
os.environ["LOQI_TEST_MODE"] = "1"
from services.platform.test_runtime import activate_test_runtime

activate_test_runtime()

import main as main_module
import services.identity.dependencies as identity_dependencies
from tests.supabase_test_safety import (
    OwnedRecordCleanup,
    validate_supabase_test_configuration,
)

def pytest_collection_modifyitems(config, items):
    """Database and external integration tests are opt-in independently."""
    skip_db = pytest.mark.skip(reason=(
        "requires_db tests need LOQI_RUN_DB_INTEGRATION=1 and approved dedicated test credentials"
    ))
    skip_external = pytest.mark.skip(reason=(
        "integration tests need LOQI_RUN_EXTERNAL_INTEGRATION=1 and a dedicated integration environment"
    ))
    for item in items:
        if item.get_closest_marker("requires_local_postgres") and os.getenv("LOQI_TEST_POSTGRES_ENABLED") != "1":
            item.add_marker(pytest.mark.skip(reason="Local PostgreSQL tests require separate explicit opt-in and target approval"))
        if item.get_closest_marker("requires_db") and os.getenv("LOQI_RUN_DB_INTEGRATION") != "1":
            item.add_marker(skip_db)
        if item.get_closest_marker("integration") and os.getenv("LOQI_RUN_EXTERNAL_INTEGRATION") != "1":
            item.add_marker(skip_external)


@pytest.fixture(scope="session")
def supabase_test_configuration():
    if os.getenv("LOQI_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Supabase integration tests require explicit opt-in")
    return validate_supabase_test_configuration()


@pytest.fixture(scope="session")
def supabase_integration_client(supabase_test_configuration):
    """Create a client only after validating dedicated test-only configuration."""
    from services.platform.test_runtime import create_supabase_client

    client = create_supabase_client(
        supabase_test_configuration.url,
        supabase_test_configuration.key,
        authorization=supabase_test_configuration,
    )
    yield client


@pytest.fixture(autouse=True)
def _require_explicit_external_integration_environment(request):
    """A marker alone never authorizes provider integration execution."""
    if request.node.get_closest_marker("integration"):
        if (os.getenv("LOQI_RUN_EXTERNAL_INTEGRATION") != "1"
                or os.getenv("LOQI_EXTERNAL_INTEGRATION_ENV") != "dedicated"):
            pytest.skip("External integration requires explicit opt-in and a dedicated environment")


@pytest.fixture()
def owned_test_records(supabase_integration_client, supabase_test_configuration):
    """Register exact rows created by an integration test for scoped cleanup."""
    owner = OwnedRecordCleanup(
        supabase_integration_client,
        supabase_test_configuration,
    )
    try:
        yield owner
    finally:
        owner.cleanup()


@pytest.fixture()
def test_run_id(owned_test_records):
    return owned_test_records.test_run_id


@pytest.fixture()
def durable_test_identity(owned_test_records):
    """Create a fresh per-test identity; never reuse or clean a shared identity."""
    return owned_test_records.create_identity()


@pytest.fixture()
def shared_test_identity(durable_test_identity):
    """Compatibility name for tests now receiving a unique identity per test."""
    return durable_test_identity


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


@pytest.fixture(autouse=True)
def _reset_persistence_provider_between_tests(request):
    """Prevent a test-installed fake Supabase provider leaking to another test."""
    from services.persistence import reset_connection_manager, reset_repository_provider
    from services.persistence.database import SupabaseConnectionManager, set_connection_manager
    from services.platform import supabase as supabase_module

    supabase_module.install_validated_test_client(None)
    reset_connection_manager()
    reset_repository_provider()
    if request.node.get_closest_marker("requires_db"):
        client = request.getfixturevalue("supabase_integration_client")
        authorization = request.getfixturevalue("supabase_test_configuration")
        supabase_module.install_validated_test_client(client, authorization)
        set_connection_manager(SupabaseConnectionManager(client=client, authorization=authorization))
    try:
        yield
    finally:
        supabase_module.install_validated_test_client(None)
        reset_connection_manager()
        reset_repository_provider()


@pytest.fixture(autouse=True)
def _block_network_for_offline_tests(request, monkeypatch):
    """Reject accidental socket connections from ordinary tests and their setup."""
    import socket

    if request.node.get_closest_marker("requires_db"):
        request.getfixturevalue("supabase_test_configuration")
        return
    if (request.node.get_closest_marker("integration")
            and os.getenv("LOQI_RUN_EXTERNAL_INTEGRATION") == "1"
            and os.getenv("LOQI_EXTERNAL_INTEGRATION_ENV") == "dedicated"):
        return

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("Network connections are disabled for offline tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


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
