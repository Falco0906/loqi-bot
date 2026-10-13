"""Offline regressions for staged Discovery results and truthful progress."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

import workflow_dispatcher as dispatcher
import services.discovery.service as discovery
import services.job_engine.storage as storage
from services.job_engine.models import Job, JobStatus
from services.job_engine.runner import BackgroundRunner


@pytest.fixture(autouse=True)
def enable_deferred_provider_path(monkeypatch):
    # These tests exercise the retained provider implementation. Beta's
    # disabled worker/finalizer boundaries are tested in workspace isolation.
    monkeypatch.setattr("services.capabilities.beta.beta_feature_enabled", lambda _feature: True)


@pytest.fixture
def workflow(monkeypatch):
    captured = {"writes": [], "progress": [], "events": [], "job_results": []}

    async def context(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("services.discovery.context.retrieve_discovery_context", context)
    monkeypatch.setattr(discovery, "get_discovery", lambda *_args, **_kwargs: {"workspace_id": "workspace-1"})
    monkeypatch.setattr("services.discovery.plan.derive_discovery_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(discovery, "update_discovery_progress", lambda *args: captured["progress"].append(args) or True)
    monkeypatch.setattr(storage.JobStorage, "update_job", lambda _self, _id, **kwargs: captured["job_results"].append(kwargs["result"]) or True)

    async def publish(*_args, **kwargs):
        captured["events"].append((asyncio.get_running_loop(), kwargs))
        return True

    monkeypatch.setattr("services.events.bus.EventBus.publish_user_event", publish)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, storage.SearchResultPersistenceError("unavailable")])
async def test_failed_append_never_advances_counts_or_publishes(workflow, monkeypatch, failure):
    def append(_self, _id, leads):
        workflow["writes"].append(leads)
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(storage.JobStorage, "append_search_results", append)

    def search(*args):
        args[-1]([{"id": "provider-1"}])
        return {"ok": True, "leads": [{"id": "provider-1"}]}

    monkeypatch.setattr(dispatcher, "_search_with_progress", search)
    job = Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders")
    await dispatcher.run_search_workflow(job, lambda *_args: None)
    assert job.result["search_staging"] == {"failed_batches": 1, "persisted_lead_count": 0, "provider_lead_count": 1}
    assert len(workflow["writes"]) == 1  # no blind replay of the failed batch
    assert workflow["progress"] == workflow["events"] == []
    assert workflow["job_results"] == [job.result]


@pytest.mark.asyncio
async def test_partial_append_progress_counts_only_confirmed_rows(workflow, monkeypatch):
    outcomes = iter([True, False, True])
    monkeypatch.setattr(storage.JobStorage, "append_search_results", lambda *_args: next(outcomes))

    def search(*args):
        for index in range(3):
            args[-1]([{"id": f"provider-{index}"}])
        return {"ok": True, "leads": [{"id": f"provider-{i}"} for i in range(3)]}

    monkeypatch.setattr(dispatcher, "_search_with_progress", search)
    job = Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders")
    owner_loop = asyncio.get_running_loop()
    await dispatcher.run_search_workflow(job, lambda *_args: None)
    assert [tick[1] for tick in workflow["progress"]] == ["1 leads found", "2 leads found"]
    assert [event[1]["progress"] for event in workflow["events"]] == [1, 2]
    assert all(loop is owner_loop for loop, _event in workflow["events"])
    assert job.result["search_staging"]["persisted_lead_count"] == 2
    assert job.result["search_staging"]["provider_lead_count"] == 3


@pytest.mark.asyncio
async def test_fallback_write_is_checked_and_progress_and_event_execute(workflow, monkeypatch):
    monkeypatch.setattr(storage.JobStorage, "append_search_results", lambda *_args: True)
    monkeypatch.setattr(dispatcher, "_search_with_progress", lambda *_args: {"ok": True, "leads": [{"id": "one"}]})
    await dispatcher.run_search_workflow(
        Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders"), lambda *_args: None,
    )
    assert workflow["progress"] == [("discovery-1", "1 leads found", 11)]
    assert len(workflow["events"]) == 1


@pytest.mark.parametrize("operation", ["get_search_results", "append_search_results", "store_search_results"])
def test_staging_database_errors_are_not_empty_success(monkeypatch, operation):
    class Query:
        def select(self, *_args): return self
        def insert(self, *_args): return self
        def eq(self, *_args): return self
        def order(self, *_args, **_kwargs): return self
        def execute(self): raise httpx.ReadTimeout("local simulated timeout")
        def range(self, *_args): return self

    monkeypatch.setattr(storage, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))
    args = ("job-1",) if operation == "get_search_results" else ("job-1", [{"id": "one"}])
    with pytest.raises((httpx.ReadTimeout, storage.SearchResultPersistenceError)):
        getattr(storage.JobStorage(), operation)(*args)


def test_missing_client_cannot_be_read_as_empty(monkeypatch):
    monkeypatch.setattr(storage, "get_supabase_client", lambda: None)
    with pytest.raises(storage.SearchResultPersistenceError):
        storage.JobStorage().get_search_results("job-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("staged,failed_batches,read_error", [([], 0, False), ([{"email": "a@example.com"}], 0, False), ([{"email": "a@example.com"}], 1, False), ([], 1, False), ([], 0, True)])
async def test_finalization_distinguishes_empty_success_partial_and_unreadable(monkeypatch, staged, failed_batches, read_error):
    row = {"id": "discovery-1", "workspace_id": "workspace-1", "status": "searching"}
    updates = []

    class Query:
        payload = None
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, payload): self.payload = payload; return self
        def execute(self):
            if self.payload is not None:
                updates.append(self.payload)
            return SimpleNamespace(data=[row])

    monkeypatch.setattr(discovery, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))

    def read(*_args):
        if read_error:
            raise httpx.ReadTimeout("local simulated timeout")
        return staged

    monkeypatch.setattr(storage.JobStorage, "get_search_results", read)
    async def normalize(*_args): return "canonical-1"
    monkeypatch.setattr("services.workspace.state._normalize_lead", normalize)
    monkeypatch.setattr(discovery, "_link_leads", lambda _id, _leads, ids: len(ids))
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: len(staged))
    monkeypatch.setattr(discovery, "mark_discovery_status", lambda _id, status, error="", **kwargs: updates.append({"status": status, "error": error, **kwargs}) or True)
    provider_count = len(staged) + failed_batches
    job = SimpleNamespace(id="job-1", discovery_id="discovery-1", query="founders", result={"search_staging": {"failed_batches": failed_batches, "provider_lead_count": provider_count}})
    completed = await discovery.finalize_discovery(job)
    assert completed is (not failed_batches and not read_error)
    if completed:
        assert updates[-1]["status"] == "completed"
        assert updates[-1]["summary"]["lead_count"] == len(staged)
    else:
        assert not any(update.get("status") == "completed" for update in updates)
        assert any(update.get("status") == "failed" and update.get("error_kind") == "persistence" for update in updates)
        if failed_batches:
            summary = updates[-1]["summary"]
            assert summary["error_kind"] == "persistence"
            assert summary["persisted_lead_count"] == len(staged)
            assert summary["failed_staging_batches"] == failed_batches
            assert summary["provider_lead_count"] == provider_count
            assert summary["staged_lead_count"] == len(staged)

    # The real runner must also refuse COMPLETED/result_ready after a failed
    # finalization, not merely return False from the Discovery service.
    class RunnerStorage:
        def update_job(self, _id, **values):
            for key, value in values.items():
                setattr(durable_job, key, value)
            return True

    async def successful_provider(_job, _progress):
        return {"ok": True}

    durable_job = Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders", result=job.result)
    await BackgroundRunner(RunnerStorage())._run_wrapper(
        durable_job, successful_provider, on_complete=discovery.finalize_discovery,
    )
    assert durable_job.status is (JobStatus.COMPLETED if completed else JobStatus.FAILED)
    assert durable_job.result_ready is completed


def test_progress_reports_metadata_write_failure(monkeypatch):
    monkeypatch.setattr(discovery, "_merge_metadata", lambda *_args: False)
    assert discovery.update_discovery_progress("discovery-1", "Searching", 10) is False


@pytest.mark.parametrize("operation", ["get_search_results", "append_search_results", "store_search_results"])
def test_unexpected_staging_errors_propagate_unchanged(monkeypatch, operation):
    class Query:
        def select(self, *_args): return self
        def insert(self, *_args): return self
        def eq(self, *_args): return self
        def order(self, *_args, **_kwargs): return self
        def execute(self): raise TypeError("local programming failure")
        def range(self, *_args): return self

    monkeypatch.setattr(storage, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))
    args = ("job-1",) if operation == "get_search_results" else ("job-1", [{"id": "one"}])
    with pytest.raises(TypeError, match="local programming failure"):
        getattr(storage.JobStorage(), operation)(*args)


@pytest.mark.asyncio
async def test_staging_failure_marker_must_be_durable(workflow, monkeypatch):
    monkeypatch.setattr(storage.JobStorage, "append_search_results", lambda *_args: False)
    monkeypatch.setattr(storage.JobStorage, "update_job", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(dispatcher, "_search_with_progress", lambda *_args: {"ok": True, "leads": [{"id": "one"}]})
    with pytest.raises(storage.SearchResultPersistenceError, match="could not be recorded"):
        await dispatcher.run_search_workflow(
            Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders"), lambda *_args: None,
        )
    assert workflow["events"] == []


@pytest.mark.asyncio
async def test_failed_progress_metadata_does_not_skip_confirmed_result_event(workflow, monkeypatch):
    monkeypatch.setattr(storage.JobStorage, "append_search_results", lambda *_args: True)
    monkeypatch.setattr(discovery, "update_discovery_progress", lambda *_args: False)
    monkeypatch.setattr(dispatcher, "_search_with_progress", lambda *_args: {"ok": True, "leads": [{"id": "one"}]})
    await dispatcher.run_search_workflow(
        Job(id="job-1", user_id="owner", discovery_id="discovery-1", query="founders"), lambda *_args: None,
    )
    assert len(workflow["events"]) == 1


def test_invalid_staged_response_cannot_be_empty_success(monkeypatch):
    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def order(self, *_args, **_kwargs): return self
        def execute(self): return SimpleNamespace(data=None)
        def range(self, *_args): return self

    monkeypatch.setattr(storage, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))
    with pytest.raises(storage.SearchResultPersistenceError, match="invalid response shape"):
        storage.JobStorage().get_search_results("job-1")


def test_staged_results_read_all_pages_in_stable_order(monkeypatch):
    rows = [{"lead_data": {"id": str(index)}} for index in range(1201)]
    requests = []

    class Query:
        def __init__(self):
            self.orders = []
        def select(self, *_args): return self
        def eq(self, key, value):
            assert (key, value) == ("job_id", "job-1")
            return self
        def order(self, key, **_kwargs):
            self.orders.append(key)
            return self
        def range(self, start, end):
            self.bounds = (start, end)
            return self
        def execute(self):
            assert self.orders == ["rank", "id"]
            start, end = self.bounds
            requests.append(self.bounds)
            return SimpleNamespace(data=rows[start:end + 1])

    monkeypatch.setattr(storage, "get_supabase_client", lambda: SimpleNamespace(table=lambda _name: Query()))
    assert storage.JobStorage().get_search_results("job-1") == [row["lead_data"] for row in rows]
    assert requests == [(0, 499), (500, 999), (1000, 1499)]
