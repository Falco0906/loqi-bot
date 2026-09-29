from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from services.leads.service import LeadImportError, parse_csv_preview, suggested_mapping
import services.leads.service as lead_service
import services.leads.api as lead_api


def test_csv_preview_maps_known_columns_and_reports_invalid_rows():
    result = parse_csv_preview("First Name,Email,Company,Unmapped\nAda,ada@example.com,Acme,x\n,,,x\n")
    assert result["mapping"] == {"First Name": "first_name", "Email": "email", "Company": "company"}
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == [{"row": 3, "reason": "Provide at least a name, email, or company"}]
    assert result["unmapped_columns"] == ["Unmapped"]


def test_csv_preview_rejects_empty_or_headerless_input():
    with pytest.raises(LeadImportError, match="empty"):
        parse_csv_preview("")
    with pytest.raises(LeadImportError, match="empty"):
        parse_csv_preview("\n\n")


def test_mapping_never_maps_unknown_columns():
    assert suggested_mapping(["Email", "Secret note"]) == {"Email": "email"}


@pytest.mark.asyncio
async def test_import_skips_workspace_duplicates_and_keeps_other_rows(monkeypatch):
    class Repo:
        async def list_by_email(self, workspace_id, email):
            assert workspace_id == "workspace-a"
            return [object()] if email == "exists@example.com" else []

    imported = []
    async def persist(workspace_id, lead):
        imported.append((workspace_id, lead))
        return "lead-new"

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_service, "import_workspace_lead", persist)
    result = await lead_service.import_csv_rows("workspace-a", "actor-a", [
        {"row": 2, "lead": {"email": "exists@example.com"}},
        {"row": 3, "lead": {"email": "new@example.com", "name": "New"}},
        {"row": 4, "lead": {"email": "new@example.com", "name": "Duplicate"}},
    ])
    assert result["imported"] == 1
    assert len(result["duplicates"]) == 2
    assert imported == [(
        "workspace-a",
        {"email": "new@example.com", "name": "New", "source": "csv_import", "csv_import_metadata": {}},
    )]


@pytest.mark.asyncio
async def test_imports_a_fifteen_row_csv_through_the_canonical_workspace_lead_path(monkeypatch):
    class Repo:
        async def list_by_email(self, workspace_id, email):
            assert workspace_id == "workspace-a"
            return []

    persisted = []
    async def persist(workspace_id, lead):
        persisted.append((workspace_id, lead))
        return f"workspace-lead-{len(persisted)}"

    csv = "Name,Email,Company,Location,Industry\n" + "\n".join(
        f"Person {number},person{number}@example.com,Acme {number},United States,SaaS"
        for number in range(1, 16)
    )
    preview = parse_csv_preview(csv)
    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_service, "import_workspace_lead", persist)

    result = await lead_service.import_csv_rows("workspace-a", "actor-a", preview["rows"])

    assert result["imported"] == 15
    assert not result["duplicates"]
    assert not result["invalid"]
    assert [lead["email"] for _, lead in persisted] == [f"person{number}@example.com" for number in range(1, 16)]
    assert persisted[0][1]["csv_import_metadata"] == {
        "company": "Acme 1", "location": "United States", "industry": "SaaS",
    }


@pytest.mark.asyncio
async def test_list_projects_canonical_workspace_leads_with_batched_related_reads(monkeypatch):
    rows = [
        SimpleNamespace(id="wl-1", lead_id="lead-1", company_id="company-1", email="", first_name="", last_name="", title="", phone="", linkedin_url="", lead_status="new", metadata={}),
        SimpleNamespace(id="wl-2", lead_id="lead-2", company_id=None, email="second@example.com", first_name="Second", last_name="Lead", title="COO", phone="", linkedin_url="", lead_status="new", metadata={"csv_import": {"company": "CSV Co", "location": "London", "industry": "SaaS"}}),
    ]

    class WorkspaceRepo:
        async def list_for_workspace(self, workspace_id):
            assert workspace_id == "workspace-a"
            return rows

    class LeadRepo:
        async def list_by_ids(self, ids):
            assert set(ids) == {"lead-1", "lead-2"}
            return [SimpleNamespace(id="lead-1", first_name="Ada", last_name="Lovelace", email="ada@example.com", title="Founder", phone="", linkedin_url="")]

    class CompanyRepo:
        async def list_by_ids(self, ids):
            assert ids == ["company-1"]
            return [SimpleNamespace(id="company-1", name="Analytical Engines", website="analytical.example", location="London", industry="Computing")]

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", LeadRepo)
    monkeypatch.setattr(lead_service, "CompanyRepository", CompanyRepo)

    result = await lead_service.list_workspace_leads("workspace-a", query="", page=1)

    assert result["total"] == 2
    by_id = {lead["id"]: lead for lead in result["leads"]}
    assert by_id["wl-1"]["company"] == "Analytical Engines"
    assert by_id["wl-2"]["company"] == "CSV Co"
    assert by_id["wl-2"]["location"] == "London"


