import logging
from typing import Optional

from services.planner.planning_models import (
    Plan, Task, TaskType, Trigger, TriggerType,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints

logger = logging.getLogger(__name__)


def apply_scheduling(
    plan: Plan,
    strategy: Optional[Strategy] = None,
) -> None:
    task_map = {t.id: t for t in plan.tasks}
    root_tasks = plan.get_root_tasks()
    terminal_tasks = plan.get_terminal_tasks()

    hints = SchedulingHints()
    if strategy:
        hints = strategy.scheduling(plan.goal) if plan.goal else hints

    for task in plan.tasks:
        if task.type == TaskType.BRANCH:
            task.trigger = Trigger(type=TriggerType.IMMEDIATELY)
        elif task.type == TaskType.JOIN:
            task.trigger = Trigger(type=TriggerType.AFTER_TASK, value=task.id)
        elif task.type == TaskType.WAIT_FOR_REPLY:
            timeout = task.params.get("timeout", "3d")
            task.trigger = Trigger(
                type=TriggerType.AFTER_REPLY,
                value=timeout,
            )
        elif task.type == TaskType.WAIT_DURATION:
            duration = task.params.get("duration", "1d")
            task.trigger = Trigger(
                type=TriggerType.AFTER_DURATION,
                value=duration,
            )
        elif task.id in [t.id for t in root_tasks]:
            task.trigger = Trigger(type=TriggerType.IMMEDIATELY)
        elif task.dependencies:
            task.trigger = Trigger(
                type=TriggerType.AFTER_TASK,
                value=task.dependencies[0],
            )
        else:
            task.trigger = Trigger(type=TriggerType.IMMEDIATELY)

    _apply_business_hours_constraints(plan, hints)

    logger.info(
        "Applied scheduling to %d tasks (business_hours=%s)",
        len(plan.tasks),
        hints.business_hours_only,
    )


def _apply_business_hours_constraints(
    plan: Plan,
    hints: SchedulingHints,
) -> None:
    if not hints.business_hours_only:
        return

    for task in plan.tasks:
        if task.trigger and task.trigger.type in (
            TriggerType.AFTER_DURATION,
            TriggerType.AFTER_REPLY,
        ):
            if not task.trigger.window_start:
                task.trigger.window_start = "09:00"
            if not task.trigger.window_end:
                task.trigger.window_end = "17:00"
            if not task.trigger.timezone or task.trigger.timezone == "UTC":
                task.trigger.timezone = hints.timezone


def collect_scheduling_issues(plan: Plan) -> list[str]:
    issues = []
    for task in plan.tasks:
        if task.type == TaskType.WAIT_FOR_REPLY:
            timeout = task.params.get("timeout", "")
            if not timeout:
                issues.append(
                    f"Task '{task.id}' (wait_for_reply) has no timeout configured"
                )
        if task.type == TaskType.WAIT_DURATION:
            duration = task.params.get("duration", "")
            if not duration:
                issues.append(
                    f"Task '{task.id}' (wait_duration) has no duration configured"
                )
        if task.trigger and task.trigger.type == TriggerType.AFTER_TASK:
            referenced_id = task.trigger.value
            if referenced_id and referenced_id != task.id:
                task_exists = any(t.id == referenced_id for t in plan.tasks)
                if not task_exists:
                    issues.append(
                        f"Task '{task.id}' trigger references non-existent task '{referenced_id}'"
                    )
    return issues
