"""Offline authorization and input contracts; SQL execution is not simulated."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.campaigns import api, creation, service
from services.workspace import access
from tests.test_saas27_multi_workspace import FakeClient
from tests.test_campaign_creation_safety import database


@pytest.mark.asyncio
@pytest.mark.parametrize("case,allowed", [
    ("owner", True), ("workspace_member", True), ("organization_member", True),
    ("workspace_member_only", False), ("owner_without_membership", False),
    ("removed", False), ("left", False), ("pending", False),
    ("deleted_membership", False), ("deleted_workspace", False),
    ("other_organization", False), ("suspended_workspace", True),
    ("archived_workspace", True),
])
async def test_creation_uses_canonical_organization_membership(monkeypatch, case, allowed):
    workspace = {"id": "selected", "organization_id": "org", "deleted_at": None,
                 "owner_user_id": "actor" if case.startswith("owner") else "someone-else",
                 "status": "active"}
    membership = {"user_id": "actor", "organization_id": "org", "status": "active", "role": "member"}
    if case in {"removed", "left", "pending"}:
        membership["status"] = case
    if case == "other_organization":
        membership["organization_id"] = "different"
    if case == "deleted_workspace":
        workspace["deleted_at"] = "2026-01-01"
    if case.endswith("_workspace") and case != "deleted_workspace":
        workspace["status"] = case.removesuffix("_workspace")
    # memberships has no deleted_at column; deletion removes the row.
    memberships = [] if case in {"deleted_membership", "workspace_member_only", "owner_without_membership"} else [membership]
    client = FakeClient({"memberships": memberships, "workspaces": [workspace],
                         "workspace_members": [{"workspace_id": "selected", "user_id": "actor", "status": "active"}]})
    monkeypatch.setattr(access, "get_supabase_client", lambda: client)
    monkeypatch.setattr(api.identity_dependencies, "web_session_token", lambda _request: "token")
    monkeypatch.setattr(api.identity_dependencies, "authenticated_user_id", AsyncMock(return_value="actor"))
    legacy = AsyncMock(side_effect=AssertionError("Creation cannot fall back to owner scope"))
    monkeypatch.setattr(access, "resolve_legacy_workspace_id", legacy)
    request = SimpleNamespace(headers={"x-workspace-id": "selected"})
    if allowed:
        assert await api._authorized_workspace(request, creation=True) == ("actor", "token", "selected")
    else:
        with pytest.raises(HTTPException) as error:
            await api._authorized_workspace(request, creation=True)
        assert error.value.status_code == 404
    legacy.assert_not_awaited()


@pytest.mark.parametrize("key", [None, "", "   ", "x" * 129])
def test_public_creation_rejects_missing_or_invalid_key(key):
    with pytest.raises(ValidationError):
        api.SaveCampaignRequest(name="Campaign", idempotency_key=key)


def test_public_creation_requires_key_even_for_legacy_inline_leads():
    with pytest.raises(ValidationError):
        api.SaveCampaignRequest(name="Campaign", leads=[{"email": "person@example.invalid"}])


@pytest.mark.asyncio
async def test_http_missing_key_is_rejected_before_authorization_or_persistence(monkeypatch):
    import httpx
    from fastapi import FastAPI
    authorize = AsyncMock(side_effect=AssertionError("Invalid body must be rejected first"))
    monkeypatch.setattr(api, "_authorized_workspace", authorize)
    app = FastAPI()
    app.include_router(api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid") as client:
        response = await client.post("/api/web/session/_/campaigns", json={"name": "Missing key"})
    assert response.status_code == 422
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_does_not_implicitly_enter_unkeyed_compatibility(monkeypatch):
    write = AsyncMock(side_effect=AssertionError("Must reject before persistence"))
    monkeypatch.setattr(creation, "persist_creation", write)
    with pytest.raises(HTTPException) as error:
        await service.create_campaign("token", "actor", "workspace", {"name": "Campaign"})
    assert error.value.status_code == 422
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_legacy_compatibility_requires_explicit_opt_in(monkeypatch):
    write = AsyncMock(return_value=False)
    monkeypatch.setattr("services.workspace.state.persist_campaign_row", write)
    with pytest.raises(HTTPException) as error:
        await service.create_campaign("token", "actor", "workspace", {"name": "Campaign"}, allow_legacy_creation=True)
    assert error.value.status_code == 503
    write.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("discovery", [None, {"id": "run", "deleted_at": "2026-01-01", "workspace_id": "workspace"}, {"id": "run", "workspace_id": "other"}])
async def test_unavailable_discovery_rejected_before_creation(monkeypatch, discovery):
    monkeypatch.setattr(creation, "recover_creation", AsyncMock(return_value=None))
    monkeypatch.setattr("services.discovery.service.get_discovery", lambda *_args: discovery)
    write = AsyncMock()
    monkeypatch.setattr(creation, "persist_creation", write)
    with pytest.raises(HTTPException) as error:
        await service.create_campaign("token", "actor", "workspace", {"name": "Campaign", "idempotency_key": "intent", "discovery_id": "run"})
    assert error.value.status_code == 404
    write.assert_not_awaited()


def test_sql_contract_locks_counts_and_attaches_one_lead_set():
    # Structural regression only: not proof of PostgreSQL locking/rollback.
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/048_campaign_creation_idempotency.sql").read_text()
    assert "from memberships m" in sql and "m.organization_id = v_workspace.organization_id" in sql
    assert "m.user_id = p_actor_user_id and m.status = 'active' for share" in sql
    assert "from workspace_members" not in sql
    assert "where w.id = p_workspace_id and w.deleted_at is null for share" in sql
    assert "d.workspace_id = p_workspace_id and d.deleted_at is null for share" in sql
    assert "order by l.id for share" in sql
    assert "into v_lead_ids" in sql and "cardinality(v_lead_ids)" in sql
    assert "from unnest(v_lead_ids)" in sql
    assert sql.count("from workspace_leads") == 1
    assert "select count(*) from workspace_leads" not in sql


@pytest.mark.asyncio
async def test_strategic_action_reuses_durable_intent_after_response_loss(database, monkeypatch):
    import httpx
    from services.strategic.actions import StrategicActionService

    client = FakeClient({"memberships": [{"user_id": "actor", "organization_id": "org", "status": "active"}],
                         "workspaces": [{"id": "workspace", "organization_id": "org", "deleted_at": None}]})
    monkeypatch.setattr(access, "get_supabase_client", lambda: client)
    action = SimpleNamespace(id="approved-action", strategic_update_id="update", proposal={"proposed_change": {"name": "Chosen campaign"}})
    database.lose_response = True
    with pytest.raises(httpx.ReadTimeout):
        await StrategicActionService()._execute_campaign("actor", "workspace", action)
    recovered = await StrategicActionService()._execute_campaign("actor", "workspace", action)
    assert recovered["idempotent"] and database.commits == 1 and database.calls == 1
    action.proposal["proposed_change"]["name"] = "Changed request"
    with pytest.raises(HTTPException) as error:
        await StrategicActionService()._execute_campaign("actor", "workspace", action)
    assert error.value.status_code == 409 and database.commits == 1


@pytest.mark.asyncio
async def test_strategic_creation_cannot_use_revoked_membership(database, monkeypatch):
    from services.strategic.actions import StrategicActionService
    client = FakeClient({"memberships": [{"user_id": "actor", "organization_id": "org", "status": "removed"}],
                         "workspaces": [{"id": "workspace", "organization_id": "org", "owner_user_id": "actor", "deleted_at": None}]})
    monkeypatch.setattr(access, "get_supabase_client", lambda: client)
    action = SimpleNamespace(id="approved-action", strategic_update_id="update", proposal={})
    with pytest.raises(access.WorkspaceAccessDenied):
        await StrategicActionService()._execute_campaign("actor", "workspace", action)
    assert database.calls == 0 and database.rows == {}
