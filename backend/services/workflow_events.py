"""Workflow Events — every execution emits events.

Events become the source for:
- Mission Control
- Activity Feed
- Copilot context
- later: audit trail

Every event has a sequence_number for efficient polling.
"""

from datetime import datetime, timezone
from enum import Enum
from threading import Lock


class EventType(str, Enum):
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_RECOVERED = "workflow_recovered"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    STEP_RETRYING = "step_retrying"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    WAITING = "waiting"
    LOG = "log"
    LOCK_CONFLICT = "lock_conflict"


_event_stores: dict[str, list[dict]] = {}
_sequences: dict[str, int] = {}
_event_lock = Lock()


def emit(workflow_id: str, event_type: EventType, message: str, metadata: dict | None = None) -> dict:
    with _event_lock:
        if workflow_id not in _event_stores:
            _event_stores[workflow_id] = []
        seq = _sequences.get(workflow_id, 0) + 1
        _sequences[workflow_id] = seq
        event = {
            "sequence_number": seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type.value,
            "message": message,
            "metadata": metadata or {},
        }
        _event_stores[workflow_id].append(event)
    return event


def get_events(workflow_id: str, limit: int = 50, after_sequence: int = 0) -> list[dict]:
    with _event_lock:
        events = _event_stores.get(workflow_id, [])
    if after_sequence > 0:
        events = [e for e in events if e.get("sequence_number", 0) > after_sequence]
    return list(reversed(events))[:limit]


def get_all_events(workflow_id: str) -> list[dict]:
    with _event_lock:
        return list(_event_stores.get(workflow_id, []))


def get_latest_sequence(workflow_id: str) -> int:
    with _event_lock:
        return _sequences.get(workflow_id, 0)


def clear(workflow_id: str | None = None) -> None:
    with _event_lock:
        if workflow_id:
            _event_stores.pop(workflow_id, None)
            _sequences.pop(workflow_id, None)
        else:
            _event_stores.clear()
            _sequences.clear()


def restore_events(workflow_id: str, events: list[dict]) -> None:
    with _event_lock:
        _event_stores[workflow_id] = list(events)
        if events:
            _sequences[workflow_id] = max(e.get("sequence_number", 0) for e in events)


def emit_workflow_started(workflow_id: str, goal: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_STARTED, f"Started: {goal}")


def emit_workflow_completed(workflow_id: str, goal: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_COMPLETED, f"Completed: {goal}")


def emit_workflow_failed(workflow_id: str, error: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_FAILED, f"Failed: {error}")


def emit_workflow_cancelled(workflow_id: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_CANCELLED, "Cancelled by user")


def emit_workflow_paused(workflow_id: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_PAUSED, "Paused")


def emit_workflow_resumed(workflow_id: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_RESUMED, "Resumed")


def emit_workflow_recovered(workflow_id: str) -> dict:
    return emit(workflow_id, EventType.WORKFLOW_RECOVERED, "Recovered after restart")


def emit_step_started(workflow_id: str, step_title: str, step_index: int) -> dict:
    return emit(workflow_id, EventType.STEP_STARTED, f"Executing: {step_title}", {"step_index": step_index})


def emit_step_finished(workflow_id: str, step_title: str, step_index: int, result: dict | None = None) -> dict:
    return emit(workflow_id, EventType.STEP_FINISHED, f"Finished: {step_title}", {"step_index": step_index, "result": result})


def emit_step_failed(workflow_id: str, step_title: str, step_index: int, error: str) -> dict:
    return emit(workflow_id, EventType.STEP_FAILED, f"Failed: {step_title}", {"step_index": step_index, "error": error})


def emit_step_retrying(workflow_id: str, step_title: str, step_index: int, attempt: int, max_retries: int, delay: float) -> dict:
    return emit(workflow_id, EventType.STEP_RETRYING, f"Retrying ({attempt}/{max_retries}): {step_title}",
                {"step_index": step_index, "attempt": attempt, "max_retries": max_retries, "delay_seconds": delay})


def emit_approval_required(workflow_id: str, step_title: str, step_index: int) -> dict:
    return emit(workflow_id, EventType.APPROVAL_REQUIRED, f"Waiting for approval: {step_title}", {"step_index": step_index})


def emit_approval_granted(workflow_id: str, step_title: str, step_index: int) -> dict:
    return emit(workflow_id, EventType.APPROVAL_GRANTED, f"Approved: {step_title}", {"step_index": step_index})


def emit_lock_conflict(workflow_id: str, resource: str) -> dict:
    return emit(workflow_id, EventType.LOCK_CONFLICT, f"Resource locked: {resource}", {"resource": resource})
