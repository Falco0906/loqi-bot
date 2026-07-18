"""Execution plan validation.

Validates a Plan before execution begins. Validation must fail before
execution starts — no silent recovery.
"""

from __future__ import annotations

from typing import Any

from services.execution.exceptions import ExecutionValidationError
from services.execution.execution_models import ValidationResult
from services.planner.planning_models import PlanStatus, TaskStatus


def validate_plan_for_execution(plan: Any) -> ValidationResult:
    """Validate a Plan for execution readiness.

    Checks:
      - Plan is not None.
      - Plan status is VALIDATED.
      - All task IDs are unique within the plan.
      - All tasks have a payload (except BRANCH/JOIN).
      - All dependency references resolve to existing task IDs.
      - The DAG contains no cycles.
      - All tasks have a valid initial status (PENDING).

    Raises:
        ExecutionValidationError if any check fails.

    Returns:
        ValidationResult with valid=True if all checks pass.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if plan is None:
        raise ExecutionValidationError(
            "Plan is None — cannot validate",
            context={"errors": ["Plan is None"]},
        )

    _check_plan_status(plan, errors)
    _check_task_ids_unique(plan, errors)
    _check_payloads_present(plan, errors)
    _check_dependency_integrity(plan, errors)
    _check_cycles(plan, errors)
    _check_initial_task_states(plan, errors)

    if errors:
        raise ExecutionValidationError(
            "Plan failed execution validation",
            context={"errors": errors, "warnings": warnings},
        )

    return ValidationResult(valid=True, warnings=warnings)


def _check_plan_status(plan: Any, errors: list[str]) -> None:
    if plan.status != PlanStatus.VALIDATED:
        errors.append(
            f"Plan status must be VALIDATED, got {plan.status.value}"
        )


def _check_task_ids_unique(plan: Any, errors: list[str]) -> None:
    ids = [t.id for t in plan.tasks]
    if len(ids) != len(set(ids)):
        seen = set()
        duplicates = []
        for tid in ids:
            if tid in seen:
                duplicates.append(tid)
            seen.add(tid)
        errors.append(f"Duplicate task IDs: {duplicates}")


def _check_payloads_present(plan: Any, errors: list[str]) -> None:
    from services.planner.planning_models import TaskType

    for task in plan.tasks:
        if task.type in (TaskType.BRANCH, TaskType.JOIN):
            continue
        if task.payload is None and not task.params.get("payload_type"):
            errors.append(f"Task {task.id} has no payload")


def _check_dependency_integrity(plan: Any, errors: list[str]) -> None:
    task_ids = {t.id for t in plan.tasks}
    for task in plan.tasks:
        for dep_id in task.dependencies:
            if dep_id not in task_ids:
                errors.append(
                    f"Task {task.id} depends on unknown task ID {dep_id}"
                )


def _check_cycles(plan: Any, errors: list[str]) -> None:
    task_ids = {t.id for t in plan.tasks}
    edges: dict[str, set[str]] = {tid: set() for tid in task_ids}
    for task in plan.tasks:
        for dep_id in task.dependencies:
            if dep_id in edges:
                edges[dep_id].add(task.id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in task_ids}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in edges.get(node, set()):
            if color.get(neighbor) == GRAY:
                return True
            if color.get(neighbor) == WHITE:
                if dfs(neighbor):
                    return True
        color[node] = BLACK
        return False

    for tid in task_ids:
        if color[tid] == WHITE:
            if dfs(tid):
                errors.append("Cycle detected in task dependency graph")
                return


def _check_initial_task_states(plan: Any, errors: list[str]) -> None:
    for task in plan.tasks:
        if task.status != TaskStatus.PENDING:
            errors.append(
                f"Task {task.id} has invalid initial status: "
                f"{task.status.value} (expected PENDING)"
            )


def validate_session_initialization(session: Any) -> ValidationResult:
    """Validate that an ExecutionSession is properly initialized.

    Checks:
      - Session has an ID.
      - Session has a plan reference.
      - Session has at least one task.
      - All tasks are in PENDING state.
      - Root tasks are identified (warning if none).
    """
    from services.execution.enums import TaskState

    errors: list[str] = []
    warnings: list[str] = []

    if not session.id:
        errors.append("Session has no ID")
    if session.plan is None:
        errors.append("Session has no plan reference")
    if not session.tasks:
        errors.append("Session has no tasks")

    if session.tasks:
        for tid, etask in session.tasks.items():
            if etask.status != TaskState.PENDING:
                errors.append(
                    f"Task {tid} should be PENDING, got {etask.status.value}"
                )

    if not session.root_tasks and session.tasks:
        warnings.append("No root tasks identified (all tasks have dependencies)")

    if errors:
        raise ExecutionValidationError(
            "Session initialization validation failed",
            context={"errors": errors, "warnings": warnings},
        )

    return ValidationResult(valid=True, warnings=warnings)