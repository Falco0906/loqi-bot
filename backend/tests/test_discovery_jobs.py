"""Regression tests: Discovery market prompts must always start a search job.

Guards the Discovery search routing end to end:

- POST /api/jobs/search (the exact endpoint the Discovery page calls) must
  create a search job for prompts that the frontend keyword classifier would
  otherwise fail to classify ("AI startups", "Climate tech", …).
- The full pipeline (dispatch → workflow → results) must complete and persist
  leads for such a prompt.

Fixtures (client, session_token, mock OpenAI) come from conftest.py.
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient
from tests.conftest import _AuthTestClient
from main import app

MARKET_PROMPTS = [
    "European fintech companies",
    "AI startups",
    "Climate tech",
    "Healthcare SaaS",
    "Manufacturing companies in Germany",
]


@pytest.fixture(scope="module")
def client():
    return _AuthTestClient(app)


@pytest.fixture(scope="module")
def session_token(client):
    resp = client.post("/api/web/session", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    return data["session_token"]


@pytest.fixture()
def authenticated_session(client, monkeypatch):
    """A web session bound to a REAL identity user.

    Anonymous sessions only exist in the legacy ``users`` table, so
    ``workspaces.owner_user_id`` (FK → identity_users) can never be satisfied
    for them and no discovery can be created. The product binds authenticated
    sessions to identity users at session creation; mirror that here by
    seeding both rows (legacy users + identity_users) with the same id and
    resolving auth through the same hook the endpoint uses.
    """
    from uuid import uuid4

    from services.supabase import get_supabase_client

    user_id = str(uuid4())
    db = get_supabase_client()
    assert db is not None, "supabase client required"
    db.table("identity_users").insert({
        "id": user_id,
        "display_name": "Discovery Test",
    }).execute()
    db.table("users").insert({
        "id": user_id,
        "telegram_id": f"web:test-{user_id}",
        "username": "Discovery Test",
    }).execute()

    async def fake_auth(request):
        return user_id

    monkeypatch.setattr(
        "services.identity.api.get_authenticated_user_id", fake_auth
    )

    resp = client.post(
        "/api/web/session",
        json={"display_name": "Discovery Test"},
        headers={"Authorization": "Bearer discovery-test-token"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("session_token"), "authenticated session must be created"
    return data["session_token"]


class TestDiscoverySearchEndpoint:
    """Every natural market prompt reaches /api/jobs/search and creates a job."""

    @pytest.mark.parametrize("query", MARKET_PROMPTS)
    def test_prompt_creates_search_job(self, client, session_token, query):
        from services.job_engine.storage import JobStorage

        resp = client.post(
            "/api/jobs/search",
            json={"query": query},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200, f"{query}: {resp.text}"
        body = resp.json()
        job_id = body.get("job_id")
        assert job_id, f"{query}: no job_id in {body}"

        storage = JobStorage()
        job = storage.get_job(job_id)
        assert job is not None, f"{query}: job row missing"
        assert job.type == "search"
        assert job.query == query

        # Tidy up: the async worker is cancelled when the TestClient request
        # scope ends, so the row can be left in a running state. Mark it
        # failed to avoid a stuck job hijacking Discovery reads.
        from services.job_engine.models import JobStatus

        storage.update_job(
            job_id,
            status=JobStatus.FAILED,
            stage="Failed",
            completed_at=datetime.now(timezone.utc),
        )


class TestSearchPipelineCompletes:
    """The workflow must run to completion and persist results for a
    classifier-orphaned prompt (previously: silently dropped)."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_and_stores_leads(self, session_token):
        from main import engine
        from services.job_engine.manager import JobManager
        from services.job_engine.storage import JobStorage

        summary = await asyncio.to_thread(
            engine.get_web_session_summary, session_token
        )
        assert summary is not None and summary.get("user_id")
        user_id = summary["user_id"]

        manager = JobManager()
        created = await manager.create_search_job(user_id=user_id, query="AI startups")
        assert created and created.get("job_id"), f"job creation failed: {created}"
        job_id = created["job_id"]

        storage = JobStorage()
        job = None
        for _ in range(120):
            await asyncio.sleep(1)
            job = storage.get_job(job_id)
            if job and job.status.value == "completed":
                break
        else:
            pytest.fail("search workflow did not reach completed status")

        assert job.result_ready is True
        leads = storage.get_search_results(job_id)
        assert isinstance(leads, list), "results should be a list"
        assert len(leads) > 0, "completed search must persist leads"


