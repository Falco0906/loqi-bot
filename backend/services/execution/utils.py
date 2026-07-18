"""Execution Engine utility functions.

Shared helpers for session initialization, ID generation, and
common data transformations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.execution.enums import TaskState
from services.execution.execution_models import (
    ExecutionMetrics,
    ExecutionSession,
    ExecutionTask,
    RetryPolicy,
    InDegreeEntry,
)


def generate_session_id() -> str:
    """Generate a unique session identifier."""
    return uuid4().hex[:12]


def build_in_degree_map(tasks: dict[str, ExecutionTask]) -> dict[str, InDegreeEntry]:
    """Build the in-degree map for DAG scheduling.

    For each task, counts how many of its dependencies are not yet
    satisfied. Tasks with no dependencies have in-degree 0.
    """
    degree_map: dict[str, InDegreeEntry] = {}
    for tid, etask in tasks.items():
        deps = getattr(etask.plan_task, "dependencies", [])
        degree_map[tid] = InDegreeEntry(
            task_id=tid,
            remaining=len(deps),
            total=len(deps),
        )
    return degree_map


def identify_root_tasks(tasks: dict[str, ExecutionTask]) -> list[str]:
    """Identify tasks with no dependencies (root tasks)."""
    return [
        tid
        for tid, etask in tasks.items()
        if not getattr(etask.plan_task, "dependencies", [])
    ]


def create_default_retry_policy() -> RetryPolicy:
    """Create a default retry policy."""
    return RetryPolicy.default()


def init_metrics(session: ExecutionSession) -> ExecutionMetrics:
    """Initialize execution metrics for a session."""
    return ExecutionMetrics(
        session_id=session.id,
        total_tasks=len(session.tasks),
        total_attempts=0,
        total_retries=0,
        approval_count=0,
        start_time=datetime.now(timezone.utc),
    )


def wrap_task(plan_task: Any, retry_policy: RetryPolicy | None = None) -> ExecutionTask:
    """Wrap a Plan Task into an ExecutionTask."""
    return ExecutionTask(
        id=plan_task.id,
        plan_task=plan_task,
        status=TaskState.PENDING,
        attempts=0,
        max_attempts=retry_policy.max_attempts if retry_policy else 3,
        retry_policy=retry_policy or RetryPolicy.default(),
        adapter_name=None,
    )