@pytest.mark.asyncio
async def test_list_reads_csv_imported_workspace_leads_when_global_projection_is_absent(monkeypatch):
    rows = [
        SimpleNamespace(
            id=f"workspace-lead-{number}", lead_id=f"global-lead-{number}", company_id=f"global-company-{number}",
            email=f"person{number}@example.com", first_name=f"Person{number}", last_name="Imported",
            title="Operations", phone="", linkedin_url="", lead_status="new",
            metadata={"csv_import": {"company": f"CSV Co {number}", "location": "United States", "industry": "SaaS"}},
        ) for number in range(1, 12)
    ]

    class WorkspaceRepo:
        async def list_for_workspace(self, workspace_id):
            assert workspace_id == "workspace-a"
            return rows

    class UnavailableLeadProjection:
        async def list_by_ids(self, ids):
            raise RuntimeError("global leads projection is unavailable")

    class UnavailableCompanyProjection:
        async def list_by_ids(self, ids):
            raise RuntimeError("global companies projection is unavailable")

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", UnavailableLeadProjection)
    monkeypatch.setattr(lead_service, "CompanyRepository", UnavailableCompanyProjection)

    result = await lead_service.list_workspace_leads("workspace-a", query="person", page=1)

    assert result["total"] == 11
    assert len(result["leads"]) == 11
    assert result["leads"][0] == {
        "id": "workspace-lead-1", "first_name": "Person1", "last_name": "Imported",
        "email": "person1@example.com", "title": "Operations", "phone": "", "linkedin_url": "",
        "company": "CSV Co 1", "website": "", "location": "United States", "industry": "SaaS", "status": "new",
        "source": "", "source_provenance": [], "source_kind": "workspace", "source_label": "Lead database",
    }


@pytest.mark.asyncio
async def test_import_reports_canonical_store_unavailability_instead_of_false_success(monkeypatch):
    class Repo:
        def _client(self):
            return None

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)

    with pytest.raises(lead_service.LeadDatabaseUnavailable, match="temporarily unavailable"):
        await lead_service.import_csv_rows("workspace-a", "actor-a", [{"row": 2, "lead": {"email": "a@example.com"}}])


@pytest.mark.asyncio
async def test_transient_lead_listing_failure_becomes_a_503(monkeypatch):
    class Repo:
        async def list_for_workspace(self, workspace_id):
            raise httpx.ReadTimeout("temporary timeout")

    async def scope(request):
        return "actor-a", "workspace-a"

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_api, "_scope", scope)

    with pytest.raises(HTTPException) as raised:
        await lead_api.list_leads("_", None)
    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_unexpected_lead_listing_failure_is_not_disguised_as_a_503(monkeypatch):
    class Repo:
        async def list_for_workspace(self, workspace_id):
            raise RuntimeError("unexpected projection bug")

    async def scope(request):
        return "actor-a", "workspace-a"

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_api, "_scope", scope)

    with pytest.raises(RuntimeError, match="unexpected projection bug"):
        await lead_api.list_leads("_", None)


@pytest.mark.asyncio
async def test_row_validation_failure_remains_an_invalid_row_result(monkeypatch):
    class Repo:
        async def list_by_email(self, workspace_id, email):
            return []

    async def invalid_row(workspace_id, lead):
        raise LeadImportError("Email format is invalid")

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_service, "import_workspace_lead", invalid_row)

    result = await lead_service.import_csv_rows("workspace-a", "actor-a", [{"row": 2, "lead": {"email": "bad"}}])
    assert result == {"imported": 0, "imported_ids": [], "duplicates": [], "invalid": [{"row": 2, "reason": "Email format is invalid"}]}


