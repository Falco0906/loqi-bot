from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from services.planner.planning_models import PlanGoal, Task, Trigger, Branch, TaskType


@dataclass
class SchedulingHints:
    timezone: str = "UTC"
    business_hours_only: bool = True
    min_delay_between_tasks: int = 30
    max_daily_tasks: int = 3
    preferred_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])


@dataclass
class ApprovalRule:
    task_type: TaskType | str = ""
    condition: str = ""
    requirement: str = "recommended"
    reason: str = ""


class Strategy(ABC):
    """Abstract base for planning strategies.

    Implementations generate a list of concrete Task objects and optionally
    declare dependencies between them.  Dependencies MUST be expressed as
    (source_task_id, target_task_id) pairs using the exact task IDs created in
    generate_tasks().  Labels are UI-only and must not be used for dependency
    resolution.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def matches(self, goal: PlanGoal) -> float:
        return 0.0

    @abstractmethod
    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        ...

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        """Return dependency edges as (source_task_id, target_task_id) pairs.

        Implementations should use the task IDs assigned in generate_tasks().
        Do NOT use task labels for dependency resolution.
        """
        return []

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints()

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        return []
