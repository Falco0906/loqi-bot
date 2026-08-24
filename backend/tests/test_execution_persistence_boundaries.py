"""Durable success-boundary regressions for core execution flows.

These tests deliberately exercise the production orchestration boundaries,
rather than treating a provider response as proof that the product operation
succeeded.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_search_job_is_not_created_when_discovery_insert_fails(monkeypatch):
    import main as main_module
    import services.discovery as discovery
    import services.workspace_state as workspace_state

    monkeypatch.setattr(workspace_state, "ensure_workspace", lambda _owner: "workspace-1")
    monkeypatch.setattr(discovery, "create_discovery", lambda *_args, **_kwargs: None)
    create_job = AsyncMock()
    monkeypatch.setattr(main_module.job_manager, "create_search_job", create_job)

    with pytest.raises(HTTPException) as error:
        await main_module._create_search_run("owner-1", "cafe owners")

    assert error.value.status_code == 503
    create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_finalization_fails_when_canonical_lead_persistence_fails(monkeypatch):
    import services.discovery as discovery

    row = {"id": "discovery-1", "workspace_id": "workspace-1", "status": "searching", "query": "cafe owners"}

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            return [{"id": "provider-lead-1", "company": "Cafe One"}]

    marked: list[tuple[str, str, str]] = []
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    monkeypatch.setattr("services.workspace_state._normalize_lead", AsyncMock(return_value=None))
    monkeypatch.setattr(discovery, "mark_discovery_status", lambda *args: marked.append(args))

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="cafe owners")
    )

    assert completed is False
    assert marked and marked[-1][1] == "failed"
    assert "canonical workspace lead" in marked[-1][2]


@pytest.mark.asyncio
async def test_strategy_enqueue_does_not_start_without_durable_job_metadata(monkeypatch):
    import main as main_module

    main_module.STRATEGY_JOBS.clear()
    monkeypatch.setattr(main_module, "_persist_strategy_job_meta", AsyncMock(return_value=False))
    runner = AsyncMock()
    monkeypatch.setattr(main_module, "_run_strategy_job", runner)

    with pytest.raises(HTTPException) as error:
        await main_module._enqueue_strategy_job(
            "session-1", "owner-1", "campaign-1", "Goal", {}, workspace_id="workspace-1",
        )

    assert error.value.status_code == 503
    runner.assert_not_called()
    assert not main_module.STRATEGY_JOBS
