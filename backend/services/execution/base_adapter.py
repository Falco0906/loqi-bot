"""Abstract base class for all execution adapters.

Adapters encapsulate all side effects. The engine routes typed tasks
to adapters and never calls external systems directly.

Every adapter must implement:
    adapter_type
    supported_task_types
    execute(task, context) -> TaskResult

Optional methods:
    validate()       — check adapter configuration at registration time
    supports(type)   — check if a task type is supported (default: list check)
    shutdown()       — clean up resources (called during engine shutdown)
    compensate()     — undo side effects for rollback scenarios
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import ExecutionTask, TaskResult
from services.planner.planning_models import TaskType


class ExecutionAdapter(ABC):
    """Abstract base class for all execution adapters.

    Subclasses must define adapter_type, supported_task_types, and execute().
    """

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Unique identifier for this adapter (e.g., 'telegram', 'gmail')."""

    @property
    @abstractmethod
    def supported_task_types(self) -> list[TaskType]:
        """Task types this adapter can handle."""

    @abstractmethod
    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        """Execute a task and return a result.

        Must be idempotent — may be called multiple times for the
        same task attempt. The adapter should check the idempotency
        store before performing side effects.

        Args:
            task: The execution task to execute.
            context: Immutable execution context.

        Returns:
            A TaskResult indicating success or failure with
            classified error_type ('transient' or 'permanent').
        """

    def validate(self) -> Optional[list[str]]:
        """Validate adapter configuration at registration time.

        Returns a list of configuration issues, or None if valid.
        """
        return None

    def supports(self, task_type: TaskType) -> bool:
        """Check if this adapter supports the given task type.

        Default implementation checks supported_task_types.
        Subclasses may override for dynamic type checking.
        """
        return task_type in self.supported_task_types

    def shutdown(self) -> None:
        """Clean up resources during engine shutdown.

        Override to close connections, flush buffers, etc.
        Default implementation is a no-op.
        """

    async def compensate(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> Optional[TaskResult]:
        """Undo side effects for rollback scenarios.

        Called when a downstream task fails and the engine decides
        to undo this task's side effects (e.g., delete a scheduled
        meeting).

        Args:
            task: The task whose side effects to undo.
            context: Immutable execution context.

        Returns:
            TaskResult of the compensation, or None if no compensation
            is needed.
        """
        return None
