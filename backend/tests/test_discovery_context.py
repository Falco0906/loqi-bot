"""PR7 — Knowledge/Strategic context integration for Discovery and ICP."""

from __future__ import annotations

import asyncio
import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

import services.icp_extractor as icp_extractor
import services.lead_provider as lead_provider
from services.commercial_qualifier import score_lead
from services.discovery_context import retrieve_discovery_context
from services.persistence.launch.models import WorkspaceLead
from services.persistence.launch.repositories import WorkspaceLeadRepository
from services.workspace_state import _qualification_metadata


def _knowledge_context():
    return type("Context", (), {
        "to_dict": lambda self: {
            "query": "crm for advisory firms",
            "items": [{
                "id": "knowledge-1",
                "category": "icp",
                "title": "Primary ICP",
                "summary": "Boutique advisory firms",
                "content": {
                    "target_industries": ["advisory firms"],
                    "target_roles": ["Managing Partner"],
                    "exclusions": ["enterprise bank"],
                    "pain_points": ["manual follow-up"],
                },
                "source_type": "user_input",
                "source_id": "source-1",
            }],
            "sources": [{"id": "source-1"}],
            "item_ids": ["knowledge-1"],
            "source_ids": ["source-1"],
        },
    })()


@pytest.fixture
def context(monkeypatch):
    async def fake_knowledge(owner_id, **kwargs):
        assert owner_id == "owner-a"
        return _knowledge_context()

    class Strategic:
        async def list_updates(self, owner_id):
            assert owner_id == "owner-a"
            return [{
                "id": "update-1",
                "update_type": "objection",
                "title": "Recurring implementation objection",
                "observation": "Implementation was mentioned repeatedly.",
                "interpretation": "This is an observation, not an ICP rule.",
                "evidence": [{"signal_id": "signal-1"}],
            }]

    monkeypatch.setattr("services.discovery_context.retrieve_knowledge_context", fake_knowledge)
    monkeypatch.setattr("services.strategic.service.StrategicIntelligenceService", Strategic)


class TestDiscoveryContext:
    def test_context_is_bounded_at_the_existing_adapter_boundary(self, context, monkeypatch):
        captured = []

        async def fake_knowledge(owner_id, **kwargs):
            captured.append((owner_id, kwargs))
            return _knowledge_context()

        monkeypatch.setattr("services.discovery_context.retrieve_knowledge_context", fake_knowledge)
        result = asyncio.run(retrieve_discovery_context("owner-a", "crm advisory"))

        assert captured[0][1]["categories"] == ["company", "icp", "messaging"]
        assert captured[0][1]["limit"] == 8
        assert result["provenance"]["knowledge_item_ids"] == ["knowledge-1"]
        assert result["provenance"]["strategic_update_ids"] == ["update-1"]

    def test_owner_isolation_is_preserved_by_retrieval(self, monkeypatch):
        seen = []

        async def fake_knowledge(owner_id, **kwargs):
            seen.append(owner_id)
            context = _knowledge_context()
            context.to_dict = lambda: {
                "items": [{"id": f"{owner_id}-knowledge", "category": "icp", "content": {}}],
                "sources": [], "item_ids": [f"{owner_id}-knowledge"], "source_ids": [],
            }
            return context

        class EmptyStrategic:
            async def list_updates(self, owner_id):
                return []

        monkeypatch.setattr("services.discovery_context.retrieve_knowledge_context", fake_knowledge)
        monkeypatch.setattr("services.strategic.service.StrategicIntelligenceService", EmptyStrategic)
        a = asyncio.run(retrieve_discovery_context("owner-a"))
        b = asyncio.run(retrieve_discovery_context("owner-b"))

        assert seen == ["owner-a", "owner-b"]
        assert a["provenance"]["knowledge_item_ids"] == ["owner-a-knowledge"]
        assert b["provenance"]["knowledge_item_ids"] == ["owner-b-knowledge"]

    def test_retrieval_failure_is_fail_soft(self, monkeypatch):
        async def fail(*args, **kwargs):
            raise RuntimeError("unavailable")

        class EmptyStrategic:
            async def list_updates(self, owner_id):
                raise RuntimeError("unavailable")

        monkeypatch.setattr("services.discovery_context.retrieve_knowledge_context", fail)
        monkeypatch.setattr("services.strategic.service.StrategicIntelligenceService", EmptyStrategic)
        result = asyncio.run(retrieve_discovery_context("owner-a", "query"))

        assert result["knowledge"]["items"] == []
        assert result["strategic_observations"] == []
        assert result["provenance"]["query"] == "query"


