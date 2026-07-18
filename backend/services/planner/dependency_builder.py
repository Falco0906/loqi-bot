import logging
from typing import Optional

from services.planner.exceptions import PlanningGraphError
from services.planner.planning_models import Plan, Task, Dependency, DependencyType
from services.planner.strategies.strategy_base import Strategy

logger = logging.getLogger(__name__)


def build_dependencies(
    plan: Plan,
    strategy: Optional[Strategy] = None,
) -> list[tuple[str, str]]:
    """Build task dependencies using stable task IDs.

    Strategies are expected to return dependency pairs where source and target
    are task IDs.  No label-based resolution is performed.
    """
    task_map = {t.id: t for t in plan.tasks}

    # Hardening: reject any pre-existing dependency references to unknown IDs
    # before doing further work.
    _validate_existing_task_dependencies(plan)

    dependency_pairs: list[tuple[str, str]] = []

    if strategy:
        try:
            strategy_deps = strategy.dependencies(plan.tasks)
            dependency_pairs.extend(strategy_deps)
            logger.info(
                "Strategy '%s' provided %d dependency hints",
                strategy.name,
                len(strategy_deps),
            )
        except Exception as e:
            raise PlanningGraphError(
                f"Strategy '{strategy.name}' dependency resolution failed: {e}",
                context={"plan_id": plan.id, "strategy": strategy.name},
            ) from e

    implicit_pairs = _detect_implicit_dependencies(plan.tasks)
    dependency_pairs.extend(implicit_pairs)
    if implicit_pairs:
        logger.info("Detected %d implicit dependencies", len(implicit_pairs))

    dependency_pairs = _deduplicate_pairs(dependency_pairs)

    _validate_dependency_refs(plan, task_map, dependency_pairs)
    _apply_dependencies(plan.tasks, dependency_pairs)

    logger.info(
        "Built %d dependencies across %d tasks",
        len(dependency_pairs),
        len(plan.tasks),
    )
    return dependency_pairs


def _detect_implicit_dependencies(tasks: list[Task]) -> list[tuple[str, str]]:
    """Detect implicit dependencies such as wait_for_reply after send_message."""
    pairs = []

    for task in tasks:
        if task.type.value == "wait_for_reply":
            send_tasks = [
                t
                for t in tasks
                if t.id != task.id
                and t.type.value in ("send_message", "send_email")
            ]
            for send_task in send_tasks:
                if task.dependencies and task.dependencies[0] == send_task.id:
                    continue
                if not any(
                    dep[1] == task.id and dep[0] == send_task.id
                    for dep in pairs
                ):
                    pairs.append((send_task.id, task.id))

    return pairs


def _deduplicate_pairs(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    seen = set()
    unique = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def _validate_existing_task_dependencies(plan: Plan) -> None:
    """Ensure every dependency already declared on a task references an existing task ID."""
    known_ids = {t.id for t in plan.tasks}
    for task in plan.tasks:
        for dep_id in task.dependencies:
            if dep_id not in known_ids:
                raise PlanningGraphError(
                    f"Task '{task.id}' depends on unknown task '{dep_id}'",
                    context={
                        "plan_id": plan.id,
                        "task_id": task.id,
                        "unknown_dependency_id": dep_id,
                    },
                )
            if dep_id == task.id:
                raise PlanningGraphError(
                    f"Task '{task.id}' depends on itself",
                    context={"plan_id": plan.id, "task_id": task.id},
                )


def _validate_dependency_refs(
    plan: Plan,
    task_map: dict[str, Task],
    pairs: list[tuple[str, str]],
) -> None:
    """Ensure all dependency references resolve to existing task IDs."""
    for source_id, target_id in pairs:
        if source_id not in task_map:
            raise PlanningGraphError(
                f"Dependency references unknown source task ID '{source_id}'",
                context={
                    "plan_id": plan.id,
                    "source_id": source_id,
                    "target_id": target_id,
                },
            )
        if target_id not in task_map:
            raise PlanningGraphError(
                f"Dependency references unknown target task ID '{target_id}'",
                context={
                    "plan_id": plan.id,
                    "source_id": source_id,
                    "target_id": target_id,
                },
            )
        if source_id == target_id:
            raise PlanningGraphError(
                f"Task '{source_id}' cannot depend on itself",
                context={"plan_id": plan.id, "task_id": source_id},
            )


def _apply_dependencies(
    tasks: list[Task],
    pairs: list[tuple[str, str]],
) -> None:
    task_map = {t.id: t for t in tasks}

    for source_id, target_id in pairs:
        target = task_map[target_id]
        if source_id not in target.dependencies:
            target.dependencies.append(source_id)


def validate_dag(plan: Plan) -> list[str]:
    errors = []

    task_ids = {t.id for t in plan.tasks}
    for task in plan.tasks:
        for dep_id in task.dependencies:
            if dep_id not in task_ids:
                errors.append(
                    f"Task '{task.id}' depends on unknown task '{dep_id}'"
                )

    if _has_cycle(plan):
        errors.append("Dependency graph contains a cycle")

    if not plan.get_terminal_tasks():
        errors.append("DAG has no terminal node")

    if not plan.get_root_tasks():
        errors.append("DAG has no root node")

    return errors


def _has_cycle(plan: Plan) -> bool:
    task_ids = {t.id for t in plan.tasks}
    adjacency: dict[str, list[str]] = {t_id: [] for t_id in task_ids}
    for task in plan.tasks:
        for dep_id in task.dependencies:
            if dep_id in adjacency:
                adjacency[dep_id].append(task.id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {t_id: WHITE for t_id in task_ids}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adjacency.get(node, []):
            if color.get(neighbor) == GRAY:
                return True
            if color.get(neighbor) == WHITE:
                if dfs(neighbor):
                    return True
        color[node] = BLACK
        return False

    for t_id in task_ids:
        if color[t_id] == WHITE:
            if dfs(t_id):
                return True
    return False
