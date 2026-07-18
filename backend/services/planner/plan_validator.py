import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from services.planner.planning_models import (
    Plan, Task, TaskType, TriggerType, PlanStatus,
)
from services.planner.dependency_builder import validate_dag
from services.planner.scheduling_engine import collect_scheduling_issues
from services.planner.branching_engine import collect_branching_issues

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    severity: str = "error"
    code: str = ""
    message: str = ""
    task_id: str = ""
    suggested_fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    valid: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [w.to_dict() for w in self.warnings],
        }


def validate_plan(plan: Plan) -> ValidationResult:
    result = ValidationResult()
    known_ids = {t.id for t in plan.tasks}

    _check_structural(plan, known_ids, result)
    _check_scheduling(plan, result)
    _check_approvals(plan, result)
    _check_integrity(plan, result)

    result.valid = len(result.issues) == 0
    if result.valid:
        logger.info("Plan '%s' passed validation with %d warnings", plan.id, len(result.warnings))
    else:
        logger.error("Plan '%s' failed validation with %d errors", plan.id, len(result.issues))
        for issue in result.issues:
            logger.error("  [%s] %s — fix: %s", issue.code, issue.message, issue.suggested_fix)
    return result


def _issue(
    code: str,
    message: str,
    suggested_fix: str,
    severity: str = "error",
    task_id: str = "",
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        task_id=task_id,
        suggested_fix=suggested_fix,
    )


def _check_structural(plan: Plan, known_ids: set[str], result: ValidationResult) -> None:
    if len(plan.tasks) == 0:
        result.issues.append(_issue(
            code="EMPTY_PLAN",
            message="Plan has no tasks",
            suggested_fix="Add at least one task to the plan before validating.",
        ))
        return

    dag_errors = validate_dag(plan)
    for err in dag_errors:
        if "cycle" in err.lower():
            result.issues.append(_issue(
                code="CYCLE_DETECTED",
                message=err,
                suggested_fix="Review task dependencies and remove circular references. Use topological ordering.",
            ))
        elif "terminal" in err.lower():
            result.issues.append(_issue(
                code="NO_TERMINAL_NODE",
                message=err,
                suggested_fix="Ensure at least one task has no downstream dependents.",
            ))
        elif "root" in err.lower():
            result.issues.append(_issue(
                code="NO_ROOT_NODE",
                message=err,
                suggested_fix="Ensure at least one task has no dependencies.",
            ))
        else:
            result.issues.append(_issue(
                code="DAG_ERROR",
                message=err,
                suggested_fix="Review the dependency graph for structural issues.",
            ))

    for t in plan.tasks:
        if t.id not in known_ids:
            continue
        for dep_id in t.dependencies:
            if dep_id not in known_ids:
                result.issues.append(_issue(
                    code="DANGLING_DEPENDENCY",
                    message=f"Task '{t.id}' depends on unknown task '{dep_id}'",
                    suggested_fix=f"Remove or correct the dependency reference '{dep_id}' in task '{t.id}'.",
                    task_id=t.id,
                ))

    task_ids_list = [t.id for t in plan.tasks]
    seen: set[str] = set()
    duplicate_ids: set[str] = set()
    for tid in task_ids_list:
        if tid in seen:
            duplicate_ids.add(tid)
        seen.add(tid)
    if duplicate_ids:
        result.issues.append(_issue(
            code="DUPLICATE_TASK_IDS",
            message=f"Duplicate task IDs: {duplicate_ids}",
            suggested_fix="Ensure every task has a unique ID. Use uuid or a stable strategy-specific prefix.",
        ))

    reachable = _find_reachable_tasks(plan)
    unreachable = known_ids - reachable
    if unreachable:
        result.issues.append(_issue(
            code="UNREACHABLE_TASKS",
            message=f"Tasks not reachable from any root: {unreachable}",
            suggested_fix="Connect unreachable tasks via dependencies or remove them from the plan.",
        ))

    terminal = plan.get_terminal_tasks()
    if not terminal:
        result.issues.append(_issue(
            code="NO_TERMINAL_NODE",
            message="DAG has no terminal node (no tasks without dependents)",
            suggested_fix="Ensure at least one task has no downstream dependents.",
        ))

    branch_structure_issues = collect_branching_issues(plan)
    for msg in branch_structure_issues:
        result.issues.append(_issue(
            code="BRANCH_STRUCTURE",
            message=msg,
            suggested_fix="Define at least one true_task_ids or false_task_ids path for the branch.",
        ))


