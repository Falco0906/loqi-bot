"""Execution Engine package.

Phase 3.6.4A — Foundation implementation.
Phase 3.6.4B — Scheduler & State Machine.
Phase 3.6.4C — Dispatcher & Base Adapter.
Phase 3.6.4D — Adapter Registry.
Phase 3.6.4F — Retry Engine.
Phase 3.6.4G — Event Bus.
"""

from services.execution.adapter_registry import AdapterDescriptor, AdapterRegistry
from services.execution.adapter_registry_resolver import AdapterRegistryResolver
from services.execution.base_adapter import ExecutionAdapter
from services.execution.bridge_adapter import BridgeAdapter
from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import (
    ExecutionEventType,
    SessionState,
    TaskState,
)
from services.execution.event_bus import EventBus, EventSubscriber
from services.execution.exceptions import (
    ExecutionAdapterError,
    ExecutionDispatchError,
    ExecutionError,
    ExecutionRetryError,
    ExecutionSchedulingError,
    ExecutionSessionError,
    ExecutionStateError,
    ExecutionValidationError,
)
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionResult,
    ExecutionSession,
    ExecutionTask,
    InDegreeEntry,
    RetryPolicy,
    TaskResult,
    ValidationResult,
)
from services.execution.execution_context import ExecutionContext
from services.execution.execution_pipeline import ExecutionEngine, get_pipeline
from services.execution.metrics_collector import AdapterMetricsSnapshot, MetricsCollector, MetricsSnapshot
from services.execution.scheduler import Scheduler
from services.execution.state_machine import StateMachine
from services.execution.validation import (
    validate_plan_for_execution,
    validate_session_initialization,
)

__all__ = [
    # Adapter Registry
    "AdapterDescriptor",
    "AdapterRegistry",
    "AdapterRegistryResolver",
    # Base Adapter
    "ExecutionAdapter",
    # Dispatcher
    "AdapterResolver",
    "Dispatcher",
    # Event Bus
    "EventBus",
    "EventSubscriber",
    # Enums
    "ExecutionEventType",
    "SessionState",
    "TaskState",
    # Exceptions
    "ExecutionAdapterError",
    "ExecutionDispatchError",
    "ExecutionError",
    "ExecutionRetryError",
    "ExecutionSchedulingError",
    "ExecutionSessionError",
    "ExecutionStateError",
    "ExecutionValidationError",
    # Models
    "ExecutionEvent",
    "ExecutionMetrics",
    "ExecutionResult",
    "ExecutionSession",
    "ExecutionTask",
    "InDegreeEntry",
    "RetryPolicy",
    "TaskResult",
    "ValidationResult",
    # Context
    "ExecutionContext",
    # Pipeline
    "ExecutionEngine",
    "get_pipeline",
    # Scheduler
    "Scheduler",
    # State Machine
    "StateMachine",
    # Validation
    "validate_plan_for_execution",
    "validate_session_initialization",
    # Metrics Collector
    "AdapterMetricsSnapshot",
    "MetricsCollector",
    "MetricsSnapshot",
]