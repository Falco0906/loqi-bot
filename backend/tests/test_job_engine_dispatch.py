"""Job-engine dispatch is type-driven while search retains its Discovery invariant."""

import pytest

from services.job_engine.models import Job, JobStatus
from services.job_engine.registry import WorkflowRegistration, get_registry
from services.job_engine.runner import BackgroundRunner


class Storage:
    def __init__(self): self.jobs = {}; self.updates = []
    def create_job(self, job): self.jobs[job.id] = job; return job
    def update_job(self, job_id, **values):
        self.updates.append(values)
        job = self.jobs[job_id]
        for key, value in values.items():
            if hasattr(job, key): setattr(job, key, value)
        return True


@pytest.mark.asyncio
async def test_search_dispatch_still_rejects_missing_discovery_id():
    storage = Storage()
    job = Job(id="search-without-discovery", user_id="user", type="search")
    storage.create_job(job)
    called = False
    async def workflow(_job, _progress):
        nonlocal called; called = True; return {"ok": True}
    await BackgroundRunner(storage)._run_wrapper(job, workflow)
    assert called is False
    assert job.status is JobStatus.FAILED
    assert any(item.get("error_message") == "Canonical discovery_id is required" for item in storage.updates)


@pytest.mark.asyncio
async def test_runner_resolves_registered_non_search_workflow_by_type():
    storage = Storage()
    job = Job(id="generic-job", user_id="user", type="example", workspace_id="workspace", payload={"key": "value"})
    storage.create_job(job)
    async def workflow(received, _progress):
        assert received.payload == {"key": "value"}
        return {"ok": True}
    get_registry().register(WorkflowRegistration(type="example", description="test", runner_fn=workflow))
    runner = BackgroundRunner(storage)
    runner.start_job(job)
    task = runner._tasks[job.id]
    await task
    assert job.status is JobStatus.COMPLETED
