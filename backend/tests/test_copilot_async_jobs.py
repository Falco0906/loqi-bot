"""Phase 3 durable-job boundary regressions."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from services.copilot_tools import execute_copilot_tool
from services.job_engine.manager import JobManager
from services.job_engine.models import Job, JobStatus
from services.job_engine.runner import BackgroundRunner


class DurableStorage:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.updates: list[dict[str, object]] = []

    def create_job(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    def update_job(self, job_id: str, **updates: object) -> bool:
        self.updates.append({"job_id": job_id, **updates})
        job = self.jobs[job_id]
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        return True


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Job, object]] = []

    def start_job(self, job: Job, runner_fn, **_kwargs: object) -> None:
        self.calls.append((job, runner_fn))


@pytest.mark.asyncio
async def test_copilot_search_is_acknowledged_after_durable_job_schedule(monkeypatch):
    """The durable queued row is returned before provider work starts."""
    import workflow_dispatcher

    storage = DurableStorage()
    manager = JobManager()
    manager._storage = storage
    runner = RecordingRunner()
    manager._runner = runner
    monkeypatch.setattr(workflow_dispatcher, "run_search_workflow", object())

    created = await manager.create_search_job(
        user_id="owner-1", query="cafe owners", discovery_id="discovery-1"
    )

    assert created == {"job_id": next(iter(storage.jobs)), "status": "queued"}
    assert storage.jobs[created["job_id"]].discovery_id == "discovery-1"
    assert storage.jobs[created["job_id"]].status is JobStatus.QUEUED
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_copilot_discovery_tool_returns_accepted_operation_without_waiting():
    calls: list[dict[str, object]] = []

    async def discovery_runner(user_id, search_context, session_token, *, workspace_id):
        calls.append({
            "user_id": user_id,
            "search_context": search_context,
            "session_token": session_token,
            "workspace_id": workspace_id,
        })
        return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

    result = await execute_copilot_tool(
        "discovery.search",
        user_id="owner-1",
        workspace_id="workspace-a",
        session_token="session-1",
        decision={"search_context": {"industry": ["cafes"]}},
        discovery_runner=discovery_runner,
    )

    assert result["ok"] is True
    assert result["status"] == "accepted"
    assert result["operation"]["status"] == "queued"
    assert calls == [{
        "user_id": "owner-1",
        "search_context": {"industry": ["cafes"]},
        "session_token": "session-1",
        "workspace_id": "workspace-a",
    }]


@pytest.mark.asyncio
async def test_runner_persists_progress_and_only_completes_after_finalization():
    storage = DurableStorage()
    job = Job(id="job-1", user_id="owner-1", type="search", discovery_id="discovery-1")
    storage.create_job(job)
    runner = BackgroundRunner(storage)
    notifications: list[dict[str, object]] = []

    async def workflow(current_job, on_progress):
        on_progress(current_job.id, "Searching", 40)
        return {"ok": True}

    async def finalize(current_job):
        assert current_job.id == "job-1"
        return True

    await runner._run_wrapper(job, workflow, notifications.append, finalize)

    statuses = [update.get("status") for update in storage.updates if update.get("status")]
    assert statuses == [JobStatus.RUNNING, JobStatus.COMPLETED]
    assert storage.jobs["job-1"].status is JobStatus.COMPLETED
    assert storage.jobs["job-1"].result_ready is True
    assert any(note["status"] == "running" and note["progress"] == 40 for note in notifications)
    assert notifications[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_timeout_marks_durable_job_failed_never_completed():
    storage = DurableStorage()
    job = Job(id="job-2", user_id="owner-1", type="search", discovery_id="discovery-1")
    storage.create_job(job)
    runner = BackgroundRunner(storage)

    async def timed_out_workflow(_job, _on_progress):
        raise asyncio.TimeoutError("provider timed out")

    await runner._run_wrapper(job, timed_out_workflow)

    assert storage.jobs["job-2"].status is JobStatus.FAILED
    assert storage.jobs["job-2"].result_ready is False
    statuses = [update.get("status") for update in storage.updates if update.get("status")]
    assert JobStatus.COMPLETED not in statuses


@pytest.mark.asyncio
async def test_cancelled_job_has_a_durable_cancelled_terminal_state():
    storage = DurableStorage()
    job = Job(id="job-3", user_id="owner-1", type="search", discovery_id="discovery-1")
    storage.create_job(job)
    runner = BackgroundRunner(storage)
    started = asyncio.Event()

    async def blocking_workflow(_job, _on_progress):
        started.set()
        await asyncio.Event().wait()
        return {"ok": True}

    task = asyncio.create_task(runner._run_wrapper(job, blocking_workflow))
    runner._tasks[job.id] = task
    await started.wait()
    assert runner.cancel_job("job-3") is True
    with suppress(asyncio.CancelledError):
        await task

    assert storage.jobs["job-3"].status is JobStatus.CANCELLED
    assert storage.jobs["job-3"].result_ready is False


def test_phase2_confirmation_stays_required_on_repeated_mutation_request():
    """Phase 3 must not turn a request retry into mutation authorization."""
    from services.copilot_tools import mutation_confirmation_state

    assert mutation_confirmation_state("lead.save", "please save these leads") == "required"
    assert mutation_confirmation_state("lead.save", "please save these leads") == "required"
    assert mutation_confirmation_state("lead.save", "confirm save these leads") == "confirmed"
