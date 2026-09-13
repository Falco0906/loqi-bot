"""R17-0 characterization for the legacy web provider/Gmail route family.

These tests freeze the route envelopes and authorization outcomes before the
provider application boundary is extracted from ``main.py``.  They deliberately
mock only provider/Supabase transport seams: the route handlers and their
current orchestration remain under test.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import main as main_module
from services.communication import api as provider_api
from services.communication import service as provider_service
import services.supabase as supabase_module
from services.communication.communication_store import store as communication_store
from services.communication.provider_models import (
    CommunicationProvider,
    ProviderStatus,
    ProviderType,
    SyncResult,
)
from services.world_model import EventType as WMEventType


OWNER_ID = "r17-provider-owner"


def _request() -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": "Bearer r17-token" if key == "authorization" else default
    return request


def _provider(provider_id: str = "provider-r17") -> CommunicationProvider:
    return CommunicationProvider(
        id=provider_id,
        provider_type=ProviderType.GMAIL,
        user_id=OWNER_ID,
        status=ProviderStatus.HEALTHY,
        metadata={"email": "owner@example.test"},
        created_at="2026-01-01T00:00:00+00:00",
        last_sync="2026-01-02T00:00:00+00:00",
        sync_cursor="cursor-r17",
    )


@pytest.fixture(autouse=True)
def _reset_provider_runtime():
    communication_store._providers.clear()
    communication_store._cursors.clear()
    communication_store._thread_mappings.clear()
    communication_store._by_conversation.clear()
    communication_store._seen_message_ids.clear()
    communication_store._user_providers.clear()
    communication_store._recent_messages.clear()
    yield
    communication_store._providers.clear()
    communication_store._cursors.clear()
    communication_store._thread_mappings.clear()
    communication_store._by_conversation.clear()
    communication_store._seen_message_ids.clear()
    communication_store._user_providers.clear()
    communication_store._recent_messages.clear()


@pytest.fixture()
def owner(monkeypatch):
    async def authenticated_user_id(_request, _session_token):
        return OWNER_ID

    monkeypatch.setattr(
        main_module.identity_dependencies,
        "authenticated_user_id",
        authenticated_user_id,
    )
    monkeypatch.setattr(
        main_module.identity_dependencies,
        "web_session_token",
        lambda _request: "r17-token",
    )


def test_provider_route_registration_contract():
    routes = {
        path: {method.upper() for method in operations}
        for path, operations in main_module.app.openapi()["paths"].items()
        if path.startswith("/api/web/session/{session_token}/providers")
    }

    assert routes == {
        "/api/web/session/{session_token}/providers/connect": {"POST"},
        "/api/web/session/{session_token}/providers/{provider_id}/disconnect": {"POST"},
        "/api/web/session/{session_token}/providers": {"GET"},
        "/api/web/session/{session_token}/providers/{provider_id}/health": {"GET"},
        "/api/web/session/{session_token}/providers/{provider_id}/sync": {"POST"},
        "/api/web/session/{session_token}/providers/{provider_id}/status": {"GET"},
        "/api/web/session/{session_token}/providers/{provider_id}/threads": {"GET"},
        "/api/web/session/{session_token}/providers/{provider_id}/messages": {"GET"},
        "/api/web/session/{session_token}/providers/events": {"GET"},
        "/api/web/session/{session_token}/providers/registered": {"GET"},
    }


def test_provider_list_uses_durable_records_and_preserves_envelope(owner, monkeypatch):
    communication_store.save_provider(_provider())
    monkeypatch.setattr(
        supabase_module,
        "get_durable_providers_for_user",
        lambda user_id, provider: [{
            "row_id": "account-r17",
            "communication_provider_id": "provider-r17",
            "email": "owner@example.test",
            "account_id": "google-account-r17",
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_synced_at": "2026-01-02T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr(provider_service, "get_provider", lambda _provider_id: None)

    result = asyncio.run(provider_api.provider_list("ignored", _request()))

    assert set(result) == {"ok", "providers"}
    assert result["ok"] is True
    assert result["providers"] == [{
        "id": "provider-r17",
        "provider_type": "gmail",
        "status": "active",
        "email": "owner@example.test",
        "last_sync": "2026-01-02T00:00:00+00:00",
        "sync_cursor": "cursor-r17",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]


def test_provider_list_returns_503_when_durable_lookup_fails(owner, monkeypatch):
    def unavailable(_user_id, _provider):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(supabase_module, "get_durable_providers_for_user", unavailable)

    with pytest.raises(HTTPException) as error:
        asyncio.run(provider_api.provider_list("ignored", _request()))

    assert error.value.status_code == 503
    assert error.value.detail == "Unable to load connected accounts"


def test_provider_status_threads_and_messages_response_contracts(owner, monkeypatch):
    provider = _provider()
    communication_store.save_provider(provider)
    communication_store.save_cursor(provider.id, "cursor-r17")
    communication_store.map_thread("thread-r17", "conversation-r17", provider.id, "Subject")
    communication_store.mark_message_seen("message-r17")
    communication_store.add_recent_message(
        "Subject", "sender@example.test", "2026-01-02", "thread-r17", "message-r17",
    )

    class RuntimeProvider:
        _watching = True

        def health(self):
            return ProviderStatus.HEALTHY

    monkeypatch.setattr(provider_service, "get_provider", lambda _provider_id: RuntimeProvider())
    monkeypatch.setattr(provider_service.outbound_service, "provider_record_owned_by", lambda provider_id, owner_id: provider_id == provider.id and owner_id == OWNER_ID)

    status = asyncio.run(provider_api.provider_status("ignored", provider.id, _request()))
    threads = asyncio.run(provider_api.provider_threads("ignored", provider.id, _request()))
    messages = asyncio.run(provider_api.provider_messages("ignored", provider.id, _request()))

    assert status == {
        "ok": True,
        "provider_id": provider.id,
        "provider_type": "gmail",
        "status": "healthy",
        "connected": True,
        "last_sync": "2026-01-02T00:00:00+00:00",
        "sync_cursor": "cursor-r17",
        "watching": True,
    }
    assert set(threads) == {"ok", "provider_id", "threads", "total"}
    assert threads["provider_id"] == provider.id
    assert threads["total"] == 1
    assert threads["threads"][0]["external_thread_id"] == "thread-r17"
    assert messages == {
        "ok": True,
        "provider_id": provider.id,
        "total_messages_seen": 1,
        "recent_messages": [{
            "subject": "Subject",
            "sender": "sender@example.test",
            "date": "2026-01-02",
            "thread_id": "thread-r17",
            "message_id": "message-r17",
            "history_id": "",
        }],
        "mailbox_email": "",
    }


def test_provider_sync_currently_rejects_the_engine_sync_result_shape(owner, monkeypatch):
    """Characterize the current route/engine field-name contradiction.

    ``InboxSyncEngine`` returns ``SyncResult`` with ``messages_synced`` and
    ``threads_synced``.  The route currently reads ``new_messages`` and
    ``updated_threads`` only while emitting the world-model event, so the
    otherwise valid sync result raises ``AttributeError`` before its HTTP
    envelope is returned.  R17 must not silently alter this in a relocation.
    """
    provider = _provider()
    communication_store.save_provider(provider)
    monkeypatch.setattr(
        provider_service.outbound_service,
        "provider_record_owned_by",
        lambda provider_id, owner_id: provider_id == provider.id and owner_id == OWNER_ID,
    )
    monkeypatch.setattr(provider_service, "publish", lambda *_args, **_kwargs: None)

    async def sync_provider_now(provider_id, cursor=""):
        assert provider_id == provider.id
        assert cursor == "client-cursor"
        return SyncResult(
            provider_id=provider.id,
            threads_synced=2,
            messages_synced=3,
            new_conversations=1,
            errors=[],
            cursor="next-cursor",
            duration_ms=12,
        )

    from services.communication.inbox_sync_engine import inbox_sync_engine

    monkeypatch.setattr(inbox_sync_engine, "sync_provider_now", sync_provider_now)

    with pytest.raises(AttributeError, match="new_messages"):
        asyncio.run(
            provider_api.provider_sync("ignored", provider.id, _request(), cursor="client-cursor")
        )


def test_provider_sync_preserves_success_envelope_and_lifecycle_event(owner, monkeypatch):
    """Freeze the established successful sync response and event payload."""
    provider = _provider()
    communication_store.save_provider(provider)
    world_events: list[tuple[object, object, object]] = []

    class LegacyRouteSyncResult:
        new_messages = 3
        updated_threads = 2

        def model_dump(self):
            return {"provider_id": provider.id, "cursor": "next-cursor"}

    async def sync_provider_now(provider_id, cursor=""):
        assert provider_id == provider.id
        assert cursor == "client-cursor"
        return LegacyRouteSyncResult()

    monkeypatch.setattr(
        provider_service.outbound_service,
        "provider_record_owned_by",
        lambda provider_id, owner_id: provider_id == provider.id and owner_id == OWNER_ID,
    )
    monkeypatch.setattr(provider_service, "publish", lambda *args, **_kwargs: world_events.append(args))
    from services.communication.inbox_sync_engine import inbox_sync_engine

    monkeypatch.setattr(inbox_sync_engine, "sync_provider_now", sync_provider_now)

    assert asyncio.run(
        provider_api.provider_sync("ignored", provider.id, _request(), cursor="client-cursor")
    ) == {
        "ok": True,
        "result": {"provider_id": provider.id, "cursor": "next-cursor"},
    }
    assert world_events == [
        (
            "r17-token",
            provider_service.WMEventType.SYNC_COMPLETED,
            {"provider_id": provider.id, "new_messages": 3, "updated_threads": 2},
        )
    ]


def test_provider_disconnect_is_owned_and_not_retry_idempotent(owner, monkeypatch):
    """Freeze disconnect's one-shot lifecycle and best-effort side effects."""
    provider = _provider()
    communication_store.save_provider(provider)
    disconnect = MagicMock(side_effect=[True, False])
    cache_invalidate = AsyncMock()
    bus_publish = AsyncMock()
    world_events: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        provider_service.outbound_service,
        "provider_record_owned_by",
        lambda provider_id, owner_id: provider_id == provider.id and owner_id == OWNER_ID,
    )
    monkeypatch.setattr(
        "services.communication.provider_registry.disconnect_provider",
        disconnect,
    )
    monkeypatch.setattr(
        provider_service,
        "publish",
        lambda session_id, event_type, data, **_kwargs: world_events.append(
            (session_id, event_type, data)
        ),
    )
    from services.events_bus import event_bus
    from services.session_cache import session_cache

    monkeypatch.setattr(session_cache, "invalidate_user", cache_invalidate)
    monkeypatch.setattr(event_bus, "publish_user_event", bus_publish)

    assert asyncio.run(
        provider_api.provider_disconnect("ignored", provider.id, _request())
    ) == {"ok": True}
    cache_invalidate.assert_awaited_once_with(OWNER_ID)
    bus_publish.assert_awaited_once_with(
        OWNER_ID,
        "provider.disconnected",
        {"provider": "gmail"},
        status="disconnected",
    )
    assert world_events == [
        ("r17-token", provider_service.WMEventType.PROVIDER_DISCONNECTED, {"provider_id": provider.id})
    ]

    with pytest.raises(HTTPException) as error:
        asyncio.run(provider_api.provider_disconnect("ignored", provider.id, _request()))
    assert error.value.status_code == 404
    assert disconnect.call_count == 2
    assert len(world_events) == 1


