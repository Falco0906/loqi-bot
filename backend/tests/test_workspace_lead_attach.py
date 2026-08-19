"""Company-only lead attach flow — campaign lifecycle advancement.

Discovery recommendations are company-level (no person email). Attaching them
to a campaign must persist a campaign_leads link so the canonical read reports
lead_count > 0 and the lifecycle advances past research. These tests fake the
repository layer in-memory (no Supabase) and drive the real normalization /
canonical-read pipeline in services.workspace_state.
"""

from __future__ import annotations

import pytest

import services.workspace_state as workspace_state
from services.persistence.launch import Campaign, Company, Lead, WorkspaceLead
from services.workspace_snapshot import enrich_campaigns
from services.workspace_state import _normalize_lead, _persist_campaign_lead_row


class _Rows:
    """Tiny in-memory table for a fake repository."""

    def __init__(self):
        self._rows: dict[str, object] = {}
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter}"

    def store(self, entity):
        if not getattr(entity, "id", ""):
            setattr(entity, "id", self.new_id())
        self._rows[entity.id] = entity
        return entity

    def get(self, entity_id: str):
        return self._rows.get(entity_id)

    def all(self):
        return list(self._rows.values())

    def matching(self, predicate):
        return [r for r in self._rows.values() if predicate(r)]


class _FakeLeadRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def get(self, entity_id: str):
        return self.rows.get(entity_id)

    async def find_by_email(self, email: str):
        rows = self.rows.matching(lambda r: r.email == email)
        return rows[0] if rows else None

    async def save(self, entity):
        return self.rows.store(entity)


class _FakeCompanyRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def get(self, entity_id: str):
        return self.rows.get(entity_id)

    async def find_by_domain(self, domain: str):
        rows = self.rows.matching(lambda r: r.domain == domain)
        return rows[0] if rows else None

    async def save(self, entity):
        return self.rows.store(entity)


class _FakeWorkspaceCompanyRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def find(self, workspace_id: str, company_id: str):
        rows = self.rows.matching(
            lambda r: r.workspace_id == workspace_id and r.company_id == company_id
        )
        return rows[0] if rows else None

    async def save(self, entity):
        return self.rows.store(entity)


class _FakeWorkspaceLeadRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def get(self, entity_id: str):
        return self.rows.get(entity_id)

    async def find_in_workspace(self, workspace_id: str, lead_id: str):
        rows = self.rows.matching(
            lambda r: r.workspace_id == workspace_id and r.lead_id == lead_id
        )
        return rows[0] if rows else None

    async def find_by_company(self, workspace_id: str, company_id: str):
        rows = self.rows.matching(
            lambda r: r.workspace_id == workspace_id and r.company_id == company_id
        )
        return rows[0] if rows else None

    async def list_by_email(self, workspace_id: str, email: str):
        return self.rows.matching(
            lambda r: r.workspace_id == workspace_id and r.email == email
        )

    async def save(self, entity):
        return self.rows.store(entity)


class _FakeCampaignLeadRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def find_link(self, campaign_id: str, lead_id: str):
        rows = self.rows.matching(
            lambda r: r.campaign_id == campaign_id and r.lead_id == lead_id
        )
        return rows[0] if rows else None

    async def list_for_campaign(self, campaign_id: str):
        return self.rows.matching(lambda r: r.campaign_id == campaign_id)

    async def save(self, entity):
        return self.rows.store(entity)


class _FakeCampaignRepo:
    def __init__(self, rows: _Rows):
        self.rows = rows

    async def list_for_workspace(self, workspace_id: str):
        return self.rows.all()


class _FakeDraftRepo:
    async def list_for_workspace(self, workspace_id: str):
        return []

    async def get(self, entity_id: str):
        return None


class _FakeStrategyRepo:
    async def current_for_campaign(self, campaign_id: str):
        return None