def _workspace_lead(
    identifier: str,
    *,
    name: str,
    source: str = "",
    provenance: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        lead_id=f"global-{identifier}",
        company_id=None,
        email=f"{identifier}@example.com",
        first_name=name,
        last_name="Lead",
        title="Operations",
        phone="",
        linkedin_url="",
        lead_status="new",
        source=source,
        metadata={"source_provenance": provenance or []},
    )


@pytest.mark.asyncio
async def test_keyword_filter_searches_canonical_workspace_lead_fields(monkeypatch):
    rows = [
        _workspace_lead("operations", name="Operations"),
        _workspace_lead("finance", name="Finance"),
    ]
    rows[0].title = "Revenue Operations"
    rows[1].title = "Finance Lead"

    class WorkspaceRepo:
        async def list_for_workspace(self, workspace_id):
            assert workspace_id == "workspace-a"
            return rows

    class EmptyProjection:
        async def list_by_ids(self, _ids):
            return []

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "CompanyRepository", EmptyProjection)

    result = await lead_service.list_workspace_leads(
        "workspace-a", filters={"keywords": "revenue"},
    )

    assert result["total"] == 1
    assert [lead["id"] for lead in result["leads"]] == ["operations"]


@pytest.mark.asyncio
async def test_lead_list_route_forwards_the_keyword_filter(monkeypatch):
    captured: dict[str, object] = {}

    async def scope(_request):
        return "actor-a", "workspace-a"

    async def list_leads(workspace_id, query, page, filters, discovery_id):
        captured.update({
            "workspace_id": workspace_id,
            "query": query,
            "page": page,
            "filters": filters,
            "discovery_id": discovery_id,
        })
        return {"leads": [], "total": 0, "page": page, "page_size": 50}

    monkeypatch.setattr(lead_api, "_scope", scope)
    monkeypatch.setattr(lead_api, "list_workspace_leads", list_leads)

    response = await lead_api.list_leads(
        "_", None, q="saas", page=2, keywords="revenue operations",
    )

    assert response["ok"] is True
    assert captured == {
        "workspace_id": "workspace-a",
        "query": "saas",
        "page": 2,
        "filters": {
            "location": "", "industry": "", "company": "", "title": "",
            "keywords": "revenue operations",
        },
        "discovery_id": "",
    }


