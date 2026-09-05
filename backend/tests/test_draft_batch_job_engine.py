import asyncio
from types import SimpleNamespace

import main
import services.drafts.service as drafts
from services.drafts.api import BatchDraftRequest, batch_draft
from services.job_engine.models import BatchItem, BatchItemStatus, Job


async def test_enqueue_persists_items_before_queueing(monkeypatch):
    captured = {}

    async def create_batch_job(job, items, *, start=True):
        captured["job"] = job
        captured["items"] = items
        captured["start"] = start
        return {"job_id": job.id, "status": "queued"}

    monkeypatch.setattr("services.job_engine.job_manager.create_batch_job", create_batch_job)
    result = await drafts.enqueue_draft_batch(
        "session", "user", "workspace", [{"id": "lead-1"}], "campaign",
    )

    assert result["batch_id"] == captured["job"].id
    assert captured["job"].type == "draft_batch"
    assert captured["items"][0].lead_snapshot == {"id": "lead-1"}
    assert captured["items"][0].workspace_id == "workspace"


async def test_draft_batch_runner_completes_durable_item(monkeypatch):
    item = BatchItem("job", "workspace", "campaign", 0, {"id": "lead-1", "name": "Ada"}, "0:lead-1")
    updates = []

    class Storage:
        def list_batch_resume_items(self, *_): return [item]
        def list_batch_items(self, *_): return [item]
        def mark_batch_item_generating(self, *_): return True
        def mark_batch_item_completed(self, *_):
            item.status = BatchItemStatus.COMPLETED
            updates.append("completed")
            return True
        def mark_batch_item_failed(self, *_): updates.append("failed"); return True

    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    monkeypatch.setattr(drafts, "_run_draft_with_retry", lambda *_: asyncio.sleep(0, result={"message": "Draft ready: ---\nHello\n---", "subject": "Hi"}))
    monkeypatch.setattr("services.workspace_state.persist_draft_awaited", lambda *_, **__: asyncio.sleep(0, result=True))
    monkeypatch.setattr("services.workspace_state.load_campaign_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    result = await drafts.run_draft_batch_job(
        Job(id="job", user_id="user", type="draft_batch", workspace_id="workspace", payload={}),
        lambda *_: None,
    )
    assert result["ok"] is True
    assert result["result"]["completed"] == 1
    assert updates == ["completed"]


async def test_manual_batch_adapter_preserves_response_shape(monkeypatch):
    async def user_id(*_): return "user"
    async def workspace(*_): return "workspace"
    async def enqueue(*_args): return {"batch_id": "job-1", "total": 1, "status": "queued"}

    monkeypatch.setattr(main.identity_dependencies, "authenticated_user_id", user_id)
    monkeypatch.setattr(main.workspace_access, "resolve_legacy_workspace_id", workspace)
    monkeypatch.setattr(drafts, "enqueue_draft_batch", enqueue)
    request = SimpleNamespace(headers={"authorization": "Bearer token"})
    payload = BatchDraftRequest(leads=[{"id": "lead-1"}])
    response = await batch_draft("_", payload, request)
    assert response == {"ok": True, "batch_id": "job-1", "total": 1}
