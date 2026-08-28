"""Tests for single-identity web session mapping.

An authenticated user must never receive a second users row when a web
session is created. The web session binds to the authenticated user's
existing row and resolves back to it through the durable
workflow_sessions mapping.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import services.conversation_store as store
import services.conversation_engine as engine_module
import main as main_module

OAUTH_USER_ID = "oauth:google:subject-123"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def execute(self):
        return MagicMock(data=self._rows)


def _supabase_client(*, users_rows=None, workflow_rows=None):
    client = MagicMock()

    def select(table):
        if table == "users":
            q = MagicMock()
            q.select.return_value.eq.return_value.limit.return_value = _Rows(
                users_rows or []
            )
            return q
        if table == "workflow_sessions":
            q = MagicMock()
            q.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value = (
                _Rows(workflow_rows or [])
            )
            return q
        raise AssertionError(f"unexpected table: {table}")

    client.table.side_effect = select
    return client


class _LegacyUserTable:
    def __init__(self, rows):
        self.rows = rows
        self._selected_id = ""
        self.inserted: list[dict] = []

    def select(self, _fields):
        return self

    def eq(self, _field, value):
        self._selected_id = value
        return self

    def limit(self, _value):
        return self

    def insert(self, payload):
        self.inserted.append(payload)
        self.rows.append(dict(payload))
        return self

    def execute(self):
        if self.inserted and self.rows[-1] == self.inserted[-1]:
            return MagicMock(data=[self.rows[-1]])
        return MagicMock(data=[row for row in self.rows if row.get("id") == self._selected_id])


def test_ensure_legacy_user_bridge_uses_authenticated_identity_uuid(monkeypatch):
    from services import supabase

    table = _LegacyUserTable([])
    client = MagicMock()
    client.table.return_value = table
    monkeypatch.setattr(supabase, "get_supabase_client", lambda: client)

    user_id = "5b8f5d21-76b3-49a3-8bc7-f9e6987f14dd"
    row = supabase.ensure_legacy_user_bridge(user_id, "Test User")

    assert row is not None
    assert row["id"] == user_id
    assert table.inserted == [{
        "id": user_id,
        "telegram_id": f"identity:{user_id}",
        "username": "Test User",
    }]

    # Repeated session bootstraps use the same row and do not create a second
    # legacy account.
    same = supabase.ensure_legacy_user_bridge(user_id, "Different Name")
    assert same["id"] == user_id
    assert len(table.inserted) == 1


def test_authenticated_bridge_is_memoized_after_successful_verification(monkeypatch):
    """Repeated session resolution must not add Supabase reads to one request."""
    from services import supabase

    class _IdentityUser:
        display_name = "Ada"

    class _UserService:
        async def get_user(self, user_id):
            assert user_id == OAUTH_USER_ID
            return _IdentityUser()

    bridge_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(main_module.identity_dependencies, "_bridge_verified", {})
    monkeypatch.setattr(
        "services.identity.api.get_auth_user_service", lambda: _UserService(),
    )
    monkeypatch.setattr(
        supabase,
        "ensure_legacy_user_bridge",
        lambda user_id, display_name: (
            bridge_calls.append((user_id, display_name)) or {"id": user_id}
        ),
    )

    asyncio.run(main_module.identity_dependencies.ensure_legacy_user_bridge(OAUTH_USER_ID))
    asyncio.run(main_module.identity_dependencies.ensure_legacy_user_bridge(OAUTH_USER_ID))

    assert bridge_calls == [(OAUTH_USER_ID, "Ada")]


# ─── create_lightweight_web_session ────────────────────────────────────────


def test_authenticated_session_does_not_create_second_user(monkeypatch):
    oauth_row = {"id": OAUTH_USER_ID, "username": "Ada", "google_refresh_token": "tok"}

    def fake_get_user(user_id):
        return oauth_row if user_id == OAUTH_USER_ID else None

    def fail_create(**kwargs):
        raise AssertionError("must not create a channel user for authenticated sessions")

    monkeypatch.setattr(store, "get_user", fake_get_user)
    monkeypatch.setattr(store, "get_or_create_channel_user", fail_create)

    created = store.create_lightweight_web_session(
        display_name="Ada",
        user_id=OAUTH_USER_ID,
    )

    assert created is not None
    assert created["user"]["id"] == OAUTH_USER_ID
    assert created["session_token"]
    assert created["channel"] == "web"


def test_anonymous_session_creates_web_user_row(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "web-user-1", "username": "web-user"}

    monkeypatch.setattr(store, "get_or_create_channel_user", fake_create)

    created = store.create_lightweight_web_session(display_name="Guest")

    assert created is not None
    assert captured["channel"] == "web"
    assert captured["external_user_id"]
    assert created["user"]["id"] == "web-user-1"


def test_authenticated_session_falls_back_when_user_missing(monkeypatch):
    captured = {}

    def fake_get_user(user_id):
        return None

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "web-fallback", "username": "web-user"}

    monkeypatch.setattr(store, "get_user", fake_get_user)
    monkeypatch.setattr(store, "get_or_create_channel_user", fake_create)

    created = store.create_lightweight_web_session(
        display_name="Ada",
        user_id=OAUTH_USER_ID,
    )

    assert created is not None
    assert created["user"]["id"] == "web-fallback"
    assert captured["external_user_id"]


# ─── get_web_session token resolution ──────────────────────────────────────


def test_get_web_session_resolves_token_to_authenticated_user(monkeypatch):
    oauth_row = {"id": OAUTH_USER_ID, "username": "Ada", "google_refresh_token": "tok"}
    client = _supabase_client(
        users_rows=[],
        workflow_rows=[{"user_id": OAUTH_USER_ID}],
    )

    def fake_client():
        return client

    def fake_get_user(user_id):
        return oauth_row if user_id == OAUTH_USER_ID else None

    monkeypatch.setattr(store, "get_supabase_client", fake_client)
    monkeypatch.setattr(store, "get_user", fake_get_user)

    user = store.get_web_session("token-123")

    assert user == oauth_row
    assert user["id"] == OAUTH_USER_ID


def test_get_web_session_prefers_legacy_web_row(monkeypatch):
    web_row = {"id": "web-row-1", "username": "anonymous", "telegram_id": "web:token-1"}
    client = _supabase_client(users_rows=[web_row])

    def fake_client():
        return client

    monkeypatch.setattr(store, "get_supabase_client", fake_client)

    user = store.get_web_session("token-1")

    assert user == web_row


def test_get_web_session_returns_none_without_mapping(monkeypatch):
    client = _supabase_client(users_rows=[], workflow_rows=[])

    monkeypatch.setattr(store, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store, "get_user", lambda user_id: None)

    assert store.get_web_session("unknown-token") is None


# ─── engine.create_web_session binding ─────────────────────────────────────


def test_engine_create_web_session_binds_authenticated_user(monkeypatch):
    calls = {"workflow": None, "logged": [], "welcome": None}

    def fake_lightweight(display_name=None, *, user_id=None):
        return {
            "session_token": "tok-1",
            "user": {"id": user_id or "anon", "username": display_name},
            "channel": "web",
        }

    def fake_ensure(*, user_id, channel, session_key):
        calls["workflow"] = (user_id, channel, session_key)
        return "wf-1"

    def fake_record_event(**kwargs):
        pass

    def fake_record_message(**kwargs):
        pass

    def fake_log_conversation(user_id, role, text):
        calls["logged"].append((user_id, role))

    def fake_generate(**kwargs):
        return "Welcome"

    def fake_variation(messages):
        return "Prompt"

    monkeypatch.setattr(engine_module, "create_lightweight_web_session", fake_lightweight)
    monkeypatch.setattr(engine_module, "ensure_workflow_session", fake_ensure)
    monkeypatch.setattr(engine_module, "record_workflow_event", fake_record_event)
    monkeypatch.setattr(engine_module, "record_workflow_message", fake_record_message)
    monkeypatch.setattr(engine_module, "log_conversation", fake_log_conversation)
    monkeypatch.setattr(
        engine_module, "generate_conversational_response", fake_generate
    )
    monkeypatch.setattr(engine_module, "_get_service_prompt_variation", fake_variation)

    result = engine_module.ConversationEngine().create_web_session(
        display_name="Ada",
        user_id=OAUTH_USER_ID,
    )

    assert result["user_id"] == OAUTH_USER_ID
    assert calls["workflow"] == (OAUTH_USER_ID, "web", "tok-1")
    assert calls["logged"][0][0] == OAUTH_USER_ID


# ─── endpoint-level single-identity guarantee ──────────────────────────────


def test_create_web_session_endpoint_binds_authenticated_identity(monkeypatch, client):
    captured = {}

    def fake_engine_create(display_name=None, *, user_id=None):
        captured["user_id"] = user_id
        return {
            "ok": True,
            "session_token": "tok-ep",
            "user_id": user_id,
            "display_name": display_name,
            "gmail_connected": True,
            "initial_messages": [],
        }

    monkeypatch.setattr(main_module, "engine", MagicMock())
    monkeypatch.setattr(
        main_module.engine, "create_web_session", fake_engine_create
    )

    async def fake_current_auth(request):
        from services.identity.dependencies import AuthContext
        return AuthContext(user_id=OAUTH_USER_ID, session_id="sess-1", organization_id="org-1")

    monkeypatch.setattr(
        "services.identity.dependencies.get_current_auth", fake_current_auth
    )

    async def fake_bridge(user_id):
        captured["bridged_user_id"] = user_id

    monkeypatch.setattr(main_module.identity_dependencies, "ensure_legacy_user_bridge", fake_bridge)

    resp = client.post(
        "/api/web/session",
        json={"display_name": "Ada"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert resp.status_code == 200
    assert captured["user_id"] == OAUTH_USER_ID
    assert captured["bridged_user_id"] == OAUTH_USER_ID
    assert resp.json()["user_id"] == OAUTH_USER_ID


def test_create_web_session_fails_closed_when_legacy_user_bridge_cannot_be_provisioned(
    monkeypatch, client,
):
    created = False

    def fake_engine_create(**_kwargs):
        nonlocal created
        created = True
        return {"ok": True, "session_token": "must-not-exist"}

    monkeypatch.setattr(main_module.engine, "create_web_session", fake_engine_create)

    async def fake_current_auth(_request):
        from services.identity.dependencies import AuthContext
        return AuthContext(user_id=OAUTH_USER_ID, session_id="sess-1", organization_id="org-1")

    monkeypatch.setattr("services.identity.dependencies.get_current_auth", fake_current_auth)

    async def failing_bridge(_user_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Authenticated user provisioning is temporarily unavailable")

    monkeypatch.setattr(main_module.identity_dependencies, "ensure_legacy_user_bridge", failing_bridge)

    response = client.post(
        "/api/web/session",
        json={"display_name": "Ada"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 503
    assert created is False


def test_authenticated_request_does_not_downgrade_bridge_failure_to_another_session(
    monkeypatch,
):
    async def fake_authenticated_user_id(_request):
        return OAUTH_USER_ID

    async def failing_bridge(_user_id):
        raise HTTPException(status_code=503, detail="Authenticated user provisioning is temporarily unavailable")

    monkeypatch.setattr(
        "services.identity.api.get_authenticated_user_id", fake_authenticated_user_id,
    )
    monkeypatch.setattr(main_module.identity_dependencies, "ensure_legacy_user_bridge", failing_bridge)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/discoveries",
        "headers": [(b"authorization", b"Bearer valid-token")],
    })

    from tests.conftest import REAL_RESOLVE_WEB_SESSION

    with pytest.raises(HTTPException) as raised:
        asyncio.run(REAL_RESOLVE_WEB_SESSION(request))

    assert raised.value.status_code == 503


def test_create_web_session_endpoint_anonymous_without_header(monkeypatch, client):
    captured = {}

    def fake_engine_create(display_name=None, *, user_id=None):
        captured["user_id"] = user_id
        return {
            "ok": True,
            "session_token": "tok-anon",
            "user_id": "web:anon",
            "display_name": display_name,
            "gmail_connected": False,
            "initial_messages": [],
        }

    monkeypatch.setattr(main_module, "engine", MagicMock())
    monkeypatch.setattr(
        main_module.engine, "create_web_session", fake_engine_create
    )

    resp = client.post("/api/web/session", json={"display_name": "Guest"})

    assert resp.status_code == 200
    assert captured["user_id"] is None
    assert resp.json()["session_token"] == "tok-anon"


# ─── get_or_create_channel_user / handle_message must not fabricate a row ───


def test_channel_user_resolution_never_creates_for_authenticated_token(monkeypatch):
    oauth_row = {"id": OAUTH_USER_ID, "username": "Ada", "google_refresh_token": "tok"}
    client = _supabase_client(
        users_rows=[],
        workflow_rows=[{"user_id": OAUTH_USER_ID}],
    )
    monkeypatch.setattr(store, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store, "get_user", lambda user_id: oauth_row)

    def fail_create(telegram_id, username=None):
        raise AssertionError("must not create a users row for an authenticated token")

    monkeypatch.setattr(store, "get_or_create_user", fail_create)

    user = store.get_or_create_channel_user(
        channel="web",
        external_user_id="token-abc",
        username="Ada",
    )

    assert user == oauth_row
    assert user["id"] == OAUTH_USER_ID


def test_channel_user_creates_row_only_for_new_anonymous_token(monkeypatch):
    captured = {}
    client = _supabase_client(users_rows=[], workflow_rows=[])
    monkeypatch.setattr(store, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store, "get_user", lambda user_id: None)

    def fake_create(telegram_id, username=None):
        captured["telegram_id"] = telegram_id
        return {"id": "web-new", "telegram_id": telegram_id}

    monkeypatch.setattr(store, "get_or_create_user", fake_create)

    user = store.get_or_create_channel_user(
        channel="web",
        external_user_id="anon-token-1",
        username="Guest",
    )

    assert user["id"] == "web-new"
    assert captured["telegram_id"] == "web:anon-token-1"
