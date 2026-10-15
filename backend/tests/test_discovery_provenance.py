"""PR7 regression tests for Discovery context provenance persistence."""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

from services.discovery.service import store_discovery_plan
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
    monkeypatch.setattr("services.discovery.service.get_supabase_client", lambda: FakeSupabaseClient(store))

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
    monkeypatch.setattr("services.discovery.service.get_supabase_client", lambda: FakeSupabaseClient(store))

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

    async def fake_context(owner_id, query, *, workspace_id):
        assert owner_id == "owner-a"
        assert workspace_id == "workspace-a"
        return {"provenance": provenance, "knowledge_icp": {}, "knowledge": {}, "strategic_observations": []}

    class WorkspaceLeads:
        async def list_for_workspace(self, workspace_id):
            assert workspace_id == "workspace-a"
            return []

    def authorize(_client, actor, workspace):
        assert (actor, workspace) == ("owner-a", "workspace-a")
        return SimpleNamespace(workspace_id=workspace)

    def forbid_provider(*_args, **_kwargs):
        raise AssertionError("Saved-workspace search must not source provider leads")

    def fake_store(discovery_id, plan, context_provenance=None):
        captured.append((discovery_id, plan, context_provenance))
        return True

    monkeypatch.setattr("services.discovery.context.retrieve_discovery_context", fake_context)
    monkeypatch.setattr("services.workspace.access.resolve_workspace_context", authorize)
    monkeypatch.setattr("services.leads.service.WorkspaceLeadRepository", WorkspaceLeads)
    monkeypatch.setattr("services.discovery.service.get_discovery", lambda *_a, **_k: {
        "id": "discovery-1", "workspace_id": "workspace-a", "created_by": "owner-a", "metadata": {}})
    monkeypatch.setattr("services.discovery.service._merge_metadata", lambda *_a: True)
    monkeypatch.setattr("services.job_engine.storage.JobStorage.store_search_results", lambda *_a: True)
    monkeypatch.setattr("workflow_dispatcher._search_with_progress", forbid_provider)
    monkeypatch.setattr("services.discovery.service.store_discovery_plan", fake_store)

    job = Job(user_id="owner-a", workspace_id="workspace-a", query="advisory firms", discovery_id="discovery-1",
              payload={"search_scope": "workspace"})
    result = asyncio.run(__import__("workflow_dispatcher").run_search_workflow(job, lambda *args: None))

    assert result["ok"] is True
    assert captured[0][0] == "discovery-1"
    assert captured[0][1]["interpretation_mode"] == "prospect_search"
    assert captured[0][1]["offering"] == captured[0][1]["messaging_angle"] == ""
    assert captured[0][2] == provenance
