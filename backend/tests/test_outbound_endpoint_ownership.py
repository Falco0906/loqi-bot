"""Session-prefixed outbound routes must enforce bearer-derived ownership."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_outbound_list_rejects_an_unowned_provider(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module, "_session_token_from_request", lambda _request: "session-1")
    monkeypatch.setattr(main_module, "_workspace_owner", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(main_module, "_provider_owned_by", lambda _provider, _owner: False)

    with pytest.raises(HTTPException) as error:
        await main_module.outbound_list_drafts("_", SimpleNamespace(), provider_id="foreign-provider")

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_outbound_list_filters_unowned_drafts(monkeypatch):
    import main as main_module

    owned = SimpleNamespace(id="owned", model_dump=lambda: {"id": "owned"})
    foreign = SimpleNamespace(id="foreign", model_dump=lambda: {"id": "foreign"})
    monkeypatch.setattr(main_module, "_session_token_from_request", lambda _request: "session-1")
    monkeypatch.setattr(main_module, "_workspace_owner", lambda *_args: _value("owner-1"))
    monkeypatch.setattr(
        main_module.outbound_draft_store,
        "list_all",
        lambda: SimpleNamespace(drafts=[owned, foreign], total=2),
    )
    monkeypatch.setattr(main_module, "_outbound_draft_owned_by", lambda draft, _owner: draft is owned)

    result = await main_module.outbound_list_drafts("_", SimpleNamespace())

    assert result == {"ok": True, "drafts": [{"id": "owned"}], "total": 1}


async def _value(value):
    return value
