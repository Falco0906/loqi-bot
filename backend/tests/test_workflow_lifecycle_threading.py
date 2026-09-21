"""Concurrency coverage for worker-owned legacy workflow lifecycle guards."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.workflows.api as workflow_api
import services.workflows.executor as workflow_executor
import services.workflows.recovery as workflow_recovery
import services.workflows.runtime as workflow_runtime
import services.workflows.service as workflow_service
from services.workflows.models import ActionType, WorkflowPlan, WorkflowStep


SESSION = "workflow-threading-session"


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": f"Bearer {SESSION}"})


def _plan(workflow_id: str, *, approval_required: bool = False) -> WorkflowPlan:
    return WorkflowPlan(
        id=workflow_id,
        goal="Threading test",
        reasoning="",
        steps=[WorkflowStep(
            id=f"{workflow_id}-step",
            title="Blocking step",
            action_type=ActionType.SEARCH_LEADS,
            approval_required=approval_required,
        )],
    )


@pytest.fixture(autouse=True)
def _clean_runtime_state(monkeypatch):
    workflow_runtime.clear()
    monkeypatch.setattr(workflow_executor, "persist", lambda _runtime: True)
    monkeypatch.setattr(workflow_service, "publish", lambda *_args, **_kwargs: None)
    yield
    workflow_runtime.clear()


async def _wait_for(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 1), "blocking dispatcher did not start"


@pytest.mark.asyncio
async def test_execute_dispatch_does_not_block_event_loop(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    progressed = asyncio.Event()

    def blocking_dispatch(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=1)
        return {"ok": True}

    monkeypatch.setattr(workflow_executor, "dispatch", blocking_dispatch)
    operation = asyncio.create_task(workflow_service.start_workflow_async(
        session_token=SESSION,
        plan_id="execute-threading",
        goal="Threading test",
        steps=[_plan("execute-threading").steps[0].model_dump()],
    ))
    await _wait_for(entered)

    async def unrelated_coroutine():
        await asyncio.sleep(0)
        progressed.set()

    await unrelated_coroutine()
    assert progressed.is_set()
    release.set()
    assert (await operation)["status"] == "completed"


async def _prepare_waiting_runtime(workflow_id: str) -> None:
    runtime = workflow_runtime.create_runtime(_plan(workflow_id).model_dump(), SESSION, workflow_id)
    workflow_runtime.set_current_step(runtime.workflow_id, 0)
    workflow_runtime.update_status(runtime.workflow_id, workflow_runtime.RuntimeStatus.WAITING_APPROVAL)
    workflow_runtime.set_pending_step(runtime.workflow_id, runtime.plan["steps"][0])


async def _prepare_paused_runtime(workflow_id: str) -> None:
    runtime = workflow_runtime.create_runtime(_plan(workflow_id).model_dump(), SESSION, workflow_id)
    workflow_runtime.set_current_step(runtime.workflow_id, 0)
    workflow_runtime.update_status(runtime.workflow_id, workflow_runtime.RuntimeStatus.PAUSED)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["approve", "resume"])
async def test_concurrent_execution_operations_run_the_step_once(monkeypatch, operation):
    workflow_id = f"{operation}-concurrent"
    if operation == "approve":
        await _prepare_waiting_runtime(workflow_id)
        route = workflow_api.approve_workflow_step
    else:
        await _prepare_paused_runtime(workflow_id)
        route = workflow_api.resume_workflow_endpoint

    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def blocking_dispatch(*_args, **_kwargs):
        calls.append("dispatch")
        entered.set()
        assert release.wait(timeout=1)
        return {"ok": True}

    monkeypatch.setattr(workflow_executor, "dispatch", blocking_dispatch)
    first = asyncio.create_task(route("ignored", workflow_id, _request()))
    await _wait_for(entered)
    second = asyncio.create_task(route("ignored", workflow_id, _request()))
    await asyncio.sleep(0)
    assert not second.done()

    release.set()
    assert (await first)["status"] == "completed"
    with pytest.raises(HTTPException) as error:
        await second
    assert error.value.status_code == 400
    assert calls == ["dispatch"]


@pytest.mark.asyncio
async def test_pause_and_cancel_wait_for_active_execution(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocking_dispatch(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=1)
        return {"ok": True}

    monkeypatch.setattr(workflow_executor, "dispatch", blocking_dispatch)
    workflow_id = "pause-cancel-concurrent"
    execution = asyncio.create_task(workflow_service.start_workflow_async(
        session_token=SESSION,
        plan_id=workflow_id,
        goal="Threading test",
        steps=[_plan(workflow_id).steps[0].model_dump()],
    ))
    await _wait_for(entered)
    pause = asyncio.create_task(workflow_api.pause_workflow_endpoint("ignored", workflow_id, _request()))
    cancel = asyncio.create_task(workflow_api.cancel_workflow_endpoint("ignored", workflow_id, _request()))
    await asyncio.sleep(0)
    assert not pause.done()
    assert not cancel.done()

    release.set()
    assert (await execution)["status"] == "completed"
    for operation in (pause, cancel):
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_cancelled_await_does_not_release_worker_owned_guard(monkeypatch):
    workflow_id = "cancelled-request"
    await _prepare_waiting_runtime(workflow_id)
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def blocking_dispatch(*_args, **_kwargs):
        calls.append("dispatch")
        entered.set()
        assert release.wait(timeout=1)
        return {"ok": True}

    monkeypatch.setattr(workflow_executor, "dispatch", blocking_dispatch)
    first = asyncio.create_task(workflow_service.approve_workflow_for_session_async(workflow_id, SESSION))
    await _wait_for(entered)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(workflow_service.approve_workflow_for_session_async(workflow_id, SESSION))
    await asyncio.sleep(0)
    assert not second.done()
    assert calls == ["dispatch"]

    release.set()
    with pytest.raises(ValueError):
        await second
    assert calls == ["dispatch"]


@pytest.mark.asyncio
async def test_url_ownership_is_checked_before_queueing_and_inside_worker(monkeypatch):
    workflow_id = "foreign-workflow"
    await _prepare_waiting_runtime(workflow_id)
    called = False

    def dispatch(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(workflow_executor, "dispatch", dispatch)
    foreign_request = SimpleNamespace(headers={"authorization": "Bearer foreign-session"})

    with pytest.raises(HTTPException) as route_error:
        await workflow_api.approve_workflow_step("ignored", workflow_id, foreign_request)
    assert route_error.value.status_code == 404
    assert called is False

    with pytest.raises(workflow_service.WorkflowNotFoundError):
        await workflow_service.approve_workflow_for_session_async(workflow_id, "foreign-session")
    assert called is False


def test_lifecycle_guard_slots_are_reclaimed_for_terminal_and_removed_runtimes():
    for status in (
        workflow_runtime.RuntimeStatus.COMPLETED,
        workflow_runtime.RuntimeStatus.FAILED,
        workflow_runtime.RuntimeStatus.CANCELLED,
    ):
        workflow_id = f"terminal-{status.value}"
        runtime = workflow_runtime.create_runtime(_plan(workflow_id).model_dump(), SESSION, workflow_id)
        workflow_runtime.update_status(runtime.workflow_id, status)
        workflow_runtime.run_lifecycle_operation(workflow_id, lambda: None)
        assert workflow_id not in workflow_runtime._lifecycle_operation_slots

    removed_id = "removed-runtime"
    workflow_runtime.create_runtime(_plan(removed_id).model_dump(), SESSION, removed_id)
    assert workflow_runtime.remove_runtime(removed_id)
    workflow_runtime.run_lifecycle_operation(removed_id, lambda: None)
    assert removed_id not in workflow_runtime._lifecycle_operation_slots

    waiting_id = "waiting-runtime"
    workflow_runtime.create_runtime(_plan(waiting_id).model_dump(), SESSION, waiting_id)
    workflow_runtime.run_lifecycle_operation(waiting_id, lambda: None)
    assert waiting_id in workflow_runtime._lifecycle_operation_slots
    workflow_runtime.clear()
    assert waiting_id not in workflow_runtime._lifecycle_operation_slots


def test_recovery_executes_running_workflow_through_lifecycle_guard(monkeypatch):
    entry = workflow_runtime.RuntimeEntry(_plan("recovery-guard").model_dump(), SESSION, "recovery-guard")
    entry.status = workflow_runtime.RuntimeStatus.RUNNING
    calls: list[str] = []
    monkeypatch.setattr(workflow_recovery, "load_all", lambda: [entry])
    monkeypatch.setattr(workflow_recovery, "restore_runtime", lambda _entry: None)
    monkeypatch.setattr(workflow_recovery, "restore_events", lambda *_args: None)
    monkeypatch.setattr(workflow_recovery, "emit_workflow_recovered", lambda *_args: None)

    def guarded(workflow_id, operation, *args):
        calls.append(workflow_id)
        return operation(*args)

    monkeypatch.setattr(workflow_recovery, "run_lifecycle_operation", guarded)
    monkeypatch.setattr(workflow_executor, "execute_remaining", lambda *_args: None)

    result = workflow_recovery.recover_all()

    assert result["resumed"] == 1
    assert calls == ["recovery-guard"]
