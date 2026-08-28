"""Characterization guards for the extracted Campaign read router."""
from __future__ import annotations

import services.campaigns.api as campaign_api
import main
import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/web/session/_/campaigns",
        "headers": [(b"authorization", b"Bearer session-token")],
    })


async def _resolve_user(_request: Request, _token: str) -> str:
    return "owner-1"


async def _resolve_workspace(_request: Request, _owner_id: str) -> str:
    return "workspace-1"


def _campaigns(*_args, **_kwargs):
    return [{
        "id": "campaign-1",
        "name": "Cafe owners",
        "status": "planning",
        "lead_count": 4,
        "launch_sent": 1,
        "launch_total": 4,
        "updated_at": "2026-08-28T00:00:00Z",
    }]


def _configure_authorized_router(monkeypatch) -> None:
    monkeypatch.setattr(campaign_api.identity_dependencies, "web_session_token", lambda _request: "session-token")
    monkeypatch.setattr(campaign_api.identity_dependencies, "authenticated_user_id", _resolve_user)
    monkeypatch.setattr(campaign_api.workspace_access, "resolve_legacy_workspace_id", _resolve_workspace)
    monkeypatch.setattr(campaign_api, "load_campaigns", _campaigns)
    monkeypatch.setattr(campaign_api, "load_drafts_only", lambda *_args, **_kwargs: [])


async def test_campaign_read_routes_keep_registered_paths_and_response_shapes(monkeypatch):
    """The router owns the five existing GET paths without changing top-level keys."""
    expected_paths = [
        "/api/web/session/{session_token}/campaigns",
        "/api/web/session/{session_token}/campaigns/summary",
        "/api/web/session/{session_token}/campaigns/{campaign_id}",
        "/api/web/session/{session_token}/campaigns/{campaign_id}/launch-progress",
        "/api/web/session/{session_token}/campaigns/{campaign_id}/timeline",
    ]
    assert [route.path for route in campaign_api.router.routes] == expected_paths
    assert any(
        getattr(route, "original_router", None) is campaign_api.router
        for route in main.app.routes
    )

    _configure_authorized_router(monkeypatch)
    monkeypatch.setattr(campaign_api, "record_campaign_open", lambda *_args: None)

    listed = await campaign_api.list_campaigns("_", _request())
    summary = await campaign_api.campaign_summary("_", _request())
    detail = await campaign_api.get_campaign("_", "campaign-1", _request())
    progress = await campaign_api.campaign_launch_progress("_", "campaign-1", _request())

    assert set(listed) == {"ok", "campaigns"}
    assert set(summary) == {"ok", "campaigns"}
    assert set(detail) == {"ok", "campaign"}
    assert set(progress) == {"ok", "launch_sent", "launch_total", "launch_complete"}
    assert progress["launch_complete"] is False


async def test_campaign_read_routes_keep_not_found_contract(monkeypatch):
    _configure_authorized_router(monkeypatch)
    monkeypatch.setattr(campaign_api, "load_campaigns", lambda *_args, **_kwargs: [])

    with pytest.raises(HTTPException) as error:
        await campaign_api.get_campaign("_", "missing", _request())

    assert error.value.status_code == 404
    assert error.value.detail == "Campaign not found"