class TestDiscoveryPlanAndQualification:
    def test_deterministic_icp_uses_knowledge_without_replacing_user_input(self, monkeypatch, context):
        monkeypatch.setattr(icp_extractor, "OPENAI_API_KEY", "")
        from services.discovery_plan import derive_discovery_plan

        plan = derive_discovery_plan(
            "crm for startups",
            existing_context=asyncio.run(retrieve_discovery_context("owner-a")),
        )

        assert "startups" in [value.lower() for value in plan.industries]
        assert "advisory firms" in [value.lower() for value in plan.industries]
        assert "Managing Partner" in plan.decision_maker_roles

    def test_qualification_uses_icp_context_and_preserves_provenance(self, context):
        lead = {
            "name": "Jordan",
            "title": "Managing Partner",
            "company": "Advisory Firm",
        }
        icp = {
            "buyer_roles": ["Managing Partner"],
            "buyer_industries": ["advisory firms"],
            "excluded_roles": [],
        }
        discovery_context = asyncio.run(retrieve_discovery_context("owner-a"))
        result = score_lead(lead, icp, context=discovery_context)

        assert result["relevance_score"] > 0
        assert result["context_provenance"]["knowledge_item_ids"] == ["knowledge-1"]
        assert result["strategic_observation_ids"] == ["update-1"]
        assert result["lead_name"] == "Jordan"

    def test_evidence_sources_are_separate_and_numeric_scores_are_unchanged(self, context):
        lead = {
            "name": "Jordan",
            "title": "Managing Partner",
            "company": "Advisory Firm",
        }
        icp = {
            "buyer_roles": ["Managing Partner"],
            "buyer_industries": ["advisory firms"],
            "excluded_roles": [],
        }
        before = score_lead(lead, icp)
        after = score_lead(lead, icp, context=asyncio.run(retrieve_discovery_context("owner-a")))

        for field in ("buyer_score", "company_score", "authority_score", "relevance_score", "drift_penalty", "final_score"):
            assert after[field] == before[field]
        assert any(item["field"] == "title" for item in after["prospect_evidence"])
        assert after["knowledge_context"]["guidance_only"] is True
        assert after["strategic_observations"]["guidance_only"] is True
        assert after["strategic_observations"]["observations"][0]["observation_only"] is True

    def test_provider_contract_unchanged_and_context_reaches_qualification(self, monkeypatch, context):
        captured = {}

        class Provider:
            def search_leads(self, *, icp, search_expansion, limit):
                captured["icp"] = icp
                return {"ok": True, "provider": "test", "leads": [{
                    "id": "lead-1", "name": "Jordan", "title": "Managing Partner",
                    "company": "Advisory Firm",
                }]}

        monkeypatch.setattr(lead_provider, "get_provider", lambda: Provider())
        monkeypatch.setattr(icp_extractor, "OPENAI_API_KEY", "")
        monkeypatch.setattr("services.search_expansion.expand_search_intent", lambda service, target, icp: {"keywords": ["Managing Partner advisory firms"]})
        monkeypatch.setattr(lead_provider, "_filter_and_rank_leads", lambda leads, icp, context=None: (leads, {"total_found": 1, "excluded_count": 0, "scored_count": 1, "average_score": 1, "excluded_reasons": {}, "drift_detected": 0}))
        monkeypatch.setattr(lead_provider, "_filter_and_rank_leads_soft", lead_provider._filter_and_rank_leads)
        discovery_context = asyncio.run(retrieve_discovery_context("owner-a"))
        result = lead_provider.search_with_expansion(
            "crm", "startups", context=discovery_context,
        )

        assert result["ok"] is True
        assert captured["icp"]["buyer_industries"]
        assert result["context_provenance"]["knowledge_item_ids"] == ["knowledge-1"]

    def test_qualification_metadata_round_trips_through_existing_workspace_lead_storage(self):
        lead = {
            "commercial_score_breakdown": {
                "context_provenance": {"knowledge_item_ids": ["knowledge-1"]},
                "strategic_observation_ids": ["update-1"],
            }
        }
        entity = WorkspaceLead(
            workspace_id="workspace-a",
            lead_id="lead-1",
            metadata=_qualification_metadata(lead),
        )
        repo = WorkspaceLeadRepository()
        restored = repo._from_row(repo._to_row(entity))
        assert restored.metadata["qualification"]["context_provenance"]["knowledge_item_ids"] == ["knowledge-1"]
        assert restored.metadata["qualification"]["strategic_observation_ids"] == ["update-1"]
