"""Saved-prospect interpretation and controlled offline worker acceptance.

No live services: the real interpreter, matcher, worker, finalizer and paginated
read run over synthetic repositories. This does not establish PostgREST/RLS.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.discovery import icp, service
from services.discovery.plan import derive_discovery_plan, prospect_match_outcome, workspace_search_matches
from services.leads import service as leads
from services.persistence.launch.models import WorkspaceLead
from services.job_engine.models import Job
from services.job_engine.storage import JobStorage, SearchResultPersistenceError


@pytest.mark.parametrize("query", ["Find operations leaders at e-commerce companies",
                                  "operations leaders at e commerce companies"])
@pytest.mark.parametrize("title,expected", [("Head of Operations", True), ("Operations Manager", True),
                                          ("COO", True), ("Engineer", False)])
def test_operations_synonyms_without_invented_product(query, title, expected, monkeypatch):
    monkeypatch.setattr(icp.requests, "post", lambda *_a, **_k: pytest.fail("No model request"))
    plan = derive_discovery_plan(query, prospect_search=True)
    assert plan.offering == plan.messaging_angle == ""
    assert plan.product_guidance == []
    assert plan.search_constraints["unresolved_constraints"] == []
    assert workspace_search_matches({"title": title, "industry": "E-commerce"}, query, plan.to_dict()) is expected


@pytest.mark.parametrize("industry,location,reason,unverified", [
    ("e commerce", "London", "matched", []),
    ("", "", "matched", ["industry", "location"]),
    ("Retail", "London", "industry", []),
    ("ecommerce", "Toronto", "location", []),
])
def test_known_contradictions_and_unknown_optional_fields(industry, location, reason, unverified):
    plan = derive_discovery_plan("operations leaders at e-commerce companies in London", prospect_search=True)
    outcome = prospect_match_outcome({"title": "COO", "industry": industry, "location": location}, plan.search_constraints)
    assert outcome == {"matched": reason == "matched", "reason": reason, "unverified_fields": unverified}


def test_product_knowledge_is_attributed_not_a_search_filter():
    context = {"knowledge": {"items": [{"id": "k", "source_id": "s", "category": "company",
        "content": {"product": "Warehouse tools"}}]},
        "knowledge_icp": {"buyer_industries": ["Manufacturing"], "buyer_roles": ["CFO"]}}
    plain = derive_discovery_plan("operations leaders at e commerce companies", prospect_search=True)
    guided = derive_discovery_plan("operations leaders at e commerce companies", context, prospect_search=True)
    assert guided.search_constraints == plain.search_constraints
    assert guided.offering == "Warehouse tools"
    assert guided.messaging_angle == ""
    assert guided.product_guidance == [{"offering": "Warehouse tools", "knowledge_item_id": "k", "knowledge_source_id": "s"}]
    assert workspace_search_matches({"title": "COO", "industry": "ecommerce"}, "", guided.to_dict())


def test_unknown_constraints_are_retained_not_an_all_leads_fallback():
    plan = derive_discovery_plan("operations leaders with quantum certification", prospect_search=True)
    assert plan.search_constraints["interpretation_status"] == "uncertain"
    assert plan.search_constraints["unresolved_constraints"] == ["quantum certification"]
    assert not workspace_search_matches({"title": "COO"}, "", plan.to_dict())
    assert workspace_search_matches({"title": "COO quantum certification"}, "", plan.to_dict())
    empty = derive_discovery_plan("please", prospect_search=True)
    assert empty.search_constraints["interpretation_status"] == "uncertain"
    assert not workspace_search_matches({"title": "COO"}, "", empty.to_dict())
    unknown_place = derive_discovery_plan("find leads in Atlantis", prospect_search=True)
    assert unknown_place.search_constraints["unresolved_constraints"] == ["atlantis"]
    assert not workspace_search_matches({"title": "COO"}, "", unknown_place.to_dict())


def test_named_company_constraint():
    plan = derive_discovery_plan("operations leaders at Acme in London", prospect_search=True)
    assert plan.search_constraints["companies"] == ["acme"]
    assert workspace_search_matches({"title": "COO", "company": "Acme", "location": "London"}, "", plan.to_dict())
    assert not workspace_search_matches({"title": "COO", "company": "Other", "location": "London"}, "", plan.to_dict())


@pytest.mark.asyncio
async def test_knowledge_reader_preserves_authorized_workspace_and_attribution(monkeypatch):
    from services.discovery.context import retrieve_discovery_context
    reader = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {
        "items": [{"id": "k", "source_id": "s", "content": {"product": "Tools"}}],
        "item_ids": ["k"], "source_ids": ["s"]}))
    monkeypatch.setattr("services.discovery.context.retrieve_knowledge_context", reader)
    updates = AsyncMock(return_value=[])
    monkeypatch.setattr("services.strategic.service.StrategicIntelligenceService", lambda: SimpleNamespace(list_updates=updates))
    context = await retrieve_discovery_context("actor", "operations leaders", workspace_id="b")
    assert reader.await_args.kwargs["workspace_id"] == "b"
    assert updates.await_args.kwargs["workspace_id"] == "b"
    assert context["provenance"]["knowledge_item_ids"] == ["k"]


@pytest.fixture
def controlled_search(monkeypatch):
    rows = {}
    specs = [("head", "b", "Head of Operations", "ecommerce", "London"),
             ("manager", "b", "Operations Manager", "e commerce", "London"),
             ("coo", "b", "COO", "e-commerce", "London"),
             ("unknown", "b", "COO", "", ""),
             ("role", "b", "Engineer", "ecommerce", "London"),
             ("industry", "b", "COO", "Retail", "London"),
             ("location", "b", "COO", "ecommerce", "Toronto"),
             ("foreign", "a", "COO", "ecommerce", "London")]
    for identity, workspace, title, industry, location in specs:
        rows[identity] = WorkspaceLead(id=identity, workspace_id=workspace, title=title,
            metadata={"csv_import": {"company": "Acme", "industry": industry, "location": location}})
    class Repository:
        async def list_for_workspace(self, workspace):
            return [row for row in rows.values() if row.workspace_id == workspace and row.deleted_at is None]
        async def get_for_workspace(self, identity, workspace):
            row = rows.get(identity)
            return row if row and row.workspace_id == workspace else None
        async def update_qualification_for_workspace(self, identity, workspace, metadata):
            row = await self.get_for_workspace(identity, workspace)
            if not row or row.deleted_at:
                return False
            row.metadata = metadata
            return True
    monkeypatch.setattr(leads, "WorkspaceLeadRepository", Repository)
    monkeypatch.setattr("services.persistence.launch.WorkspaceLeadRepository", Repository)
    monkeypatch.setattr("services.workspace.access.resolve_workspace_context", lambda *_a: SimpleNamespace(workspace_id="b"))
    monkeypatch.setattr("services.discovery.context.retrieve_discovery_context", AsyncMock(return_value={"provenance": {}}))
    row = {"id": "run", "workspace_id": "b", "created_by": "actor", "status": "searching", "metadata": {}}
    monkeypatch.setattr(service, "get_discovery", lambda *_a, **_k: row)
    class Query:
        inserted = None
        def select(self, *_a): return self
        def eq(self, *_a): return self
        def limit(self, *_a): return self
        def update(self, payload): row.update(payload); return self
        def insert(self, payload): self.inserted = payload; return self
        def execute(self):
            if self.inserted is not None:
                assert all(link["discovery_id"] == "run" for link in self.inserted)
                links.extend(link["lead_id"] for link in self.inserted)
                row["discovery_leads"] = [dict(link) for link in self.inserted]
                return SimpleNamespace(data=self.inserted)
            return SimpleNamespace(data=[row])
    monkeypatch.setattr(service, "get_supabase_client", lambda: SimpleNamespace(table=lambda *_a: Query()))
    staged, links = [], []
    monkeypatch.setattr(JobStorage, "store_search_results", lambda _s, _id, results: staged.extend(results) or True)
    monkeypatch.setattr(JobStorage, "get_search_results", lambda *_a: staged)
    monkeypatch.setattr(service, "_link_companies", lambda *_a: 1 if staged else 0)
    monkeypatch.setattr(leads, "_provider_sources_for_discovery", AsyncMock(side_effect=lambda *_a: {identity: ["lead_database"] for identity in links}))
    job = Job(id="job", user_id="actor", workspace_id="b", discovery_id="run",
              query="operations leaders at e commerce companies in London", payload={"search_scope": "workspace"})
    return job, rows, row, staged, links


@pytest.mark.asyncio
@pytest.mark.parametrize("location_requested", [False, True])
async def test_controlled_search_finalizes_links_pages_and_reconciled_counts(controlled_search, location_requested):
    job, rows, run, staged, links = controlled_search
    if not location_requested:
        job.query = "operations leaders at e commerce companies"
    expected = {"head", "manager", "coo", "unknown"} | (set() if location_requested else {"location"})
    result = await service.search_saved_workspace_leads(job, lambda *_a: None)
    assert {item["id"] for item in staged} == expected
    counts = result["result"]["candidate_outcomes"]
    assert counts["retrieved_count"] == counts["evaluated_count"] == 7
    assert counts["matched_count"] == len(expected)
    assert counts["unverified_match_count"] == 1
    assert counts["exclusions"] == {"explicit_filter": 0, "explicit_keywords": 0, "literal_query": 0,
                                     "role": 1, "industry": 1, **({"location": 1} if location_requested else {})}
    assert counts["retrieved_count"] == counts["matched_count"] + sum(counts["exclusions"].values())
    assert run["metadata"]["candidate_outcomes"] == counts
    assert "qualification" not in rows["foreign"].metadata
    assert rows["unknown"].metadata["qualification"]["search_match"]["unverified_fields"] == (["industry", "location"] if location_requested else ["industry"])
    assert await service.finalize_discovery(job)
    assert set(links) == expected
    assert {link["lead_id"] for link in run["discovery_leads"]} == set(links)
    assert [link["rank"] for link in run["discovery_leads"]] == list(range(1, len(expected) + 1))
    assert run["status"] == "completed"
    assert run["summary"]["lead_count"] == len(expected)
    assert run["summary"]["candidate_outcomes"] == counts
    first = await leads.list_workspace_leads("b", job.query, page=1, page_size=3, discovery_id="run")
    second = await leads.list_workspace_leads("b", job.query, page=2, page_size=3, discovery_id="run")
    assert first["total"] == second["total"] == len(expected)
    ids = [lead["id"] for lead in first["leads"] + second["leads"]]
    assert len(ids) == len(set(ids)) == len(expected)
    assert set(ids) == set(links)


@pytest.mark.asyncio
@pytest.mark.parametrize("filters,matched,excluded", [({"industry": "ecommerce"}, {"head", "role", "location"}, 4),
                                                   ({"location": "London"}, {"head", "manager", "coo", "role", "industry"}, 2)])
async def test_explicit_filters_remain_strict_and_counts_reconcile(controlled_search, filters, matched, excluded):
    result = await leads.list_workspace_leads("b", filters=filters, page_size=None, include_outcomes=True)
    assert {lead["id"] for lead in result["leads"]} == matched
    assert result["candidate_outcomes"]["exclusions"]["explicit_filter"] == excluded
    assert result["candidate_outcomes"]["retrieved_count"] == result["total"] + excluded


@pytest.mark.asyncio
async def test_worker_explicit_filter_exclusions_and_match_exclusions_reconcile(controlled_search):
    job, _, run, staged, _ = controlled_search
    run["metadata"]["ui_filters"] = {"location": "London"}
    result = await service.search_saved_workspace_leads(job, lambda *_a: None)
    counts = result["result"]["candidate_outcomes"]
    assert counts["retrieved_count"] == 7
    assert counts["filtered_candidate_count"] == counts["evaluated_count"] == 5
    assert counts["exclusions"]["explicit_filter"] == 2
    assert counts["exclusions"]["role"] == counts["exclusions"]["industry"] == 1
    assert counts["matched_count"] == 3
    assert counts["unverified_match_count"] == 0
    assert {lead["id"] for lead in staged} == {"head", "manager", "coo"}
    assert counts["retrieved_count"] == counts["matched_count"] + sum(counts["exclusions"].values())


@pytest.mark.asyncio
async def test_candidate_metadata_failure_is_not_zero_success(controlled_search, monkeypatch):
    job, _, _, staged, _ = controlled_search
    monkeypatch.setattr(service, "store_discovery_plan", lambda *_a: True)
    monkeypatch.setattr(service, "_merge_metadata", lambda *_a: False)
    with pytest.raises(SearchResultPersistenceError, match="candidate outcomes could not be saved"):
        await service.search_saved_workspace_leads(job, lambda *_a: None)
    assert staged == []


@pytest.mark.asyncio
async def test_empty_controlled_search_records_zero_without_failure(controlled_search):
    job, rows, run, staged, links = controlled_search
    rows.clear()
    outcome = await service.search_saved_workspace_leads(job, lambda *_a: None)
    counts = outcome["result"]["candidate_outcomes"]
    assert counts["retrieved_count"] == counts["evaluated_count"] == counts["matched_count"] == 0
    assert sum(counts["exclusions"].values()) == 0
    assert staged == links == []
    assert await service.finalize_discovery(job)
    assert run["status"] == "completed"
    assert run["summary"]["lead_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("staging_change", ["missing", "truncated", "duplicate"])
async def test_finalization_rejects_staging_count_mismatch(controlled_search, staging_change):
    job, _, run, staged, _ = controlled_search
    result = await service.search_saved_workspace_leads(job, lambda *_a: None)
    counts = dict(result["result"]["candidate_outcomes"])
    if staging_change == "missing":
        staged.clear()
    elif staging_change == "truncated":
        staged.pop()
    else:
        staged.append(dict(staged[0]))
    assert await service.finalize_discovery(job) is False
    assert run["status"] == "failed"
    assert run["summary"]["error_kind"] == "persistence"
    assert run["summary"]["candidate_outcomes"] == counts
    assert "counts do not match" in run["summary"]["error"]


@pytest.mark.asyncio
async def test_recovery_retains_counts_from_durable_discovery_metadata(controlled_search):
    job, _, run, _, _ = controlled_search
    result = await service.search_saved_workspace_leads(job, lambda *_a: None)
    counts = dict(result["result"]["candidate_outcomes"])
    job.result = {}  # Worker ended before its completion result was saved.
    assert await service.finalize_discovery(job)
    assert run["summary"]["candidate_outcomes"] == counts
    assert run["summary"]["lead_count"] == counts["matched_count"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_staging", [False, True])
async def test_runner_completion_requires_reconciled_persisted_results(controlled_search, lose_staging):
    from services.job_engine.models import JobStatus
    from services.job_engine.runner import BackgroundRunner
    job, _, run, staged, _ = controlled_search
    writes = []
    class Storage:
        def update_job(self, _identity, **values):
            writes.append(values)
            for key, value in values.items():
                setattr(job, key, value)
            return True
    async def work(current_job, progress):
        result = await service.search_saved_workspace_leads(current_job, progress)
        if lose_staging:
            staged.clear()
        return result
    await BackgroundRunner(Storage())._run_wrapper(job, work, on_complete=service.finalize_discovery)
    assert job.status == (JobStatus.FAILED if lose_staging else JobStatus.COMPLETED)
    assert job.result_ready is (not lose_staging)
    counts = run["summary"]["candidate_outcomes"]
    assert counts["retrieved_count"] == counts["matched_count"] + sum(counts["exclusions"].values())
    if not lose_staging:
        assert job.result["candidate_outcomes"] == counts
        assert job.result["matched_lead_count"] == run["summary"]["lead_count"] == 4
    else:
        assert not any(write.get("status") == JobStatus.COMPLETED for write in writes)


def test_sales_extractor_keeps_its_contract_and_receives_knowledge(monkeypatch):
    import json
    captured = []
    monkeypatch.setattr(icp, "OPENAI_API_KEY", "offline-only")
    def model_reply(*_args, **kwargs):
        captured.append(kwargs["json"])
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
            json=lambda: {"output_text": json.dumps({"offer": "CRM software", "buyer_roles": ["Founder"], "buyer_industries": ["SaaS"]})})
    monkeypatch.setattr(icp.requests, "post", model_reply)
    context = {"knowledge": {"items": [{"id": "k", "category": "company", "title": "Company context",
        "content": {"product": "CRM software"}}]}}
    result = icp.extract_structured_icp("crm for startups", context)
    assert result["offer"] == "CRM software"
    assert "WORKSPACE CONTEXT" in captured[0]["input"][1]["content"][0]["text"]
