from types import SimpleNamespace

import pytest

import services.leads.api as lead_api
import services.leads.service as lead_service
from services.knowledge.context_adapter import KnowledgePromptContext
from services.leads.service import LeadImportError, analyze_workspace_leads


def _workspace_lead(lead_id: str, workspace_id: str = "workspace-a"):
    return SimpleNamespace(
        id=lead_id,
        workspace_id=workspace_id,
        lead_id=f"profile-{lead_id}",
        company_id=f"company-{lead_id}",
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        title="COO",
        phone="",
        linkedin_url="",
        metadata={},
        deleted_at=None,
    )


class _WorkspaceLeadRepo:
    def __init__(self, rows):
        self.rows = rows

    async def get_for_workspace(self, lead_id, workspace_id):
        row = self.rows.get(lead_id)
        return row if row and row.workspace_id == workspace_id else None


class _ProfileRepo:
    async def get(self, _lead_id):
        return SimpleNamespace(first_name="", last_name="", email="", title="", phone="", linkedin_url="")


class _CompanyRepo:
    async def get(self, company_id):
        return SimpleNamespace(
            name="Acme", website="https://acme.example", location="United States",
            industry="Software", description="Workflow software", employee_count=120,
            revenue_band="", metadata={},
        ) if company_id else None


class _SignalRepo:
    async def list_for_lead(self, lead_id):
        return [SimpleNamespace(
            signal_type="hiring", label="Hiring operations leaders", strength=0.8,
            source="user_import", detected_at="2026-01-01T00:00:00Z",
        )] if lead_id == "lead-a" else []


def _install_repositories(monkeypatch, rows):
    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", lambda: _WorkspaceLeadRepo(rows))
    monkeypatch.setattr(lead_service, "LeadRepository", _ProfileRepo)
    monkeypatch.setattr(lead_service, "CompanyRepository", _CompanyRepo)
    monkeypatch.setattr(lead_service, "LeadSignalRepository", _SignalRepo)


@pytest.mark.asyncio
async def test_analysis_loads_only_requested_workspace_leads_and_returns_categories(monkeypatch):
    _install_repositories(monkeypatch, {"lead-a": _workspace_lead("lead-a")})

    async def guidance(owner_id, **kwargs):
        assert owner_id == "actor-a"
        assert kwargs["workspace_id"] == "workspace-a"
        return KnowledgePromptContext(
            query=kwargs["query"], categories=("icp",),
            items=[{"id": "knowledge-a", "title": "ICP", "summary": "Operations teams", "category": "icp", "source_type": "user"}],
        )

    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", guidance)

    def no_broad_list(*_args, **_kwargs):
        raise AssertionError("analysis must not validate through list_workspace_leads")

    monkeypatch.setattr(lead_service, "list_workspace_leads", no_broad_list)
    result = await analyze_workspace_leads("workspace-a", "actor-a", ["lead-a"])

    item = result["results"][0]
    assert item["status"] == "completed"
    assert item["facts"][0] == {"label": "Name", "value": "Ada Lovelace", "source": "canonical workspace lead data"}
    assert item["observed_signals"] == [{
        "type": "hiring", "label": "Hiring operations leaders", "strength": 0.8,
        "source": "user_import", "detected_at": "2026-01-01T00:00:00Z",
    }]
    assert item["derived_assessment"]["priority"] in {"high", "medium", "low"}
    assert result["business_guidance"]["note"].startswith("This is user-provided")
    assert result["business_guidance"]["items"][0]["id"] == "knowledge-a"


@pytest.mark.asyncio
async def test_analysis_rejects_cross_workspace_selected_id(monkeypatch):
    _install_repositories(monkeypatch, {"lead-b": _workspace_lead("lead-b", "workspace-b")})
    with pytest.raises(LeadImportError, match="unavailable"):
        await analyze_workspace_leads("workspace-a", "actor-a", ["lead-b"])


@pytest.mark.asyncio
async def test_analysis_keeps_other_selected_leads_when_one_processing_step_fails(monkeypatch):
    _install_repositories(monkeypatch, {
        "lead-a": _workspace_lead("lead-a"),
        "lead-b": _workspace_lead("lead-b"),
    })

    async def empty_guidance(*_args, **_kwargs):
        return KnowledgePromptContext()

    original = lead_service._analyze_selected_lead

    async def one_failure(lead):
        if lead["id"] == "lead-b":
            raise RuntimeError("bad canonical data")
        return await original(lead)

    monkeypatch.setattr(lead_service, "_business_guidance", empty_guidance)
    monkeypatch.setattr(lead_service, "_analyze_selected_lead", one_failure)
    result = await analyze_workspace_leads("workspace-a", "actor-a", ["lead-a", "lead-b"])
    assert [item["status"] for item in result["results"]] == ["completed", "failed"]


@pytest.mark.asyncio
async def test_analysis_never_invokes_openai_or_external_enrichment(monkeypatch):
    _install_repositories(monkeypatch, {"lead-a": _workspace_lead("lead-a")})

    async def empty_guidance(*_args, **_kwargs):
        return KnowledgePromptContext()

    monkeypatch.setattr(lead_service, "_business_guidance", empty_guidance)
    monkeypatch.setattr("services.intelligence.ai._send_openai_request", lambda *_args: (_ for _ in ()).throw(AssertionError("OpenAI must not be called")))
    result = await analyze_workspace_leads("workspace-a", "actor-a", ["lead-a"])
    assert result["results"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_api_passes_authorized_actor_and_workspace_to_analysis(monkeypatch):
    async def scope(_request):
        return "actor-a", "workspace-a"

    async def analyze(workspace_id, actor_user_id, lead_ids):
        assert (workspace_id, actor_user_id, lead_ids) == ("workspace-a", "actor-a", ["lead-a"])
        return {"results": [], "business_guidance": {}}

    monkeypatch.setattr(lead_api, "_scope", scope)
    monkeypatch.setattr(lead_api, "analyze_workspace_leads", analyze)
    response = await lead_api.analyze_leads("_", lead_api.LeadAnalysisRequest(lead_ids=["lead-a"]), object())
    assert response == {"ok": True, "results": [], "business_guidance": {}}
