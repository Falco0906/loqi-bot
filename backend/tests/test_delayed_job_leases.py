"""Characterization for durable delayed-job claims and lease recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from services.job_engine.manager import JobManager
from services.job_engine.models import Job, JobStatus
from services.job_engine.registry import WorkflowRegistration, get_registry
from services.job_engine.storage import JobStorage


class _AtomicClaimClient:
    """Minimal RPC fake that models the database claim as one locked update."""

    def __init__(self, row: dict, barrier: Barrier | None = None):
        self.row = row
        self._barrier = barrier
        self._lock = Lock()

    def rpc(self, name: str, params: dict):
        assert name == "claim_due_jobs"
        client = self

        class _Request:
            def execute(self):
                if client._barrier:
                    client._barrier.wait(timeout=2)
                with client._lock:
                    now = datetime.now(timezone.utc)
                    lease_expired = not client.row.get("lease_expires_at") or client.row["lease_expires_at"] <= now
                    eligible = (
                        client.row["status"] in {"queued", "running"}
                        and client.row["run_at"] <= now
                        and lease_expired
                        and client.row["type"] in params["p_job_types"]
                    )
                    if not eligible:
                        return SimpleNamespace(data=[])
                    client.row.update({
                        "status": "running",
                        "stage": "Starting...",
                        "progress": 0,
                        "lease_owner": params["p_lease_owner"],
                        "lease_expires_at": now + timedelta(seconds=params["p_lease_seconds"]),
                    })
                    return SimpleNamespace(data=[dict(client.row)])

        return _Request()


def _due_row(*, status: str = "queued", lease_expires_at=None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": "delayed-job",
        "user_id": "user",
        "type": "delayed_test",
        "status": status,
        "stage": "Queued",
        "progress": 0,
        "query": "",
        "workspace_id": "workspace",
        "campaign_id": None,
        "payload": {},
        "result": {},
        "run_at": now - timedelta(seconds=1),
        "lease_owner": "dead-worker" if lease_expires_at else None,
        "lease_expires_at": lease_expires_at,
        "created_at": now - timedelta(minutes=1),
        "updated_at": now,
    }


def test_concurrent_due_claims_return_exactly_one_claim(monkeypatch):
    """Two workers race through the atomic claim boundary; only one wins."""
    client = _AtomicClaimClient(_due_row(), Barrier(2))
    monkeypatch.setattr("services.job_engine.storage.get_supabase_client", lambda: client)

    def claim(worker_id: str):
        return JobStorage().claim_due_jobs(worker_id, ["delayed_test"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(claim, ["worker-a", "worker-b"]))

    assert sorted([len(first), len(second)]) == [0, 1]
    assert client.row["lease_owner"] in {"worker-a", "worker-b"}
    assert client.row["status"] == "running"


def test_expired_lease_is_reclaimable(monkeypatch):
    client = _AtomicClaimClient(
        _due_row(status="running", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    monkeypatch.setattr("services.job_engine.storage.get_supabase_client", lambda: client)

    claimed = JobStorage().claim_due_jobs("replacement-worker", ["delayed_test"])

    assert [job.id for job in claimed] == ["delayed-job"]
    assert client.row["lease_owner"] == "replacement-worker"


@pytest.mark.asyncio
async def test_immediate_jobs_still_start_while_delayed_jobs_wait_for_claim():
    starts: list[tuple[str, bool]] = []

    class _Storage:
        def create_job(self, job):
            return job

    manager = JobManager()
    manager._storage = _Storage()
    manager._runner.start_job = lambda job, **kwargs: starts.append((job.id, kwargs.get("claimed", False)))
    get_registry().register(WorkflowRegistration(type="delayed_test", description="test", runner_fn=lambda *_: None))

    immediate = Job(id="immediate", user_id="user", type="delayed_test")
    delayed = Job(
        id="delayed",
        user_id="user",
        type="delayed_test",
        run_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    assert await manager.create_job(immediate) == {"job_id": "immediate", "status": "queued"}
    assert await manager.create_job(delayed) == {"job_id": "delayed", "status": "queued"}
    assert starts == [("immediate", False)]


@pytest.mark.asyncio
async def test_due_jobs_start_only_after_the_storage_claim(monkeypatch):
    claimed_job = Job(
        id="claimed",
        user_id="user",
        type="delayed_test",
        run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    starts: list[tuple[str, bool]] = []

    class _Storage:
        def claim_due_jobs(self, owner, types, *, limit, lease_seconds):
            assert owner
            assert "delayed_test" in types
            assert limit == 3
            assert lease_seconds == 120
            return [claimed_job]

    manager = JobManager()
    manager._storage = _Storage()
    manager._runner._storage = manager._storage
    manager._runner.start_job = lambda job, **kwargs: starts.append((job.id, kwargs.get("claimed", False)))
    get_registry().register(WorkflowRegistration(type="delayed_test", description="test", runner_fn=lambda *_: None))

    assert await manager.start_due_jobs(limit=3) == 1
    assert starts == [("claimed", True)]


def test_cancelling_unclaimed_delayed_job_never_interrupts_a_remote_runner():
    job = Job(
        id="scheduled",
        user_id="user",
        type="delayed_test",
        run_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    class _Storage:
        def get_job(self, job_id):
            assert job_id == job.id
            return job

        def cancel_unclaimed_delayed_job(self, job_id):
            assert job_id == job.id
            return True

    manager = JobManager()
    manager._storage = _Storage()
    manager._runner._storage = manager._storage
    manager._runner.cancel_job = lambda _job_id: pytest.fail("local runner must not be used")

    assert manager.cancel_job(job.id) is True


def test_delayed_job_migration_uses_database_claim_lock():
    migration = (
        Path(__file__).resolve().parents[1] / "supabase/migrations/036_delayed_job_leases.sql"
    ).read_text().lower()
    assert "for update skip locked" in migration
    assert "lease_expires_at" in migration
    assert "run_at" in migration
