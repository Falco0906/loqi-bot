"""Offline leased-job/result recovery contracts; no provider or database calls."""
import asyncio
import copy
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from services.leads import generation, service
from services.intelligence import ai
from services.job_engine.models import JobStatus
from services.job_engine.runner import BackgroundRunner


def evidence(ids):
    return {"business_guidance": {"items": []}, "results": [
        {"lead": {"id": identity}, "status": "completed", "facts": [{"label": "Company", "value": identity}],
         "observed_signals": [], "derived_assessment": {}} for identity in ids
    ]}


@pytest.fixture
def durable_jobs(monkeypatch):
    monkeypatch.setattr(generation.get_registry(), "_workflows", dict(generation.get_registry()._workflows))
    class Storage:
        def __init__(self): self.rows = {}; self.lock = threading.Lock(); self.creates = 0
        def get_job(self, identity, *, strict=False): return copy.deepcopy(self.rows.get(identity))
        def create_job(self, job, *, strict=False):
            assert strict
            with self.lock:
                if job.id not in self.rows:
                    self.rows[job.id] = copy.deepcopy(job); self.creates += 1
                return copy.deepcopy(self.rows[job.id])
        def update_job(self, identity, *, strict=False, lease_owner="", **updates):
            assert strict
            job = self.rows[identity]
            assert job.lease_owner == lease_owner
            for key, value in updates.items(): setattr(job, key, copy.deepcopy(value))
            return True
        def claimed(self, identity, owner="worker"):
            job = self.rows[identity]; job.status = JobStatus.RUNNING; job.lease_owner = owner
            return copy.deepcopy(job)

    storage = Storage()
    monkeypatch.setattr(generation.job_manager, "_storage", storage)
    monkeypatch.setattr("services.workspace.access.resolve_workspace_context", lambda _client, actor, workspace: SimpleNamespace(workspace_id=workspace))
    class Leads:
        async def get_for_workspace(self, identity, workspace):
            return SimpleNamespace(id=identity, deleted_at=None) if not identity.startswith("foreign") else None
    monkeypatch.setattr(generation, "WorkspaceLeadRepository", Leads)
    async def analysis(workspace, actor, ids): return evidence(ids)
    monkeypatch.setattr(generation, "analyze_workspace_leads", analysis)
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", lambda _bundle: {"strategy": {}, "outreach": {"subject": "Hi", "body": "Hello"}, "evidence_used": []})
    return storage


