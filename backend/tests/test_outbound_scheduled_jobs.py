"""Durable scheduled-send workflow coverage without provider/network calls."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import services.outbound.service as outbound
from services.job_engine.models import Job, JobStatus
from services.outbound.outbound_models import ApprovalState, DraftMessage, DraftStatus, Recipient


OWNER = "owner"
WORKSPACE = "workspace"
DRAFT_ID = "draft-id"


def _draft(*, status: DraftStatus = DraftStatus.APPROVED) -> DraftMessage:
    return DraftMessage(
        id=DRAFT_ID,
        provider_id="provider",
        workflow_id="campaign",
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="sender@example.com", name="Sender"),
        status=status,
        approval_state=ApprovalState.APPROVED,
        metadata={},
    )


@pytest.mark.asyncio
async def test_enqueue_scheduled_send_persists_a_delayed_job_before_returning(monkeypatch):
    created: list[Job] = []
    updates: list[dict] = []

    async def create_job(job):
        created.append(job)
        return {"job_id": job.id, "status": "queued"}

    async def persist_update(*_args, **kwargs):
        updates.append(_args[2])
        return True

    monkeypatch.setattr("services.job_engine.job_manager.create_job", create_job)
    monkeypatch.setattr(outbound, "resolve_provider_for_draft", lambda *_: "provider")
    monkeypatch.setattr(outbound, "persist_outbound_projection", lambda *_args, **_kwargs: _async(True))
    monkeypatch.setattr("services.workspace_state.persist_draft_update_awaited", persist_update)

    draft = _draft()
    result = await outbound.enqueue_scheduled_outbound_send(
        OWNER, WORKSPACE, {"id": DRAFT_ID, "campaign_id": "campaign"}, draft,
        "2099-01-01T00:00:00Z",
    )

    assert result["ok"] is True
    assert result["schedule_id"] == DRAFT_ID
    assert len(created) == 1
    assert created[0].type == outbound.SCHEDULED_SEND_JOB_TYPE
    assert created[0].run_at is not None
    assert created[0].payload == {"draft_id": DRAFT_ID, "provider_id": "provider"}
    assert draft.status is DraftStatus.SCHEDULED
    assert draft.metadata["scheduled_job_id"] == created[0].id
    assert updates == [{"status": "scheduled"}]


@pytest.mark.asyncio
async def test_scheduled_workflow_hydrates_then_sends_and_persists_terminal_state(monkeypatch):
    draft = _draft(status=DraftStatus.SCHEDULED)
    draft.metadata["scheduled_job_id"] = "job-id"
    canonical = {
        "id": DRAFT_ID,
        "status": "scheduled",
        "metadata": {"outbound_projection": {"scheduled_job_id": "job-id"}},
    }
    updates: list[dict] = []
    projections: list[str] = []
    executed: list[dict] = []

    monkeypatch.setattr("services.workspace_state.load_drafts_only", lambda *_args, **_kwargs: [canonical])
    async def persist_update(*args, **_kwargs):
        updates.append(args[2])
        return True
    monkeypatch.setattr("services.workspace_state.persist_draft_update_awaited", persist_update)
    monkeypatch.setattr(outbound, "hydrate_outbound_draft", lambda *_args, **_kwargs: draft)
    monkeypatch.setattr(outbound, "resolve_provider_for_draft", lambda *_: "provider")
    monkeypatch.setattr(
        outbound, "persist_outbound_projection",
        lambda *_args, **kwargs: projections.append(kwargs["change_summary"]) or _async(True),
    )
    monkeypatch.setattr(
        outbound.outbound_executor,
        "send_hydrated_draft",
        lambda sent_draft, *, provider_id: executed.append({"draft_id": sent_draft.id, "provider_id": provider_id}) or {"ok": True, "send_result": {"id": "sent"}},
    )
    monkeypatch.setattr(outbound, "publish_draft_event", lambda *_args, **_kwargs: _async(None))

    job = Job(
        id="job-id", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, payload={"draft_id": DRAFT_ID, "provider_id": "provider"},
    )
    result = await outbound.run_scheduled_outbound_send(job, lambda *_: None)

    assert result["ok"] is True
    assert updates == [{"status": "sending"}, {"status": "sent"}]
    assert projections == ["scheduled send started", "scheduled send completed"]
    assert executed[0]["draft_id"] == DRAFT_ID
    assert draft.status is DraftStatus.SENT


@pytest.mark.asyncio
async def test_cancelled_queued_send_never_reaches_the_provider(monkeypatch):
    draft = _draft(status=DraftStatus.SCHEDULED)
    draft.metadata["scheduled_job_id"] = "job-id"
    job = Job(
        id="job-id", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, status=JobStatus.QUEUED, payload={"draft_id": DRAFT_ID},
    )
    cancelled: list[str] = []

    monkeypatch.setattr("services.job_engine.job_manager.get_job", lambda job_id: job.to_dict() if job_id == job.id else None)
    monkeypatch.setattr("services.job_engine.job_manager.cancel_job", lambda job_id: cancelled.append(job_id) or True)
    monkeypatch.setattr("services.workspace_state.persist_draft_update_awaited", lambda *_args, **_kwargs: _async(True))
    monkeypatch.setattr(outbound, "persist_outbound_projection", lambda *_args, **_kwargs: _async(True))

    result = await outbound.cancel_scheduled_outbound_send(
        OWNER, WORKSPACE, {"id": DRAFT_ID}, draft,
    )

    assert result == {"ok": True}
    assert cancelled == ["job-id"]
    assert draft.status is DraftStatus.PENDING_APPROVAL
    assert "scheduled_job_id" not in draft.metadata


@pytest.mark.asyncio
async def test_running_scheduled_send_is_not_falsely_reported_cancelled(monkeypatch):
    draft = _draft(status=DraftStatus.SCHEDULED)
    draft.metadata["scheduled_job_id"] = "job-id"
    job = Job(
        id="job-id", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, status=JobStatus.RUNNING, payload={"draft_id": DRAFT_ID},
    )
    monkeypatch.setattr("services.job_engine.job_manager.get_job", lambda _job_id: job.to_dict())
    monkeypatch.setattr(
        "services.job_engine.job_manager.cancel_job",
        lambda _job_id: pytest.fail("a remote running provider call must not be cancelled"),
    )

    result = await outbound.cancel_scheduled_outbound_send(
        OWNER, WORKSPACE, {"id": DRAFT_ID}, draft,
    )

    assert result == {"ok": False, "error": "Scheduled send is already running"}


@pytest.mark.asyncio
async def test_restart_re_evaluation_starts_only_due_scheduled_sends(monkeypatch):
    """Future and cancelled rows are not returned by the durable claim query."""
    from services.job_engine import job_manager

    now = datetime.now(timezone.utc)
    due = Job(
        id="due", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, run_at=now - timedelta(seconds=1),
    )
    future = Job(
        id="future", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, run_at=now + timedelta(hours=1),
    )
    cancelled = Job(
        id="cancelled", user_id=OWNER, type=outbound.SCHEDULED_SEND_JOB_TYPE,
        workspace_id=WORKSPACE, run_at=now - timedelta(seconds=1), status=JobStatus.CANCELLED,
    )
    started: list[str] = []

    class _Storage:
        def claim_due_jobs(self, _owner, _types, **_kwargs):
            rows = [due, future, cancelled]
            return [
                row for row in rows
                if row.status is JobStatus.QUEUED and row.run_at is not None and row.run_at <= now
            ]

    original_storage = job_manager._storage
    original_runner_storage = job_manager._runner._storage
    original_start = job_manager._runner.start_job
    try:
        job_manager._storage = _Storage()
        job_manager._runner._storage = job_manager._storage
        job_manager._runner.start_job = lambda job, **_kwargs: started.append(job.id)
        outbound.register_scheduled_send_workflow()
        assert await job_manager.start_due_jobs() == 1
    finally:
        job_manager._storage = original_storage
        job_manager._runner._storage = original_runner_storage
        job_manager._runner.start_job = original_start

    assert started == ["due"]


async def _async(value):
    return value
