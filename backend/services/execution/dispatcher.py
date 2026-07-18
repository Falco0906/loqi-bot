"""Execution Engine dispatcher.

The dispatcher receives a READY task and resolves it to an adapter.
It performs no business logic — it is a pure routing layer.

The dispatcher must not:
  - modify scheduler state
  - transition task states
  - retry execution
  - emit events
  - call planner components
  - directly execute business logic
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from services.execution.base_adapter import ExecutionAdapter
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import ExecutionTask, TaskResult
from services.execution.exceptions import ExecutionDispatchError
from services.planner.planning_models import TaskType


class AdapterResolver(Protocol):
    """Interface for resolving an adapter by task type.

    The resolver implementation (AdapterRegistry) belongs to Phase 3.6.4D.
    This protocol defines the contract the dispatcher expects.
    """

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        """Resolve the best adapter for the given task type.

        Args:
            task_type: The type of task to resolve an adapter for.

        Returns:
            An ExecutionAdapter instance, or None if no adapter is
            registered for the given task type.
        """


class Dispatcher:
    """Pure orchestration layer — routes tasks to adapters.

    Stateless and side-effect free. Never transitions task state,
    never knows about concrete adapters, depends only on abstractions.
    """

    @staticmethod
    async def dispatch(
        task: ExecutionTask,
        context: ExecutionContext,
        resolver: AdapterResolver,
    ) -> TaskResult:
        """Resolve adapter and execute the task.

        Args:
            task: The execution task to dispatch.
            context: Immutable execution context for adapter invocation.
            resolver: Adapter resolver to find the appropriate adapter.

        Returns:
            A TaskResult produced by the adapter.

        Raises:
            ExecutionDispatchError: If no adapter is registered for the
                task's type.
        """
        adapter = resolver.resolve(task.plan_task.type)

        if adapter is None:
            raise ExecutionDispatchError(
                f"No adapter registered for task type: "
                f"{task.plan_task.type.value}",
                context={
                    "task_id": task.id,
                    "task_type": task.plan_task.type.value,
                },
            )

        task.adapter_name = adapter.adapter_type

        return await adapter.execute(task, context)
