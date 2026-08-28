"""R2-A.1 behavior freeze for the current main/web-session and workspace boundaries."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import main
from services import workspace_context


def _request(headers=()):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": list(headers)})


def test_legacy_bearer_is_header_only():
    assert main.identity_dependencies.web_session_token(_request([(b"authorization", b"Bearer token-a")])) == "token-a"
    assert main.identity_dependencies.web_session_token(_request()) == ""
    assert main.identity_dependencies.web_session_token(_request([(b"authorization", b"Basic token-a")])) == ""


@pytest.mark.asyncio
async def test_legacy_session_requires_bearer():
    with pytest.raises(HTTPException) as error:
        await main.identity_dependencies.resolve_web_session(_request())
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_request_workspace_selection_maps_the_authorized_context(monkeypatch):
    expected = workspace_context.WorkspaceContext(
        user_id="user-a",
        organization_id="org-a",
        workspace_id="workspace-a",
        workspace_name="A",
    )
    seen = {}

    def resolve(_client, user_id, requested_workspace_id):
        seen.update(user_id=user_id, requested_workspace_id=requested_workspace_id)
        return expected

    monkeypatch.setattr(workspace_context, "resolve_workspace_context", resolve)
    request = _request([(b"x-workspace-id", b"workspace-a")])

    resolved = await workspace_context.resolve_selected_workspace_context(request, "user-a")

    assert resolved == expected
    assert seen == {"user_id": "user-a", "requested_workspace_id": "workspace-a"}


@pytest.mark.asyncio
async def test_legacy_workspace_fallback_only_applies_when_no_workspace_exists(monkeypatch):
    async def no_workspace(_request, _user_id):
        raise HTTPException(status_code=404, detail="No accessible workspace")

    async def legacy_workspace(_user_id):
        return "legacy-workspace"

    monkeypatch.setattr(workspace_context, "resolve_selected_workspace_id", no_workspace)
    monkeypatch.setattr("services.workspace_state._async_workspace", legacy_workspace)

    assert await workspace_context.resolve_legacy_workspace_id(None, "legacy-user") == "legacy-workspace"


@pytest.mark.asyncio
async def test_legacy_workspace_fallback_never_masks_an_inaccessible_selection(monkeypatch):
    async def inaccessible(_request, _user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    monkeypatch.setattr(workspace_context, "resolve_selected_workspace_id", inaccessible)

    with pytest.raises(HTTPException) as error:
        await workspace_context.resolve_legacy_workspace_id(_request(), "user-a")
    assert error.value.status_code == 404
    assert error.value.detail == "Workspace not found"


def test_selected_workspace_requires_active_membership(monkeypatch):
    monkeypatch.setattr(workspace_context, "workspaces_for_user", lambda *_: [])
    with pytest.raises(workspace_context.WorkspaceAccessDenied):
        workspace_context.resolve_workspace_context(object(), "user-a", "workspace-b")


def test_selected_workspace_rejects_ambiguous_implicit_selection(monkeypatch):
    rows = [{"id": "a", "organization_id": "org-a", "name": "A"}, {"id": "b", "organization_id": "org-b", "name": "B"}]
    monkeypatch.setattr(workspace_context, "workspaces_for_user", lambda *_: rows)
    with pytest.raises(workspace_context.AmbiguousWorkspaceError):
        workspace_context.resolve_workspace_context(object(), "user-a")
