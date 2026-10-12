"""Campaign event-loop, worker error, and explicit strategy boundaries."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.campaigns import api, service
from services.workspace import state


@pytest.mark.asyncio
async def test_compatibility_worker_exception_preserves_original_context():
    original = RuntimeError("worker operation failed")
    async def fail(): raise original
    with pytest.raises(RuntimeError) as caught:
        state._run_sync(fail())
    assert caught.value is original
    assert "fail" in [frame.name for frame in caught.traceback]


@pytest.mark.asyncio
async def test_bridge_waits_for_actual_outcome_instead_of_returning_none_at_deadline():
    async def finish():
        await asyncio.sleep(0.02)
        return "completed"
    assert state._run_sync(finish(), timeout=0.001) == "completed"
    assert state._compatibility_workers._max_workers == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["campaign", "workspace", "drafts"])
async def test_strict_campaign_reads_propagate_failures_not_empty_state(monkeypatch, reader):
    failure = RuntimeError("canonical projection failed")
    monkeypatch.setattr(state, "get_supabase_client", lambda: object())
    monkeypatch.setattr(state, "_load_canonical_state", AsyncMock(side_effect=failure))
    monkeypatch.setattr(state, "_async_workspace", AsyncMock(return_value="workspace"))
    monkeypatch.setattr(state, "DraftRepository", lambda: SimpleNamespace(list_for_workspace=AsyncMock(side_effect=failure)))
    operations = {
        "campaign": lambda: state.load_campaign_state("actor", "campaign", workspace_id="workspace", strict=True),
        "workspace": lambda: state.load_workspace_state("actor", workspace_id="workspace", strict=True),
        "drafts": lambda: state.load_drafts_only("actor", workspace_id="workspace", strict=True),
    }
    with pytest.raises(RuntimeError) as caught:
        await asyncio.to_thread(operations[reader])
    assert caught.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["summary", "detail", "progress", "update"])
async def test_campaign_async_requests_offload_sync_loaders(monkeypatch, endpoint):
    main_thread = threading.get_ident()
    reads = []
    def campaigns(_actor, **kwargs):
        assert threading.get_ident() != main_thread
        assert kwargs["workspace_id"] == "selected"
        reads.append("campaigns")
        return [{"id": "campaign", "name": "Selected", "status": "planning", "leads": [], "lead_count": 0}]
    def drafts(_actor, **kwargs):
        assert threading.get_ident() != main_thread
        assert kwargs["strict"] is True
        reads.append("drafts")
        return []
    async def authorize(_request): return "actor", "token", "selected"
    monkeypatch.setattr(api, "_authorized_workspace", authorize)
    monkeypatch.setattr(api, "load_campaigns", campaigns)
    monkeypatch.setattr(service, "load_campaigns", campaigns)
    monkeypatch.setattr(api, "load_drafts_only", drafts)
    monkeypatch.setattr(api, "record_campaign_open", lambda *_args: None)
    operations = {
        "summary": lambda: api.campaign_summary("_", SimpleNamespace()),
        "detail": lambda: api.get_campaign("_", "campaign", SimpleNamespace()),
        "progress": lambda: api.campaign_launch_progress("_", "campaign", SimpleNamespace()),
        "update": lambda: service.update_campaign("token", "actor", "selected", "campaign", {}),
    }
    await operations[endpoint]()
    assert reads


@pytest.mark.asyncio
async def test_explicit_strategy_action_queues_existing_authorized_workflow(monkeypatch):
    async def authorize(_request): return "actor", "token", "selected"
    monkeypatch.setattr(api, "_authorized_workspace", authorize)
    monkeypatch.setattr(service, "load_campaigns", lambda _actor, **kwargs: [{"id": "campaign", "objective": "Meet buyers", "leads": [{"id": "saved"}]}])
    enqueue = AsyncMock(return_value=("strategy-job", "queued"))
    monkeypatch.setattr(service, "enqueue_strategy_job", enqueue)
    response = await api.generate_campaign_strategy("_", "campaign", api.RegenerateStrategyRequest(force=False), SimpleNamespace())
    assert response == {"ok": True, "job_id": "strategy-job", "status": "queued"}
    assert enqueue.await_args.kwargs == {"workspace_id": "selected"}


@pytest.mark.asyncio
async def test_explicit_strategy_reuses_stored_data_without_regenerating(monkeypatch):
    strategy = {"objective": "Meet buyers", "messaging_angle": "Stored guidance"}
    monkeypatch.setattr(service, "load_campaigns", lambda *_args, **_kwargs: [{"id": "campaign", "objective": "Meet buyers", "leads": [{"id": "saved"}], "strategy": strategy}])
    enqueue = AsyncMock()
    monkeypatch.setattr(service, "enqueue_strategy_job", enqueue)
    response = await service.start_strategy_generation("token", "actor", "selected", "campaign", force=False)
    assert response["reused"] and response["strategy"] == strategy
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_strategy_worker_failure_remains_terminal_and_logged(monkeypatch, caplog):
    from services.job_engine import Job
    monkeypatch.setattr(service, "persist_strategy_job_meta", AsyncMock(return_value=True))
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", AsyncMock(side_effect=RuntimeError("context read failed")))
    job = Job(user_id="actor", campaign_id="campaign", workspace_id="selected", payload={"objective": "Meet buyers", "target": {}})
    result = await service.run_strategy_job(job, None)
    assert result == {"ok": False, "error": "context read failed"}
    assert service.persist_strategy_job_meta.await_args.args[2]["status"] == "failed"
    assert "strategy_job_failed" in caplog.text


@pytest.mark.asyncio
async def test_metadata_read_failure_is_not_reported_as_no_job(monkeypatch):
    monkeypatch.setattr(state, "load_campaign_state", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("metadata unavailable")))
    with pytest.raises(RuntimeError, match="metadata unavailable"):
        await service.load_strategy_job_meta("actor", "campaign", workspace_id="selected")


@pytest.mark.asyncio
async def test_strategy_progress_persistence_failure_cannot_report_success(monkeypatch):
    from services.job_engine import Job
    monkeypatch.setattr(service, "persist_strategy_job_meta", AsyncMock(return_value=False))
    knowledge = AsyncMock(side_effect=AssertionError("Must stop before model context work"))
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", knowledge)
    result = await service.run_strategy_job(Job(user_id="actor", workspace_id="selected", campaign_id="campaign", payload={}), None)
    assert result == {"ok": False, "error": "Strategy running status could not be persisted"}
    knowledge.assert_not_awaited()