@pytest.mark.asyncio
async def test_provider_normalization_preserves_csv_source_and_appends_durable_provenance(monkeypatch):
    """One canonical workspace lead can retain both CSV and provider origin."""
    from services.persistence.launch import Lead, WorkspaceLead
    import services.workspace.state as workspace_state

    profile = Lead(id="global-1", email="ada@example.com")
    existing = WorkspaceLead(
        id="workspace-lead-1",
        workspace_id="workspace-a",
        lead_id="global-1",
        email="ada@example.com",
        source="csv_import",
        metadata={"source_provenance": ["csv_import"]},
    )
    saved: list[WorkspaceLead] = []

    class LeadRepo:
        async def find_by_email(self, email):
            assert email == "ada@example.com"
            return profile

    class WorkspaceRepo:
        async def find_in_workspace(self, workspace_id, lead_id):
            assert (workspace_id, lead_id) == ("workspace-a", "global-1")
            return existing

        async def save(self, row):
            saved.append(row)
            return row

    monkeypatch.setattr(workspace_state, "LeadRepository", LeadRepo)
    monkeypatch.setattr(workspace_state, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(workspace_state, "_lead_domain", lambda _lead: None)

    result = await workspace_state._normalize_lead(
        "workspace-a", {"email": "ada@example.com", "provider": "apollo"},
    )

    assert result == "workspace-lead-1"
    assert saved == [existing]
    assert existing.source == "csv_import"
    assert existing.metadata["source_provenance"] == ["csv_import", "apollo"]


@pytest.mark.asyncio
async def test_discovery_results_are_canonical_deduplicated_and_keep_provider_provenance(monkeypatch):
    """A provider link augments one workspace_lead, never adds a second row."""
    rows = [
        _workspace_lead("shared", name="Acme", source="csv_import", provenance=["csv_import", "apollo"]),
        _workspace_lead("provider-only", name="Provider Match", source="pdl", provenance=["pdl"]),
    ]

    class WorkspaceRepo:
        async def list_for_workspace(self, workspace_id):
            assert workspace_id == "workspace-a"
            return rows

    class EmptyProjection:
        async def list_by_ids(self, _ids):
            return []

    def provenance(discovery_id, workspace_id):
        assert (discovery_id, workspace_id) == ("discovery-a", "workspace-a")
        return {"shared": ["apollo"], "provider-only": ["pdl"]}

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "CompanyRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "get_discovery_lead_provenance", provenance)

    result = await lead_service.list_workspace_leads(
        "workspace-a", query="provider query not in a row", page=1,
        discovery_id="discovery-a",
    )

    assert result["total"] == 2
    assert {lead["id"] for lead in result["leads"]} == {"shared", "provider-only"}
    assert len(result["leads"]) == 2
    assert all(lead["source_kind"] == "provider" for lead in result["leads"])
    assert {lead["source_label"] for lead in result["leads"]} == {"Apollo", "PDL"}

    # Reloading without a run id still reads the durable workspace-lead
    # provenance rather than degrading the provider result to "Lead database".
    reloaded = await lead_service.list_workspace_leads("workspace-a", page=1)
    shared = next(lead for lead in reloaded["leads"] if lead["id"] == "shared")
    assert shared["source"] == "csv_import"
    assert shared["source_provenance"] == ["csv_import", "apollo"]
    assert shared["source_kind"] == "provider"
    assert shared["source_label"] == "Apollo"


@pytest.mark.asyncio
async def test_discovery_union_is_counted_and_paginated_before_the_response_is_sliced(monkeypatch):
    rows = [
        _workspace_lead(f"lead-{number:02d}", name=f"Lead {number:02d}")
        for number in range(52)
    ]
    rows[51].metadata = {"source_provenance": ["apollo"]}

    class WorkspaceRepo:
        async def list_for_workspace(self, _workspace_id):
            return rows

    class EmptyProjection:
        async def list_by_ids(self, _ids):
            return []

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "CompanyRepository", EmptyProjection)
    monkeypatch.setattr(
        lead_service,
        "get_discovery_lead_provenance",
        lambda _discovery_id, _workspace_id: {"lead-51": ["apollo"]},
    )

    first = await lead_service.list_workspace_leads(
        "workspace-a", query="lead", page=1, page_size=50,
        discovery_id="discovery-a",
    )
    second = await lead_service.list_workspace_leads(
        "workspace-a", query="lead", page=2, page_size=50,
        discovery_id="discovery-a",
    )

    # The provider-linked canonical lead is counted once in the same sorted
    # set as workspace results.  It is not appended to page one after the
    # server has calculated a different total/page boundary.
    assert first["total"] == second["total"] == 52
    assert len(first["leads"]) == 50
    assert len(second["leads"]) == 2
    assert {lead["id"] for lead in first["leads"]}.isdisjoint(
        {lead["id"] for lead in second["leads"]}
    )
    assert "lead-51" in {lead["id"] for lead in second["leads"]}


@pytest.mark.asyncio
async def test_provider_projection_failure_does_not_hide_workspace_results(monkeypatch):
    class WorkspaceRepo:
        async def list_for_workspace(self, _workspace_id):
            return [_workspace_lead("workspace-only", name="Workspace")]

    class EmptyProjection:
        async def list_by_ids(self, _ids):
            return []

    def unavailable(_discovery_id, _workspace_id):
        raise RuntimeError("discovery projection unavailable")

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", WorkspaceRepo)
    monkeypatch.setattr(lead_service, "LeadRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "CompanyRepository", EmptyProjection)
    monkeypatch.setattr(lead_service, "get_discovery_lead_provenance", unavailable)

    result = await lead_service.list_workspace_leads(
        "workspace-a", query="workspace", page=1, discovery_id="discovery-a",
    )
    assert result["total"] == 1
    assert result["leads"][0]["id"] == "workspace-only"


@pytest.mark.asyncio
async def test_systemic_import_failure_remains_observable(monkeypatch):
    class Repo:
        async def list_by_email(self, workspace_id, email):
            return []

    async def broken_persistence(workspace_id, lead):
        raise RuntimeError("workspace_leads schema mismatch")

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_service, "import_workspace_lead", broken_persistence)

    with pytest.raises(RuntimeError, match="workspace_leads schema mismatch"):
        await lead_service.import_csv_rows("workspace-a", "actor-a", [{"row": 2, "lead": {"email": "a@example.com"}}])
