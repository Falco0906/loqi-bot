"""Execution Engine adapter registry.

Manages adapter registration, resolution, and introspection.
The registry is the single point of truth for adapter availability.

Thread-safe: concurrent reads are supported; mutating operations
(register / unregister / clear) are serialized via a lock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.exceptions import ExecutionAdapterError
from services.planner.planning_models import TaskType


@dataclass
class AdapterDescriptor:
    """Internal descriptor wrapping a registered adapter.

    Stored in the registry instead of raw adapter instances to support
    introspection, version tracking, and priority-based resolution.
    """

    adapter_type: str
    adapter: ExecutionAdapter
    priority: int
    supported_task_types: list[TaskType]
    version: Optional[str] = None
    registered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AdapterRegistry:
    """Pluggable registry for execution adapters.

    Supports registration, priority-based resolution, unregistration,
    introspection, and thread-safe concurrent access.
    """

    def __init__(self):
        self._descriptors: dict[str, AdapterDescriptor] = {}
        self._task_type_map: dict[TaskType, list[str]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        adapter: ExecutionAdapter,
        priority: int = 100,
        version: Optional[str] = None,
    ) -> None:
        """Register an adapter.

        Idempotent — re-registering the same adapter_type updates the
        priority and version. Registration order determines tie-breaking
        when multiple adapters share the same priority (first-registered
        wins among equal priorities).

        Args:
            adapter: The adapter instance to register.
            priority: Resolution priority (higher = selected first).
            version: Optional version string for introspection.

        Raises:
            ExecutionAdapterError: If the adapter is invalid.
        """
        self._validate_adapter(adapter, priority)

        adapter_type = adapter.adapter_type

        with self._lock:
            old_descriptor = self._descriptors.get(adapter_type)
            is_new = old_descriptor is None

            descriptor = AdapterDescriptor(
                adapter_type=adapter_type,
                adapter=adapter,
                priority=priority,
                supported_task_types=list(adapter.supported_task_types),
                version=version or (old_descriptor.version if old_descriptor else None),
                registered_at=(
                    old_descriptor.registered_at
                    if old_descriptor
                    else datetime.now(timezone.utc)
                ),
            )

            self._descriptors[adapter_type] = descriptor

            if is_new:
                for tt in adapter.supported_task_types:
                    if tt not in self._task_type_map:
                        self._task_type_map[tt] = []
                    self._task_type_map[tt].append(adapter_type)
                    self._sort_by_priority(tt)
            else:
                old_types = set(old_descriptor.supported_task_types)
                new_types = set(adapter.supported_task_types)

                for tt in old_types - new_types:
                    if tt in self._task_type_map:
                        try:
                            self._task_type_map[tt].remove(adapter_type)
                        except ValueError:
                            pass

                for tt in new_types:
                    if tt not in self._task_type_map:
                        self._task_type_map[tt] = []
                    if adapter_type not in self._task_type_map[tt]:
                        self._task_type_map[tt].append(adapter_type)
                    self._sort_by_priority(tt)

    def _sort_by_priority(self, task_type: TaskType) -> None:
        """Sort the adapter list for a task type by priority desc.

        Higher priority first. Same priority: preserve insertion order
        (stable sort).
        """
        entries = self._task_type_map[task_type]
        entries.sort(
            key=lambda at: (
                -(self._descriptors[at].priority if at in self._descriptors else 0),
                at,
            ),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_adapter(
        self,
        adapter: ExecutionAdapter,
        priority: int,
    ) -> None:
        """Validate an adapter before registration.

        Raises:
            ExecutionAdapterError: On any validation failure.
        """
        if not isinstance(adapter, ExecutionAdapter):
            raise ExecutionAdapterError(
                "Adapter must be an ExecutionAdapter instance",
                context={"adapter_type": type(adapter).__name__},
            )

        adapter_type = getattr(adapter, "adapter_type", None)
        if not adapter_type or not isinstance(adapter_type, str):
            raise ExecutionAdapterError(
                "Adapter must have a non-empty adapter_type string",
                context={"adapter_type": str(adapter_type)},
            )

        supported = getattr(adapter, "supported_task_types", None)
        if not supported or not isinstance(supported, (list, tuple)):
            raise ExecutionAdapterError(
                "Adapter must have a non-empty supported_task_types list",
                context={"adapter_type": adapter_type},
            )

        if not all(isinstance(tt, TaskType) for tt in supported):
            raise ExecutionAdapterError(
                "supported_task_types must contain only TaskType values",
                context={
                    "adapter_type": adapter_type,
                    "supported_types": [str(s) for s in supported],
                },
            )

        if priority < 0:
            raise ExecutionAdapterError(
                "Priority must be non-negative",
                context={"adapter_type": adapter_type, "priority": priority},
            )

        issues = adapter.validate()
        if issues:
            raise ExecutionAdapterError(
                "Adapter validation failed",
                context={
                    "adapter_type": adapter_type,
                    "issues": issues,
                },
            )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        """Resolve the best adapter for a task type.

        Uses priority-based selection:
          1. Collect all adapters registered for this task type.
          2. Sort by priority descending.
          3. Return the highest-priority adapter.

        Args:
            task_type: The task type to resolve.

        Returns:
            The best ExecutionAdapter, or None if no adapter is registered.
        """
        adapter_types = self._task_type_map.get(task_type)
        if not adapter_types:
            return None

        for at in adapter_types:
            descriptor = self._descriptors.get(at)
            if descriptor is not None:
                return descriptor.adapter

        return None

    # ------------------------------------------------------------------
    # Unregistration
    # ------------------------------------------------------------------

    def unregister(self, adapter_type: str) -> None:
        """Remove a registered adapter by type.

        Removes the adapter from all internal data structures.
        Silently succeeds if the adapter is not registered.

        Args:
            adapter_type: The adapter type string to remove.
        """
        with self._lock:
            descriptor = self._descriptors.pop(adapter_type, None)
            if descriptor is None:
                return

            for tt in descriptor.supported_task_types:
                if tt in self._task_type_map:
                    try:
                        self._task_type_map[tt].remove(adapter_type)
                    except ValueError:
                        pass
                    if not self._task_type_map[tt]:
                        del self._task_type_map[tt]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_supported_types(self) -> dict[str, list[TaskType]]:
        """Return all registered adapters and their supported task types.

        Returns:
            A dict mapping adapter_type to list of supported TaskTypes.
        """
        return {
            at: list(desc.supported_task_types)
            for at, desc in self._descriptors.items()
        }

    def list_registered(self) -> list[AdapterDescriptor]:
        """Return descriptors for all registered adapters.

        Returns:
            A list of AdapterDescriptor instances (sorted by adapter_type).
        """
        return sorted(
            list(self._descriptors.values()),
            key=lambda d: d.adapter_type,
        )

    def clear(self) -> None:
        """Remove all registered adapters.

        Intended for testing and live reconfiguration.
        """
        with self._lock:
            self._descriptors.clear()
            self._task_type_map.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Return the number of registered adapters."""
        return len(self._descriptors)

    def get_descriptor(self, adapter_type: str) -> Optional[AdapterDescriptor]:
        """Get the descriptor for a specific adapter type.

        Args:
            adapter_type: The adapter type string.

        Returns:
            The AdapterDescriptor, or None if not registered.
        """
        return self._descriptors.get(adapter_type)
