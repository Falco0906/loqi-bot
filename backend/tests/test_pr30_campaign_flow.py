"""PR3.0: end-to-end campaign flow regression — no prompt hacking.

Full restaurant-style campaign loop against the real durable stack:

  discovery → attach leads → generate strategy (mocked LLM) →
  rich playbook visible flat in the API → regenerate (leads preserved) →
  generate drafts (playbook grounding + evidence tracing) →
  re-kickoff (no duplicates) → approve → state transitions

Every OpenAI interaction is stubbed at ``services.ai._send_openai_request``
so the assertions target the *pipeline*, not the model.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import services.ai as ai_module
import main as main_module
from main import app
from services.job_engine.storage import JobStorage

# ─────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────


def _playbook_response() -> dict:
    return {
        "campaign_objective": "Sell AI order-flow automation to restaurant groups",
        "icp": "Restaurant chains with 3-20 locations",
        "channel": "email",
        "market_summary": "Multi-location casual dining brands with legacy ordering flows",
        "market_attractiveness": "Observed expansion and hiring across researched companies",
        "market_common_patterns": ["No online ordering", "Phone-answer staff constraints"],
        "market_technologies": ["Gallery POS", "Monday.com"],
        "market_maturity": "Early adoption",
        "observed_patterns": ["Recent openings"],
        "buying_signals": ["Hiring front of house"],
        "pain_points": ["No online ordering", "Staff scheduling"],
        "pain_prioritization": [
            {"pain": "No online ordering", "why": "Observed across the researched restaurants"},
            {"pain": "Staff scheduling", "why": "Weekend coverage gaps"},
        ],
        "personas": [
            {
                "persona": "Operations Manager",
                "priorities": ["Higher table turnover", "Fewer manual phone orders"],
                "incentives": ["Labor savings"],
                "kpis": ["Orders per day"],
                "fears": ["Costly rollout"],
                "likely_objections": ["Already use a POS"],
                "authority_level": "Decision maker",
            }
        ],
        "value_proposition": "Take phone orders with an automated flow",
        "positioning": "The ordering channel, not the POS replacement",
        "differentiators": ["Works on the existing POS"],
        "proof_points": ["Observed on Gallery POS", "Recent location expansion"],
        "why_now": "Order volume is rising into the season",
        "outreach_strategy": {
            "first_touch_goal": "Open on the observed ordering gap",
            "first_touch_cta": "Reply with whether phone orders are still manual",
            "follow_up_strategy": "One concrete example follow-up",
            "personalization_opportunities": ["Name their POS", "Reference recent openings"],
            "topics_to_avoid": ["Franchise talk"],
        },
        "messaging_angles": ["Ordering relief", "Labor relief"],
        "objection_handling": ["Objection: has a POS, Response: integration"],
        "outreach_sequence": ["Intro", "Follow-up", "Final check-in"],
        "personalization": "Reference the observed tech and growth signals",
        "cta": "Reply with one detail",
        "success_metrics": ["Reply rate"],
        "risks": ["Seasonality"],
        "confidence": "Medium — grounded in 14 researched companies",
        "tone": "direct",
        "persona": "Loqi operator",
        "offer": {"type": "call", "detail": "15-min"},
    }


def _draft_response() -> dict:
    return {
        "subject": "Phone orders at Harvest Kitchen",
        "body": "You mentioned hiring front-of-house at Harvest Kitchen — "
                "when a group of people is calling in orders at peak, is that "
                "still a phone-first process? If yes, I have an idea worth "
                "15 minutes.",
    }


@pytest.fixture
def fake_llm(monkeypatch):
    """One capture buffer for the whole E2E chain."""
    captured = {"strategy_system": "", "strategy_user": "",
                "draft_user": [], "draft_system": []}

    def fake(system_text: str, user_text: str) -> str:
        if "Sales Playbook architect" in system_text:
            captured["strategy_system"] = system_text
            captured["strategy_user"] = user_text
            return json.dumps(_playbook_response())
        if "cold email" in (system_text or "").lower() or "outreac" in (system_text or "").lower():
            captured["draft_system"].append(system_text)
            captured["draft_user"].append(user_text)
            return json.dumps(_draft_response())
        raise AssertionError(f"unexpected OpenAI call: {system_text[:80]}")

    monkeypatch.setattr(ai_module, "_send_openai_request", fake)
    return captured


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture()
def authenticated_session(client, monkeypatch):
    from services.supabase import get_supabase_client

    user_id = str(uuid4())
    db = get_supabase_client()
    assert db is not None, "supabase client required"
    db.table("identity_users").insert({
        "id": user_id,
        "display_name": "PR30 E2E Test",
    }).execute()
    db.table("users").insert({
        "id": user_id,
        "telegram_id": f"web:test-{user_id}",
        "username": "PR30 E2E Test",
    }).execute()

    async def fake_auth(request):
        return user_id

    monkeypatch.setattr("services.identity.api.get_authenticated_user_id", fake_auth)

    resp = client.post(
        "/api/web/session",
        json={"display_name": "PR30 E2E Test"},
        headers={"Authorization": "Bearer pr30-e2e-token"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("session_token")
    assert token
    return token


from tests.test_lead_round_trip import (  # shared E2E harness helpers
    _tidy,
    _run_completed_discovery,
    _lead_payload,
    _create_campaign as _create_campaign_shared,
    _read_campaign as _read_campaign_shared,
)


def _create_campaign(client, token) -> str:
    return _create_campaign_shared(
        client, token, "PR30 Restaurant Campaign", "Sell AI order automation to restaurant chains")


def _read_campaign(client, token, campaign_id) -> dict:
    return _read_campaign_shared(client, token, campaign_id)


def _attach_company_leads(client, token, campaign_id, detail, limit=3):
    companies = detail.get("discovery_companies") or []
    assert companies, "completed discovery must surface companies"
    for company in companies[:limit]:
        resp = client.post(
            f"/api/web/session/{token}/campaigns/{campaign_id}/leads",
            json={"lead": _lead_payload(company),
                  "discovery_id": detail.get("id", "")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("ok") is True


async def _generate_strategy_direct(main_module, token, campaign_id) -> dict:
    """Start + await a strategy job in the *test* event loop.

    TestClient serves each HTTP request on a fresh event loop, so background
    asyncio tasks launched inside the endpoint die with that loop. Calling the
    endpoint function directly runs the job task on this loop, where the
    async wait below keeps it progressing.
    """
    from unittest.mock import MagicMock

    from main import engine

    summary = await asyncio.to_thread(engine.get_web_session_summary, token)
    user_id = summary["user_id"]

    async def _owner(request, session_token):
        return user_id

    original = main_module._workspace_owner
    main_module._workspace_owner = _owner
    try:
        started = await main_module.generate_campaign_strategy(
            token, campaign_id, MagicMock())
    finally:
        main_module._workspace_owner = original
    assert started.get("ok") is True and started.get("job_id"), started
    job_id = started["job_id"]

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        job = main_module.STRATEGY_JOBS.get(job_id)
        if job and job.get("status") in ("queued", "running"):
            await asyncio.sleep(0.5)
            continue
        break
    else:
        pytest.fail("strategy job did not finish before timeout")

    job = main_module.STRATEGY_JOBS.get(job_id)
    assert job is not None and job["status"] == "completed", job
    return job["strategy"]


async def _start_draft_batch(main_module, token, campaign_id, user_id):
    """Start draft generation in the *test* event loop.

    TestClient serves each HTTP request on a fresh event loop, so background
    asyncio tasks launched inside the endpoint die with that loop. Calling the
    endpoint function directly runs the batch task on this loop, where the
    async wait-poll below keeps it progressing.
    """
    from unittest.mock import MagicMock

    async def _owner(request, session_token):
        return user_id

    original = main_module._workspace_owner
    main_module._workspace_owner = _owner
    try:
        return await main_module.generate_campaign_drafts(
            token, campaign_id, MagicMock())
    finally:
        main_module._workspace_owner = original


async def _await_batch_done(main_module, token, campaign_id, timeout=150):
    """Run the generation batch to completion in the test loop; return (batch_id, final_status)."""
    from unittest.mock import MagicMock

    from main import engine

    summary = await asyncio.to_thread(engine.get_web_session_summary, token)
    user_id = summary["user_id"]
    started = await _start_draft_batch(main_module, token, campaign_id, user_id)
    assert started.get("ok") is True and started.get("batch_id")
    batch_id = started["batch_id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = main_module.batch_jobs.get(batch_id)
        if job and job.get("status") == "processing":
            await asyncio.sleep(1)
            continue
        break
    else:
        pytest.fail("draft batch did not finish before timeout")

    async def _owner(request, session_token):
        return user_id

    original = main_module._workspace_owner
    main_module._workspace_owner = _owner
    try:
        status = await main_module.campaign_generation_status(
            token, campaign_id, MagicMock())
    finally:
        main_module._workspace_owner = original
    return batch_id, status


@pytest.fixture(autouse=True)
def _clean_batch_stores():
    main_module.batch_jobs.clear()
    main_module.STRATEGY_JOBS.clear()
    main_module._draft_batch_tasks.clear()
    main_module._strategy_job_tasks.clear()
    yield
    main_module.batch_jobs.clear()
    main_module.STRATEGY_JOBS.clear()
    main_module._draft_batch_tasks.clear()
    main_module._strategy_job_tasks.clear()


# ─────────────────────────────────────────────────────────────────────────
# The E2E campaign flow
# ─────────────────────────────────────────────────────────────────────────


class TestPr30CampaignFlow:
    async def test_full_campaign_flow(
        self, client, authenticated_session, fake_llm
    ):
        token = authenticated_session
        detail, discovery_id, job_id = await _run_completed_discovery(
            client, token, query="restaurant chains with multiple locations")
        campaign_id = None
        try:
            assert discovery_id
            campaign_id = _create_campaign(client, token)
            _attach_company_leads(client, token, campaign_id, detail)

            first_read = _read_campaign(client, token, campaign_id)
            assert int(first_read.get("lead_count") or 0) > 0, "leads must attach"
            lead_ids = {lead.get("id") for lead in (first_read.get("leads") or [])}
            assert lead_ids, "attached leads must carry ids"

            # ── Strategy generation (202 → background job → poll) ──
            strategy = await _generate_strategy_direct(main_module, token, campaign_id)
            for key in ("market_summary", "pain_prioritization", "personas",
                        "outreach_strategy", "proof_points", "why_now"):
                assert key in strategy, f"playbook key {key} missing at API edge"

            assert "Sales Playbook architect" in fake_llm["strategy_system"], (
                "strategy call must go through the playbook pipeline"
            )

            after_strategy = _read_campaign(client, token, campaign_id)
            strategy_snapshot = after_strategy.get("strategy") or {}
            assert "pain_prioritization" in strategy_snapshot, (
                "playbook must be served at the top level of the campaign detail "
            )
            assert "content" not in strategy_snapshot, (
                "no legacy `content` wrapper may survive at the API edge"
            )
            assert strategy_snapshot.get("personas"), "personas must be served flat"
            first_strategy_generated = strategy_snapshot.get("generated_at")

            # ── Regeneration must preserve leads ──
            await _generate_strategy_direct(main_module, token, campaign_id)
            after_regenerate = _read_campaign(client, token, campaign_id)
            assert int(after_regenerate.get("lead_count") or 0) == int(
                first_read.get("lead_count") or 0), "regenerate must not drop leads"
            regenerated_ids = {
                lead.get("id") for lead in (after_regenerate.get("leads") or [])
            }
            _dump = lambda ls: sorted((l.get("id"), l.get("company")) for l in ls)
            assert regenerated_ids == lead_ids, (
                "lead identities must survive regeneration; "
                f"before={_dump(first_read.get('leads') or [])} "
                f"after={_dump(after_regenerate.get('leads') or [])}"
            )
            second_generated = (after_regenerate.get("strategy") or {}).get("generated_at")
            assert second_generated != first_strategy_generated, (
                "strategy must actually refresh on regenerate"
            )

            # ── Draft generation ──
            batch_id, batch_status = await _await_batch_done(
                main_module, token, campaign_id)
            assert batch_status.get("active") is False
            assert batch_status.get("status") in ("completed", "failed")
            assert batch_status.get("batch_id") == batch_id

            drafts = client.get(
                f"/api/web/session/{token}/campaigns/{campaign_id}/drafts").json()
            draft_list = drafts.get("drafts") or []
            assert len(draft_list) > 0, "drafts must be generated and persisted"
            seen_ids = set()
            for draft in draft_list:
                assert draft.get("id") not in seen_ids, "duplicate draft ids"
                seen_ids.add(draft.get("id"))
                assert draft.get("subject"), "each draft needs a subject"
                assert (draft.get("text") or "").strip(), "each draft needs a body"

            evidence_trace = draft_list[0].get("evidence_trace") or {}
            assert "strategy_used" in evidence_trace, (
                "drafts must carry the strategy-provenance trace"
            )
            assert "pain_prioritization" in evidence_trace.get("strategy_used", []), (
                "played playbook sections must be recorded"
            )
            assert "confidence" in evidence_trace.get("strategy_used", []), (
                "confidence must be traced when available"
            )

            # ── Re-kickoff must be idempotent ──
            from main import engine as _engine
            summary = await asyncio.to_thread(_engine.get_web_session_summary, token)
            user_id = summary["user_id"]
            again = await _start_draft_batch(
                main_module, token, campaign_id, user_id)
            assert again.get("ok") is True
            assert again.get("batch_id") == batch_id, (
                "re-kickoff must return the completed batch, not a new one "
                f"(first={batch_id} got={again.get('batch_id')})"
            )
            assert again.get("ok") is True
            assert again.get("batch_id") == batch_id, (
                "re-kickoff must return the completed batch, not a new one "
                f"(first={batch_id} got={again.get('batch_id')})"
            )
            drafts_after = client.get(
                f"/api/web/session/{token}/campaigns/{campaign_id}/drafts").json()
            assert len(drafts_after.get("drafts") or []) == len(draft_list), (
                "re-running generation must not duplicate drafts"
            )

            # ── Approval → state transitions ──
            resp = client.post(
                f"/api/web/session/{token}/drafts/{draft_list[0]['id']}/approve")
            assert resp.status_code == 200, resp.text
            approved = resp.json()
            assert approved.get("draft", {}).get("status") == "approved"

            drafts_check = client.get(
                f"/api/web/session/{token}/campaigns/{campaign_id}/drafts").json()
            statuses = {d.get("status") for d in (drafts_check.get("drafts") or [])}
            assert "approved" in statuses, "approval must persist on re-read"

            for draft in draft_list[1:]:
                r = client.post(
                    f"/api/web/session/{token}/drafts/{draft['id']}/approve")
                assert r.status_code == 200, r.text

            final = client.get(
                f"/api/web/session/{token}/campaigns/{campaign_id}/drafts").json()
            final_statuses = {d.get("status") for d in (final.get("drafts") or [])}
            assert final_statuses == {"approved"}, (
                "approving every draft must narrow the status set"
            )
            return
        finally:
            if campaign_id:
                try:
                    client.delete(
                        f"/api/web/session/{token}/campaigns/{campaign_id}")
                except Exception:
                    pass
            _tidy(discovery_id, job_id)