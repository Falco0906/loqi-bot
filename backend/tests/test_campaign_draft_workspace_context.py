"""Offline HTTP boundary checks with the real membership resolver and fake rows."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from services.campaigns import api as campaigns_api
from services.drafts import api as drafts_api, service as drafts
from services.persistence.launch import Draft
from services.workspace import access, state
from tests.test_saas27_multi_workspace import FakeClient


@pytest.fixture
def scoped_app(monkeypatch):
    client = FakeClient({
        "memberships": [{"user_id": "actor", "organization_id": org, "status": "active", "role": "member"} for org in ("org-a", "org-b")],
        "workspaces": [{"id": "ws-a", "organization_id": "org-a"}, {"id": "ws-b", "organization_id": "org-b"}],
    })
    monkeypatch.setattr(access, "get_supabase_client", lambda: client)
    async def actor(*_): return "actor"
    monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", actor)
    entity = Draft(id="draft-b", workspace_id="ws-b", campaign_id="campaign-b", subject="Original", body="Original", status="pending")
    repo = SimpleNamespace(get=AsyncMock(return_value=entity), save=AsyncMock(side_effect=lambda row: row))
    monkeypatch.setattr(state, "DraftRepository", lambda: repo)
    async def resolve(actor, *, workspace_id): return access.resolve_workspace_context(client, actor, workspace_id).workspace_id
    monkeypatch.setattr(state, "_async_workspace", resolve)
    def rows(actor, *, workspace_id, strict):
        assert actor == "actor" and strict
        return [state._draft_as_dict(entity)] if workspace_id == "ws-b" else []
    def campaign(actor, identity, *, workspace_id, strict):
        assert strict
        return {"id": "campaign-b"} if (identity, workspace_id) == ("campaign-b", "ws-b") else None
    monkeypatch.setattr(state, "load_drafts_only", rows)
    monkeypatch.setattr(campaigns_api, "load_drafts_only", rows)
    monkeypatch.setattr(state, "load_campaign_state", campaign)
    monkeypatch.setattr(campaigns_api, "load_campaigns", lambda _, *, workspace_id: [{"id": "campaign-b", "name": "Campaign B"}] if workspace_id == "ws-b" else [])
    monkeypatch.setattr(state, "append_event", Mock(return_value=True))
    monkeypatch.setattr(drafts, "publish", Mock())
    app = FastAPI()
    app.include_router(campaigns_api.router)
    app.include_router(drafts_api.router)
    return app, entity, repo


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace,status", [("ws-b", 200), ("ws-a", 404), ("unknown", 404), ("", 409)])
async def test_campaign_detail_and_campaign_drafts_share_membership_scope(scoped_app, workspace, status):
    app, _, _ = scoped_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers={"Authorization": "Bearer offline", "X-Workspace-Id": workspace}) as client:
        for path in ("campaigns/campaign-b", "campaigns/campaign-b/drafts"):
            response = await client.get("/api/web/session/_/" + path)
            assert response.status_code == status


@pytest.mark.asyncio
async def test_scoped_http_read_edit_and_empty_subject_readback(scoped_app):
    app, entity, repo = scoped_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers={"Authorization": "Bearer offline", "X-Workspace-Id": "ws-b"}) as client:
        before = await client.get("/api/web/session/_/drafts")
        assert before.json()["drafts"][0]["id"] == "draft-b"
        response = await client.put("/api/web/session/_/drafts/draft-b", json={"text": "Subject: \n\nEdited"})
        assert response.status_code == 200
        after = (await client.get("/api/web/session/_/drafts")).json()["drafts"][0]
        assert (after["subject"], after["text"], after["status"]) == ("", "Edited", "pending")
        forbidden = await client.put("/api/web/session/_/drafts/draft-b", headers={"X-Workspace-Id": "ws-a"}, json={"text": "Wrong"})
        assert forbidden.status_code == 404 and entity.body == "Edited"
        assert repo.save.await_count == 1


@pytest.mark.asyncio
async def test_refinement_refuses_foreign_draft_before_model_work(scoped_app, monkeypatch):
    app, _, repo = scoped_app
    rewrite = Mock(side_effect=AssertionError("No model call allowed"))
    monkeypatch.setattr(drafts, "execute_rewrite", rewrite)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers={"Authorization": "Bearer offline", "X-Workspace-Id": "ws-a"}) as client:
        response = await client.post("/api/web/session/_/drafts/draft-b/refine", json={"edit_request": "Shorter", "previous_message": "Original", "lead": {}})
        assert response.status_code == 404
    rewrite.assert_not_called()
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_refinement_writes_only_the_selected_workspace(scoped_app, monkeypatch):
    app, entity, repo = scoped_app
    monkeypatch.setattr(drafts, "execute_rewrite", Mock(return_value=SimpleNamespace(text="Scoped rewrite", change_summary=[], confidence="low")))
    monkeypatch.setattr(drafts, "compare_versions", Mock(return_value=SimpleNamespace(to_dict=lambda: {})))
    monkeypatch.setattr(drafts, "analyze_draft_intelligence", Mock(return_value=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers={"Authorization": "Bearer offline", "X-Workspace-Id": "ws-b"}) as client:
        response = await client.post("/api/web/session/_/drafts/draft-b/refine", json={"edit_request": "Shorter", "previous_message": "Original", "lead": {}})
        assert response.status_code == 200 and response.json()["ok"]
    assert entity.workspace_id == "ws-b" and entity.body == "Scoped rewrite" and entity.status == "pending"
    assert repo.save.await_count == 1


@pytest.mark.asyncio
async def test_explicit_scope_read_failure_is_not_successful_empty_drafts(scoped_app, monkeypatch):
    app, _, _ = scoped_app
    def unavailable(*_args, **_kwargs): raise RuntimeError("local repository failure")
    monkeypatch.setattr(state, "load_drafts_only", unavailable)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers={"Authorization": "Bearer offline", "X-Workspace-Id": "ws-b"}) as client:
        with pytest.raises(RuntimeError, match="local repository failure"):
            await client.get("/api/web/session/_/drafts")
