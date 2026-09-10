"""Durable draft-batch status and restart recovery contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import main
import services.drafts.service as drafts
from services.job_engine.models import BatchItem, BatchItemStatus, Job, JobStatus


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
        def get_job(self, job_id):
            return job if job_id == "batch-1" else None

        def list_batch_items(self, *_args):
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

    monkeypatch.setattr(main.identity_dependencies, "web_session_token", lambda _request: "token")
    monkeypatch.setattr(main.identity_dependencies, "authenticated_user_id", user_id)
    monkeypatch.setattr(main.workspace_access, "resolve_legacy_workspace_id", workspace)
    from services.drafts.api import batch_status

    monkeypatch.setattr(drafts, "draft_batch_status", status)
    response = await batch_status("_", "batch-1", SimpleNamespace(headers={}))

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

        def list_batch_resume_items(self, *_args): return [interrupted]
        def list_batch_items(self, *_args): return all_items
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
        return {"message": "Draft ready: ---\nHello\n---", "subject": "Hi"}

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

    monkeypatch.setattr(main.identity_dependencies, "web_session_token", lambda _request: "token")
    monkeypatch.setattr(main.identity_dependencies, "authenticated_user_id", user_id)
    monkeypatch.setattr(main.workspace_access, "resolve_legacy_workspace_id", workspace)
    monkeypatch.setattr(drafts, "active_draft_batch", active)
    monkeypatch.setattr(drafts, "draft_batch_status", status)
    from services.campaigns.api import campaign_generation_status
    response = await campaign_generation_status("_", "campaign-1", SimpleNamespace(headers={}))

    assert response == {
        "ok": True, "active": True, "status": "processing", "total": 2,
        "completed": 1, "batch_id": "batch-1",
    }
