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
        async def update_qualification_for_workspace(self, identity, workspace, metadata):
            row = rows.get(identity)
            if row is None or row.workspace_id != workspace or row.deleted_at is not None:
                return False
            row.metadata = metadata
            return True

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
    monkeypatch.setattr("services.discovery.context.retrieve_discovery_context", AsyncMock(return_value={"provenance": {}}))
    monkeypatch.setattr(discovery, "store_discovery_plan", Mock(return_value=True))
    monkeypatch.setattr(discovery, "_merge_metadata", Mock(return_value=True))
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
    assert progress == [("job", "Understanding target market", 10), ("job", "Finding matching companies", 40),
                        ("job", "Ranking prospects", 65), ("job", "Preparing recommendations", 90)]
    assert "qualification" in two_workspaces["own"].metadata
    assert "qualification" not in two_workspaces["other"].metadata
    assert "qualification" not in two_workspaces["filtered"].metadata


@pytest.mark.asyncio
async def test_empty_workspace_is_successful_zero_matches(saved_search):
    job, staged, _ = saved_search
    result = await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert result == {"ok": True, "result": {"search_scope": "workspace", "matched_lead_count": 0,
        "candidate_outcomes": {"retrieved_count": 0, "filtered_candidate_count": 0, "evaluated_count": 0,
            "matched_count": 0, "unverified_match_count": 0, "interpretation_status": "uncertain",
            "exclusions": {"explicit_filter": 0, "explicit_keywords": 0, "literal_query": 0}}}}
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
async def test_smart_search_restores_plan_assessments_and_keeps_workspace_isolation(saved_search, two_workspaces, monkeypatch):
    from services.discovery.plan import derive_discovery_plan
    job, staged, _ = saved_search
    job.query = "Find SaaS founders in the US"
    monkeypatch.setattr(discovery, "get_discovery", lambda *args, **kwargs: {
        "id": "run", "workspace_id": "b", "created_by": "actor-b", "metadata": {}})
    plan = derive_discovery_plan(job.query, prospect_search=True)
    interpreter = Mock(return_value=plan)
    monkeypatch.setattr("services.discovery.plan.derive_discovery_plan", interpreter)
    for identity, workspace, title, location in [
        ("own", "b", "Founder", "US"), ("foreign", "a", "Founder", "US"),
        ("wrong-role", "b", "Engineer", "US"), ("wrong-country", "b", "Founder", "Canada"),
    ]:
        two_workspaces[identity] = WorkspaceLead(id=identity, workspace_id=workspace,
            first_name="Alice", title=title, metadata={"csv_import": {"company": "Acme", "industry": "SaaS", "location": location}})
    result = await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert result["result"]["matched_lead_count"] == 1
    assert [row["workspace_lead_id"] for row in staged] == ["own"]
    interpreter.assert_called_once_with(job.query, existing_context={"provenance": {}}, prospect_search=True)
    discovery.store_discovery_plan.assert_called_once_with("run", plan.to_dict(), {})
    assessment = two_workspaces["own"].metadata["qualification"]
    assert any(item["field"] == "title" and item["value"] == "Founder" for item in assessment["prospect_evidence"])
    assert "qualification" not in two_workspaces["foreign"].metadata
    listed = await leads.list_workspace_leads("b", "Alice")
    own = next(row for row in listed["leads"] if row["id"] == "own")
    assert own["metadata"]["qualification"] == assessment
    assert "csv_import" not in own["metadata"]  # fields projected separately, not extra raw metadata


@pytest.mark.asyncio
async def test_context_loading_failure_is_not_silently_empty_smart_search(saved_search, monkeypatch):
    job, staged, _ = saved_search
    monkeypatch.setattr("services.discovery.context.retrieve_discovery_context", AsyncMock(side_effect=RuntimeError("Context unavailable")))
    with pytest.raises(RuntimeError, match="Context unavailable"):
        await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert staged == []


@pytest.mark.asyncio
async def test_plan_persistence_failure_cannot_report_research_complete(saved_search, monkeypatch):
    job, staged, _ = saved_search
    monkeypatch.setattr(discovery, "store_discovery_plan", Mock(return_value=False))
    with pytest.raises(SearchResultPersistenceError, match="criteria could not be saved"):
        await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert staged == []


