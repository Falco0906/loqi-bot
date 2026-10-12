"""Batch 8: fake repositories/clients only; no external persistence."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.persistence.launch import WorkspaceLead, Lead
from services.persistence.launch.repositories import WorkspaceLeadRepository, CompanyRepository
import services.leads.service as leads
import services.workspace.state as state


@pytest.mark.asyncio
async def test_workspace_read_exceeds_response_cap_and_validates_every_page(monkeypatch):
    offsets = []
    class Query:
        def table(self, name): assert name == "workspace_leads"; return self
        def select(self, *_): return self
        def eq(self, key, value): assert (key, value) == ("workspace_id", "selected"); return self
        def is_(self, key, value): assert (key, value) == ("deleted_at", "null"); return self
        def order(self, key): assert key == "id"; return self
        def range(self, start, end): self.start, self.end = start, end; offsets.append(start); return self
        def execute(self):
            return SimpleNamespace(data=[{"id": f"id-{i:04d}", "workspace_id": "selected"}
                                         for i in range(self.start, min(self.end + 1, 1101))])
    monkeypatch.setattr(WorkspaceLeadRepository, "_client", lambda _: Query())
    rows = await WorkspaceLeadRepository().list_for_workspace("selected")
    assert len(rows) == len({row.id for row in rows}) == 1101
    assert offsets == [0, 500, 1000]
    monkeypatch.setattr(Query, "execute", lambda _: SimpleNamespace(data=None))
    with pytest.raises(ValueError, match="Invalid"):
        await WorkspaceLeadRepository().list_for_workspace("selected")


@pytest.mark.asyncio
async def test_optional_projection_queries_are_bounded_and_deduplicated(monkeypatch):
    batches = []
    async def read(self, where, limit):
        ids = where[0][2]; batches.append(ids)
        assert limit == len(ids) <= 200
        return ids
    monkeypatch.setattr(CompanyRepository, "_list", read)
    ids = [str(i) for i in range(1101)]
    assert await CompanyRepository().list_by_ids(ids + ids) == ids
    assert len(batches) == 6


def test_provider_aliases_and_malformed_scalars_are_data_only():
    raw = {"full_name": " Ada  Lovelace ", "company_name": "Acme", "job_title": "COO",
           "company_website": "https://acme.example", "company_industry": "SaaS",
           "email": {"unexpected": "container"}, "location": ["London"]}
    normalized = state._canonicalize_lead_payload(raw)
    assert normalized["first_name"] == "Ada"
    assert normalized["last_name"] == "Lovelace"
    assert normalized["company"] == "Acme" and normalized["title"] == "COO"
    assert normalized["email"] == normalized["location"] == ""
    assert raw["email"] == {"unexpected": "container"}
    metadata = state._qualification_metadata({"provider": "apollo", "company": "New Co"},
                                            {"provider_context": {"company": "Known Co", "website": "known.example"}})
    assert metadata["provider_context"] == {"company": "Known Co", "website": "known.example"}
    for payload in ({"domain": "HTTPS://WWW.Acme.Example/path"}, {"website": "www.acme.example"}, {"domain": "acme.example"}):
        assert state._lead_domain(payload) == "acme.example"
    assert state._lead_domain({"website": "https://[invalid"}) is None


def test_search_and_intelligence_use_same_csv_facts_and_provider_fallback():
    row = WorkspaceLead(id="canonical", first_name="Ada", title="COO",
                        metadata={"csv_import": {"company": "Imported Co", "industry": "SaaS", "company_size": "50–500"},
                                  "provider_context": {"company": "Provider Co", "website": "acme.example"}})
    company = SimpleNamespace(name="Global Co", metadata=None, industry=None, location=[])
    display = leads._canonical_display_fields(row, None, company)
    analysis = leads._canonical_analysis_lead(row, None, company)
    assert display["company"] == "Imported Co"
    assert display["website"] == "acme.example"
    assert display["location"] == ""
    assert analysis["id"] == "canonical"
    assert all(analysis[key] == value for key, value in display.items())
    assert analysis["company_size"] == "50–500"
    assert {"label": "Company size", "value": "50–500", "source": "canonical workspace lead data"} in leads._facts(analysis)
    row.metadata = {"csv_import": ["malformed"]}
    assert leads._canonical_analysis_lead(row, None, None)["company"] == ""


@pytest.mark.asyncio
async def test_filters_and_stable_pages_ignore_repository_row_order(monkeypatch):
    rows = [WorkspaceLead(id=f"id-{i:03d}", first_name="Same", title="COO",
                          metadata={"csv_import": {"company": "Acme", "location": "London", "industry": "SaaS"}})
            for i in range(105)]
    repo = SimpleNamespace(list_for_workspace=AsyncMock(side_effect=lambda _: list(reversed(rows))))
    projection = SimpleNamespace(list_by_ids=AsyncMock(return_value=[]))
    monkeypatch.setattr(leads, "WorkspaceLeadRepository", lambda: repo)
    monkeypatch.setattr(leads, "LeadRepository", lambda: projection)
    monkeypatch.setattr(leads, "CompanyRepository", lambda: projection)
    filters = {"company": "acme", "title": "coo", "industry": "saas", "location": "london", "keywords": "same"}
    pages = [await leads.list_workspace_leads("selected", page=p, filters=filters) for p in (1, 2, 3)]
    assert [item["id"] for page in pages for item in page["leads"]] == [row.id for row in rows]
    assert all(page["total"] == 105 for page in pages)
    assert (await leads.list_workspace_leads("selected", filters={"industry": "finance"}))["total"] == 0
    assert (await leads.list_workspace_leads("selected", query="id-"))["total"] == 0


@pytest.mark.asyncio
async def test_saved_run_failure_is_not_silent_zero_result_success(monkeypatch):
    monkeypatch.setattr(leads, "WorkspaceLeadRepository", lambda: SimpleNamespace(list_for_workspace=AsyncMock(return_value=[])))
    projection = SimpleNamespace(list_by_ids=AsyncMock(return_value=[]))
    monkeypatch.setattr(leads, "LeadRepository", lambda: projection)
    monkeypatch.setattr(leads, "CompanyRepository", lambda: projection)
    def failure(*_): raise RuntimeError("projection failure")
    monkeypatch.setattr(leads, "get_discovery_lead_provenance", failure)
    failed = await leads.list_workspace_leads("selected", discovery_id="run")
    assert failed["total"] == 0 and failed["warnings"]
    empty = await leads.list_workspace_leads("selected")
    assert empty["total"] == 0 and not empty.get("warnings")


@pytest.mark.asyncio
async def test_email_less_csv_contacts_remain_distinct_and_retries_reuse_identity(monkeypatch):
    profiles, rows = {}, {}
    class ProfileRepo:
        async def find_by_canonical_id(self, key): return profiles.get(key)
        async def save(self, row): profiles[row.canonical_id] = row; return row
    class WorkspaceRepo:
        async def find_in_workspace(self, workspace, profile): return rows.get((workspace, profile))
        async def save(self, row): rows[(row.workspace_id, row.lead_id)] = row; return row
    monkeypatch.setattr(state, "LeadRepository", ProfileRepo)
    monkeypatch.setattr(state, "WorkspaceLeadRepository", WorkspaceRepo)
    # No domain means there is no company lookup in this bounded test case.
    first = {"name": "Ada Lovelace", "company": "Acme", "source": "csv_import", "csv_import_metadata": {"company": "Acme"}}
    second = {**first, "name": "Grace Hopper"}
    a = await state._normalize_lead("selected", first)
    b = await state._normalize_lead("selected", second)
    assert a != b
    assert await state._normalize_lead("selected", first) == a
    assert len(rows) == 2
    assert {row.first_name for row in rows.values()} == {"Ada", "Grace"}


@pytest.mark.asyncio
async def test_provider_does_not_overwrite_populated_csv_contact(monkeypatch):
    row = WorkspaceLead(id="canonical", workspace_id="selected", lead_id="profile", first_name="Ada", title="COO", source="csv_import")
    monkeypatch.setattr(state, "LeadRepository", lambda: SimpleNamespace(find_by_email=AsyncMock(return_value=Lead(id="profile"))))
    monkeypatch.setattr(state, "WorkspaceLeadRepository", lambda: SimpleNamespace(find_in_workspace=AsyncMock(return_value=row), save=AsyncMock(side_effect=lambda r: r)))
    monkeypatch.setattr(state, "_lead_domain", lambda _: None)
    assert await state._normalize_lead("selected", {"email": "ada@example.com", "first_name": "Wrong", "title": "CEO", "provider": "apollo", "company_name": "Acme"}) == "canonical"
    assert (row.first_name, row.title) == ("Ada", "COO")
    assert row.metadata["source_provenance"] == ["csv_import", "apollo"]
    assert row.metadata["provider_context"]["company"] == "Acme"


@pytest.mark.asyncio
async def test_csv_workspace_fields_win_over_an_existing_global_profile(monkeypatch):
    saved = []
    profile = Lead(id="global-profile", first_name="Outdated", title="Old role")
    async def save(row): saved.append(row); return row
    monkeypatch.setattr(state, "LeadRepository", lambda: SimpleNamespace(find_by_email=AsyncMock(return_value=profile)))
    monkeypatch.setattr(state, "WorkspaceLeadRepository", lambda: SimpleNamespace(find_in_workspace=AsyncMock(return_value=None), save=save))
    monkeypatch.setattr(state, "_lead_domain", lambda _: None)
    identity = await state._normalize_lead("selected", {"email": "ada@example.com", "name": "Ada Lovelace", "title": "COO", "source": "csv_import"})
    assert saved[0].id == identity
    assert saved[0].workspace_id == "selected"
    assert (saved[0].first_name, saved[0].last_name, saved[0].title) == ("Ada", "Lovelace", "COO")
    assert profile.first_name == "Outdated"  # Do not mutate another workspace's global profile.


@pytest.mark.asyncio
async def test_duplicate_sources_normalize_once_per_source_but_count_one_canonical_lead(monkeypatch):
    import services.discovery.service as discovery
    from services.job_engine.storage import JobStorage
    row = {"id": "run", "workspace_id": "selected", "status": "searching"}
    updates, sources = [], []
    class Query:
        def select(self, *_): return self
        def eq(self, *_): return self
        def limit(self, *_): return self
        def update(self, value): updates.append(value); return self
        def execute(self): return SimpleNamespace(data=[row])
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: SimpleNamespace(table=lambda _: Query()))
    monkeypatch.setattr(JobStorage, "get_search_results", lambda *_: [
        {"email": "ada@example.com", "provider": source} for source in ("apollo", "apollo", "pdl")])
    async def normalize(workspace, lead):
        assert workspace == "selected"
        sources.append(lead["provider"])
        return "canonical"
    monkeypatch.setattr(state, "_normalize_lead", normalize)
    def link(_run, values, ids):
        assert ids == ["canonical"] and len(values) == 1
        return 1
    monkeypatch.setattr(discovery, "_link_leads", link)
    monkeypatch.setattr(discovery, "_link_companies", lambda *_: 1)
    job = SimpleNamespace(id="job", discovery_id="run", query="founders", result={})
    assert await discovery.finalize_discovery(job) is True
    assert sources == ["apollo", "pdl"]
    assert updates[-1]["summary"]["lead_count"] == 1
