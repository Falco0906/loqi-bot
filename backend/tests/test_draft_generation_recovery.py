"""Durable draft-batch status and restart recovery contracts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import pytest
from types import SimpleNamespace

from services.campaigns import api as campaigns_api
from services.drafts import api as drafts_api
import services.drafts.service as drafts
from services.job_engine.models import BatchItem, BatchItemStatus, Job, JobStatus
from services.knowledge.context_adapter import KnowledgePromptContext
from services.persistence.launch import CampaignRepository


@pytest.fixture(autouse=True)
def valid_empty_workspace_knowledge(monkeypatch):
    monkeypatch.setattr(drafts, "_recover_batch_draft", lambda *_args: asyncio.sleep(0, result=None))
    async def context(*_args, **kwargs):
        assert kwargs["workspace_id"] == "workspace-1"
        return KnowledgePromptContext()
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", context)


def _job(status: JobStatus = JobStatus.RUNNING) -> Job:
    return Job(
        id="batch-1", user_id="owner-1", type="draft_batch", status=status,
        workspace_id="workspace-1", campaign_id="campaign-1",
        payload={"session_token": "token", "total": 2},
    )


def _item(position: int, status: BatchItemStatus, draft_id: str = "") -> BatchItem:
    return BatchItem(
        id=f"item-{position}", job_id="batch-1", workspace_id="workspace-1",
        campaign_id="campaign-1", position=position,
        lead_snapshot={"id": f"lead-{position}", "name": f"Lead {position}"},
        idempotency_key=f"{position}:lead-{position}", status=status, draft_id=draft_id,
    )


async def test_durable_batch_status_preserves_progress_shape(monkeypatch):
    job = _job()
    items = [_item(0, BatchItemStatus.COMPLETED, "draft-0"), _item(1, BatchItemStatus.GENERATING)]

    class Storage:
        def get_job(self, job_id, **_kwargs):
            return job if job_id == "batch-1" else None

        def list_batch_items(self, *_args, **_kwargs):
            return items

    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    status = await drafts.draft_batch_status("owner-1", "workspace-1", "batch-1")

    assert status == {
        "status": "processing", "total": 2, "completed": 1,
        "current_index": 1, "current_name": "Lead 1", "drafts": [],
        "error": None, "campaign_id": "campaign-1", "batch_id": "batch-1",
        "started_at": job.created_at.isoformat(),
    }


async def test_batch_status_adapter_preserves_response_shape(monkeypatch):
    async def user_id(*_args): return "owner-1"
    async def workspace(*_args): return "workspace-1"
    async def status(*_args):
        return {
            "status": "processing", "total": 2, "completed": 1,
            "current_index": 1, "current_name": "Lead 1", "drafts": [],
            "error": None, "campaign_id": "campaign-1", "batch_id": "batch-1",
            "started_at": "now",
        }

    monkeypatch.setattr(drafts_api.identity_dependencies, "web_session_token", lambda _request: "token")
    monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", user_id)
    monkeypatch.setattr(drafts_api.workspace_access, "resolve_legacy_workspace_id", workspace)

    monkeypatch.setattr(drafts, "draft_batch_status", status)
    response = await drafts_api.batch_status("_", "batch-1", SimpleNamespace(headers={}))

    assert response["ok"] is True
    assert {"batch_id", "total", "completed", "current_index", "current_name", "status"} <= response.keys()


async def test_restart_resumes_only_incomplete_items_without_duplicate_drafts(monkeypatch):
    completed = _item(0, BatchItemStatus.COMPLETED, "draft-0")
    interrupted = _item(1, BatchItemStatus.GENERATING)
    all_items = [completed, interrupted]
    workflow_leads: list[str] = []

    class Storage:
        def list_active_jobs_by_type(self, job_type):
            return [_job(JobStatus.RUNNING)] if job_type == "draft_batch" else []

        def list_batch_resume_items(self, *_args, **_kwargs): return [interrupted]
        def list_batch_items(self, *_args, **_kwargs): return all_items
        def reset_batch_items_for_resume(self, *_args):
            interrupted.status = BatchItemStatus.PENDING
            return True
        def mark_batch_item_generating(self, item_id): return item_id == interrupted.id

        def mark_batch_item_completed(self, _job_id, key, draft_id):
            assert key == interrupted.idempotency_key
            interrupted.status = BatchItemStatus.COMPLETED
            interrupted.draft_id = draft_id
            return True

        def mark_batch_item_failed(self, *_args):
            raise AssertionError("the resumed item should succeed")

    resumed: list[str] = []
    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    monkeypatch.setattr("services.job_engine.job_manager.resume_job", lambda job: resumed.append(job.id) or True)
    monkeypatch.setattr(drafts, "register_draft_batch_workflow", lambda: None)
    assert await drafts.reconcile_stale_draft_batch_jobs() == 1
    assert resumed == ["batch-1"]

    async def run_workflow(_loop, payload):
        workflow_leads.append(payload["lead"]["id"])
        return {"ok": True, "message": "Draft ready: ---\nHello\n---", "subject": "Hi"}

    monkeypatch.setattr(drafts, "_run_draft_with_retry", run_workflow)
    monkeypatch.setattr("services.workspace.state.load_campaign_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("services.workspace.state.persist_draft_awaited", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    job = _job()
    job.campaign_id = ""
    result = await drafts.run_draft_batch_job(job, lambda *_args: None)

    assert result["ok"] is True
    assert workflow_leads == ["lead-1"]
    assert completed.draft_id == "draft-0"
    assert interrupted.status == BatchItemStatus.COMPLETED


async def test_generation_status_uses_active_durable_batch(monkeypatch):
    async def user_id(*_args): return "owner-1"
    async def workspace(*_args): return "workspace-1"
    async def active(*_args): return {"batch_id": "batch-1", "total": 2, "status": "running"}
    async def status(*_args): return {"batch_id": "batch-1", "total": 2, "completed": 1}

    monkeypatch.setattr(campaigns_api.identity_dependencies, "web_session_token", lambda _request: "token")
    monkeypatch.setattr(campaigns_api.identity_dependencies, "authenticated_user_id", user_id)
    monkeypatch.setattr(campaigns_api.workspace_access, "resolve_legacy_workspace_id", workspace)
    monkeypatch.setattr(drafts, "active_draft_batch", active)
    monkeypatch.setattr(drafts, "draft_batch_status", status)
    response = await campaigns_api.campaign_generation_status("_", "campaign-1", SimpleNamespace(headers={}))

    assert response == {
        "ok": True, "active": True, "status": "processing", "total": 2,
        "completed": 1, "batch_id": "batch-1",
    }


@pytest.fixture
def generation_state(monkeypatch):
    """Private durable doubles; no application client or worker startup."""
    state = SimpleNamespace(
        job=_job(JobStatus.FAILED),
        items=[_item(0, BatchItemStatus.PENDING), _item(1, BatchItemStatus.PENDING)],
        campaign={"id": "campaign-1", "generation": {
            "batch_id": "batch-1", "total": 2, "completed": 0, "status": "processing",
        }},
        writes=[], read_error=False,
    )

    class Storage:
        def list_active_jobs_by_type(self, _kind, **_kwargs):
            if state.read_error:
                raise RuntimeError("synthetic storage unavailable")
            return [state.job] if state.job and state.job.status in {JobStatus.QUEUED, JobStatus.RUNNING} else []

        def get_job(self, _id, **_kwargs):
            if state.read_error:
                raise RuntimeError("synthetic storage unavailable")
            return state.job

        def list_batch_items(self, *_args, **_kwargs): return state.items
        def list_batch_resume_items(self, *_args, **_kwargs):
            return [item for item in state.items if item.status != BatchItemStatus.COMPLETED]

        def update_job(self, _id, **updates):
            for key, value in updates.items():
                setattr(state.job, key, value)
            return True

        def mark_batch_item_generating(self, item_id):
            item = next(item for item in state.items if item.id == item_id)
            if item.status != BatchItemStatus.PENDING:
                return False
            item.status = BatchItemStatus.GENERATING
            return True

        def mark_batch_item_completed(self, job_id, key, draft_id):
            assert job_id == state.job.id
            item = next(item for item in state.items if item.idempotency_key == key)
            item.status = BatchItemStatus.COMPLETED
            item.draft_id = draft_id
            return True

        def mark_batch_item_failed(self, item_id, error):
            item = next(item for item in state.items if item.id == item_id)
            item.status = BatchItemStatus.FAILED
            item.last_error = error
            return True

    async def reconcile(_self, campaign_id, workspace_id, batch_id, generation, *, expected_generation):
        assert (campaign_id, workspace_id, batch_id) == ("campaign-1", "workspace-1", "batch-1")
        assert expected_generation == state.campaign["generation"]
        state.writes.append(generation)
        state.campaign["generation"] = generation
        return True

    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    monkeypatch.setattr("services.workspace.state.load_campaign_state", lambda *_args, **_kwargs: state.campaign)
    monkeypatch.setattr(CampaignRepository, "reconcile_generation_for_workspace", reconcile, raising=False)
    return state


async def test_worker_crash_is_reconciled_from_failed_durable_job(monkeypatch, generation_state):
    from services.job_engine import job_manager
    from services.job_engine.runner import BackgroundRunner

    state = generation_state
    state.job.status = JobStatus.QUEUED

    async def unavailable_knowledge(*_args, **_kwargs):
        raise RuntimeError("synthetic knowledge read failed")

    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", unavailable_knowledge)
    runner = BackgroundRunner(job_manager._storage)
    await runner._run_wrapper(state.job, drafts.run_draft_batch_job)

    assert state.job.status == JobStatus.FAILED
    assert state.campaign["generation"]["status"] == "processing"
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response == {"ok": True, "active": False, "status": "failed", "total": 2,
                        "completed": 0, "batch_id": "batch-1"}
    assert state.campaign["generation"]["status"] == "failed"
    assert state.campaign["generation"]["generated"] == 0
    assert state.campaign["generation"]["failed"] == 0
    assert all(item.status == BatchItemStatus.PENDING for item in state.items)


async def test_item_crash_preserves_partial_drafts_and_repairs_generation(monkeypatch, generation_state):
    from services.job_engine import job_manager
    from services.job_engine.runner import BackgroundRunner

    state = generation_state
    state.job.status = JobStatus.QUEUED
    state.items[0] = _item(0, BatchItemStatus.COMPLETED, "saved-draft")

    async def broken_generation(*_args):
        raise RuntimeError("synthetic execution failure")

    monkeypatch.setattr(drafts, "_run_draft_with_retry", broken_generation)
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    await BackgroundRunner(job_manager._storage)._run_wrapper(state.job, drafts.run_draft_batch_job)
    assert state.job.status == JobStatus.FAILED
    assert state.campaign["generation"]["status"] == "processing"
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response["status"] == "failed"
    assert response["completed"] == 2
    assert state.campaign["generation"]["generated"] == 1
    assert state.campaign["generation"]["failed"] == 1
    assert state.campaign["generation"]["outcome"] == "partial"
    assert state.items[0].draft_id == "saved-draft"


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
async def test_real_active_batch_keeps_processing_without_repair(generation_state, status):
    state = generation_state
    state.job.status = status
    state.items[0].status = BatchItemStatus.COMPLETED
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response == {"ok": True, "active": True, "status": "processing", "total": 2,
                        "completed": 1, "batch_id": "batch-1"}
    assert state.writes == []


@pytest.mark.parametrize("job_status,item_statuses,expected_status,generated,failed", [
    (JobStatus.COMPLETED, [BatchItemStatus.COMPLETED, BatchItemStatus.COMPLETED], "completed", 2, 0),
    (JobStatus.COMPLETED, [BatchItemStatus.COMPLETED, BatchItemStatus.FAILED], "completed", 1, 1),
    (JobStatus.COMPLETED, [BatchItemStatus.COMPLETED, BatchItemStatus.PENDING], "failed", 1, 0),
    (JobStatus.FAILED, [BatchItemStatus.COMPLETED, BatchItemStatus.GENERATING], "failed", 1, 0),
    (JobStatus.FAILED, [BatchItemStatus.COMPLETED, BatchItemStatus.FAILED], "failed", 1, 1),
    (JobStatus.CANCELLED, [BatchItemStatus.PENDING, BatchItemStatus.PENDING], "cancelled", 0, 0),
])
async def test_terminal_batch_uses_persisted_item_counts(
    generation_state, job_status, item_statuses, expected_status, generated, failed,
):
    state = generation_state
    state.job.status = job_status
    for item, status in zip(state.items, item_statuses):
        item.status = status
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response["active"] is False
    assert response["status"] == expected_status
    assert response["total"] == 2
    assert response["completed"] == generated + failed
    generation = state.campaign["generation"]
    assert generation["generated"] == generated
    assert generation["failed"] == failed
    assert generation["outcome"] != "completed" or generated == 2
    assert [item.status for item in state.items] == item_statuses


async def test_missing_batch_is_unavailable_not_completed(generation_state):
    state = generation_state
    state.job = None
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response == {"ok": True, "active": False, "status": "failed", "total": 2,
                        "completed": 0, "batch_id": "batch-1"}
    assert state.campaign["generation"]["outcome"] == "unknown"


@pytest.mark.parametrize("field,value", [("user_id", "other-owner"), ("workspace_id", "other-workspace"),
                                         ("campaign_id", "other-campaign"), ("type", "search")])
async def test_generation_repair_does_not_use_another_scope(generation_state, field, value):
    state = generation_state
    setattr(state.job, field, value)
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response["status"] == "unknown"
    assert state.writes == []


async def test_unavailable_active_lookup_cannot_enqueue_duplicate(monkeypatch, generation_state):
    state = generation_state
    state.read_error = True

    async def unexpected_schedule(**_kwargs):
        pytest.fail("Uncertain persistence must not schedule a second batch")

    monkeypatch.setattr(drafts, "schedule_campaign_draft_batch", unexpected_schedule)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await drafts.start_campaign_draft_generation("token", "owner-1", "workspace-1", "campaign-1")
    assert error.value.status_code == 503
    assert state.writes == []


async def test_missing_item_checkpoints_cannot_be_completed(generation_state):
    state = generation_state
    state.job.status = JobStatus.COMPLETED
    state.items = [_item(0, BatchItemStatus.COMPLETED, "draft-0")]
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response["status"] == "failed"
    assert response["completed"] == 1 and response["total"] == 2
    assert state.campaign["generation"]["outcome"] == "partial"


async def test_exact_job_read_can_find_active_batch_after_scan(monkeypatch, generation_state):
    state = generation_state
    state.job.status = JobStatus.RUNNING
    monkeypatch.setattr("services.job_engine.job_manager._storage.list_active_jobs_by_type", lambda *_args, **_kwargs: [])
    response = await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert response["active"] is True and response["status"] == "processing"
    assert state.writes == []


@pytest.mark.parametrize("operation", ["get_job", "list_batch_items"])
async def test_unknown_storage_state_does_not_repair_metadata(monkeypatch, generation_state, operation):
    from fastapi import HTTPException

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic read failure")

    monkeypatch.setattr(f"services.job_engine.job_manager._storage.{operation}", unavailable)
    with pytest.raises(HTTPException) as error:
        await drafts.campaign_draft_generation_status("owner-1", "workspace-1", "campaign-1")
    assert error.value.status_code == 503
    assert generation_state.writes == []
    assert generation_state.campaign["generation"]["status"] == "processing"


async def test_batch_completion_waits_for_campaign_metadata(monkeypatch, generation_state):
    from services.job_engine import job_manager
    from services.job_engine.runner import BackgroundRunner

    state = generation_state
    state.job.status = JobStatus.QUEUED
    state.items = [_item(i, BatchItemStatus.COMPLETED, f"draft-{i}") for i in range(2)]
    entered, release = asyncio.Event(), asyncio.Event()

    async def persist(owner, campaign, updates, *, workspace_id):
        assert (owner, campaign, workspace_id) == ("owner-1", "campaign-1", "workspace-1")
        entered.set()
        await release.wait()
        state.campaign.update(updates)
        return True

    monkeypatch.setattr("services.workspace.state.persist_campaign_update_awaited", persist)
    monkeypatch.setattr("services.workspace.state.load_workspace_state", lambda *_args, **_kwargs: {"campaigns": []})
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    task = asyncio.create_task(BackgroundRunner(job_manager._storage)._run_wrapper(state.job, drafts.run_draft_batch_job))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert state.job.status == JobStatus.RUNNING
        assert state.campaign["generation"]["status"] == "processing"
    finally:
        release.set()
        await task
    assert state.job.status == JobStatus.COMPLETED
    assert state.campaign["generation"]["status"] == "completed"
    assert state.campaign["generation"]["completed"] == 2


@pytest.mark.parametrize("race", [None, "new-batch", "settings-edit", "generation-before-read", "generation-during-write"])
async def test_generation_repair_preserves_concurrent_settings(monkeypatch, race):
    settings = {"generation": {"batch_id": "batch-1", "status": "processing"}, "other": "keep"}
    stored = {"settings": deepcopy(settings)}
    filters = {}
    updates = {}

    async def get_creation(_self, campaign_id, workspace_id):
        assert (campaign_id, workspace_id) == ("campaign-1", "workspace-1")
        if race == "generation-before-read":
            stored["settings"]["generation"]["completed"] = 1
        return SimpleNamespace(settings=deepcopy(stored["settings"]), deleted_at=None)

    class Query:
        def table(self, table): assert table == "campaigns"; return self
        def update(self, value): updates.update(value); return self
        def eq(self, key, value): filters[key] = value; return self
        def is_(self, key, value): filters[key] = value; return self
        def execute(self):
            assert filters["id"] == "campaign-1"
            assert filters["workspace_id"] == "workspace-1"
            assert filters["deleted_at"] == "null"
            if race == "new-batch":
                stored["settings"]["generation"]["batch_id"] = "batch-2"
            elif race == "settings-edit":
                stored["settings"]["other"] = "new value"
            elif race == "generation-during-write":
                stored["settings"]["generation"]["status"] = "completed"
            if stored["settings"] != json.loads(filters["settings"]):
                return SimpleNamespace(data=[])
            stored.update(updates)
            return SimpleNamespace(data=[{"id": "campaign-1"}])

    monkeypatch.setattr(CampaignRepository, "get_creation", get_creation)
    monkeypatch.setattr(CampaignRepository, "_client", lambda _self: Query())
    repaired = {"batch_id": "batch-1", "status": "failed"}
    result = await CampaignRepository().reconcile_generation_for_workspace(
        "campaign-1", "workspace-1", "batch-1", repaired, expected_generation=settings["generation"],
    )
    assert result is (race is None)
    if race is None:
        assert stored["settings"] == {"generation": repaired, "other": "keep"}
    elif race == "new-batch":
        assert stored["settings"]["generation"] == {"batch_id": "batch-2", "status": "processing"}
    elif race == "settings-edit":
        assert stored["settings"] == {"generation": settings["generation"], "other": "new value"}
    elif race == "generation-before-read":
        assert stored["settings"]["generation"] == {"batch_id": "batch-1", "status": "processing", "completed": 1}
    else:
        assert stored["settings"]["generation"] == {"batch_id": "batch-1", "status": "completed"}


async def test_incomplete_initial_batch_cannot_publish_success(monkeypatch, generation_state):
    from services.job_engine import job_manager
    from services.job_engine.runner import BackgroundRunner

    state = generation_state
    state.job.status = JobStatus.QUEUED
    state.items = [_item(0, BatchItemStatus.COMPLETED, "saved-draft")]

    async def persist(_owner, _campaign, updates, **_kwargs):
        state.campaign.update(updates)
        return True

    monkeypatch.setattr("services.workspace.state.persist_campaign_update_awaited", persist)
    monkeypatch.setattr("services.workspace.state.load_workspace_state", lambda *_args, **_kwargs: {"campaigns": []})
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    await BackgroundRunner(job_manager._storage)._run_wrapper(state.job, drafts.run_draft_batch_job)
    assert state.job.status == JobStatus.FAILED
    assert state.campaign["generation"]["status"] == "processing"
    assert state.items[0].draft_id == "saved-draft"


@pytest.mark.parametrize("mode", ["recovered", "provider-failure"])
async def test_resumed_batch_counts_recovered_and_failed_items_once(monkeypatch, generation_state, mode):
    from services.intelligence.ai import OpenAIError
    from services.job_engine import job_manager
    from services.job_engine.runner import BackgroundRunner

    state = generation_state
    state.job.status = JobStatus.QUEUED
    state.items[0] = _item(0, BatchItemStatus.COMPLETED, "saved-draft")
    provider_calls = []

    async def recover(*_args):
        return object() if mode == "recovered" else None

    async def provider(*_args):
        provider_calls.append(1)
        raise OpenAIError("synthetic provider failure", kind="provider")

    async def persist(_owner, _campaign, updates, **_kwargs):
        state.campaign.update(updates)
        return True

    async def unexpected_draft_write(*_args, **_kwargs):
        pytest.fail("Recovery and provider failure must not create a replacement draft")

    monkeypatch.setattr(drafts, "_recover_batch_draft", recover)
    monkeypatch.setattr(drafts, "_run_draft_with_retry", provider)
    monkeypatch.setattr("services.workspace.state.persist_draft_awaited", unexpected_draft_write)
    monkeypatch.setattr("services.workspace.state.persist_campaign_update_awaited", persist)
    monkeypatch.setattr("services.workspace.state.load_workspace_state", lambda *_args, **_kwargs: {"campaigns": []})
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    await BackgroundRunner(job_manager._storage)._run_wrapper(state.job, drafts.run_draft_batch_job)
    assert state.job.status == JobStatus.COMPLETED
    generation = state.campaign["generation"]
    assert generation["status"] == "completed"
    assert generation["total"] == generation["completed"] == 2
    assert generation["generated"] == (2 if mode == "recovered" else 1)
    assert generation["failed"] == (0 if mode == "recovered" else 1)
    assert generation["outcome"] == ("completed" if mode == "recovered" else "partial")
    assert state.items[0].draft_id == "saved-draft"
    assert provider_calls == ([] if mode == "recovered" else [1])


def test_strict_active_job_lookup_does_not_hide_unavailability(monkeypatch):
    from services.job_engine.storage import JobStorage

    monkeypatch.setattr("services.job_engine.storage.get_supabase_client", lambda: None)
    with pytest.raises(RuntimeError, match="persistence unavailable"):
        JobStorage().list_active_jobs_by_type("draft_batch", strict=True)