def test_provider_events_merges_durable_and_runtime_events(owner, monkeypatch):
    runtime_event = SimpleNamespace(
        id="runtime-event",
        event_type=SimpleNamespace(value="sync_completed"),
        provider_id="provider-r17",
        message="runtime event",
        timestamp="2026-01-02T00:00:00+00:00",
        sequence=8,
        metadata={"source": "runtime"},
    )
    durable_event = SimpleNamespace(
        id="durable-event",
        event_type="provider_connected",
        provider_id="provider-r17",
        message="durable event",
        event_timestamp=None,
        metadata={"source": "durable"},
    )

    async def workspace_id(_request, _owner_id):
        return "workspace-r17"

    monkeypatch.setattr(provider_service, "get_events", lambda **_kwargs: [runtime_event])
    monkeypatch.setattr(provider_service, "latest_sequence", lambda: 8)
    monkeypatch.setattr(provider_api.workspace_access, "resolve_legacy_workspace_id", workspace_id)
    monkeypatch.setattr(
        "services.persistence.launch.communication_persistence.list_provider_events",
        lambda workspace_id, provider_id, limit: [durable_event],
    )

    result = asyncio.run(
        provider_api.provider_events_endpoint("ignored", _request(), "provider-r17", after=7)
    )

    assert result == {
        "ok": True,
        "events": [
            {
                "id": "durable-event",
                "event_type": "provider_connected",
                "provider_id": "provider-r17",
                "message": "durable event",
                "timestamp": "",
                "sequence": 0,
                "metadata": {"source": "durable"},
            },
            {
                "id": "runtime-event",
                "event_type": "sync_completed",
                "provider_id": "provider-r17",
                "message": "runtime event",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "sequence": 8,
                "metadata": {"source": "runtime"},
            },
        ],
        "latest_sequence": 8,
    }


