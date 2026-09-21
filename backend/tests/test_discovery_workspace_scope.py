"""Request-scoped workspace regressions for the Discovery API."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import main
import services.discovery.api as discovery_api
import services.discovery.service as discovery_service


def _request(workspace_id: str = "workspace-selected") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/discoveries",
        "headers": [
            (b"authorization", b"Bearer session-token"),
            (b"x-workspace-id", workspace_id.encode()),
        ],
    })


async def test_discovery_create_list_and_get_share_authenticated_workspace(monkeypatch):
    """A selected workspace must remain stable across the full API lifecycle."""
    selected_workspace = "workspace-selected"
    created: dict[str, str] = {}
    calls: list[tuple[str, str]] = []

    async def resolve_user(_request):
        return "authenticated-user", "session-token"

    async def resolve_workspace(_request, owner_id):
        assert owner_id == "authenticated-user"
        return selected_workspace

    async def create_run(user_id, query, session_token, **kwargs):
        created.update({
            "user_id": user_id,
            "query": query,
            "session_token": session_token,
            "workspace_id": kwargs["workspace_id"],
        })
        return {"discovery_id": "discovery-1", "job_id": "job-1"}

    def list_rows(workspace_id):
        calls.append(("list", workspace_id))
        return [{"id": "discovery-1", "workspace_id": workspace_id}]

    def get_row(discovery_id, workspace_id):
        calls.append(("get", workspace_id))
        assert discovery_id == "discovery-1"
        return {"id": discovery_id, "workspace_id": workspace_id}

    monkeypatch.setattr(discovery_api.identity_dependencies, "resolve_web_session", resolve_user)
    monkeypatch.setattr(discovery_api.workspace_access, "resolve_legacy_workspace_id", resolve_workspace)
    monkeypatch.setattr(discovery_api, "create_search_run", create_run)
    monkeypatch.setattr(discovery_api, "list_discoveries", list_rows)
    monkeypatch.setattr(discovery_api, "get_discovery", get_row)

    request = _request(selected_workspace)
    created_response = await discovery_api.create_discovery_endpoint(
        discovery_api.CreateDiscoveryRequest(query="cafe owners"), request,
    )
    listed_response = await discovery_api.list_discoveries_endpoint(request)
    detail_response = await discovery_api.get_discovery_endpoint("discovery-1", request)

    assert created_response["discovery_id"] == "discovery-1"
    assert created["workspace_id"] == selected_workspace
    assert set(listed_response) == {"ok", "discoveries"}
    assert set(detail_response) == {"ok", "discovery"}
    assert listed_response["discoveries"] == [{"id": "discovery-1", "workspace_id": selected_workspace}]
    assert detail_response["discovery"]["workspace_id"] == selected_workspace
    assert calls == [("list", selected_workspace), ("get", selected_workspace)]


async def test_discovery_read_routes_keep_their_registered_http_contract(monkeypatch):
    """The read router keeps the legacy paths and their 404 response contract."""
    paths = [route.path for route in discovery_api.router.routes]
    assert paths == [
        "/api/jobs/search",
        "/api/discoveries",
        "/api/discoveries",
        "/api/discoveries/{discovery_id}",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/results",
        "/api/jobs",
    ]
    assert any(
        getattr(route, "original_router", None) is discovery_api.router
        for route in main.app.routes
    )

    async def resolve_user(_request):
        return "authenticated-user", "session-token"

    async def resolve_workspace(_request, _owner_id):
        return "workspace-selected"

    monkeypatch.setattr(discovery_api.identity_dependencies, "resolve_web_session", resolve_user)
    monkeypatch.setattr(discovery_api.workspace_access, "resolve_legacy_workspace_id", resolve_workspace)
    monkeypatch.setattr(discovery_api, "get_discovery", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        await discovery_api.get_discovery_endpoint("missing", _request())

    assert error.value.status_code == 404
    assert error.value.detail == "Discovery not found"


async def test_create_search_run_keeps_explicit_workspace(monkeypatch):
    """The lower-level kickoff must not replace selected workspace with a default."""
    persisted: dict[str, str] = {}

    def create_discovery(workspace_id, owner_id, query, display_title=None):
        persisted.update({"workspace_id": workspace_id, "owner_id": owner_id, "query": query})
        return {"id": "discovery-1"}

    async def create_job(**_kwargs):
        return {"job_id": "job-1"}

    monkeypatch.setattr(discovery_service, "create_discovery", create_discovery)
    monkeypatch.setattr(discovery_service.job_manager, "create_search_job", create_job)

    result = await discovery_service.create_search_run(
        "owner-1", "cafe owners", workspace_id="workspace-selected",
    )

    assert result["discovery_id"] == "discovery-1"
    assert persisted["workspace_id"] == "workspace-selected"
