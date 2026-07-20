"""AdapterRegistryResolver — a generic AdapterResolver backed by the
execution AdapterRegistry.

Maps ``TaskType`` → ``ExecutionAdapter`` by delegating to the
``AdapterRegistry`` that is populated during application startup.
This replaces ad-hoc per-adapter resolvers (e.g. the inline
``_SendResolver`` in ``workflows.py``) with a single reusable
resolver that supports any registered TaskType.

Global accessor
---------------
Call ``init_planner_registry(registry)`` once at startup with the
global ``AdapterRegistry`` instance (populated in ``main.py``).

After init, ``get_planner_resolver()`` returns a shared
``AdapterRegistryResolver`` that the ``PlannerRouter`` can discover
automatically via its ``_auto_resolver()`` stub replacement.
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Optional

from services.execution.adapter_registry import AdapterRegistry
from services.execution.base_adapter import ExecutionAdapter
from services.planner.planning_models import TaskType

logger = logging.getLogger(__name__)

# Global registry reference — set once at startup by main.py.
_planner_registry: AdapterRegistry | None = None
_planner_registry_lock = Lock()


def init_planner_registry(registry: AdapterRegistry) -> None:
    """Set the global planner registry reference.

    Must be called once during application startup (typically in the
    lifespan callback after ``_register_execution_adapters()``).

    Args:
        registry: The global ``AdapterRegistry`` instance populated
                  during startup.

    Raises:
        RuntimeError: If the registry has already been initialised.
    """
    global _planner_registry
    with _planner_registry_lock:
        if _planner_registry is not None:
            raise RuntimeError("Planner registry already initialised")
        _planner_registry = registry
        logger.info("Planner registry initialised (%d adapter(s))", len(registry.list_registered()))


def get_planner_registry() -> AdapterRegistry | None:
    """Return the global planner registry, or *None* if not yet set."""
    return _planner_registry


def get_planner_resolver() -> AdapterRegistryResolver | None:
    """Return a shared resolver backed by the global planner registry.

    Returns *None* when the registry has not been initialised (e.g.
    before ``init_planner_registry()`` has been called at startup).
    This lets callers fall back gracefully.
    """
    registry = get_planner_registry()
    if registry is None:
        logger.debug("Planner registry not available — resolver unavailable")
        return None
    return AdapterRegistryResolver(registry)


class AdapterRegistryResolver:
    """Resolves ``TaskType`` → ``ExecutionAdapter`` via an ``AdapterRegistry``.

    Implements the ``AdapterResolver`` protocol used by the
    ``Dispatcher``.  Any adapter that has been registered with the
    provided registry (typically the global ``_execution_adapter_registry``
    populated in ``main.py``) can be resolved.

    Args:
        registry: The ``AdapterRegistry`` instance to delegate to.
    """

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        return self._registry.resolve(task_type)
