"""HTTP characterization for the workspace lifecycle route family."""

from __future__ import annotations

from types import SimpleNamespace

from services.identity import dependencies as identity_dependencies
from services.persistence.launch import repositories
from services.workspace import access as workspace_access


def _authenticate(monkeypatch, user_id: str = "user-a") -> None:
    monkeypatch.setattr(identity_dependencies, "web_session_token", lambda _request: "bearer-a")

    async def authenticated_user(_request, _token=""):
        return user_id

    monkeypatch.setattr(identity_dependencies, "authenticated_user_id", authenticated_user)


def test_list_workspaces_preserves_safe_workspace_envelope(client, monkeypatch):
    _authenticate(monkeypatch)
    expected = [{
        "id": "workspace-a",
        "organization_id": "organization-a",
        "owner_user_id": "user-a",
        "name": "Workspace A",
        "slug": "workspace-a",
        "status": "active",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-02T00:00:00+00:00",
    }]
    seen = []

    def list_for_user(client_arg=None, user_id=""):
        seen.append((client_arg, user_id))
        return expected

    monkeypatch.setattr(workspace_access, "workspaces_for_user", list_for_user)

    response = client.get("/api/web/session/path-token/workspaces")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "workspaces": expected}
    assert seen == [(None, "user-a")]


def test_select_workspace_preserves_context_envelope(client, monkeypatch):
    _authenticate(monkeypatch)
    expected = workspace_access.WorkspaceContext(
        user_id="user-a",
        organization_id="organization-a",
        workspace_id="workspace-a",
        workspace_name="Workspace A",
        membership_role="admin",
        membership_status="active",
    )
    seen = []

    async def resolve(request, user_id):
        seen.append((request.headers.get("x-workspace-id"), user_id))
        return expected

    monkeypatch.setattr(workspace_access, "resolve_selected_workspace_context", resolve)

    response = client.post(
        "/api/web/session/path-token/workspaces/select",
        headers={"X-Workspace-Id": "workspace-a"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "workspace": {
            "id": "workspace-a",
            "organization_id": "organization-a",
            "name": "Workspace A",
            "membership_role": "admin",
            "membership_status": "active",
        },
    }
    assert seen == [("workspace-a", "user-a")]


def test_select_workspace_preserves_resolver_http_errors(client, monkeypatch):
    _authenticate(monkeypatch)

    async def inaccessible(_request, _user_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Workspace not found")

    monkeypatch.setattr(workspace_access, "resolve_selected_workspace_context", inaccessible)
    missing = client.post("/api/web/session/path-token/workspaces/select")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Workspace not found"}

    async def ambiguous(_request, _user_id):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="Multiple workspaces available; select one via the X-Workspace-Id header",
        )

    monkeypatch.setattr(workspace_access, "resolve_selected_workspace_context", ambiguous)
    multiple = client.post("/api/web/session/path-token/workspaces/select")
    assert multiple.status_code == 409
    assert multiple.json() == {
        "detail": "Multiple workspaces available; select one via the X-Workspace-Id header",
    }


def test_create_workspace_preserves_membership_validated_payload(client, monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        workspace_access,
        "active_memberships",
        lambda _client, user_id: [{"organization_id": "organization-a", "role": "owner"}]
        if user_id == "user-a" else [],
    )
    saved = []

    class WorkspaceRepository:
        async def save(self, entity):
            saved.append(entity)

    class WorkspaceMemberRepository:
        async def save(self, entity):
            saved.append(entity)

    monkeypatch.setattr(repositories, "WorkspaceRepository", WorkspaceRepository)
    monkeypatch.setattr(repositories, "WorkspaceMemberRepository", WorkspaceMemberRepository)

    response = client.post(
        "/api/web/session/path-token/workspaces",
        json={"organization_id": "organization-a", "name": "Sales Workspace", "slug": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert set(body["workspace"]) == {
        "id", "organization_id", "name", "slug", "owner_user_id", "status",
    }
    assert body["workspace"]["organization_id"] == "organization-a"
    assert body["workspace"]["name"] == "Sales Workspace"
    assert body["workspace"]["owner_user_id"] == "user-a"
    assert body["workspace"]["status"] == "active"
    assert body["workspace"]["slug"] == f"sales-workspace-{body['workspace']['id'][:8]}"
    assert len(saved) == 2
    workspace, membership = saved
    assert workspace.id == body["workspace"]["id"]
    assert workspace.organization_id == "organization-a"
    assert membership.workspace_id == workspace.id
    assert membership.user_id == "user-a"
    assert membership.role == "owner"
    assert membership.status == "active"


def test_create_workspace_preserves_membership_error_contracts(client, monkeypatch):
    _authenticate(monkeypatch)

    monkeypatch.setattr(workspace_access, "active_memberships", lambda *_args: [])
    missing = client.post(
        "/api/web/session/path-token/workspaces",
        json={"organization_id": "organization-a"},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Organization not found"}

    monkeypatch.setattr(
        workspace_access,
        "active_memberships",
        lambda *_args: [{"organization_id": "organization-a", "role": "member"}],
    )
    denied = client.post(
        "/api/web/session/path-token/workspaces",
        json={"organization_id": "organization-a"},
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Insufficient role to create a workspace"}
