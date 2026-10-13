"""Cross-feature contracts using in-memory repositories and a mocked model.

No server, database, network, or provider is used. This is NOT browser E2E
and does not validate the campaign RPC against PostgreSQL.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx
from fastapi import FastAPI, HTTPException

from services.campaigns import api as campaigns_api, service as campaigns
from services.drafts import api as drafts_api, service as drafts
from services.intelligence import ai
from services.job_engine.models import JobStatus
from services.leads import generation, service as leads
from services.leads import api as leads_api
from services.persistence.launch import Draft
from services.workspace import state
from tests.test_campaign_creation_safety import database
from tests.test_lead_generation_reliability import durable_jobs

AUTHORIZE_LEAD = campaigns._authorize_selected_lead
MODEL_GENERATOR = ai.generate_evidence_grounded_lead_strategy


@pytest.fixture
def canonical_data(monkeypatch):
    profiles, rows = {}, {}

    class Profiles:
        async def find_by_email(self, email):
            return next((row for row in profiles.values() if row.email == email), None)
        async def save(self, row):
            profiles[row.id] = row
            return row
        async def get(self, identity): return profiles.get(identity)
        async def list_by_ids(self, ids): return [profiles[key] for key in ids if key in profiles]

    class WorkspaceLeads:
        async def list_by_email(self, workspace, email):
            return [row for row in rows.values() if row.workspace_id == workspace and row.email == email]
        async def find_in_workspace(self, workspace, profile):
            return next((row for row in rows.values() if row.workspace_id == workspace and row.lead_id == profile), None)
        async def save(self, row):
            rows[row.id] = row
            return row
        async def get_for_workspace(self, identity, workspace):
            row = rows.get(identity)
            return row if row and row.workspace_id == workspace else None
        async def list_for_workspace(self, workspace):
            return [row for row in rows.values() if row.workspace_id == workspace]

    empty_companies = lambda: SimpleNamespace(get=AsyncMock(return_value=None), list_by_ids=AsyncMock(return_value=[]))
    for module in (state, leads):
        monkeypatch.setattr(module, "WorkspaceLeadRepository", WorkspaceLeads)
    monkeypatch.setattr(state, "LeadRepository", Profiles)
    monkeypatch.setattr(state, "CompanyRepository", empty_companies)
    monkeypatch.setattr("services.persistence.launch.repositories.WorkspaceLeadRepository", WorkspaceLeads)
    monkeypatch.setattr(state, "_lead_domain", lambda _: None)
    monkeypatch.setattr(leads, "LeadSignalRepository", lambda: SimpleNamespace(list_for_lead=AsyncMock(return_value=[])))
    async def guidance(actor, workspace):
        assert (actor, workspace) == ("actor", "workspace")
        return {"items": [{"title": "Offer", "summary": "Operations assistance", "category": "sales_offer"}], "note": "Business guidance, not prospect facts"}
    monkeypatch.setattr(leads, "_business_guidance", guidance)
    return SimpleNamespace(rows=rows, repo=WorkspaceLeads)


@pytest.mark.asyncio
async def test_in_process_http_import_read_analysis_and_generation_contracts(durable_jobs, canonical_data, monkeypatch):
    # Exercise real route/schema/service boundaries. Identity and membership
    # resolution are test doubles, not evidence of live authentication safety.
    async def actor(request, _token):
        if request.headers.get("authorization") != "Bearer offline":
            raise HTTPException(401, "Authentication required")
        return "actor"
    async def scope(request, owner):
        assert owner == "actor"
        if request.headers.get("x-workspace-id") != "workspace":
            raise HTTPException(403, "Workspace unavailable")
        return SimpleNamespace(workspace_id="workspace")
    monkeypatch.setattr(leads_api.identity_dependencies, "authenticated_user_id", actor)
    monkeypatch.setattr(leads_api.access, "resolve_selected_workspace_context", scope)
    monkeypatch.setattr(generation, "WorkspaceLeadRepository", canonical_data.repo)
    app = FastAPI()
    app.include_router(leads_api.router)
    prefix = "/api/web/session/_/leads"
    headers = {"Authorization": "Bearer offline", "X-Workspace-Id": "workspace"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid", headers=headers) as client:
        preview = await client.post(prefix + "/csv-preview", json={"csv": "Name,Email,Company\nAda,ada@example.com,Acme\n"})
        assert preview.status_code == 200
        imported = await client.post(prefix + "/csv-import", json={"rows": preview.json()["rows"]})
        assert imported.status_code == 200 and imported.json()["imported"] == 1
        listing = await client.get(prefix, params={"q": "Acme", "page": 1})
        assert listing.status_code == 200 and listing.json()["total"] == 1
        ids = [row["id"] for row in listing.json()["leads"]]
        analysis = await client.post(prefix + "/analyze", json={"lead_ids": ids})
        assert analysis.status_code == 200 and analysis.json()["results"][0]["lead"]["id"] == ids[0]
        assert durable_jobs.creates == 0
        queued = await client.post(prefix + "/generate-strategy", json={"lead_ids": ids, "request_key": "http-intent"})
        assert queued.status_code == 200 and queued.json()["status"] == "queued"
        recovered = await client.get(prefix + "/generation", params={"request_key": "http-intent"})
        assert recovered.json()["job_id"] == queued.json()["job_id"] and durable_jobs.creates == 1
        forbidden = await client.get(prefix, headers={"X-Workspace-Id": "other-workspace"})
        assert forbidden.status_code == 403
        unauthorized = await client.post(prefix + "/csv-import", json={"rows": preview.json()["rows"]}, headers={"Authorization": ""})
        assert unauthorized.status_code == 401 and len(canonical_data.rows) == 1


@pytest.mark.asyncio
async def test_csv_search_analysis_generation_recovery_and_campaign_replay(database, durable_jobs, canonical_data, monkeypatch):
    preview = leads.parse_csv_preview("Name,Email,Company,Title,Location,Industry\nAda Lovelace,ada@example.com,Acme,COO,London,SaaS\nGrace Hopper,grace@example.com,Acme,COO,London,SaaS\n")
    imported = await leads.import_csv_rows("workspace", "actor", preview["rows"])
    assert imported["imported"] == 2 and len(canonical_data.rows) == 2
    replay = await leads.import_csv_rows("workspace", "actor", preview["rows"])
    assert replay["imported"] == 0 and len(replay["duplicates"]) == 2
    result = await leads.list_workspace_leads("workspace", query="acme", filters={"location": "London", "industry": "SaaS", "title": "COO"})
    ids = [row["id"] for row in result["leads"]]
    assert result["total"] == 2 and set(ids) == set(canonical_data.rows)
    assert (await leads.list_workspace_leads("other-workspace"))["total"] == 0
    analysis = await leads.analyze_workspace_leads("workspace", "actor", ids)
    assert all(row["status"] == "completed" for row in analysis["results"])
    assert all({fact["label"]: fact["value"] for fact in row["facts"]}["Company"] == "Acme" for row in analysis["results"])
    assert analysis["business_guidance"]["items"]
    assert durable_jobs.creates == 0  # Reading/analyzing does not start generation.

    monkeypatch.setattr(generation, "WorkspaceLeadRepository", canonical_data.repo)
    monkeypatch.setattr(generation, "analyze_workspace_leads", leads.analyze_workspace_leads)
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", MODEL_GENERATOR)
    model = Mock(return_value=json.dumps({
        "strategy": {"relevance_summary": "Potential role fit", "recommended_angle": "Ask about operations", "key_message": "Offer assistance", "things_to_avoid": ["Unsupported claims"], "next_action": "Human review"},
        "outreach": {"subject": "Operations", "body": "Would an operations conversation be relevant?"},
        "evidence_used": [{"source_type": "canonical_fact", "statement": "Company: Acme"}],
    }))
    monkeypatch.setattr(ai, "_send_openai_request", model)
    jobs = await asyncio.gather(*(generation.start_lead_generation("workspace", "actor", ids, "explicit-intent") for _ in range(2)))
    assert jobs[0]["job_id"] == jobs[1]["job_id"] and durable_jobs.creates == 1
    model.assert_not_called()  # POST queues work, it doesn't make a model call.
    completed = await generation.run_lead_generation(durable_jobs.claimed(jobs[0]["job_id"]), None)
    job = durable_jobs.rows[jobs[0]["job_id"]]
    job.result, job.status = completed["result"], JobStatus.COMPLETED
    recovered = await generation.start_lead_generation("workspace", "actor", ids, "explicit-intent")
    assert recovered["completed"] == 2 and model.call_count == 2
    assert all(row["status"] == "completed" for row in recovered["results"])
    with pytest.raises(HTTPException) as denied:
        await generation.generation_status("other-workspace", "actor", job.id)
    assert denied.value.status_code == 404

    monkeypatch.setattr(campaigns, "_authorize_selected_lead", AUTHORIZE_LEAD)
    request = campaigns_api.SaveCampaignRequest(name="Human controlled", idempotency_key="campaign-intent", leads=[{"workspace_lead_id": identity} for identity in ids])
    created = await campaigns_api.save_campaign("_", request, SimpleNamespace())
    repeated = await campaigns_api.save_campaign("_", request, SimpleNamespace())
    assert repeated["campaign"]["id"] == created["campaign"]["id"]
    assert database.commits == 1 and {lead_id for _, lead_id in database.links} == set(ids)
    campaigns.maybe_auto_strategy.assert_not_awaited()
    with pytest.raises(HTTPException) as denied:
        await AUTHORIZE_LEAD("other-workspace", {"workspace_lead_id": ids[0]})
    assert denied.value.status_code == 404


@pytest.fixture
def editable_draft(monkeypatch):
    entity = Draft(id="draft", workspace_id="workspace", subject="Original", body="Original body", status="pending")
    repo = SimpleNamespace(get=AsyncMock(return_value=entity), save=AsyncMock(side_effect=lambda row: row))
    monkeypatch.setattr(state, "DraftRepository", lambda: repo)
    async def workspace(actor, *, workspace_id):
        assert actor == "actor"
        return workspace_id
    monkeypatch.setattr(state, "_async_workspace", workspace)
    monkeypatch.setattr(state, "append_event", Mock(return_value=True))
    def load(actor, *, workspace_id, strict):
        assert actor == "actor" and strict
        return [{"id": entity.id, "text": entity.body}] if entity.workspace_id == workspace_id else []
    monkeypatch.setattr(state, "load_drafts_only", load)
    monkeypatch.setattr(drafts, "publish", Mock())
    async def authorized(_request): return "actor", "bearer", "workspace"
    monkeypatch.setattr(drafts_api, "_authorized_workspace", authorized)
    return entity, repo


@pytest.mark.asyncio
async def test_draft_review_edit_is_scoped_and_survives_canonical_readback(editable_draft):
    entity, repo = editable_draft
    response = await drafts_api.update_draft("_", "draft", drafts_api.UpdateDraftRequest(text="Subject: Edited subject\n\nEdited message"), SimpleNamespace())
    assert response["ok"] and (entity.subject, entity.body) == ("Edited subject", "Edited message")
    assert state._draft_as_dict(entity)["text"] == "Edited message"
    assert state._draft_as_dict(entity)["subject"] == "Edited subject"
    assert repo.save.await_count == 1


@pytest.mark.asyncio
async def test_draft_edit_rejects_another_workspace_without_writing(editable_draft):
    entity, repo = editable_draft
    with pytest.raises(HTTPException) as denied:
        await drafts.update_draft("_", "actor", "draft", "Changed", workspace_id="other-workspace")
    assert denied.value.status_code == 404 and entity.body == "Original body"
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_edit_persistence_failure_is_not_success(editable_draft):
    _, repo = editable_draft
    error = RuntimeError("schema failure")
    repo.save.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        await drafts.update_draft("_", "actor", "draft", "Changed", workspace_id="workspace")
    assert caught.value is error
    drafts.publish.assert_not_called()


@pytest.mark.asyncio
async def test_body_only_edit_keeps_existing_subject(editable_draft):
    entity, _ = editable_draft
    await drafts.update_draft("_", "actor", "draft", "Message without header", workspace_id="workspace")
    assert entity.subject == "Original" and entity.body == "Message without header"


@pytest.mark.asyncio
async def test_clearing_review_subject_is_persisted(editable_draft):
    entity, _ = editable_draft
    await drafts.update_draft("_", "actor", "draft", "Subject: \n\nEdited message", workspace_id="workspace")
    assert entity.subject == "" and entity.body == "Edited message" and entity.status == "pending"
