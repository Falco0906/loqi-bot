"""PR7 regression tests for Discovery context provenance persistence."""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

from services.discovery import store_discovery_plan
from services.job_engine.models import Job
from tests.test_knowledge_service import FakeSupabaseClient


def test_plan_and_context_provenance_are_written_in_one_metadata_update(monkeypatch):
    store = {
        "discoveries": [{
            "id": "discovery-1",
            "workspace_id": "workspace-a",
            "metadata": {},
        }],
    }
    monkeypatch.setattr("services.discovery.get_supabase_client", lambda: FakeSupabaseClient(store))

    provenance = {
        "query": "crm for advisory firms",
        "knowledge_item_ids": ["knowledge-1"],
        "knowledge_source_ids": ["source-1"],
        "strategic_update_ids": ["update-1"],
    }
    assert store_discovery_plan(
        "discovery-1",
        {"industries": ["advisory firms"], "messaging_angle": "implementation simplicity"},
        provenance,
    ) is True

    metadata = store["discoveries"][0]["metadata"]
    assert metadata["plan"]["industries"] == ["advisory firms"]
    assert metadata["context_provenance"] == provenance


def test_empty_context_still_persists_plan_without_fake_provenance(monkeypatch):
    store = {
        "discoveries": [{"id": "discovery-2", "workspace_id": "workspace-a", "metadata": {}}],
    }
    monkeypatch.setattr("services.discovery.get_supabase_client", lambda: FakeSupabaseClient(store))

    assert store_discovery_plan("discovery-2", {"industries": []}, {}) is True
    metadata = store["discoveries"][0]["metadata"]
    assert metadata["plan"] == {"industries": []}
    assert metadata["context_provenance"] == {}


def test_search_workflow_passes_provenance_to_discovery_plan_writer(monkeypatch):
    provenance = {
        "query": "advisory firms",
        "knowledge_item_ids": ["knowledge-1"],
        "knowledge_source_ids": ["source-1"],
        "strategic_update_ids": ["update-1"],
    }
    captured = []

    async def fake_context(owner_id, query):
        return {"provenance": provenance, "knowledge_icp": {}, "knowledge": {}, "strategic_observations": []}

    class Plan:
        def to_dict(self):
            return {"industries": ["advisory firms"]}

    def fake_search(service, target, plan, context, on_progress):
        assert context["provenance"] == provenance
        return {"ok": True, "leads": []}

    def fake_store(discovery_id, plan, context_provenance=None):
        captured.append((discovery_id, plan, context_provenance))
        return True

    monkeypatch.setattr("services.discovery_context.retrieve_discovery_context", fake_context)
    monkeypatch.setattr("services.discovery_plan.derive_discovery_plan", lambda query, existing_context=None: Plan())
    monkeypatch.setattr("workflow_dispatcher._search_with_progress", fake_search)
    monkeypatch.setattr("services.discovery.store_discovery_plan", fake_store)

    job = Job(user_id="owner-a", query="crm for advisory firms", discovery_id="discovery-1")
    result = asyncio.run(__import__("workflow_dispatcher").run_search_workflow(job, lambda *args: None))

    assert result["ok"] is True
    assert captured[0][0] == "discovery-1"
    assert captured[0][2] == provenance