def _check_scheduling(plan: Plan, result: ValidationResult) -> None:
    scheduling_issues = collect_scheduling_issues(plan)
    for msg in scheduling_issues:
        result.issues.append(_issue(
            code="SCHEDULING_ERROR",
            message=msg,
            suggested_fix="Provide a valid timeout duration (e.g., '3d') for wait_for_reply, or duration for wait_duration.",
        ))

    for t in plan.tasks:
        if t.trigger and t.trigger.type == TriggerType.AFTER_TASK:
            referenced_id = t.trigger.value
            if referenced_id and referenced_id != t.id:
                exists = any(other.id == referenced_id for other in plan.tasks)
                if not exists:
                    result.issues.append(_issue(
                        code="INVALID_SCHEDULE_REFERENCE",
                        message=f"Task '{t.id}' trigger references non-existent task '{referenced_id}'",
                        suggested_fix=f"Update the trigger value to reference an existing task ID, or use 'immediately'.",
                        task_id=t.id,
                    ))

        if t.trigger and t.trigger.type == TriggerType.AFTER_REPLY:
            payload = t.get_payload()
            timeout = ""
            if payload is not None and hasattr(payload, "timeout"):
                timeout = getattr(payload, "timeout", "")
            if not timeout:
                timeout = t.params.get("timeout", "")
            if not timeout:
                result.issues.append(_issue(
                    code="REPLY_NO_TIMEOUT",
                    message=f"After-reply task '{t.id}' has no timeout configured",
                    suggested_fix="Set a timeout duration (e.g., WaitForReplyPayload(timeout='3d')).",
                    task_id=t.id,
                ))


def _check_approvals(plan: Plan, result: ValidationResult) -> None:
    from services.planner.planning_models import ApprovalRequirement
    for t in plan.tasks:
        if t.approval == ApprovalRequirement.POLICY_MANDATED:
            # Future: ensure a corresponding Approval record exists.
            pass


def _check_integrity(plan: Plan, result: ValidationResult) -> None:
    for t in plan.tasks:
        if not t.reasoning_trace:
            result.warnings.append(_issue(
                code="MISSING_REASONING_TRACE",
                message=f"Task '{t.id}' is missing reasoning_trace",
                suggested_fix="Populate reasoning_trace to explain why this task exists.",
                severity="warning",
                task_id=t.id,
            ))
        if not t.reasoning_goal:
            result.warnings.append(_issue(
                code="MISSING_REASONING_GOAL",
                message=f"Task '{t.id}' is missing reasoning_goal",
                suggested_fix="Populate reasoning_goal to link the task to its parent planning goal.",
                severity="warning",
                task_id=t.id,
            ))

    for t in plan.tasks:
        if not t.instructions:
            result.issues.append(_issue(
                code="MISSING_INSTRUCTIONS",
                message=f"Task '{t.id}' has empty instructions",
                suggested_fix="Provide clear instructions describing what the task should do.",
                task_id=t.id,
            ))

        payload = t.get_payload()
        if payload is not None and hasattr(payload, "validate"):
            payload_errors = payload.validate()
            for err in payload_errors:
                result.issues.append(_issue(
                    code="INVALID_PAYLOAD",
                    message=f"Task '{t.id}' payload validation failed: {err}",
                    suggested_fix="Correct the task payload fields before validating the plan.",
                    task_id=t.id,
                ))


def _find_reachable_tasks(plan: Plan) -> set[str]:
    root_ids = {t.id for t in plan.get_root_tasks()}
    reachable: set[str] = set()
    adjacency: dict[str, list[str]] = {}
    for t in plan.tasks:
        adjacency[t.id] = []
    for t in plan.tasks:
        for dep_id in t.dependencies:
            if dep_id in adjacency:
                adjacency[dep_id].append(t.id)

    def dfs(node: str) -> None:
        if node in reachable:
            return
        reachable.add(node)
        for child in adjacency.get(node, []):
            dfs(child)

    for root_id in root_ids:
        dfs(root_id)

    return reachable