@pytest.mark.asyncio
async def test_deleted_or_moved_lead_during_assessment_cannot_be_recreated(saved_search, two_workspaces, monkeypatch):
    job, staged, _ = saved_search
    two_workspaces["own"] = WorkspaceLead(id="own", workspace_id="b", first_name="Builder", title="CTO")
    from services.persistence.launch import WorkspaceLeadRepository
    # A concurrent deletion/move means the guarded UPDATE finds no row.
    monkeypatch.setattr(WorkspaceLeadRepository, "update_qualification_for_workspace", AsyncMock(return_value=False))
    with pytest.raises(SearchResultPersistenceError, match="assessment could not be saved"):
        await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert staged == []
    assert len(two_workspaces) == 1


@pytest.mark.parametrize("lead,expected", [
    ({"title": "Founder", "industry": "SaaS", "location": "USA"}, True),
    ({"title": "Founder", "industry": "SaaS", "location": "Canada"}, False),
    ({"title": "Founder", "industry": "SaaS"}, False),
    ({"title": "Engineer", "industry": "SaaS", "location": "US"}, False),
    ({"title": "Founder", "industry": "Retail", "location": "US"}, False),
])
def test_smart_target_matching_requires_persisted_facts_for_each_dimension(lead, expected):
    from services.discovery.plan import workspace_search_matches
    assert workspace_search_matches(lead, "Find SaaS founders in the US", {
        "decision_maker_roles": ["Founder"], "industries": ["SaaS"], "geography": ["United States"],
    }) is expected


@pytest.mark.parametrize("query,expected", [
    ("find leads", True), ("show me my saved leads", True), ("list imported contacts", True),
    ("find Alice", True), ("search for Acme", True), ("find founders", True),
    ("find engineers", False), ("find Nonexistent Company", False), ("please", False),
    ("find Alice founders", True), ("find Bob founders", False),
])
def test_saved_search_handles_normal_wording_without_inferred_hard_filters(query, expected):
    from services.discovery.plan import workspace_search_matches
    assert workspace_search_matches({"first_name": "Alice", "company": "Acme", "title": "Founder"}, query, {
        "industries": ["SaaS", "startups"], "decision_maker_roles": ["Founder", "CEO"],
        "geography": ["United States"],
    }) is expected


def test_target_audience_is_not_invented_as_an_industry(monkeypatch):
    from services.discovery.plan import derive_discovery_plan
    monkeypatch.setattr("services.discovery.icp.extract_structured_icp", lambda *_args: {
        "offer": "Sales assistance", "target_audience": "startup founders", "buyer_roles": ["Founder"],
    })
    plan = derive_discovery_plan("find founders")
    assert plan.target_audience == "startup founders"
    assert plan.industries == []


@pytest.mark.asyncio
async def test_generic_search_stages_saved_leads_but_keeps_explicit_filters_and_workspace(saved_search, two_workspaces):
    job, staged, _ = saved_search
    job.query = "show me my saved leads"
    for identity, workspace, title in [("own", "b", "CTO"), ("foreign", "a", "CTO"), ("filtered", "b", "CEO")]:
        two_workspaces[identity] = WorkspaceLead(id=identity, workspace_id=workspace, title=title)
    result = await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert result["result"]["matched_lead_count"] == 1
    assert [row["workspace_lead_id"] for row in staged] == ["own"]


