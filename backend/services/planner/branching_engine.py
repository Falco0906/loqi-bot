import logging
from typing import Optional

from services.planner.planning_models import (
    Plan, Task, Branch, TaskType, BranchCondition,
)
from services.planner.payloads import BranchPayload, JoinPayload

logger = logging.getLogger(__name__)


def apply_branching(plan: Plan) -> None:
    task_map = {t.id: t for t in plan.tasks}

    for task in plan.tasks:
        if task.branch and task.branch.condition:
            _resolve_branch_references(task, task_map)

    _insert_branch_nodes(plan)
    _insert_join_nodes(plan)

    logger.info("Applied branching to plan with %d tasks", len(plan.tasks))


def _resolve_branch_references(
    task: Task,
    task_map: dict[str, Task],
) -> None:
    if not task.branch:
        return

    resolved_true = []
    for ref_id in task.branch.true_task_ids:
        if ref_id in task_map:
            resolved_true.append(ref_id)
        else:
            logger.warning(
                "Branch true_task_ids references unknown task '%s'",
                ref_id,
            )
    task.branch.true_task_ids = resolved_true

    resolved_false = []
    for ref_id in task.branch.false_task_ids:
        if ref_id in task_map:
            resolved_false.append(ref_id)
        else:
            logger.warning(
                "Branch false_task_ids references unknown task '%s'",
                ref_id,
            )
    task.branch.false_task_ids = resolved_false


def _insert_branch_nodes(plan: Plan) -> None:
    task_map = {t.id: t for t in plan.tasks}

    branch_tasks = [t for t in plan.tasks if t.branch and t.branch.condition]
    for branch_task in branch_tasks:
        branch_node = Task(
            type=TaskType.BRANCH,
            label=f"Branch: {branch_task.branch.condition.value}",
            instructions=f"Evaluate condition: {branch_task.branch.condition.value}",
            payload=BranchPayload(condition=branch_task.branch.condition.value),
            dependencies=[branch_task.id],
            reasoning_trace=f"Branch node for condition '{branch_task.branch.condition.value}'",
            reasoning_goal=branch_task.reasoning_goal,
        )
        plan.tasks.append(branch_node)

        if branch_task.dependencies:
            branch_node.dependencies = list(branch_task.dependencies)

        branch_task.dependencies = [branch_node.id]

    if branch_tasks:
        logger.info(
            "Inserted %d branch nodes",
            len(branch_tasks),
        )


def _insert_join_nodes(plan: Plan) -> None:
    task_map = {t.id: t for t in plan.tasks}

    branch_tasks = [t for t in plan.tasks if t.branch and t.branch.condition]
    for branch_task in branch_tasks:
        if not branch_task.branch:
            continue

        downstream_ids = set(
            branch_task.branch.true_task_ids + branch_task.branch.false_task_ids
        )
        if not downstream_ids:
            continue

        downstream_tasks = [
            t for t in plan.tasks if t.id in downstream_ids
        ]

        terminal_ids = set()
        for dt in downstream_tasks:
            has_downstream = any(
                dt.id in t.dependencies for t in plan.tasks if t.id != dt.id
            )
            if not has_downstream:
                terminal_ids.add(dt.id)

        if terminal_ids:
            join_node = Task(
                type=TaskType.JOIN,
                label=f"Join after {branch_task.branch.condition.value}",
                instructions=f"Synchronization point after branch condition '{branch_task.branch.condition.value}'",
                payload=JoinPayload(
                    branch_task_id=branch_task.id,
                    condition=branch_task.branch.condition.value,
                ),
                dependencies=list(terminal_ids),
                reasoning_trace=f"Join node after condition '{branch_task.branch.condition.value}'",
                reasoning_goal=branch_task.reasoning_goal,
            )
            plan.tasks.append(join_node)

    join_count = len([t for t in plan.tasks if t.type == TaskType.JOIN])
    if join_count:
        logger.info("Inserted %d join nodes", join_count)


def collect_branching_issues(plan: Plan) -> list[str]:
    issues = []
    for task in plan.tasks:
        if task.branch and task.branch.condition:
            if not task.branch.true_task_ids and not task.branch.false_task_ids:
                issues.append(
                    f"Branch task '{task.id}' has no true or false task paths"
                )
    return issues
