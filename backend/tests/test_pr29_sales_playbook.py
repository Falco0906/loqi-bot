"""PR2.9: Sales Intelligence Upgrade regression tests.

Covers:
  - the Sales Playbook JSON contract parsing (strategy generation)
  - the fallback playbook shape when OpenAI fails
  - evidence-first draft generation rules + playbook injection
  - guided retry of per-lead draft generation
  - idempotent draft kickoff after a completed batch (no duplicate runs)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import main as main_module
import services.ai as ai_module
from main import (
    _create_batch_job,
    _run_draft_with_retry,
    batch_jobs,
)

from tests.test_draft_generation_recovery import _fake_owner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def fake_persist(monkeypatch):
    """Persist campaign updates in-memory; assertable from the test."""
    import services.workspace_state as workspace_state
    updates: list[tuple[str, str, dict]] = []

    def fake(user_id: str, campaign_id: str, payload: dict) -> bool:
        updates.append((user_id, campaign_id, payload))
        return True

    async def fake_awaited(user_id: str, campaign_id: str, payload: dict) -> bool:
        updates.append((user_id, campaign_id, payload))
        return True

    monkeypatch.setattr(workspace_state, "persist_campaign_update", fake)
    monkeypatch.setattr(
        workspace_state, "persist_campaign_update_awaited", fake_awaited)
    return updates


def _campaign(**overrides) -> dict:
    campaign = {
        "id": str(uuid.uuid4()),
        "name": "Test Campaign",
        "status": "active",
        "lead_count": 1,
        "leads": [{"id": "lead-1", "company": "Acme"}],
    }
    campaign.update(overrides)
    return campaign


def _playbook_payload() -> dict:
    """A complete playbook-shaped model response."""
    return {
        "campaign_objective": "Sell AI automations to cafe owners",
        "icp": "Cafe owners with 3-20 locations",
        "channel": "email",
        "market_summary": "Independent cafes, mostly 1-5 outlets, legacy ordering flows",
        "market_attractiveness": "Observed hiring and expansion signals across companies",
        "market_common_patterns": ["No online ordering", "Weekend-only kitchen staff"],
        "market_technologies": ["Toast POS"],
        "market_maturity": "Early adopter stage",
        "observed_patterns": ["Recent openings"],
        "buying_signals": ["Hiring front of house"],
        "pain_points": ["No online ordering"],
        "pain_prioritization": [
            {"pain": "No online ordering", "why": "Observed across 12 of 14 researched companies"},
            {"pain": "Staff scheduling", "why": "Weekend staffing gaps"},
        ],
        "personas": [
            {
                "persona": "Cafe Owner",
                "priorities": ["Higher table turnover", "Less manual work"],
                "incentives": ["Free weekends"],
                "kpis": ["Revenue per seat"],
                "fears": ["Costly tech"],
                "likely_objections": ["Already have a POS"],
                "authority_level": "Decision maker",
            }
        ],
        "value_proposition": "Automate order follow-up",
        "positioning": "The fix, not the feature",
        "differentiators": ["Runs on their existing POS"],
        "proof_points": ["Seen on Toast", "Expanding locations"],
        "why_now": "Seasonal order volume is peaking",
        "outreach_strategy": {
            "first_touch_goal": "Open on the ordering gap",
            "first_touch_cta": "15-min call",
            "follow_up_strategy": "One value-led follow-up",
            "personalization_opportunities": ["Name their POS", "Reference recent opening"],
            "topics_to_avoid": ["Franchise talk"],
        },
        "messaging_angles": ["Angle A", "Angle B"],
        "objection_handling": ["Objection: cost, Response: ROI"],
        "outreach_sequence": ["Intro", "Follow-up"],
        "personalization": "Reference their ordering flow",
        "cta": "15-min call",
        "success_metrics": ["Reply rate"],
        "risks": ["Seasonality"],
        "confidence": "Medium — driven by evidence from 14 researched companies",
        "tone": "direct",
        "persona": "Loqi operator",
        "offer": {"type": "call", "detail": "15-min"},
    }


FAKE_PLAN = {
    "discovery_plan": {
        "offering": "AI automations",
        "primary_services": ["AI Automation"],
        "industries": ["cafes"],
        "decision_maker_roles": ["Cafe Owner", "Operations Manager"],
        "negative_keywords": ["franchise chain"],
        "pain_points": ["No online ordering", "Staff scheduling"],
        "buying_signals": ["Recently opened second location"],
        "technologies": ["Toast POS"],
        "messaging_angle": "Relief first",
        "target_list_segment": "3-20 locations",
    },
    "market_research": {
        "companies": [
            {"company": "Daily Grind Cafe", "company_industry": "Restaurant", "company_city": "Austin"},
            {"company": "Blue Cup Coffee", "company_industry": "Restaurant"},
        ],
        "observed_pain_points": ["No online ordering"],
        "observed_buying_signals": ["Expanding locations"],
        "industry_distribution": {"Restaurant": 2},
    },
}

PLAYBOOK_KEY_GROUPS = {
    "market": ["market_summary", "market_attractiveness", "market_common_patterns",
               "market_technologies", "market_maturity"],
    "pain": ["pain_points", "pain_prioritization"],
    "personas": ["personas"],
    "positioning": ["value_proposition", "positioning", "differentiators",
                    "proof_points", "why_now"],
    "outreach": ["outreach_strategy", "messaging_angles", "objection_handling",
                 "outreach_sequence", "cta"],
    "confidence": ["confidence"],
}


@pytest.fixture(autouse=True)
def _clean_stores():
    batch_jobs.clear()
    yield
    batch_jobs.clear()


class TestStrategyPlaybookContract:
    def test_new_playbook_keys_are_extracted(self, monkeypatch):
        """The generator must surface the full playbook keys from the model
        response, preserving structures (object lists, nested dict)."""
        captured: dict = {}

        def _fake_openai(system_text: str, user_text: str) -> str:
            captured["system"] = system_text
            captured["user"] = user_text
            return json.dumps(_playbook_payload())

        monkeypatch.setattr(ai_module, "_send_openai_request", _fake_openai)
        strategy = ai_module.generate_campaign_strategy("Sell AI to cafes", FAKE_PLAN)

        for group in ("market", "pain", "personas", "positioning", "outreach", "confidence"):
            for key in PLAYBOOK_KEY_GROUPS[group]:
                assert key in strategy, f"missing playbook key {key}"

        assert strategy["pain_prioritization"][0]["pain"] == "No online ordering"
        assert strategy["pain_prioritization"][0]["why"].startswith("Observed")
        assert strategy["personas"][0]["authority_level"] == "Decision maker"
        assert strategy["outreach_strategy"]["first_touch_cta"] == "15-min call"
        assert strategy["market_attractiveness"]
        assert strategy["differentiators"]
        assert strategy["proof_points"]
        assert strategy["why_now"]

    def test_strategy_prompt_demands_evidence(self, monkeypatch):
        captured: dict = {}

        def _fake_openai(system_text: str, user_text: str) -> str:
            captured["system"] = system_text
            return json.dumps(_playbook_payload())

        monkeypatch.setattr(ai_module, "_send_openai_request", _fake_openai)
        ai_module.generate_campaign_strategy("Sell AI to cafes", FAKE_PLAN)

        sys = captured["system"]
        assert "pain_prioritization" in sys
        assert "personas" in sys
        assert "outreach_strategy" in sys
        assert "why this market" in sys.lower()
        # the generic-filler ban list itself must be present
        assert "improve efficiency" in sys
        assert "modernize operations" in sys
        assert sys.index("improve efficiency") > sys.index("Never use"), (
            "generic filler must only appear inside the ban rule"
        )

    def test_fallback_playbook_keeps_shape_when_openai_fails(self):
        """Fallback (no LLM) must still yield the full playbook shape with
        grounded, honest content."""
        strategy = ai_module._fallback_playbook("Sell AI to cafes", FAKE_PLAN)
        for key in ("market_summary", "market_attractiveness", "market_common_patterns",
                    "market_technologies", "market_maturity", "pain_prioritization",
                    "personas", "differentiators", "proof_points", "why_now",
                    "outreach_strategy", "confidence"):
            assert key in strategy, f"fallback missing {key}"
        assert strategy["confidence"].startswith("Low")
        assert isinstance(strategy["pain_prioritization"], list)
        assert isinstance(strategy["personas"], list)
        assert isinstance(strategy["outreach_strategy"], dict)
        assert "cafe" in str(strategy["market_summary"]).lower(), (
            "fallback market summary must be grounded in the plan")


class TestDraftGroundedGeneration:
    def _capture(self, monkeypatch):
        captured: dict = {}

        def fake_openai(system_text: str, user_text: str) -> str:
            captured["system"] = system_text
            captured["user"] = user_text
            return json.dumps({"subject": "Ordering flow", "body": "Hi Sarah"})

        monkeypatch.setattr(ai_module, "_send_openai_request", fake_openai)
        return captured

    def test_prompt_demands_evidence_first(self, monkeypatch):
        captured = self._capture(monkeypatch)
        ai_module.generate_outreach_email(
            {"name": "Sarah", "company": "Acme", "title": "Owner"},
            company_intelligence={"company_summary": "Acme runs Toast"},
            lead_intelligence={"buying_stage": "Active"},
            strategy={"icp": "Cafe owners", "messaging_angle": "Relief first"},
        )
        sys = captured["system"]
        assert "WHY THIS COMPANY FIRST" in sys
        assert "hope this finds you well" in sys
        assert "improve efficiency" in sys

    def test_playbook_block_is_injected_when_strategy_passed(self, monkeypatch):
        captured = self._capture(monkeypatch)
        ai_module.generate_outreach_email(
            {"name": "Sarah", "company": "Acme"},
            strategy={"icp": "Cafe owners", "messaging_angle": "Relief first",
                      "confidence": "Medium + why"},
        )
        assert "CAMPAIGN SALES PLAYBOOK" in captured["user"]
        assert "Cafe owners" in captured["user"]

    def test_no_playbook_block_without_strategy(self, monkeypatch):
        captured = self._capture(monkeypatch)
        ai_module.generate_outreach_email({"name": "Sarah", "company": "Acme"})
        assert "CAMPAIGN SALES PLAYBOOK" not in captured["user"]

    def test_no_fabricated_pain_points_when_lead_has_none(self, monkeypatch):
        """PR3.1 Part D: absent pain points must never be invented in the prompt."""
        captured = self._capture(monkeypatch)
        ai_module.generate_outreach_email({"name": "Sarah", "company": "Acme"})
        user = captured["user"]
        assert "manual outbound, low reply rates, poor personalization" not in user
        assert "do not invent any" in user

    def test_draft_response_is_passed_through(self, monkeypatch):
        captured = self._capture(monkeypatch)
        email = ai_module.generate_outreach_email({"name": "Sarah"})
        assert email == {"subject": "Ordering flow", "body": "Hi Sarah"}


class TestDraftBatchIdempotency:
    async def test_completed_generation_returns_same_batch_without_relaunch(
        self, monkeypatch,
    ):
        """A client retry that lands after the batch finished must NOT start a
        second batch — it gets the completed batch_id back."""
        campaign = _campaign()
        campaign["generation"] = {
            "batch_id": "batch-1",
            "total": campaign["lead_count"],
            "completed": campaign["lead_count"],
            "status": "completed",
            "started_at": _now(),
            "finished_at": _now(),
        }
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(main_module, "_workspace_campaigns",
                            lambda uid, tok="": [campaign])
        launched: list = []
        monkeypatch.setattr(main_module, "_launch_batch_task",
                            lambda *args, **kwargs: launched.append(args))

        result = await main_module.generate_campaign_drafts(
            "token", campaign["id"], MagicMock())

        assert result["ok"] is True
        assert result["batch_id"] == "batch-1"
        assert launched == [], "must not start a second batch for a completed generation"

    async def test_completed_generation_without_drafts_still_relaunches(
        self, monkeypatch, fake_persist,
    ):
        """Only an actually-completed generation short-circuits; a failed one
        (interrupted, no drafts) must be allowed to run again."""
        campaign = _campaign()
        campaign["generation"] = {
            "batch_id": "batch-old",
            "total": campaign["lead_count"],
            "completed": 0,
            "status": "failed",
            "error": "interrupted",
            "started_at": _now(),
        }
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(main_module, "_workspace_campaigns",
                            lambda uid, tok="": [campaign])
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])
        launched: list = []
        monkeypatch.setattr(main_module, "_launch_batch_task",
                            lambda *args, **kwargs: launched.append(args))

        result = await main_module.generate_campaign_drafts(
            "token", campaign["id"], MagicMock())

        assert result["ok"] is True
        assert len(launched) == 1, "failed generations must be allowed to retry"
        assert result["batch_id"] != "batch-old"