def test_registered_provider_types_remain_an_unscoped_registry_read(monkeypatch):
    monkeypatch.setattr(
        provider_service,
        "list_registered_types",
        lambda: [ProviderType.GMAIL],
    )

    assert asyncio.run(provider_api.provider_registered_types("ignored")) == {
        "ok": True,
        "types": ["gmail"],
    }


def test_gmail_auth_url_requires_provable_identity():
    request = MagicMock()
    request.headers.get = lambda _key, default="": default

    with pytest.raises(HTTPException) as error:
        asyncio.run(provider_api.gmail_auth_url(request))

    assert error.value.status_code == 401
    assert error.value.detail == "Authentication required to connect a provider"


def test_legacy_google_callback_preserves_popup_and_provider_event(monkeypatch):
    async def consume_state(_state):
        return OWNER_ID, {"channel": "web"}

    events: list[tuple[str, object, dict, str]] = []
    monkeypatch.setattr("services.oauth_state.consume_state", consume_state)
    monkeypatch.setattr(
        "services.google_auth.exchange_code_for_tokens",
        lambda _code: {
            "email": "owner@example.test",
            "access_token": "access",
            "refresh_token": "refresh",
            "token_expiry": "2030-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr("services.supabase.save_google_tokens", lambda *_args, **_kwargs: {"id": OWNER_ID})
    monkeypatch.setattr(
        "services.world_model.publish",
        lambda session_id, event_type, payload, actor: events.append(
            (session_id, event_type, payload, actor)
        ),
    )
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.test")

    response = asyncio.run(provider_api.legacy_google_callback("code", "issued-state"))

    body = response.body.decode()
    assert response.status_code == 200
    assert "loqi:gmail-connected" in body
    assert '"https://app.example.test"' in body
    assert events == [
        (
            f"web:{OWNER_ID}",
            WMEventType.PROVIDER_CONNECTED,
            {
                "provider_type": "gmail",
                "email": "owner@example.test",
                "channel": "web",
            },
            "user",
        )
    ]


def test_web_gmail_status_preserves_session_summary_envelope(monkeypatch):
    async def cached_identity(_token):
        return {"gmail_connected": True}

    monkeypatch.setattr(provider_api.identity_dependencies, "web_session_token", lambda _request: "bound-token")
    monkeypatch.setattr(provider_api.identity_dependencies, "cached_web_session_identity", cached_identity)
    monkeypatch.setattr(
        provider_service,
        "legacy_web_gmail_connect_url",
        lambda _token: "https://accounts.google.test/oauth?state=issued",
    )

    result = asyncio.run(provider_api.web_gmail_status("ignored", MagicMock()))

    assert result == {
        "ok": True,
        "gmail_connected": True,
        "connect_url": "https://accounts.google.test/oauth?state=issued",
    }
