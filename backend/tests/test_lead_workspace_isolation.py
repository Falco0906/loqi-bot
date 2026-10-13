"""Workspace confidentiality and saved-only Discovery, with offline fakes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.discovery import service as discovery
from services.leads import service as leads
from services.persistence.launch import Lead, Company, WorkspaceLead
from services.workspace import state
from services.workspace.lead_projection import workspace_lead_context
from services.job_engine.models import Job
from services.job_engine.storage import JobStorage, SearchResultPersistenceError
import workflow_dispatcher


@pytest.fixture
def two_workspaces(monkeypatch):
    # Existing globally deduplicated rows contain account A's private fields.
    profile = Lead(id="global-person", email="shared@example.test", first_name="Private A",
                   title="Private role A", phone="private-phone-A")
    company = Company(id="global-company", domain="example.test", name="Private company A",
                      description="Private description A", industry="Private industry A")
    rows = {}

    class WorkspaceLeads:
        async def find_in_workspace(self, workspace, lead_id):
            return next((row for row in rows.values() if row.workspace_id == workspace and row.lead_id == lead_id), None)
        async def list_for_workspace(self, workspace):
            return [row for row in rows.values() if row.workspace_id == workspace]
        async def get_for_workspace(self, identity, workspace):
            row = rows.get(identity)
            return row if row and row.workspace_id == workspace else None
        async def save(self, row):
            rows[row.id] = row
            return row

    monkeypatch.setattr(state, "LeadRepository", lambda: SimpleNamespace(find_by_email=AsyncMock(return_value=profile)))
    monkeypatch.setattr(state, "CompanyRepository", lambda: SimpleNamespace(find_by_domain=AsyncMock(return_value=company)))
    monkeypatch.setattr(state, "WorkspaceCompanyRepository", lambda: SimpleNamespace(
        find=AsyncMock(return_value=None), save=AsyncMock(side_effect=lambda row: row)))
    monkeypatch.setattr(state, "WorkspaceLeadRepository", WorkspaceLeads)
    monkeypatch.setattr(leads, "WorkspaceLeadRepository", WorkspaceLeads)
    monkeypatch.setattr("services.persistence.launch.WorkspaceLeadRepository", WorkspaceLeads)
    return rows


@pytest.mark.asyncio
async def test_same_email_in_two_workspaces_never_copies_global_private_fields(two_workspaces):
    first = await state.import_workspace_lead("a", {"email": "shared@example.test", "first_name": "Alice",
        "source": "csv_import", "csv_import_metadata": {"company": "Company A", "industry": "Private A"}})
    second = await state.import_workspace_lead("b", {"email": "shared@example.test", "source": "csv_import"})
    assert first != second
    assert two_workspaces[first].lead_id == two_workspaces[second].lead_id
    assert two_workspaces[second].first_name == two_workspaces[second].phone == two_workspaces[second].title == ""
    listed = await leads.list_workspace_leads("b")
    assert [row["id"] for row in listed["leads"]] == [second]
    assert listed["leads"][0]["company"] == listed["leads"][0]["industry"] == ""
    assert (await leads.list_workspace_leads("b", "Private A"))["total"] == 0
    assert (await leads.list_workspace_leads("new-account"))["total"] == 0
    analysis = (await leads._load_selected_workspace_leads("b", [second]))[0]
    assert analysis["company"] == analysis["company_description"] == ""
    assert analysis["buying_signals"] == []
    campaign_lead = state._lead_as_dict(two_workspaces[second])
    assert campaign_lead["name"] == campaign_lead["company"] == campaign_lead["phone"] == ""
    with pytest.raises(leads.LeadImportError, match="unavailable"):
        await leads._load_selected_workspace_leads("b", [first])


@pytest.mark.asyncio
async def test_own_import_and_provider_fields_survive_without_global_enrichment(two_workspaces):
    identity = await state.import_workspace_lead("b", {
        "email": "shared@example.test", "name": "Bob Builder", "provider": "explicit-source",
        "company": "Company B", "industry": "B Industry", "description": "B description", "employee_count": 42,
    })
    record = (await leads.list_workspace_leads("b"))["leads"][0]
    assert (record["first_name"], record["last_name"], record["company"], record["industry"]) == (
        "Bob", "Builder", "Company B", "B Industry")
    analysis = (await leads._load_selected_workspace_leads("b", [identity]))[0]
    assert analysis["company_description"] == "B description"
    assert analysis["company_employees"] == 42


def test_discovery_detail_excludes_global_and_foreign_linked_data():
    row = {"workspace_id": "b", "discovery_leads": [
        {"lead_id": "own", "workspace_lead": {"id": "own", "workspace_id": "b", "company_id": "shared",
            "metadata": {"csv_import": {"company": "Company B"}}, "lead": {"phone": "Private A"}}},
        {"lead_id": "foreign", "workspace_lead": {"id": "foreign", "workspace_id": "a"}},
        {"lead_id": "deleted", "workspace_lead": {"id": "deleted", "workspace_id": "b", "deleted_at": "yesterday"}},
    ], "discovery_companies": [{"company_id": "shared", "company": {"name": "Private A"}}, {"company_id": "foreign"}]}
    projected = discovery._workspace_discovery_results(row)
    assert [lead["lead_id"] for lead in projected["discovery_leads"]] == ["own"]
    assert "lead" not in projected["discovery_leads"][0]["workspace_lead"]
    assert projected["discovery_companies"] == [{"company_id": "shared", "company": {
        "id": "shared", "company": "Company B", "name": "Company B"}}]
    assert "Private A" not in str(projected)


def test_malformed_workspace_context_is_not_stringified_as_facts():
    assert workspace_lead_context({"metadata": {"provider_context": {
        "company": {"secret": "invalid"}, "employee_count": True, "buying_signals": "not a list",
        "technology": "not a mapping", "description": "Own description",
    }}}) == {"description": "Own description"}


@pytest.fixture
def saved_search(monkeypatch, two_workspaces):
    job = Job(id="job", user_id="actor-b", workspace_id="b", discovery_id="run", query="Builder",
              payload={"search_scope": "workspace"})
    monkeypatch.setattr(discovery, "get_discovery", lambda *args, **kwargs: {
        "id": "run", "workspace_id": "b", "created_by": "actor-b", "metadata": {"ui_filters": {"title": "CTO"}}})
    authorized = Mock(return_value=SimpleNamespace(workspace_id="b"))
    monkeypatch.setattr("services.workspace.access.resolve_workspace_context", authorized)
    staged = []
    monkeypatch.setattr(JobStorage, "store_search_results", lambda _self, _id, rows: staged.extend(rows) or True)
    monkeypatch.setattr(workflow_dispatcher, "_search_with_progress", Mock(side_effect=AssertionError("No provider search")))
    monkeypatch.setattr("services.discovery.plan.derive_discovery_plan", Mock(side_effect=AssertionError("No model call")))
    return job, staged, authorized


@pytest.mark.asyncio
async def test_saved_search_stages_only_matching_current_workspace_ids(saved_search, two_workspaces):
    job, staged, authorized = saved_search
    for identity, workspace, title in [("own", "b", "CTO"), ("other", "a", "CTO"), ("filtered", "b", "CEO")]:
        two_workspaces[identity] = WorkspaceLead(id=identity, workspace_id=workspace, first_name="Builder", title=title)
    progress = []
    def on_progress(job_id, stage, percent):
        progress.append((job_id, stage, percent))
    result = await workflow_dispatcher.run_search_workflow(job, on_progress)
    assert result["ok"] is True
    assert result["result"]["matched_lead_count"] == 1
    assert [row["workspace_lead_id"] for row in staged] == ["own"]
    assert "email" not in staged[0]
    authorized.assert_called_once_with(None, "actor-b", "b")
    assert len(two_workspaces) == 3  # search never imports or copies a lead
    assert progress == [("job", "Searching your workspace's saved leads", 10), ("job", "Saving your workspace search", 90)]


@pytest.mark.asyncio
async def test_empty_workspace_is_successful_zero_matches(saved_search):
    job, staged, _ = saved_search
    result = await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert result == {"ok": True, "result": {"search_scope": "workspace", "matched_lead_count": 0}}
    assert staged == []


@pytest.mark.asyncio
async def test_failed_staging_is_not_empty_search_success(saved_search, monkeypatch):
    job, _, _ = saved_search
    monkeypatch.setattr(JobStorage, "store_search_results", lambda *_args: False)
    with pytest.raises(SearchResultPersistenceError):
        await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)


@pytest.mark.asyncio
async def test_revoked_membership_stops_search_before_read_or_write(saved_search, monkeypatch):
    job, staged, authorized = saved_search
    authorized.side_effect = PermissionError("Workspace unavailable")
    read = AsyncMock(side_effect=AssertionError("No unauthorized lead read"))
    monkeypatch.setattr(leads, "list_workspace_leads", read)
    with pytest.raises(PermissionError):
        await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    read.assert_not_awaited()
    assert staged == []


@pytest.mark.asyncio
async def test_old_provider_jobs_cannot_source_leads_in_beta(monkeypatch):
    search = Mock(side_effect=AssertionError("No provider call"))
    monkeypatch.setattr(workflow_dispatcher, "_search_with_progress", search)
    result = await workflow_dispatcher.run_search_workflow(Job(query="founders"), lambda *_args: None)
    assert result["ok"] is False
    assert result["provider_error_kind"] == "permanent"
    search.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("lead_workspace,expected", [("b", True), ("a", False)])
async def test_saved_search_finalization_validates_ids_without_importing(two_workspaces, monkeypatch, lead_workspace, expected):
    two_workspaces["saved"] = WorkspaceLead(id="saved", workspace_id=lead_workspace)
    row = {"id": "run", "workspace_id": "b", "status": "searching"}
    updates = []
    class Query:
        def __init__(self): self.payload = None
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, payload): self.payload = payload; return self
        def execute(self):
            if self.payload is not None: updates.append(self.payload)
            return SimpleNamespace(data=[row])
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))
    monkeypatch.setattr(JobStorage, "get_search_results", lambda *_args: [
        {"id": "saved", "workspace_lead_id": "saved", "source": "lead_database"}])
    normalize = AsyncMock(side_effect=AssertionError("A saved search must never normalize/import leads"))
    monkeypatch.setattr(state, "_normalize_lead", normalize)
    links = []
    monkeypatch.setattr(discovery, "_link_leads", lambda _id, _leads, ids: links.extend(ids) or len(ids))
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: 0)
    monkeypatch.setattr(discovery, "mark_discovery_status", lambda *_args, **kwargs: True)
    job = Job(id="job", workspace_id="b", discovery_id="run", payload={"search_scope": "workspace"})
    assert await discovery.finalize_discovery(job) is expected
    assert links == (["saved"] if expected else [])
    normalize.assert_not_awaited()
    assert len(two_workspaces) == 1
    if not expected:
        assert updates[-1]["summary"]["error_kind"] == "persistence"


@pytest.mark.asyncio
async def test_discovery_route_has_no_legacy_workspace_fallback(monkeypatch):
    from fastapi import HTTPException
    from services.discovery import api
    monkeypatch.setattr(api.identity_dependencies, "resolve_web_session", AsyncMock(return_value=("new-user", "token")))
    monkeypatch.setattr(api.workspace_access, "resolve_selected_workspace_id", AsyncMock(side_effect=HTTPException(404, "Workspace unavailable")))
    legacy = AsyncMock(side_effect=AssertionError("No automatic legacy workspace"))
    monkeypatch.setattr(api.workspace_access, "resolve_legacy_workspace_id", legacy)
    with pytest.raises(HTTPException) as error:
        await api._authorized_workspace(SimpleNamespace())
    assert error.value.status_code == 404
    legacy.assert_not_awaited()