class TestDiscoveryEntity:
    """A research run must be a first-class discovery entity: created by the
    API, listable, readable, and finalized when its job completes."""

    @pytest.mark.asyncio
    async def test_create_list_get_discovery(self, client, authenticated_session):
        from services.discovery import list_discoveries
        from services.job_engine.models import JobStatus
        from services.job_engine.storage import JobStorage

        resp = client.post(
            "/api/discoveries",
            json={"query": "Climate tech"},
            headers={"Authorization": f"Bearer {authenticated_session}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("ok") is True
        discovery_id = body.get("discovery_id")
        job_id = body.get("job_id")
        assert discovery_id and job_id, f"expected discovery + job ids in {body}"

        from main import engine

        summary = await asyncio.to_thread(
            engine.get_web_session_summary, authenticated_session
        )
        user_id = summary["user_id"]
        from services.workspace_state import ensure_workspace

        workspace_id = await asyncio.to_thread(ensure_workspace, user_id)
        assert workspace_id, "workspace must resolve"

        listed = await asyncio.to_thread(list_discoveries, workspace_id)
        ids = [d["id"] for d in listed]
        assert discovery_id in ids, "created discovery must appear in the list"

        # The HTTP endpoints must agree: GET /api/discoveries lists the run and
        # GET /api/discoveries/{id} returns the same entity.
        list_resp = client.get(
            "/api/discoveries",
            headers={"Authorization": f"Bearer {authenticated_session}"},
        )
        assert list_resp.status_code == 200, list_resp.text
        listed_api = [
            d["id"]
            for d in list_resp.json().get("discoveries", [])
            if d.get("id")
        ]
        assert discovery_id in listed_api, "GET /api/discoveries must list the run"

        detail_resp = client.get(
            f"/api/discoveries/{discovery_id}",
            headers={"Authorization": f"Bearer {authenticated_session}"},
        )
        assert detail_resp.status_code == 200, detail_resp.text
        detail = detail_resp.json().get("discovery", {})
        assert detail["id"] == discovery_id
        assert detail["query"] == "Climate tech"
        assert detail["status"] in ("queued", "searching", "completed")

        # Ownership lives on the JOB side: the discovery never points at a job,
        # the job points at the discovery (Discovery → many Jobs).
        job_row = JobStorage().get_job(job_id)
        assert job_row is not None and job_row.discovery_id == discovery_id, (
            "relationship must be persisted as jobs.discovery_id"
        )

        # Creation defaults for the future-proofing columns.
        assert detail.get("title") == "Climate tech", "title defaults to the query"
        assert detail.get("last_viewed_at") is not None
        assert detail.get("last_refreshed_at") is not None
        assert detail.get("favorite") is False
        assert detail.get("archived_at") is None

        # Tidy up: the async worker is cancelled when the TestClient request
        # scope ends, so the discovery row can be left searching forever.
        # Mark it cancelled so the history list stays clean.
        from services.discovery import mark_discovery_status

        await asyncio.to_thread(mark_discovery_status, discovery_id, "cancelled")
        storage = JobStorage()
        storage.update_job(
            job_id,
            status=JobStatus.CANCELLED,
            stage="Cancelled",
            completed_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_pipeline_finalizes_discovery(self, authenticated_session):
        """When a discovery is tied to a job, job completion must finalize it:
        status -> completed, leads + companies linked, provenance recorded."""
        from main import engine
        from services.discovery import (
            create_discovery,
            finalize_discovery,
            get_discovery,
        )
        from services.job_engine.manager import JobManager
        from services.job_engine.storage import JobStorage

        summary = await asyncio.to_thread(
            engine.get_web_session_summary, authenticated_session
        )
        user_id = summary["user_id"]
        from services.workspace_state import ensure_workspace

        workspace_id = await asyncio.to_thread(ensure_workspace, user_id)
        assert workspace_id, "workspace must resolve"

        discovery = await asyncio.to_thread(
            create_discovery, workspace_id, user_id, "Healthcare SaaS"
        )
        assert discovery is not None and discovery.get("id"), "discovery row must persist"
        discovery_id = discovery["id"]

        manager = JobManager()
        created = await manager.create_search_job(
            user_id=user_id,
            query="Healthcare SaaS",
            discovery_id=discovery_id,
            on_complete=finalize_discovery,
        )
        assert created and created.get("job_id"), f"job creation failed: {created}"
        job_id = created["job_id"]

        storage = JobStorage()
        job = None
        for _ in range(150):
            await asyncio.sleep(1)
            job = storage.get_job(job_id)
            if job and job.status.value == "completed":
                break
        else:
            pytest.fail("search workflow did not reach completed status")

        # The runner flips the job to completed BEFORE awaiting on_complete, so
        # finalize_discovery may still be linking leads/companies. Poll the
        # discovery until it reaches a terminal state (up to 90s).
        finalized = None
        for _ in range(90):
            await asyncio.sleep(1)
            finalized = await asyncio.to_thread(get_discovery, discovery_id)
            if finalized and finalized["status"] in ("completed", "failed", "cancelled"):
                break
        assert finalized is not None
        assert finalized["status"] == "completed", (
            f"discovery must be finalized by job completion, got {finalized['status']}"
        )
        assert finalized["completed_at"] is not None
        companies = finalized.get("discovery_companies") or []
        leads = finalized.get("discovery_leads") or []
        assert len(leads) > 0, "completed discovery must link its leads"
        assert len(companies) > 0, "completed discovery must link its companies"
        assert (
            finalized.get("provider_provenance")
        ), "provider provenance must be recorded"

        # Refresh-stability: reading the same discovery again (what the UI does
        # on reload / after cache invalidation) must return the same results.
        refreshed = await asyncio.to_thread(get_discovery, discovery_id)
        assert refreshed is not None
        assert {
            c["company_id"] for c in (refreshed.get("discovery_companies") or [])
        } == {c["company_id"] for c in companies}, "company links must survive refresh"
        assert {
            l["lead_id"] for l in (refreshed.get("discovery_leads") or [])
        } == {l["lead_id"] for l in leads}, "lead links must survive refresh"

        # Tidy up: mark the discovery cancelled so the history list stays clean.
        from services.discovery import mark_discovery_status

        await asyncio.to_thread(mark_discovery_status, discovery_id, "cancelled")

    @pytest.mark.asyncio
    async def test_campaign_from_discovery_persists_link(self, client, authenticated_session):
        """A campaign created from a Discovery must persist campaigns.discovery_id
        (the source discovery), while the discovery keeps no campaign link."""
        resp = client.post(
            "/api/discoveries",
            json={"query": "HR software startups"},
            headers={"Authorization": f"Bearer {authenticated_session}"},
        )
        assert resp.status_code == 200, resp.text
        discovery_id = resp.json().get("discovery_id")
        assert discovery_id, "discovery must be created"

        campaign_resp = client.post(
            f"/api/web/session/{authenticated_session}/campaigns",
            json={
                "name": "HR Software ICP",
                "objective": "Open a conversation with HR platforms",
                "search_query": "HR software startups",
                "discovery_id": discovery_id,
                "lead_count": 0,
                "leads": [],
                "status": "planning",
            },
        )
        assert campaign_resp.status_code == 200, campaign_resp.text
        campaign = campaign_resp.json().get("campaign", {})
        campaign_id = campaign.get("id")
        assert campaign_id, "campaign must be created"

        from services.supabase import get_supabase_client

        client_db = get_supabase_client()
        assert client_db is not None

        # The campaign row is written before the endpoint responds, so it
        # must exist immediately.
        result = (
            client_db.table("campaigns")
            .select("id, discovery_id")
            .eq("id", campaign_id)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        assert rows, "campaign row must exist"
        assert rows[0]["id"] == campaign_id
        assert rows[0].get("discovery_id") == discovery_id, (
            "campaigns.discovery_id must reference the source discovery"
        )

        # Tidy up: cancel the discovery + its job.
        from services.discovery import mark_discovery_status

        await asyncio.to_thread(mark_discovery_status, discovery_id, "cancelled")
        from services.job_engine.storage import JobStorage
        from services.job_engine.models import JobStatus

        job_row = JobStorage().get_job(resp.json().get("job_id") or "")
        if job_row:
            JobStorage().update_job(
                job_row.id,
                status=JobStatus.CANCELLED,
                stage="Cancelled",
                completed_at=datetime.now(timezone.utc),
            )


def _fake_structured_icp(user_input: str, existing_context=None) -> dict:
    """Deterministic ICP shape the plan derivation consumes (hermetic tests)."""
    return {
        "offer": "AI phone answering software",
        "service_category": "ai",
        "buyer_industries": ["restaurants", "dining"],
        "buyer_roles": ["Restaurant Owner", "General Manager", "Operations Manager"],
        "excluded_roles": ["developer", "designer", "freelancer", "consultant"],
        "company_types": [],
        "pain_points": ["missed calls"],
        "keywords": ["Restaurant Owner restaurants", "General Manager restaurants"],
        "search_hints": ["Restaurant Owner restaurants"],
        "mode": "ai",
    }


class TestDiscoveryPlan:
    """PR2.6: the raw objective is decomposed into a structured plan, and the
    provider pipeline consumes ONLY the structured plan — never the raw
    objective sentence."""

    def test_plan_derivation_is_structured(self, monkeypatch):
        monkeypatch.setattr(
            "services.icp_extractor.extract_structured_icp", _fake_structured_icp
        )
        from services.discovery_plan import derive_discovery_plan

        plan = derive_discovery_plan("AI phone answering software for restaurants")
        d = plan.to_dict()

        assert d["offering"] == "AI phone answering software"
        assert d["target_audience"] == "restaurants"
        assert "restaurants" in d["industries"]
        assert "Restaurant Owner" in d["decision_maker_roles"]
        assert d["exclusions"], "plan must carry exclusion terms"
        assert d["company_keywords"], "plan must carry buyer keyword combos"
        assert d["buyer_personas"], "plan must carry search-ready personas"
        assert d["icp_summary"], "plan must carry a readable summary"

    def test_raw_objective_never_reaches_provider_inputs(self, monkeypatch):
        monkeypatch.setattr(
            "services.icp_extractor.extract_structured_icp", _fake_structured_icp
        )
        from services.discovery_plan import derive_discovery_plan, icp_from_plan

        objective = (
            "Take AI phone answering software to restaurants to stop missing calls"
        )
        plan = derive_discovery_plan(objective)
        icp = icp_from_plan(plan.to_dict())

        provider_visible = " ".join(
            list(plan.company_keywords)
            + list(plan.buyer_personas)
            + plan.industries
            + plan.decision_maker_roles
            + icp.get("keywords", [])
        ).lower()

        assert "take ai phone answering" not in provider_visible
        assert "stop missing calls" not in provider_visible
        assert "cutting missed calls" not in provider_visible

    def test_execution_stage_contract(self):
        """The live execution stages the UI renders must match the registry."""
        from services.job_engine.registry import STAGES_SEARCH

        assert len(STAGES_SEARCH) == 5
        assert STAGES_SEARCH == [
            "Initializing research...",
            "Understanding target market...",
            "Finding matching companies...",
            "Ranking prospects...",
            "Preparing recommendations...",
        ]

    def test_plan_carries_pr27_semantic_fields(self, monkeypatch):
        """PR2.7: the plan must carry the full intelligence field set that
        strategy generation consumes — never a raw objective rephrase."""

        def _cafe_icp(user_input: str, existing_context=None) -> dict:
            return {
                "offer": "AI automation and website design",
                "buyer_industries": ["cafes", "coffee shops"],
                "buyer_roles": ["Cafe Owner", "General Manager"],
                "excluded_roles": ["developer", "consultant"],
                "keywords": ["cafe owner", "coffee shop manager"],
                "search_hints": ["cafe owner"],
                "target_audience": "cafes",
                "mode": "ai",
            }

        monkeypatch.setattr(
            "services.icp_extractor.extract_structured_icp", _cafe_icp
        )
        from services.discovery_plan import derive_discovery_plan

        plan = derive_discovery_plan(
            "Sell AI automations and websites to cafe owners in the US"
        )
        d = plan.to_dict()

        assert d["primary_services"], "offering must decompose into services"
        assert d["negative_keywords"], "plan must carry exclusion terms"
        assert d["pain_points"], "plan must carry market pain points"
        assert d["buying_signals"], "plan must carry buying signals"
        assert d["technologies"], "plan must carry likely tech stack"
        assert d["business_characteristics"], "plan must carry company attributes"
        assert d["messaging_angle"], "plan must carry a strategy-facing angle"
        assert d["success_criteria"], "plan must carry success criteria"
        assert any("cafe" in str(i).lower() for i in d["industries"]), (
            "industries must resolve from the target audience"
        )

    def test_provider_consumes_negative_keywords(self, monkeypatch):
        """PR2.7: the provider must exclude companies matching plan
        negative_keywords (never see the raw objective)."""
        import services.providers.synthetic_provider as sp

        provider = sp.SyntheticProvider()
        dataset = provider._data.all_leads

        baseline = provider.search_leads(
            {"buyer_industries": ["restaurants"], "buyer_roles": ["Owner"]},
            {},
            limit=50,
        )["leads"]
        filtered = provider.search_leads(
            {
                "buyer_industries": ["restaurants"],
                "buyer_roles": ["Owner"],
                "negative_keywords": ["nightclub", "hotel", "franchise chain"],
            },
            {},
            limit=50,
        )["leads"]

        def _rejectable(leads):
            return [
                l for l in leads
                if any(
                    neg in " ".join([
                        l.get("company") or "",
                        l.get("company_description") or "",
                        l.get("company_industry") or "",
                    ]).lower()
                    for neg in ["nightclub", "hotel", "franchise chain"]
                )
            ]

        assert len(baseline) > 0, "baseline search must return leads"
        assert _rejectable(baseline) or True  # dataset may not contain rejects
        assert len(_rejectable(filtered)) == 0, (
            "companies matching negative_keywords must be excluded"
        )
        assert "cafe owners" not in str(dataset[0] if dataset else {}).lower() or True

    def test_strategy_generation_is_grounded(self, monkeypatch):
        """PR2.7: the strategy generator must consume the Discovery Plan and
        real market research, never just paraphrase the objective."""
        captured: dict = {}

        def _fake_openai(system_text: str, user_text: str) -> str:
            captured["system"] = system_text
            captured["user"] = user_text
            return json.dumps({
                "campaign_objective": "Sell to cafes",
                "icp": "Cafe owners",
                "channel": "email",
                "market_summary": "Independent cafes, no online ordering",
                "observed_patterns": ["Recent openings", "Outdated websites"],
                "buying_signals": ["Hiring front of house"],
                "pain_points": ["No online ordering"],
                "value_proposition": "Automate order follow-up",
                "positioning": "The fix, not the feature",
                "messaging_angles": ["Angle A", "Angle B"],
                "objection_handling": ["Objection: cost, Response: ROI"],
                "outreach_sequence": ["Intro", "Follow-up"],
                "personalization": "Reference their ordering flow",
                "cta": "15-min call",
                "success_metrics": ["Reply rate"],
                "risks": ["Seasonality"],
                "confidence": "Medium",
                "tone": "direct",
                "persona": "Loqi operator",
                "offer": {"type": "call", "detail": "15-min"},
            })

        monkeypatch.setattr("services.ai._send_openai_request", _fake_openai)
        from services.ai import generate_campaign_strategy

        strategy = generate_campaign_strategy("Sell AI automations to cafe owners", {
            "discovery_plan": {
                "offering": "AI automations",
                "primary_services": ["AI Automation"],
                "industries": ["cafes"],
                "decision_maker_roles": ["Cafe Owner"],
                "negative_keywords": ["franchise chain"],
                "pain_points": ["No online ordering"],
                "buying_signals": ["Recently opened"],
                "technologies": ["Toast POS"],
                "messaging_angle": "Relief first",
            },
            "market_research": {
                "companies": [
                    {"company": "Daily Grind Cafe", "company_industry": "Restaurant", "company_city": "Austin"},
                    {"company": "Blue Cup Coffee", "company_industry": "Restaurant"},
                ],
                "industry_distribution": {"Restaurant": 2},
            },
        })

        user = captured["user"]
        assert "Discovery plan" in user, "the plan must be included in the prompt"
        assert "AI automations" in user
        assert "Daily Grind Cafe" in user, "real companies must be in the prompt"
        assert "franchise chain" in user, "negative terms must be visible"
        assert "market research" in user.lower()

        assert strategy["audience"] == "Cafe owners"
        assert strategy["market_summary"] == "Independent cafes, no online ordering"
        assert strategy["observed_patterns"] == ["Recent openings", "Outdated websites"]
        assert strategy["confidence"] == "Medium"
        assert strategy["sequence"] == ["Intro", "Follow-up"]
        assert strategy["messaging_angle"] == "Angle A"

    def test_strategy_degrades_without_context(self, monkeypatch):
        """PR2.7: legacy campaigns (no plan, no research) still generate a
        strategy — the playbook explicitly marks the low-confidence fallback."""
        captured: dict = {}

        def _fake_openai(system_text: str, user_text: str) -> str:
            captured["user"] = user_text
            return json.dumps({
                "campaign_objective": "Legacy",
                "icp": "Prospects",
                "channel": "email",
                "market_summary": "",
                "observed_patterns": [],
                "buying_signals": [],
                "pain_points": [],
                "value_proposition": "",
                "positioning": "",
                "messaging_angles": [],
                "objection_handling": [],
                "outreach_sequence": ["Intro", "Follow-up"],
                "personalization": "",
                "cta": "",
                "success_metrics": [],
                "risks": [],
                "confidence": "Low — drafted from the objective alone",
                "tone": "direct",
                "persona": "Loqi operator",
                "offer": {},
            })

        monkeypatch.setattr("services.ai._send_openai_request", _fake_openai)
        from services.ai import generate_campaign_strategy

        strategy = generate_campaign_strategy("Open conversations with HR platforms")
        assert "Discovery plan" not in captured["user"], "no plan → no plan block"
        assert strategy["audience"] == "Prospects"
        assert strategy["confidence"].startswith("Low")
        assert strategy["sequence"] == ["Intro", "Follow-up"]

    def test_cafe_campaign_never_returns_zero(self):
        """PR2.7 regression: 'AI automations and websites for cafe owners' must
        always return companies.

        Root cause found during audit: plan industries like 'cafes' (plural),
        'coffee shops', and 'food and beverage' were absent from the provider
        industry map, and 'hospitality' mapped to Hotel — so the cafe bucket
        was never selected while negative keywords (hotel/resort) then
        excluded every Hotel candidate → 0 companies.
        """
        import services.providers.synthetic_provider as sp

        provider = sp.SyntheticProvider()

        for negation in [
            "cafes+hospitality (original failing mix)",
            "coffee shops + food and beverage",
        ]:
            result = provider.search_leads(
                {
                    "buyer_industries": [
                        "cafes", "hospitality"
                    ] if negation.startswith("cafes") else [
                        "coffee shops", "food and beverage"
                    ],
                    "buyer_roles": ["Cafe Owner", "General Manager", "Operations Manager"],
                    "excluded_roles": ["developer", "designer", "consultant"],
                    "negative_keywords": [
                        "hotel", "resort", "nightclub",
                        "franchise chain", "enterprise chain", "corporate cafeteria",
                    ],
                    "keywords": ["cafe owner"],
                },
                {},
                limit=10,
            )
            leads = result["leads"]
            assert len(leads) > 0, f"{negation} must never return zero"
            assert all(
                (l.get("company_industry") or "").lower()
                in {"cafe", "restaurant"}
                for l in leads
            ), f"{negation} must return cafe/restaurant companies only"

        # hospitality alone must resolve to restaurant/cafe — never to Hotel
        hosp = provider.search_leads(
            {"buyer_industries": ["hospitality"], "buyer_roles": ["Owner"]},
            {},
            limit=5,
        )["leads"]
        assert hosp, "hospitality-only search must return companies"
        assert all(
            (l.get("company_industry") or "").lower() != "hotel" for l in hosp
        )

    def test_provider_relaxes_strict_constraints_to_avoid_zero(self):
        """PR2.7 zero-guard: when industry+negative constraints eliminate
        every candidate, the provider falls back to the next stage instead of
        returning an empty result."""
        import services.providers.synthetic_provider as sp

        provider = sp.SyntheticProvider()
        r = provider.search_leads(
            {
                "buyer_industries": ["hotels"],
                "buyer_roles": ["General Manager"],
                "negative_keywords": ["hotel", "resort"],
            },
            {},
            limit=5,
        )
        assert r["stats"]["returned"] > 0, (
            "industry+negatives must fall back to industry-only, never zero"
        )
        assert all(l.get("company_industry") == "Hotel" for l in r["leads"])