@pytest.mark.asyncio
async def test_concurrent_retries_use_one_durable_job_and_conflicting_selection_rejected(durable_jobs):
    states = await asyncio.gather(*(generation.start_lead_generation("workspace", "actor", ["one", "two"], "intent") for _ in range(8)))
    assert durable_jobs.creates == 1 and len({state["job_id"] for state in states}) == 1
    with pytest.raises(HTTPException) as caught:
        await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_lost_response_recovers_operation_without_model_reexecution(durable_jobs, monkeypatch):
    original = generation.generation_status
    async def lost_response(*_args): raise httpx.ReadTimeout("HTTP response lost")
    monkeypatch.setattr(generation, "generation_status", lost_response)
    with pytest.raises(httpx.ReadTimeout):
        await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    monkeypatch.setattr(generation, "generation_status", original)
    state = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    result = await generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None)
    durable_jobs.rows[state["job_id"]].result = result["result"]
    durable_jobs.rows[state["job_id"]].status = JobStatus.COMPLETED
    calls = AsyncMock(side_effect=AssertionError("Completed operation must not regenerate"))
    monkeypatch.setattr(generation, "analyze_workspace_leads", calls)
    recovered = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    assert recovered["results"][0]["status"] == "completed" and durable_jobs.creates == 1
    calls.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_wait_timeout_does_not_cancel_durable_generation(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    entered, release = threading.Event(), threading.Event()
    def slow_provider(_evidence):
        entered.set(); assert release.wait(2)
        return {"strategy": {}, "outreach": {"subject": "Hi", "body": "Hello"}}
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", slow_provider)
    task = asyncio.create_task(generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        with pytest.raises(asyncio.TimeoutError): await asyncio.wait_for(asyncio.shield(task), 0.01)
        assert not task.done()
    finally:
        release.set()
    assert (await task)["ok"]
    assert (await generation.generation_status("workspace", "actor", state["job_id"]))["results"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_partial_failure_has_saved_success_and_typed_provider_timeout(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one", "two"], "intent")
    def provider(bundle):
        if bundle["facts"][0]["value"] == "two":
            raise ai.OpenAIError("private provider detail", kind="provider_timeout")
        return {"strategy": {}, "outreach": {"subject": "Hi", "body": "Hello"}}
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", provider)
    result = await generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None)
    assert result["ok"] and result["result"]["outcome"] == "partial"
    assert result["result"]["completed"] == result["result"]["failed"] == 1
    assert result["result"]["results"][1]["error_kind"] == "provider_timeout"
    assert "private provider" not in str(result)


@pytest.mark.asyncio
async def test_interrupted_worker_reuses_evidence_and_skips_checkpointed_leads(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one", "two"], "intent")
    calls = []
    def provider(bundle):
        identity = bundle["facts"][0]["value"]; calls.append(identity)
        if identity == "two" and calls.count("two") == 1: raise RuntimeError("worker interrupted")
        return {"strategy": {}, "outreach": {"subject": "Hi", "body": "Hello"}}
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", provider)
    with pytest.raises(RuntimeError): await generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None)
    monkeypatch.setattr(generation, "analyze_workspace_leads", AsyncMock(side_effect=AssertionError("Do not hydrate twice")))
    assert (await generation.run_lead_generation(durable_jobs.claimed(state["job_id"], "new-worker"), None))["ok"]
    assert calls == ["one", "two", "two"]


@pytest.mark.asyncio
async def test_worker_failure_is_terminal_and_does_not_erase_saved_partial_results(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one", "two"], "intent")
    runner = BackgroundRunner(durable_jobs)
    job = durable_jobs.claimed(state["job_id"], runner.worker_id)
    def provider(bundle):
        if bundle["facts"][0]["value"] == "two": raise RuntimeError("private programming failure")
        return {"strategy": {}, "outreach": {"subject": "Hi", "body": "Hello"}}
    monkeypatch.setattr(ai, "generate_evidence_grounded_lead_strategy", provider)
    await runner._run_wrapper(job, generation.run_lead_generation, claimed=True)
    recovered = await generation.generation_status("workspace", "actor", job.id)
    assert recovered["status"] == "failed" and len(recovered["results"]) == 1
    assert "private programming" not in recovered["error"]


@pytest.mark.asyncio
async def test_workspace_isolation_and_foreign_lead_rejection(durable_jobs):
    with pytest.raises(service.LeadImportError):
        await generation.start_lead_generation("workspace", "actor", ["foreign-lead"], "intent")
    assert durable_jobs.creates == 0
    state = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    for workspace, actor in [("other-workspace", "actor"), ("workspace", "other-actor")]:
        with pytest.raises(HTTPException) as caught: await generation.generation_status(workspace, actor, state["job_id"])
        assert caught.value.status_code == 404


def test_csv_company_facts_are_present_without_global_projection():
    row = SimpleNamespace(id="one", first_name="Ada", last_name="", email="", title="CEO", phone="", linkedin_url="",
                          metadata={"csv_import": {"company": "Acme", "website": "https://acme.test", "industry": "Software", "location": "India"}, "source_provenance": ["csv"]})
    lead = service._canonical_analysis_lead(row)
    assert lead["company"] == "Acme" and lead["industry"] == "Software" and lead["source_provenance"] == ["csv"]
    assert {fact["label"]: fact["value"] for fact in service._facts(lead)}["Website"] == "https://acme.test"


@pytest.mark.asyncio
async def test_resumed_evidence_does_not_bypass_workspace_authorization(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    durable_jobs.rows[state["job_id"]].result["analysis"] = evidence(["one"])
    from services.workspace.access import WorkspaceAccessDenied
    def denied(*_args): raise WorkspaceAccessDenied("workspace")
    monkeypatch.setattr("services.workspace.access.resolve_workspace_context", denied)
    with pytest.raises(WorkspaceAccessDenied):
        await generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None)


@pytest.mark.asyncio
async def test_context_loading_failure_remains_a_worker_failure_not_empty_context(durable_jobs, monkeypatch):
    state = await generation.start_lead_generation("workspace", "actor", ["one"], "intent")
    error = RuntimeError("Knowledge loading failed")
    monkeypatch.setattr(generation, "analyze_workspace_leads", AsyncMock(side_effect=error))
    with pytest.raises(RuntimeError) as caught:
        await generation.run_lead_generation(durable_jobs.claimed(state["job_id"]), None)
    assert caught.value is error and durable_jobs.rows[state["job_id"]].result == {"results": []}


@pytest.mark.asyncio
async def test_claims_respect_bounded_selected_generation_capacity(monkeypatch):
    from services.job_engine.manager import JobManager
    from services.job_engine.models import Job
    manager = JobManager()
    registry = generation.get_registry()
    monkeypatch.setattr(registry, "_workflows", {})
    generation.register_lead_generation_workflow()
    calls = []
    class Storage:
        def claim_due_jobs(self, owner, types, **kwargs):
            if not types: return []
            assert kwargs["strict"]
            calls.append(kwargs["limit"])
            return [Job(id=str(i), type="lead_strategy") for i in range(kwargs["limit"])]
    manager._storage = Storage()
    def start(job, **kwargs):
        assert kwargs["claimed"]
        manager._runner._lead_tasks.add(job.id)
    monkeypatch.setattr(manager._runner, "start_job", start)
    assert await manager.start_due_jobs() == 2
    assert await manager.start_due_jobs() == 0
    assert calls == [2]