@pytest.fixture
def env(monkeypatch):
    """In-memory fakes wired into the workspace_state module for one test."""
    companies = _Rows()
    companies.store(Company(
        id="company-acme", name="Acme Inc", domain="acme.com", industry="Software",
    ))
    campaigns = _Rows()
    campaigns.store(Campaign(
        id="campaign-1", workspace_id="ws-1", name="Outbound", status="planning",
    ))

    ws_companies = _Rows()
    ws_leads = _Rows()
    lead_profiles = _Rows()
    links = _Rows()

    async def fake_async_workspace(user_id: str, **kwargs) -> str:
        return "ws-1"

    def fake_workflow_session_id(user_id: str) -> str:
        return "ws-1"

    monkeypatch.setattr(workspace_state, "_async_workspace", fake_async_workspace)
    monkeypatch.setattr(workspace_state, "_workflow_session_id", fake_workflow_session_id)
    monkeypatch.setattr(workspace_state, "LeadRepository", lambda: _FakeLeadRepo(lead_profiles))
    monkeypatch.setattr(workspace_state, "CompanyRepository", lambda: _FakeCompanyRepo(companies))
    monkeypatch.setattr(workspace_state, "WorkspaceCompanyRepository", lambda: _FakeWorkspaceCompanyRepo(ws_companies))
    monkeypatch.setattr(workspace_state, "WorkspaceLeadRepository", lambda: _FakeWorkspaceLeadRepo(ws_leads))
    monkeypatch.setattr(workspace_state, "CampaignLeadRepository", lambda: _FakeCampaignLeadRepo(links))
    monkeypatch.setattr(workspace_state, "CampaignRepository", lambda: _FakeCampaignRepo(campaigns))
    monkeypatch.setattr(workspace_state, "DraftRepository", lambda: _FakeDraftRepo())
    monkeypatch.setattr(workspace_state, "StrategyRepository", lambda: _FakeStrategyRepo())

    return {
        "campaigns": campaigns,
        "ws_companies": ws_companies,
        "ws_leads": ws_leads,
        "lead_profiles": lead_profiles,
        "links": links,
    }


def _company_attach(**overrides) -> dict:
    payload = {
        "id": "company-acme",
        "company": "Acme Inc",
        "title": "Head of Growth",
        "source": "discovery",
    }
    payload.update(overrides)
    return payload


def _acme_ws_leads(env):
    return env["ws_leads"].matching(lambda r: r.company_id == "company-acme")


async def test_company_only_lead_attaches_and_advances_lifecycle(env):
    ok = await workspace_state.persist_campaign_lead_awaited(
        "user-1", "campaign-1", _company_attach(),
    )
    assert ok is True

    ws_leads = _acme_ws_leads(env)
    assert len(ws_leads) == 1
    ws_lead = ws_leads[0]
    assert ws_lead.workspace_id == "ws-1"

    assert env["ws_companies"].matching(
        lambda r: r.workspace_id == "ws-1" and r.company_id == "company-acme"
    ), "workspace<->company link should be created"
    links = env["links"].matching(
        lambda r: r.campaign_id == "campaign-1" and r.lead_id == ws_lead.id
    )
    assert links, "campaign_leads link should be written"

    state = await workspace_state._load_canonical_state("user-1")
    campaign = next(c for c in state["campaigns"] if c["id"] == "campaign-1")
    assert campaign["lead_count"] == 1
    assert campaign["leads"][0]["company"] == "Acme Inc"

    enriched = enrich_campaigns(state["campaigns"], state["drafts"])
    assert next(c for c in enriched if c["id"] == "campaign-1")["current_step"] == "strategy"


async def test_company_only_lead_dedupes_per_company(env):
    first = await _normalize_lead("ws-1", _company_attach())
    second = await _normalize_lead("ws-1", _company_attach())
    assert first == second
    assert len(_acme_ws_leads(env)) == 1

    other = await _normalize_lead("ws-1", {
        "id": "company-other", "company": "Other Co",
    })
    assert other != first
    assert len(_acme_ws_leads(env)) == 1


async def test_person_lead_path_is_unchanged(env):
    env["lead_profiles"].store(Lead(
        id="lead-person", email="ada@acme.com", first_name="Ada",
    ))
    env["ws_leads"].store(WorkspaceLead(
        id="ws-person", workspace_id="ws-1", lead_id="lead-person",
        email="ada@acme.com",
    ))

    lead_id = await _normalize_lead("ws-1", {"email": "ada@acme.com", "company": "Acme Inc"})
    assert lead_id == "ws-person"


async def test_failed_persist_reports_false(monkeypatch):
    async def boom(user_id: str, campaign_id: str, lead: dict) -> bool:
        return False

    monkeypatch.setattr(workspace_state, "_persist_campaign_lead_row", boom)
    assert await workspace_state.persist_campaign_lead_awaited("u", "c", {}) is False


async def test_direct_persist_returns_bool(env):
    assert await _persist_campaign_lead_row("user-1", "campaign-1", _company_attach()) is True