@pytest.mark.asyncio
async def test_http_discovery_start_worker_and_lead_database_reads_share_authorized_ids(saved_search, two_workspaces, monkeypatch, client):
    """Exercise mounted FastAPI routes, the saved worker and canonical reads offline."""
    from services.identity import dependencies
    from services.workspace import access
    from services.discovery.plan import derive_discovery_plan

    job, staged, _ = saved_search
    job.query = "heads of sales"
    row = {"id": "run", "workspace_id": "b", "created_by": "actor-b", "metadata": {"search_scope": "workspace"}}
    monkeypatch.setattr(discovery, "create_discovery", lambda *_args, **_kwargs: row)
    monkeypatch.setattr(discovery, "get_discovery", lambda *_args, **_kwargs: row)
    create_job = AsyncMock(return_value={"job_id": "job", "status": "queued"})
    monkeypatch.setattr(discovery.job_manager, "create_search_job", create_job)
    monkeypatch.setattr("services.discovery.plan.derive_discovery_plan", Mock(return_value=derive_discovery_plan(job.query, prospect_search=True)))

    auth_calls = []
    async def authenticate(request):
        assert request.headers["authorization"] == "Bearer offline-session"
        auth_calls.append(request.url.path)
        return "actor-b", ""  # No optional event publication in this offline fixture.
    async def selected(request, owner):
        assert owner == "actor-b"
        assert request.headers["x-workspace-id"] == "b"
        return SimpleNamespace(workspace_id="b")
    monkeypatch.setattr(dependencies, "resolve_web_session", authenticate)
    monkeypatch.setattr(access, "resolve_selected_workspace_context", selected)
    headers = {"Authorization": "Bearer offline-session", "X-Workspace-Id": "b"}
    two_workspaces["own"] = WorkspaceLead(id="own", workspace_id="b", first_name="Alice", title="Head of Sales")
    two_workspaces["foreign"] = WorkspaceLead(id="foreign", workspace_id="a", first_name="Bob", title="Head of Sales")
    two_workspaces["nonmatch"] = WorkspaceLead(id="nonmatch", workspace_id="b", title="Engineer")

    preflight = client.options("/api/discoveries", headers={"Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,x-workspace-id,content-type"})
    assert preflight.status_code == 200
    assert auth_calls == []  # CORS preflight never performs session/database lookups.
    response = client.post("/api/discoveries", headers=headers, json={"query": job.query, "initiation": "manual", "filters": {}})
    assert response.status_code == 200
    assert response.json()["discovery_id"] == "run"
    assert create_job.await_args.kwargs["workspace_id"] == "b"
    assert create_job.await_args.kwargs["search_scope"] == "workspace"
    outcome = await workflow_dispatcher.run_search_workflow(job, lambda *_args: None)
    assert outcome["result"]["matched_lead_count"] == 1
    assert [lead["workspace_lead_id"] for lead in staged] == ["own"]
    monkeypatch.setattr(leads, "_provider_sources_for_discovery", AsyncMock(return_value={"own": ["lead_database"]}))
    results = client.get("/api/web/session/_/leads", headers=headers, params={"q": job.query, "discovery_id": "run"})
    database = client.get("/api/web/session/_/leads", headers=headers)
    assert results.status_code == database.status_code == 200
    assert [lead["id"] for lead in results.json()["leads"]] == ["own"]
    assert {lead["id"] for lead in database.json()["leads"]} == {"own", "nonmatch"}
    assert auth_calls.count("/api/web/session/_/leads") == 4  # Middleware + route, twice.


@pytest.mark.asyncio
@pytest.mark.parametrize("returned,expected", [([{"id": "own"}], True), ([], False)])
async def test_assessment_update_is_scoped_metadata_only_never_insert_or_resurrect(monkeypatch, returned, expected):
    from services.persistence.launch import WorkspaceLeadRepository
    operations = []
    class Query:
        def update(self, payload): operations.append(("update", payload)); return self
        def eq(self, key, value): operations.append(("eq", key, value)); return self
        def is_(self, key, value): operations.append(("is", key, value)); return self
        def execute(self): return SimpleNamespace(data=returned)
    monkeypatch.setattr(WorkspaceLeadRepository, "_client", lambda _self: SimpleNamespace(table=lambda table: Query() if table == "workspace_leads" else None))
    metadata = {"csv_import": {"company": "Own company"}, "qualification": {"final_score": 20}}
    assert await WorkspaceLeadRepository().update_qualification_for_workspace("own", "b", metadata) is expected
    assert operations == [("update", {"metadata": metadata}), ("eq", "id", "own"),
                          ("eq", "workspace_id", "b"), ("is", "deleted_at", "null")]


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
