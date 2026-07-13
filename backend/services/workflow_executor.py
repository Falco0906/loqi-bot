"""Workflow Executor — deterministic step-by-step execution engine.

Now with:
- Retry logic (immediate/fixed/exponential)
- Error classification (retryable vs fatal)
- Pause/resume/cancel
- Resource locking
- Persistence after every state transition
"""

import time as time_module
from services.workflow_models import WorkflowPlan, WorkflowStep, StepStatus
from services.workflow_runtime import (
    RuntimeEntry, RuntimeStatus, create_runtime, get_runtime,
    update_status, add_log, set_current_step,
    record_completed_step, record_failed_step, set_pending_step,
    increment_retry_count,
)
from services.workflow_progress import calculate_progress
from services.workflow_events import (
    emit_workflow_started, emit_workflow_completed, emit_workflow_failed,
    emit_workflow_cancelled, emit_workflow_paused, emit_workflow_resumed,
    emit_step_started, emit_step_finished, emit_step_failed,
    emit_step_retrying, emit_approval_required, emit_approval_granted,
    emit_lock_conflict,
)
from services.workflow_registry import dispatch
from services.workflow_retry import (
    RetryState, classify_error, ErrorClass, should_retry,
    DEFAULT_MAX_RETRIES, DEFAULT_POLICY,
)
from services.workflow_locks import try_lock, unlock_all, is_locked
from services.workflow_persistence import persist
from services.workflow_scheduler import schedule


_PERSIST_AFTER_EVERY_STEP = True


def execute(plan: WorkflowPlan, session_token: str) -> RuntimeEntry:
    runtime = create_runtime(plan.model_dump(), session_token, plan.id)
    update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
    emit_workflow_started(runtime.workflow_id, plan.goal)
    add_log(runtime.workflow_id, "info", f"Workflow started: {plan.goal}")
    _try_persist(runtime)

    return _execute_steps(runtime, plan.steps, 0)


def _execute_steps(runtime: RuntimeEntry, steps: list, start_index: int) -> RuntimeEntry:
    total = len(runtime.plan.get("steps", []))

    for relative_idx, step_dict in enumerate(steps):
        step_index = start_index + relative_idx
        step = WorkflowStep(**step_dict) if isinstance(step_dict, dict) else step_dict
        step_dict = step.model_dump() if hasattr(step, 'model_dump') else step.__dict__

        set_current_step(runtime.workflow_id, step_index)
        runtime = get_runtime(runtime.workflow_id)

        if runtime.status == RuntimeStatus.CANCELLED:
            add_log(runtime.workflow_id, "warn", "Workflow was cancelled, stopping execution")
            return runtime

        if runtime.status == RuntimeStatus.PAUSED:
            add_log(runtime.workflow_id, "info", "Workflow was paused")
            return runtime

        emit_step_started(runtime.workflow_id, step.title, step_index)
        add_log(runtime.workflow_id, "info", f"Step {step_index + 1}/{total}: {step.title}")

        if step.approval_required:
            update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
            set_pending_step(runtime.workflow_id, step_dict)
            emit_approval_required(runtime.workflow_id, step.title, step_index)
            add_log(runtime.workflow_id, "info", f"Waiting approval for: {step.title}")
            _try_persist(runtime)
            return get_runtime(runtime.workflow_id)

        result = _execute_with_retry(runtime, step, step_dict, session_token=runtime.session_token)
        runtime = get_runtime(runtime.workflow_id)

        if not result.get("ok"):
            record_failed_step(runtime.workflow_id, step_dict, result.get("error", "Unknown error"))
            emit_step_failed(runtime.workflow_id, step.title, step_index, result.get("error", "Unknown error"))
            add_log(runtime.workflow_id, "error", f"Step failed: {step.title}: {result.get('error')}")
            update_status(runtime.workflow_id, RuntimeStatus.FAILED)
            _try_persist(runtime)
            return get_runtime(runtime.workflow_id)

        record_completed_step(runtime.workflow_id, step_dict, result)
        emit_step_finished(runtime.workflow_id, step.title, step_index, result)

    update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
    emit_workflow_completed(runtime.workflow_id, runtime.plan.get("goal", ""))
    add_log(runtime.workflow_id, "info", "Workflow completed successfully")
    unlock_all(runtime.workflow_id)
    _try_persist(runtime)
    return get_runtime(runtime.workflow_id)


def _execute_with_retry(runtime: RuntimeEntry, step: WorkflowStep, step_dict: dict, session_token: str) -> dict:
    retry_state = RetryState(max_retries=DEFAULT_MAX_RETRIES, policy=DEFAULT_POLICY)

    while True:
        start = time_module.time()
        result = dispatch(step.action_type, step, session_token)
        duration = time_module.time() - start

        if result.get("ok"):
            return result

        error = result.get("error", "Unknown error")
        error_class = classify_error(error)

        if error_class == ErrorClass.FATAL:
            add_log(runtime.workflow_id, "error", f"Fatal error (no retry): {error}")
            return result

        if not retry_state.can_retry():
            add_log(runtime.workflow_id, "error", f"Retries exhausted for {step.title}")
            return result

        delay = retry_state.next_delay()
        increment_retry_count(runtime.workflow_id)
        emit_step_retrying(runtime.workflow_id, step.title, runtime.current_step_index,
                           retry_state.current_attempt, retry_state.max_retries, delay)
        add_log(runtime.workflow_id, "warn", f"Retrying {step.title} in {delay}s (attempt {retry_state.current_attempt}/{retry_state.max_retries}): {error}")
        _try_persist(runtime)

        if delay > 0:
            time_module.sleep(delay)


