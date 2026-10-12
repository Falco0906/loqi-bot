"""Offline selected-workspace propagation through Discovery and strategy."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import workflow_dispatcher as dispatcher
import services.campaigns.service as campaigns
import services.discovery.context as context
import services.discovery.service as discovery
import services.knowledge.context_adapter as adapter
import services.workspace.access as access
from services.job_engine.manager import JobManager
from services.job_engine.models import Job
from services.knowledge.service import KnowledgeService
from services.strategic.service import StrategicIntelligenceService


@pytest.fixture
def scoped_readers(monkeypatch):
    reads = []
    def authorized(_client, actor, workspace):
        assert actor == "actor"
        if workspace != "selected": raise access.WorkspaceAccessDenied(workspace)
        return SimpleNamespace(workspace_id=workspace)

    class Repo:
        async def list_for_workspace(self, workspace):
            reads.append(workspace)
            return []

    monkeypatch.setattr(access, "resolve_workspace_context", authorized)
    monkeypatch.setattr("services.knowledge.service.KnowledgeItemRepository", Repo)
    monkeypatch.setattr("services.knowledge.service.KnowledgeSourceRepository", Repo)
    monkeypatch.setattr("services.strategic.service.StrategicUpdateRepository", Repo)
    return reads


@pytest.mark.asyncio
async def test_selected_discovery_scope_reaches_both_canonical_readers(scoped_readers, monkeypatch):
    async def no_default(*_args, **_kwargs):
        raise AssertionError("selected scope must not resolve the owner default")
    monkeypatch.setattr("services.workspace.state._async_workspace", no_default)
    result = await context.retrieve_discovery_context("actor", "founders", workspace_id="selected")
    assert scoped_readers == ["selected", "selected", "selected"]
    assert result["knowledge"]["items"] == []  # valid missing context
    assert result["strategic_observations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["knowledge", "strategic", "discovery"])
async def test_explicit_unauthorized_context_is_rejected(scoped_readers, reader):
    if reader == "knowledge": operation = adapter.retrieve_knowledge_context
    elif reader == "strategic": operation = StrategicIntelligenceService().list_updates
    else: operation = context.retrieve_discovery_context
    with pytest.raises(access.WorkspaceAccessDenied):
        await operation("actor", workspace_id="foreign")
    assert scoped_readers == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["knowledge", "discovery"])
async def test_explicit_workspace_without_actor_is_not_authorized(scoped_readers, reader):
    operation = adapter.retrieve_knowledge_context if reader == "knowledge" else context.retrieve_discovery_context
    with pytest.raises(access.WorkspaceAccessDenied):
        await operation("", workspace_id="selected")
    assert scoped_readers == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["knowledge", "strategic", "discovery"])
async def test_explicit_context_loading_failure_is_not_empty(scoped_readers, monkeypatch, reader):
    def unavailable(*_args): raise httpx.ReadTimeout("local membership read timeout")
    monkeypatch.setattr(access, "resolve_workspace_context", unavailable)
    if reader == "knowledge": operation = adapter.retrieve_knowledge_context
    elif reader == "strategic": operation = StrategicIntelligenceService().list_updates
    else: operation = context.retrieve_discovery_context
    with pytest.raises(httpx.ReadTimeout):
        await operation("actor", workspace_id="selected")
    assert scoped_readers == []


@pytest.mark.asyncio
async def test_legitimate_owner_only_readers_keep_default_behavior(scoped_readers, monkeypatch):
    monkeypatch.setattr("services.workspace.state._async_workspace", AsyncMock(return_value="default"))
    result = await KnowledgeService().get_knowledge_context("actor")
    assert result["workspace_id"] == "default"
    assert await StrategicIntelligenceService().list_updates("actor") == []
    assert scoped_readers == ["default", "default", "default"]


@pytest.mark.asyncio
async def test_repository_outage_not_disguised_as_missing_selected_knowledge(scoped_readers, monkeypatch):
    async def unavailable(*_args): raise httpx.ReadTimeout("local context read timeout")
    monkeypatch.setattr("services.knowledge.service.KnowledgeItemRepository.list_for_workspace", unavailable)
    with pytest.raises(httpx.ReadTimeout):
        await adapter.retrieve_knowledge_context("actor", workspace_id="selected")


@pytest.mark.asyncio
async def test_job_creation_retains_selected_workspace(monkeypatch):
    manager = JobManager()
    saved = []
    def save(job): saved.append(job); return job
    manager._storage = SimpleNamespace(create_job=save)
    manager._runner = SimpleNamespace(start_job=lambda *_args, **_kwargs: None)
    await manager.create_search_job("actor", "founders", discovery_id="discovery-1", workspace_id="selected")
    assert saved[0].workspace_id == "selected"
    assert Job.from_dict(saved[0].to_dict()).workspace_id == "selected"


@pytest.mark.asyncio
async def test_search_kickoff_forwards_request_workspace_to_job(monkeypatch):
    monkeypatch.setattr(discovery, "create_discovery", lambda *_args: {"id": "discovery-1"})
    create = AsyncMock(return_value={"job_id": "job-1"})
    monkeypatch.setattr(discovery.job_manager, "create_search_job", create)
    await discovery.create_search_run("actor", "founders", workspace_id="selected", initiation="manual")
    assert create.call_args.kwargs["workspace_id"] == "selected"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_job", [False, True])
async def test_worker_uses_selected_or_durable_discovery_scope(monkeypatch, legacy_job):
    load = lambda *_args, **kwargs: {"workspace_id": "selected"} if kwargs["strict"] else None
    monkeypatch.setattr(discovery, "get_discovery", load)
    retrieval = AsyncMock(return_value={})
    monkeypatch.setattr(context, "retrieve_discovery_context", retrieval)
    monkeypatch.setattr("services.discovery.plan.derive_discovery_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatcher, "_search_with_progress", lambda *_args: {"ok": True, "leads": []})
    result = await dispatcher.run_search_workflow(Job(user_id="actor", query="founders", discovery_id="discovery-1", workspace_id="" if legacy_job else "selected"), lambda *_args: None)
    assert result["ok"]
    assert retrieval.call_args.kwargs["workspace_id"] == "selected"


@pytest.mark.asyncio
async def test_worker_context_failure_never_searches_with_default(monkeypatch):
    monkeypatch.setattr(context, "retrieve_discovery_context", AsyncMock(side_effect=httpx.ReadTimeout("local timeout")))
    monkeypatch.setattr(dispatcher, "_search_with_progress", lambda *_args: pytest.fail("context failure must not search"))
    with pytest.raises(httpx.ReadTimeout):
        await dispatcher.run_search_workflow(Job(user_id="actor", query="founders", discovery_id="discovery-1", workspace_id="selected"), lambda *_args: None)


@pytest.mark.asyncio
async def test_old_job_missing_discovery_scope_never_uses_default(monkeypatch):
    monkeypatch.setattr(discovery, "get_discovery", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="workspace could not be loaded"):
        await dispatcher.run_search_workflow(Job(user_id="actor", query="founders", discovery_id="missing"), lambda *_args: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_campaign_worker_passes_authorized_workspace_and_stops_on_context_failure(monkeypatch, failure):
    reads = []
    def read(discovery_id, workspace_id, **kwargs):
        reads.append((discovery_id, workspace_id, kwargs))
        return {"metadata": {"plan": {"offering": "CRM"}}}
    monkeypatch.setattr(discovery, "get_discovery", read)
    retrieval = AsyncMock(return_value=adapter.KnowledgePromptContext())
    if failure: retrieval.side_effect = access.WorkspaceAccessDenied("selected")
    monkeypatch.setattr(adapter, "retrieve_knowledge_context", retrieval)
    monkeypatch.setattr(campaigns, "persist_strategy_job_meta", AsyncMock(return_value=True))
    monkeypatch.setattr("services.workspace.state.persist_campaign_update_awaited", AsyncMock(return_value=True))
    generate = lambda *_args: pytest.fail("unauthorized context must not generate") if failure else {"angle": "Conservative"}
    monkeypatch.setattr("services.intelligence.ai.generate_campaign_strategy", generate)
    result = await campaigns.run_strategy_job(Job(user_id="actor", workspace_id="selected", campaign_id="campaign-1", payload={"target": {"discovery_id": "discovery-1"}, "objective": "Meet buyers"}), None)
    assert reads == ([] if failure else [("discovery-1", "selected", {"strict": True})])
    assert retrieval.call_args.kwargs["workspace_id"] == "selected"
    assert result["ok"] is not failure


@pytest.mark.asyncio
async def test_campaign_missing_discovery_context_is_empty_but_load_error_propagates(monkeypatch):
    monkeypatch.setattr(discovery, "get_discovery", lambda *_args, **_kwargs: None)
    assert await campaigns.build_strategy_context({"discovery_id": "missing"}, workspace_id="selected") == {}
    def unavailable(*_args, **_kwargs): raise httpx.ReadTimeout("local context timeout")
    monkeypatch.setattr(discovery, "get_discovery", unavailable)
    with pytest.raises(httpx.ReadTimeout):
        await campaigns.build_strategy_context({"discovery_id": "discovery-1"}, workspace_id="selected")


def test_strict_discovery_reader_distinguishes_missing_row_and_failure(monkeypatch):
    class Query:
        fail = False
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def is_(self, *_args): return self
        def limit(self, *_args): return self
        def execute(self):
            if self.fail: raise httpx.ReadTimeout("local timeout")
            return SimpleNamespace(data=[])
    query = Query()
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: query))
    assert discovery.get_discovery("missing", "selected", strict=True) is None
    query.fail = True
    with pytest.raises(httpx.ReadTimeout): discovery.get_discovery("missing", "selected", strict=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_campaign", [False, True])
async def test_old_campaign_job_recovers_campaign_scope_not_default(monkeypatch, has_campaign):
    class CampaignRepo:
        async def get(self, campaign_id):
            assert campaign_id == "campaign-1"
            return SimpleNamespace(workspace_id="selected") if has_campaign else None
    monkeypatch.setattr("services.persistence.launch.CampaignRepository", CampaignRepo)
    retrieval = AsyncMock(return_value=adapter.KnowledgePromptContext())
    monkeypatch.setattr(adapter, "retrieve_knowledge_context", retrieval)
    monkeypatch.setattr(campaigns, "persist_strategy_job_meta", AsyncMock(return_value=True))
    monkeypatch.setattr("services.workspace.state.persist_campaign_update_awaited", AsyncMock(return_value=True))
    monkeypatch.setattr("services.intelligence.ai.generate_campaign_strategy", lambda *_args: {})
    result = await campaigns.run_strategy_job(Job(user_id="actor", campaign_id="campaign-1", payload={"target": {}, "objective": "Meet buyers"}), None)
    assert result["ok"] is has_campaign
    if has_campaign: assert retrieval.call_args.kwargs["workspace_id"] == "selected"
    else: retrieval.assert_not_awaited()
