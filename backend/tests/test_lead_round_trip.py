"""PR2.8 regression: attached leads must survive a Research -> Attach -> Return
round trip with lead_count > 0.

The Discovery detail page attaches recommendations one-by-one via
POST /campaigns/{id}/leads (payload built by DiscoveryDetailWorkspace's
leadPayload()), then routes back to the campaign page which re-reads the
campaign via GET /campaigns/{id}. The campaign page's lead count and lead list
must come from the same persisted campaign_leads state, never from in-memory
counters or events.

Also guards the candidate-facing bulk path (attach-discovery) and the
discovery -> new-campaign creation flow.
"""

import asyncio
import time
from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient
from tests.conftest import _AuthTestClient
from main import app


@pytest.fixture(scope="module")
def client():
    return _AuthTestClient(app)


@pytest.fixture()
def authenticated_session(client, monkeypatch):
    """A web session bound to a REAL identity user. (Same pattern as
    test_discovery_jobs.py; kept here so this suite is self-contained.)"""
    from uuid import uuid4

    from services.supabase import get_supabase_client

    user_id = str(uuid4())
    db = get_supabase_client()
    assert db is not None, "supabase client required"
    db.table("identity_users").insert({
        "id": user_id,
        "display_name": "Lead Round Trip Test",
    }).execute()
    db.table("users").insert({
        "id": user_id,
        "telegram_id": f"web:test-{user_id}",
        "username": "Lead Round Trip Test",
    }).execute()

    async def fake_auth(request):
        return user_id

    monkeypatch.setattr(
        "services.identity.api.get_authenticated_user_id", fake_auth
    )

    resp = client.post(
        "/api/web/session",
        json={"display_name": "Lead Round Trip Test"},
        headers={"Authorization": "Bearer lead-round-trip-test-token"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("session_token"), "authenticated session must be created"
    return data["session_token"]


async def _run_completed_discovery(client, token, query="HR software startups"):
    """Create a discovery via the API and run its job to completion.

    Returns (discovery_detail, discovery_id, job_id).
    """
    from main import engine
    from services.discovery import finalize_discovery
    from services.job_engine.manager import JobManager
    from services.job_engine.storage import JobStorage

    summary = await asyncio.to_thread(engine.get_web_session_summary, token)
    assert summary is not None and summary.get("user_id")
    user_id = summary["user_id"]

    resp = client.post(
        "/api/discoveries",
        json={"query": query},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    discovery_id = resp.json().get("discovery_id")
    job_id = resp.json().get("job_id")
    assert discovery_id and job_id

    manager = JobManager()
    created = await manager.create_search_job(
        user_id=user_id, query=query, discovery_id=discovery_id,
        on_complete=finalize_discovery,
    )
    assert created and created.get("job_id")
    job_id = created["job_id"]

    for _ in range(150):
        await asyncio.sleep(1)
        job = JobStorage().get_job(job_id)
        if job and job.status.value == "completed":
            break
    else:
        pytest.fail("search workflow did not reach completed status")

    detail = None
    for _ in range(90):
        await asyncio.sleep(1)
        r = client.get(
            f"/api/discoveries/{discovery_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        detail = r.json().get("discovery", {})
        if detail.get("status") == "completed":
            break
    assert detail is not None and detail["status"] == "completed", (
        "discovery must be completed before attaching"
    )
    return detail, discovery_id, job_id


def _tidy(discovery_id, job_id):
    from services.discovery import mark_discovery_status
    from services.job_engine.models import JobStatus
    from services.job_engine.storage import JobStorage

    try:
        asyncio.run(mark_discovery_status(discovery_id, "cancelled"))
    except Exception:
        pass
    job = JobStorage().get_job(job_id or "") if job_id else None
    if job:
        try:
            JobStorage().update_job(
                job.id,
                status=JobStatus.CANCELLED,
                stage="Cancelled",
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass


def _lead_payload(company: dict) -> dict:
    """Mirror DiscoveryDetailWorkspace's leadPayload() (company rec path)."""
    return {
        "id": str((company.get("company") or {}).get("id") or company.get("company_id") or ""),
        "company": str((company.get("company") or {}).get("name") or ""),
        "title": str((company.get("company") or {}).get("industry") or ""),
        "seniority": "Prospect",
        "location": str((company.get("company") or {}).get("city") or ""),
        "buying_signal": "Research match",
        "buying_signal_detail": "",
    }


def _create_campaign(client, token, name, objective):
    resp = client.post(
        f"/api/web/session/{token}/campaigns",
        json={
            "name": name,
            "objective": objective,
            "search_query": "HR software startups",
            "lead_count": 0,
            "leads": [],
            "status": "planning",
        },
    )
    assert resp.status_code == 200, resp.text
    campaign_id = resp.json().get("campaign", {}).get("id")
    assert campaign_id
    return campaign_id


def _read_campaign(client, token, campaign_id) -> dict:
    resp = client.get(f"/api/web/session/{token}/campaigns/{campaign_id}")
    assert resp.status_code == 200, resp.text
    return resp.json().get("campaign", {})


class TestLeadRoundTrip:
    """Research -> Attach -> Return => campaign lead_count > 0."""

    @pytest.mark.asyncio
    async def test_discovery_companies_carry_provenance(self, client, authenticated_session):
        """Provider provenance must survive finalize: discovery_companies and
        companies carry the search provider (PR3.1 Part F)."""
        from services.supabase import get_supabase_client

        detail, discovery_id, job_id = await _run_completed_discovery(
            client, authenticated_session)
        _tidy(discovery_id, job_id)

        db = get_supabase_client()
        rows = (
            db.table("discovery_companies")
            .select("company_id, source_provider")
            .eq("discovery_id", discovery_id)
            .limit(20)
            .execute()
            .data
        )
        assert rows, "discovery must link companies"
        populated = [r for r in rows if (r.get("source_provider") or "").strip()]
        assert populated, (
            "source_provider must be carried from the search provider; "
            f"all rows were empty: {rows}"
        )

    @pytest.mark.asyncio
    async def test_attach_then_return_keeps_leads(self, client, authenticated_session):
        """The per-lead attach flow must survive a return trip: re-reading the
        campaign reports the same persisted lead_count > 0."""
        detail, discovery_id, job_id = await _run_completed_discovery(
            client, authenticated_session
        )
        try:
            companies = detail.get("discovery_companies") or []
            leads = detail.get("discovery_leads") or []
            assert companies or leads, "completed discovery must surface candidates"

            campaign_id = _create_campaign(
                client, authenticated_session, "Lead Round Trip", "Talk to HR platforms"
            )

            for company in companies[:3]:
                resp = client.post(
                    f"/api/web/session/{authenticated_session}/campaigns/{campaign_id}/leads",
                    json={
                        "lead": _lead_payload(company),
                        "discovery_id": discovery_id,
                    },
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body.get("ok") is True

            back = _read_campaign(client, authenticated_session, campaign_id)
            assert int(back.get("lead_count") or 0) > 0, (
                "attached leads must survive the return trip; "
                f"lead_count={back.get('lead_count')} leads={len(back.get('leads') or [])}"
            )
            assert len(back.get("leads") or []) > 0, (
                "the campaign must re-surface its attached leads"
            )

            # Dedupe safety: attach the same company again — count stays stable.
            before = int(back.get("lead_count") or 0)
            company = companies[0]
            resp = client.post(
                f"/api/web/session/{authenticated_session}/campaigns/{campaign_id}/leads",
                json={
                    "lead": _lead_payload(company),
                    "discovery_id": discovery_id,
                },
            )
            assert resp.status_code == 200, resp.text
            again = _read_campaign(client, authenticated_session, campaign_id)
            after = int(again.get("lead_count") or 0)
            assert after == before, "duplicate attach must not inflate the count"
        finally:
            _tidy(discovery_id, job_id)

    @pytest.mark.asyncio
    async def test_new_campaign_from_discovery_keeps_leads(self, client, authenticated_session):
        """Campaign creation with attached-lead payloads (New Campaign page flow
        from Discovery) must persist each lead and re-read count > 0."""
        from main import engine
        from services.discovery import finalize_discovery
        from services.job_engine.manager import JobManager
        from services.job_engine.storage import JobStorage

        summary = await asyncio.to_thread(
            engine.get_web_session_summary, authenticated_session
        )
        user_id = summary["user_id"]

        resp = client.post(
            "/api/discoveries",
            json={"query": "HR software startups"},
            headers={"Authorization": f"Bearer {authenticated_session}"},
        )
        assert resp.status_code == 200, resp.text
        discovery_id = resp.json().get("discovery_id")
        job_id = resp.json().get("job_id")
        assert discovery_id

        manager = JobManager()
        created = await manager.create_search_job(
            user_id=user_id, query="HR software startups",
            discovery_id=discovery_id, on_complete=finalize_discovery,
        )
        assert created and created.get("job_id")
        job_id = created["job_id"]

        for _ in range(150):
            await asyncio.sleep(1)
            job = JobStorage().get_job(job_id)
            if job and job.status.value == "completed":
                break
        else:
            pytest.fail("search workflow did not reach completed status")

        detail = None
        for _ in range(90):
            await asyncio.sleep(1)
            r = client.get(
                f"/api/discoveries/{discovery_id}",
                headers={"Authorization": f"Bearer {authenticated_session}"},
            )
            assert r.status_code == 200, r.text
            detail = r.json().get("discovery", {})
            if detail.get("status") == "completed":
                break
        assert detail is not None and detail["status"] == "completed"

        companies = detail.get("discovery_companies") or []
        assert companies, "completed discovery must surface companies"
        leads = [_lead_payload(c) for c in companies[:2]]

        campaign_resp = client.post(
            f"/api/web/session/{authenticated_session}/campaigns",
            json={
                "name": "From Discovery",
                "objective": "Open conversations",
                "search_query": "AI startups",
                "discovery_id": discovery_id,
                "lead_count": len(leads),
                "leads": leads,
                "status": "planning",
            },
        )
        assert campaign_resp.status_code == 200, campaign_resp.text
        campaign_id = campaign_resp.json().get("campaign", {}).get("id")
        assert campaign_id

        stored = _read_campaign(client, authenticated_session, campaign_id)
        assert int(stored.get("lead_count") or 0) == len(leads), (
            "campaign created with leads must report them; "
            f"lead_count={stored.get('lead_count')} expected={len(leads)}"
        )
        assert len(stored.get("leads") or []) == len(leads)

        from services.supabase import get_supabase_client

        db = get_supabase_client()
        result = (
            db.table("campaign_leads")
            .select("lead_id")
            .eq("campaign_id", campaign_id)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        assert len(rows) == len(leads), "campaign_leads rows must persist in the DB"

        _tidy(discovery_id, job_id)