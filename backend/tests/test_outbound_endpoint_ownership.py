"""Session-prefixed outbound routes must enforce bearer-derived ownership."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_outbound_list_rejects_an_unowned_provider(monkeypatch):
    import main as main_module
    import services.outbound.service as outbound_service

    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(outbound_service, "provider_owned_by", lambda _provider, _owner: False)

    with pytest.raises(HTTPException) as error:
        await main_module.outbound_list_drafts("_", SimpleNamespace(), provider_id="foreign-provider")

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_outbound_list_reads_authorized_canonical_drafts(monkeypatch):
    import main as main_module
    import services.outbound.service as outbound_service
    import services.workspace_state as workspace_state

    owned = SimpleNamespace(id="owned", model_dump=lambda: {"id": "owned"})
    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(
        main_module.workspace_access,
        "resolve_legacy_workspace_id",
        lambda *_args: _value("workspace-1"),
    )
    monkeypatch.setattr(
        workspace_state,
        "load_drafts_only",
        lambda *_args, **_kwargs: [{"id": "owned", "provider": "provider-1"}],
    )
    monkeypatch.setattr(outbound_service, "hydrate_outbound_draft", lambda *_args, **_kwargs: owned)

    result = await main_module.outbound_list_drafts("_", SimpleNamespace())

    assert result == {"ok": True, "drafts": [{"id": "owned"}], "total": 1}


async def _value(value):
    return value
