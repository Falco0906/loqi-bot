"""Session-prefixed outbound routes must enforce bearer-derived ownership."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_outbound_list_rejects_an_unowned_provider(monkeypatch):
    import services.outbound.api as outbound_api
    import services.outbound.service as outbound_service
    from services.outbound.api import outbound_list_drafts

    monkeypatch.setattr(outbound_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(outbound_api.identity_dependencies, "authenticated_user_id", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(outbound_service, "provider_owned_by", lambda _provider, _owner: False)

    with pytest.raises(HTTPException) as error:
        await outbound_list_drafts("_", SimpleNamespace(), provider_id="foreign-provider")

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_outbound_list_reads_authorized_canonical_drafts(monkeypatch):
    import services.outbound.api as outbound_api
    import services.outbound.service as outbound_service
    from services.outbound.api import outbound_list_drafts

    owned = SimpleNamespace(id="owned", model_dump=lambda: {"id": "owned"})
    calls = []
    monkeypatch.setattr(outbound_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(outbound_api.identity_dependencies, "authenticated_user_id", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(
        outbound_api.workspace_access,
        "resolve_legacy_workspace_id",
        lambda *_args: _value("workspace-1"),
    )
    monkeypatch.setattr(outbound_service, "provider_owned_by", lambda *_args: True)
    monkeypatch.setattr(
        outbound_api,
        "load_drafts_only",
        lambda *args, **kwargs: calls.append((args, kwargs)) or [
            {"id": "owned", "provider": "provider-1"},
            {"id": "other-provider", "provider": "provider-2"},
            {"id": "not-outbound"},
        ],
    )
    monkeypatch.setattr(
        outbound_service,
        "hydrate_outbound_draft",
        lambda draft, *_args, **_kwargs: owned if draft["id"] == "owned" else None,
    )

    result = await outbound_list_drafts("_", SimpleNamespace(), provider_id="provider-1")

    assert result == {"ok": True, "drafts": [{"id": "owned"}], "total": 1}
    assert calls == [(("owner-1",), {"workspace_id": "workspace-1"})]


@pytest.mark.asyncio
async def test_outbound_list_preserves_auth_error_without_reading_drafts(monkeypatch):
    import services.outbound.api as outbound_api

    async def denied(*_args, **_kwargs):
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(outbound_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(outbound_api.identity_dependencies, "authenticated_user_id", denied)
    monkeypatch.setattr(
        outbound_api,
        "load_drafts_only",
        lambda *_args, **_kwargs: pytest.fail("unauthorized request read canonical drafts"),
    )

    with pytest.raises(HTTPException) as error:
        await outbound_api.outbound_list_drafts("_", SimpleNamespace())

    assert error.value.status_code == 401
    assert error.value.detail == "Authentication required"


@pytest.mark.asyncio
async def test_outbound_list_draft_read_does_not_block_event_loop(monkeypatch):
    """The canonical synchronous draft read must run outside the request loop."""
    import services.outbound.api as outbound_api
    import services.outbound.service as outbound_service

    entered = threading.Event()
    release = threading.Event()
    progressed = asyncio.Event()

    monkeypatch.setattr(outbound_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(outbound_api.identity_dependencies, "authenticated_user_id", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(
        outbound_api.workspace_access,
        "resolve_legacy_workspace_id",
        lambda *_args: _value("workspace-1"),
    )

    def blocking_load(owner_id, *, workspace_id):
        assert (owner_id, workspace_id) == ("owner-1", "workspace-1")
        entered.set()
        assert release.wait(timeout=1)
        return [{"id": "owned", "provider": "provider-1"}]

    owned = SimpleNamespace(id="owned", model_dump=lambda: {"id": "owned"})
    monkeypatch.setattr(outbound_api, "load_drafts_only", blocking_load)
    monkeypatch.setattr(outbound_service, "hydrate_outbound_draft", lambda *_args, **_kwargs: owned)

    operation = asyncio.create_task(outbound_api.outbound_list_drafts("_", SimpleNamespace()))
    assert await asyncio.to_thread(entered.wait, 1), "draft read stub was not invoked"

    async def unrelated_coroutine():
        await asyncio.sleep(0)
        progressed.set()

    await unrelated_coroutine()
    assert progressed.is_set(), "blocking draft read stalled the event loop"
    release.set()

    assert await operation == {"ok": True, "drafts": [{"id": "owned"}], "total": 1}


async def _value(value):
    return value