def approve(workflow_id: str) -> RuntimeEntry:
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise ValueError(f"Workflow not found: {workflow_id}")
    if runtime.status != RuntimeStatus.WAITING_APPROVAL:
        raise ValueError(f"Workflow {workflow_id} is not waiting for approval (status: {runtime.status.value})")

    pending = runtime.pending_step
    if not pending:
        raise ValueError(f"Workflow {workflow_id} has no pending step to approve")

    emit_approval_granted(workflow_id, pending.get("title", ""), runtime.current_step_index)
    add_log(workflow_id, "info", f"Approval granted for: {pending.get('title')}")
    set_pending_step(workflow_id, None)
    update_status(workflow_id, RuntimeStatus.RUNNING)

    step = WorkflowStep(**pending)
    step_dict = pending

    result = _execute_with_retry(runtime, step, step_dict, session_token=runtime.session_token)
    runtime = get_runtime(workflow_id)

    if not result.get("ok"):
        record_failed_step(workflow_id, step_dict, result.get("error", "Unknown error"))
        emit_step_failed(workflow_id, step.title, runtime.current_step_index, result.get("error", "Unknown error"))
        add_log(workflow_id, "error", f"Step failed after approval: {step.title}: {result.get('error')}")
        update_status(workflow_id, RuntimeStatus.FAILED)
        _try_persist(runtime)
        return get_runtime(workflow_id)

    record_completed_step(workflow_id, step_dict, result)
    emit_step_finished(workflow_id, step.title, runtime.current_step_index, result)

    remaining = runtime.plan.get("steps", [])[runtime.current_step_index + 1:]
    if not remaining:
        update_status(workflow_id, RuntimeStatus.COMPLETED)
        emit_workflow_completed(workflow_id, runtime.plan.get("goal", ""))
        add_log(workflow_id, "info", "Workflow completed successfully")
        unlock_all(workflow_id)
        _try_persist(runtime)
        return get_runtime(workflow_id)

    plan = WorkflowPlan(**runtime.plan)
    return _execute_steps(runtime, remaining, runtime.current_step_index + 1)


def execute_remaining(plan: WorkflowPlan, session_token: str, start_index: int) -> RuntimeEntry:
    existing = get_runtime(plan.id)
    runtime = existing if existing else create_runtime(plan.model_dump(), session_token, plan.id)

    if runtime.status == RuntimeStatus.PLANNED:
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)

    steps = plan.steps[start_index:]
    return _execute_steps(runtime, steps, start_index)


def pause(workflow_id: str) -> RuntimeEntry:
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise ValueError(f"Workflow not found: {workflow_id}")
    if runtime.status not in (RuntimeStatus.RUNNING, RuntimeStatus.RETRYING):
        raise ValueError(f"Cannot pause workflow in state: {runtime.status.value}")

    update_status(runtime.workflow_id, RuntimeStatus.PAUSED)
    emit_workflow_paused(workflow_id)
    add_log(workflow_id, "info", "Workflow paused by user")
    _try_persist(runtime)
    return get_runtime(workflow_id)


def resume(workflow_id: str) -> RuntimeEntry:
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise ValueError(f"Workflow not found: {workflow_id}")
    if runtime.status != RuntimeStatus.PAUSED:
        raise ValueError(f"Cannot resume workflow in state: {runtime.status.value}")

    update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
    emit_workflow_resumed(workflow_id)
    add_log(workflow_id, "info", "Workflow resumed by user")

    remaining = runtime.plan.get("steps", [])[runtime.current_step_index:]
    plan = WorkflowPlan(**runtime.plan)
    return _execute_steps(runtime, remaining, runtime.current_step_index)


def cancel(workflow_id: str) -> RuntimeEntry:
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise ValueError(f"Workflow not found: {workflow_id}")
    if runtime.status in (RuntimeStatus.COMPLETED, RuntimeStatus.CANCELLED, RuntimeStatus.FAILED):
        raise ValueError(f"Cannot cancel workflow in state: {runtime.status.value}")

    update_status(runtime.workflow_id, RuntimeStatus.CANCELLED)
    emit_workflow_cancelled(workflow_id)
    add_log(workflow_id, "info", "Workflow cancelled by user")
    unlock_all(workflow_id)
    _try_persist(runtime)
    return get_runtime(workflow_id)


def _try_persist(runtime: RuntimeEntry) -> None:
    if _PERSIST_AFTER_EVERY_STEP:
        try:
            persist(runtime)
        except Exception as e:
            print(f"[workflow_executor] persist failed: {e}")
