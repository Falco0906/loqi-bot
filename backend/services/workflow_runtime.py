"""Workflow Runtime — single source of truth for execution state.

Stores ONLY execution state, not business data.
PAUSED status, metrics accumulation, history queries, thread-safe.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from typing import Optional
from threading import Lock


class RuntimeStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {RuntimeStatus.RUNNING, RuntimeStatus.WAITING_APPROVAL, RuntimeStatus.RETRYING}
TERMINAL_STATUSES = {RuntimeStatus.COMPLETED, RuntimeStatus.FAILED, RuntimeStatus.CANCELLED}


class RuntimeEntry:
    def __init__(self, plan: dict, session_token: str, workflow_id: str | None = None):
        now = datetime.now(timezone.utc)
        self.workflow_id: str = workflow_id or plan.get("id", "") or str(uuid4())[:8]
        self.session_token: str = session_token
        self.plan: dict = plan
        self.status: RuntimeStatus = RuntimeStatus.PLANNED
        self.current_step_index: int = -1
        self.completed_steps: list[dict] = []
        self.failed_steps: list[dict] = []
        self.pending_step: Optional[dict] = None
        self.logs: list[dict] = []
        self.events: list[dict] = []
        self.metrics: dict = {
            "step_durations": [],
            "retry_count": 0,
            "failure_count": 0,
            "cancel_count": 0,
            "approval_wait_start": None,
            "total_approval_wait_seconds": 0,
            "workflow_duration_seconds": None,
        }
        self.started_at: Optional[str] = None
        self.updated_at: str = now.isoformat()
        self.completed_at: Optional[str] = None
        self.resource_locks: list[str] = []

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "session_token": self.session_token,
            "plan": self.plan,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "pending_step": self.pending_step,
            "logs": self.logs,
            "events": self.events,
            "metrics": dict(self.metrics),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "resource_locks": list(self.resource_locks),
        }

    def summary(self) -> dict:
        steps = self.plan.get("steps", [])
        return {
            "workflow_id": self.workflow_id,
            "plan_goal": self.plan.get("goal", ""),
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "completed_steps": len(self.completed_steps),
            "failed_steps": len(self.failed_steps),
            "total_steps": len(steps),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeEntry":
        entry = cls(data.get("plan", {}), data.get("session_token", ""), data.get("workflow_id"))
        entry.status = RuntimeStatus(data.get("status", "planned"))
        entry.current_step_index = data.get("current_step_index", -1)
        entry.completed_steps = list(data.get("completed_steps", []))
        entry.failed_steps = list(data.get("failed_steps", []))
        entry.pending_step = data.get("pending_step")
        entry.logs = list(data.get("logs", []))
        entry.events = list(data.get("events", []))
        entry.metrics = dict(data.get("metrics", {}))
        entry.started_at = data.get("started_at")
        entry.updated_at = data.get("updated_at", datetime.now(timezone.utc).isoformat())
        entry.completed_at = data.get("completed_at")
        entry.resource_locks = list(data.get("resource_locks", []))
        return entry


_runtimes: dict[str, RuntimeEntry] = {}
_runtime_lock = Lock()


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _runtime_lock:
            return fn(*args, **kwargs)
    return wrapper


def create_runtime(plan, session_token: str, workflow_id: str | None = None) -> RuntimeEntry:
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump()
    elif hasattr(plan, "get"):
        plan = dict(plan)
    entry = RuntimeEntry(plan, session_token, workflow_id)
    with _runtime_lock:
        _runtimes[entry.workflow_id] = entry
    return entry


def get_runtime(workflow_id: str) -> Optional[RuntimeEntry]:
    with _runtime_lock:
        return _runtimes.get(workflow_id)


def get_active_runtimes(session_token: str) -> list[RuntimeEntry]:
    with _runtime_lock:
        return [
            r for r in _runtimes.values()
            if r.session_token == session_token and r.status in ACTIVE_STATUSES
        ]


def get_all_runtimes(session_token: str) -> list[RuntimeEntry]:
    with _runtime_lock:
        return [r for r in _runtimes.values() if r.session_token == session_token]


def get_all_workflows() -> list[RuntimeEntry]:
    with _runtime_lock:
        return list(_runtimes.values())


def update_status(workflow_id: str, status: RuntimeStatus) -> bool:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        _do_update_status(entry, status)
    return True


def _do_update_status(entry: RuntimeEntry, status: RuntimeStatus) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    old_status = entry.status
    entry.status = status
    entry.updated_at = now_iso

    if status == RuntimeStatus.RUNNING and not entry.started_at:
        entry.started_at = now_iso

    if status in TERMINAL_STATUSES:
        entry.completed_at = now_iso
        if entry.started_at:
            try:
                start = datetime.fromisoformat(entry.started_at.replace("Z", "+00:00"))
                entry.metrics["workflow_duration_seconds"] = int((now - start).total_seconds())
            except (ValueError, TypeError):
                pass

    if status == RuntimeStatus.WAITING_APPROVAL:
        entry.metrics["approval_wait_start"] = now_iso

    if status == RuntimeStatus.RUNNING and entry.metrics.get("approval_wait_start"):
        try:
            wait_start = datetime.fromisoformat(entry.metrics["approval_wait_start"].replace("Z", "+00:00"))
            entry.metrics["total_approval_wait_seconds"] += int((now - wait_start).total_seconds())
        except (ValueError, TypeError):
            pass
        entry.metrics["approval_wait_start"] = None

    add_log_locked(entry, "info", f"Status: {old_status.value} -> {status.value}")


def add_log(workflow_id: str, level: str, message: str, metadata: dict | None = None) -> bool:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        add_log_locked(entry, level, message, metadata)
    return True


def add_log_locked(entry: RuntimeEntry, level: str, message: str, metadata: dict | None = None) -> None:
    entry.logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "metadata": metadata or {},
    })
    entry.updated_at = datetime.now(timezone.utc).isoformat()


def set_current_step(workflow_id: str, step_index: int) -> bool:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        entry.current_step_index = step_index
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def _step_dict(step) -> dict:
    if isinstance(step, dict):
        return step
    if hasattr(step, "model_dump"):
        return step.model_dump()
    if hasattr(step, "__dict__"):
        return step.__dict__
    return {"id": "", "title": str(step), "action_type": ""}


def record_completed_step(workflow_id: str, step, result: dict, duration_seconds: float = 0) -> bool:
    sd = _step_dict(step)
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        entry.completed_steps.append({
            "step_id": sd.get("id", ""),
            "title": sd.get("title", ""),
            "action_type": sd.get("action_type", ""),
            "result": result,
            "duration_seconds": duration_seconds,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        if duration_seconds > 0:
            entry.metrics["step_durations"].append(duration_seconds)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def record_failed_step(workflow_id: str, step, error: str) -> bool:
    sd = _step_dict(step)
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        entry.failed_steps.append({
            "step_id": sd.get("id", ""),
            "title": sd.get("title", ""),
            "action_type": sd.get("action_type", ""),
            "error": error,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })
        entry.metrics["failure_count"] += 1
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def set_pending_step(workflow_id: str, step) -> bool:
    sd = _step_dict(step) if step is not None else None
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        entry.pending_step = sd
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def increment_retry_count(workflow_id: str) -> int:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return 0
        entry.metrics["retry_count"] += 1
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        return entry.metrics["retry_count"]


def increment_cancel_count(workflow_id: str) -> int:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return 0
        entry.metrics["cancel_count"] += 1
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        return entry.metrics["cancel_count"]


def acquire_lock(workflow_id: str, resource: str) -> bool:
    with _runtime_lock:
        for existing in _runtimes.values():
            if existing.workflow_id != workflow_id and resource in existing.resource_locks and existing.status in ACTIVE_STATUSES:
                return False
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        if resource not in entry.resource_locks:
            entry.resource_locks.append(resource)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def release_lock(workflow_id: str, resource: str) -> bool:
    with _runtime_lock:
        entry = _runtimes.get(workflow_id)
        if not entry:
            return False
        if resource in entry.resource_locks:
            entry.resource_locks.remove(resource)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
    return True


def has_active_lock(resource: str, exclude_workflow_id: str | None = None) -> bool:
    with _runtime_lock:
        for entry in _runtimes.values():
            if entry.workflow_id == exclude_workflow_id:
                continue
            if resource in entry.resource_locks and entry.status in ACTIVE_STATUSES:
                return True
    return False


def remove_runtime(workflow_id: str) -> bool:
    with _runtime_lock:
        if workflow_id in _runtimes:
            del _runtimes[workflow_id]
            return True
    return False


def restore_runtime(entry: RuntimeEntry) -> None:
    with _runtime_lock:
        _runtimes[entry.workflow_id] = entry


def clear() -> None:
    with _runtime_lock:
        _runtimes.clear()


def get_history(session_token: str, status_filter: str | None = None, limit: int = 50) -> list[dict]:
    with _runtime_lock:
        results = [r for r in _runtimes.values() if r.session_token == session_token]
    if status_filter:
        results = [r for r in results if r.status.value == status_filter]
    results.sort(key=lambda r: r.updated_at or "", reverse=True)
    return [r.summary() for r in results[:limit]]
