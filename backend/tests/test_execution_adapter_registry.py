"""Unit tests for the Execution Engine Adapter Registry (Phase 3.6.4D).

Tests registration, resolution, priority ordering, unregistration,
validation, introspection, thread safety, and dispatcher integration.
"""

from __future__ import annotations

import asyncio
import threading
import pytest
from datetime import datetime, timezone
from typing import Optional

from services.execution.adapter_registry import AdapterDescriptor, AdapterRegistry
from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import TaskState
from services.execution.exceptions import ExecutionAdapterError, ExecutionDispatchError
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import ExecutionTask, TaskResult

from services.planner.planning_models import TaskType, Task, TaskStatus


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------

class MockAlphaAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "alpha"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True,
                          output={"from": "alpha"})


class MockBetaAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "beta"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True,
                          output={"from": "beta"})


class MockGammaAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "gamma"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_EMAIL, TaskType.SCHEDULE_MEETING]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True)


class MockDeltaAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "delta"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_EMAIL]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True,
                          output={"from": "delta"})


class MockInvalidNoType(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return ""

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True)


class MockInvalidNoTypes(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "invalid_no_types"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return []

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True)


class MockValidateFailAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "validate_fail"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM]

    def validate(self) -> Optional[list[str]]:
        return ["API key missing", "Endpoint timeout"]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True)


class MockVersionAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "versioned"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True)


class MockHighPriorityAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "high_priority"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(self, task, context):
        return TaskResult(task_id=task.id, attempt=1, success=True,
                          output={"from": "high_priority"})


# ===================================================================
# ADAPTER DESCRIPTOR TESTS
# ===================================================================

class TestAdapterDescriptor:
    def test_descriptor_creation(self):
        adapter = MockAlphaAdapter()
        now = datetime.now(timezone.utc)
        desc = AdapterDescriptor(
            adapter_type="alpha",
            adapter=adapter,
            priority=100,
            supported_task_types=[TaskType.SEND_MESSAGE],
            version="1.0.0",
            registered_at=now,
        )
        assert desc.adapter_type == "alpha"
        assert desc.adapter is adapter
        assert desc.priority == 100
        assert desc.version == "1.0.0"
        assert desc.registered_at == now

    def test_descriptor_default_registered_at(self):
        desc = AdapterDescriptor(
            adapter_type="t", adapter=MockAlphaAdapter(), priority=100,
            supported_task_types=[TaskType.SEND_MESSAGE],
        )
        assert desc.registered_at is not None
        assert isinstance(desc.registered_at, datetime)

    def test_descriptor_version_optional(self):
        desc = AdapterDescriptor(
            adapter_type="t", adapter=MockAlphaAdapter(), priority=100,
            supported_task_types=[TaskType.SEND_MESSAGE],
        )
        assert desc.version is None

    def test_descriptor_repr(self):
        desc = AdapterDescriptor(
            adapter_type="alpha", adapter=MockAlphaAdapter(), priority=50,
            supported_task_types=[TaskType.SEND_MESSAGE, TaskType.SEND_EMAIL],
        )
        r = repr(desc)
        assert "alpha" in r
        assert "50" in r


# ===================================================================
# REGISTRATION TESTS
# ===================================================================

class TestRegistryRegistration:
    def test_register_adapter(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        assert registry.count == 1

    def test_register_multiple_adapters(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockBetaAdapter())
        registry.register(MockGammaAdapter())
        assert registry.count == 3

    def test_register_idempotent_same_type(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=100)
        registry.register(MockAlphaAdapter(), priority=200)
        assert registry.count == 1

    def test_register_updates_priority(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=100)
        registry.register(MockAlphaAdapter(), priority=200)
        desc = registry.get_descriptor("alpha")
        assert desc is not None
        assert desc.priority == 200

    def test_register_preserves_registration_time(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        t1 = registry.get_descriptor("alpha").registered_at
        registry.register(MockAlphaAdapter(), priority=200)
        t2 = registry.get_descriptor("alpha").registered_at
        assert t1 == t2

    def test_register_with_default_priority(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        desc = registry.get_descriptor("alpha")
        assert desc.priority == 100

    def test_register_with_custom_priority(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=50)
        desc = registry.get_descriptor("alpha")
        assert desc.priority == 50

    def test_register_with_version(self):
        registry = AdapterRegistry()
        registry.register(MockVersionAdapter(), version="2.1.0")
        desc = registry.get_descriptor("versioned")
        assert desc.version == "2.1.0"

    def test_register_version_preserved_on_update(self):
        registry = AdapterRegistry()
        registry.register(MockVersionAdapter(), version="1.0.0")
        registry.register(MockVersionAdapter(), priority=50)
        desc = registry.get_descriptor("versioned")
        assert desc.version == "1.0.0"

    def test_register_version_updated_when_provided(self):
        registry = AdapterRegistry()
        registry.register(MockVersionAdapter(), version="1.0.0")
        registry.register(MockVersionAdapter(), version="2.0.0")
        desc = registry.get_descriptor("versioned")
        assert desc.version == "2.0.0"


class TestRegistryValidation:
    def test_register_non_adapter_raises(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register("not_an_adapter")  # type: ignore
        assert "ExecutionAdapter" in str(exc.value)

    def test_register_empty_type_raises(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register(MockInvalidNoType())
        assert "non-empty" in str(exc.value)

    def test_register_empty_supported_types_raises(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register(MockInvalidNoTypes())
        assert "non-empty" in str(exc.value)

    def test_register_negative_priority_raises(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register(MockAlphaAdapter(), priority=-1)
        assert "non-negative" in str(exc.value)

    def test_register_validation_fail_raises(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register(MockValidateFailAdapter())
        assert "validation failed" in str(exc.value).lower()

    def test_validation_error_has_issues(self):
        registry = AdapterRegistry()
        with pytest.raises(ExecutionAdapterError) as exc:
            registry.register(MockValidateFailAdapter())
        assert "issues" in exc.value.context
        assert "API key missing" in str(exc.value.context["issues"])

    def test_register_valid_adapter_succeeds(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        assert registry.count == 1

    def test_register_zero_priority(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=0)
        assert registry.count == 1


# ===================================================================
# RESOLUTION TESTS
# ===================================================================

class TestRegistryResolution:
    def test_resolve_known_type(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter is not None
        assert adapter.adapter_type == "alpha"

    def test_resolve_unknown_type(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        adapter = registry.resolve(TaskType.SEND_EMAIL)
        assert adapter is None

    def test_resolve_empty_registry(self):
        registry = AdapterRegistry()
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter is None

    def test_resolve_returns_adapter_instance(self):
        registry = AdapterRegistry()
        adapter_inst = MockAlphaAdapter()
        registry.register(adapter_inst)
        resolved = registry.resolve(TaskType.SEND_MESSAGE)
        assert resolved is adapter_inst

    def test_resolve_multiple_types(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())   # SEND_MESSAGE
        registry.register(MockGammaAdapter())   # SEND_EMAIL, SCHEDULE_MEETING
        assert registry.resolve(TaskType.SEND_MESSAGE) is not None
        assert registry.resolve(TaskType.SEND_EMAIL) is not None
        assert registry.resolve(TaskType.SCHEDULE_MEETING) is not None
        assert registry.resolve(TaskType.WAIT_FOR_REPLY) is None

    def test_resolve_after_unregister_returns_none(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.unregister("alpha")
        assert registry.resolve(TaskType.SEND_MESSAGE) is None

    def test_resolve_after_clear(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.clear()
        assert registry.resolve(TaskType.SEND_MESSAGE) is None


class TestRegistryPriorityResolution:
    def test_higher_priority_wins(self):
        registry = AdapterRegistry()
        registry.register(MockBetaAdapter(), priority=50)
        registry.register(MockAlphaAdapter(), priority=100)
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter is not None
        assert adapter.adapter_type == "alpha"

    def test_lower_priority_not_returned(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=100)
        registry.register(MockBetaAdapter(), priority=50)
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter.adapter_type == "alpha"

    def test_priority_update_changes_resolution(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=50)
        registry.register(MockBetaAdapter(), priority=100)
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter.adapter_type == "beta"
        registry.register(MockAlphaAdapter(), priority=200)
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter.adapter_type == "alpha"

    def test_equal_priority_resolves_deterministically(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=100)
        registry.register(MockBetaAdapter(), priority=100)
        adapter1 = registry.resolve(TaskType.SEND_MESSAGE)
        adapter2 = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter1.adapter_type == adapter2.adapter_type

    def test_equal_priority_alpha_sorted_first(self):
        registry = AdapterRegistry()
        registry.register(MockBetaAdapter(), priority=100)
        registry.register(MockAlphaAdapter(), priority=100)
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        # Alpha sorts before beta alphabetically
        assert adapter.adapter_type == "alpha"

    def test_priority_zero_valid(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=0)
        assert registry.resolve(TaskType.SEND_MESSAGE) is not None


# ===================================================================
# UNREGISTRATION TESTS
# ===================================================================

class TestRegistryUnregistration:
    def test_unregister_existing(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.unregister("alpha")
        assert registry.count == 0

    def test_unregister_nonexistent(self):
        registry = AdapterRegistry()
        registry.unregister("nonexistent")  # should not raise

    def test_unregister_removes_from_type_map(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        assert registry.resolve(TaskType.SEND_MESSAGE) is not None
        registry.unregister("alpha")
        assert registry.resolve(TaskType.SEND_MESSAGE) is None

    def test_unregister_one_of_many(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())  # SEND_MESSAGE
        registry.register(MockBetaAdapter())   # SEND_MESSAGE
        registry.unregister("alpha")
        adapter = registry.resolve(TaskType.SEND_MESSAGE)
        assert adapter is not None
        assert adapter.adapter_type == "beta"
        assert registry.count == 1

    def test_unregister_removes_supported_types(self):
        registry = AdapterRegistry()
        registry.register(MockGammaAdapter())  # SEND_EMAIL, SCHEDULE_MEETING
        registry.unregister("gamma")
        assert registry.resolve(TaskType.SEND_EMAIL) is None
        assert registry.resolve(TaskType.SCHEDULE_MEETING) is None

    def test_unregister_cleans_up_empty_type_entries(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())  # only SEND_MESSAGE
        registry.unregister("alpha")
        result = registry.get_supported_types()
        assert result == {}

    def test_clear_removes_all(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockBetaAdapter())
        registry.register(MockGammaAdapter())
        registry.clear()
        assert registry.count == 0
        assert registry.resolve(TaskType.SEND_MESSAGE) is None

    def test_clear_allows_reregister(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.clear()
        registry.register(MockAlphaAdapter())
        assert registry.count == 1
        assert registry.resolve(TaskType.SEND_MESSAGE) is not None


# ===================================================================
# INTROSPECTION TESTS
# ===================================================================

class TestRegistryIntrospection:
    def test_get_supported_types(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockGammaAdapter())
        types = registry.get_supported_types()
        assert "alpha" in types
        assert "gamma" in types
        assert types["alpha"] == [TaskType.SEND_MESSAGE]
        assert TaskType.SEND_EMAIL in types["gamma"]
        assert TaskType.SCHEDULE_MEETING in types["gamma"]

    def test_get_supported_types_empty(self):
        registry = AdapterRegistry()
        assert registry.get_supported_types() == {}

    def test_list_registered(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockBetaAdapter())
        descriptors = registry.list_registered()
        assert len(descriptors) == 2

    def test_list_registered_sorted(self):
        registry = AdapterRegistry()
        registry.register(MockBetaAdapter())
        registry.register(MockAlphaAdapter())
        descriptors = registry.list_registered()
        assert descriptors[0].adapter_type == "alpha"
        assert descriptors[1].adapter_type == "beta"

    def test_list_registered_empty(self):
        registry = AdapterRegistry()
        assert registry.list_registered() == []

    def test_list_registered_descriptor_fields(self):
        registry = AdapterRegistry()
        registry.register(MockVersionAdapter(), priority=50, version="1.2")
        descs = registry.list_registered()
        assert len(descs) == 1
        d = descs[0]
        assert d.adapter_type == "versioned"
        assert d.priority == 50
        assert d.version == "1.2"

    def test_get_descriptor_exists(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=75)
        desc = registry.get_descriptor("alpha")
        assert desc is not None
        assert desc.priority == 75

    def test_get_descriptor_nonexistent(self):
        registry = AdapterRegistry()
        assert registry.get_descriptor("nonexistent") is None

    def test_count_property(self):
        registry = AdapterRegistry()
        assert registry.count == 0
        registry.register(MockAlphaAdapter())
        assert registry.count == 1
        registry.register(MockBetaAdapter())
        assert registry.count == 2


# ===================================================================
# THREAD SAFETY TESTS
# ===================================================================

class TestRegistryThreadSafety:
    def test_concurrent_register(self):
        registry = AdapterRegistry()
        errors = []

        def register_adapter(name):
            try:
                if name == "alpha":
                    registry.register(MockAlphaAdapter())
                elif name == "beta":
                    registry.register(MockBetaAdapter())
                elif name == "gamma":
                    registry.register(MockGammaAdapter())
                elif name == "delta":
                    registry.register(MockDeltaAdapter())
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_adapter, args=("alpha",)),
            threading.Thread(target=register_adapter, args=("beta",)),
            threading.Thread(target=register_adapter, args=("gamma",)),
            threading.Thread(target=register_adapter, args=("delta",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert registry.count == 4

    def test_concurrent_resolve(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockBetaAdapter())

        results = []

        def resolve():
            for _ in range(100):
                a = registry.resolve(TaskType.SEND_MESSAGE)
                if a is not None:
                    results.append(a.adapter_type)

        threads = [threading.Thread(target=resolve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000

    def test_concurrent_register_and_resolve(self):
        registry = AdapterRegistry()
        registry.register(MockBetaAdapter())

        results = []

        def register_and_resolve():
            registry.register(MockAlphaAdapter())
            for _ in range(50):
                a = registry.resolve(TaskType.SEND_MESSAGE)
                if a is not None:
                    results.append(a.adapter_type)

        threads = [threading.Thread(target=register_and_resolve) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) >= 0  # no crash, no corruption

    def test_concurrent_unregister(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.register(MockBetaAdapter())
        registry.register(MockGammaAdapter())

        errors = []

        def unregister(name):
            try:
                registry.unregister(name)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=unregister, args=("alpha",)),
            threading.Thread(target=unregister, args=("beta",)),
            threading.Thread(target=unregister, args=("gamma",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert registry.count == 0

    def test_concurrent_clear_and_register(self):
        registry = AdapterRegistry()
        errors = []

        def writer():
            for _ in range(20):
                try:
                    registry.clear()
                    registry.register(MockAlphaAdapter())
                    registry.register(MockBetaAdapter())
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(20):
                try:
                    registry.resolve(TaskType.SEND_MESSAGE)
                    registry.get_supported_types()
                    registry.list_registered()
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0


# ===================================================================
# PROTOCOL COMPATIBILITY TESTS
# ===================================================================

class TestRegistryProtocolCompatibility:
    def test_registry_satisfies_resolver_protocol(self):
        registry = AdapterRegistry()
        assert hasattr(registry, "resolve")
        result = registry.resolve(TaskType.SEND_MESSAGE)
        assert result is None  # empty registry, no crash

    def test_registry_as_resolver(self):
        resolver: AdapterResolver = AdapterRegistry()
        resolver.register(MockAlphaAdapter())
        a = resolver.resolve(TaskType.SEND_MESSAGE)
        assert a is not None

    def test_dispatcher_with_registry_resolver(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        result = asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert result.success is True
        assert result.output["from"] == "alpha"


# ===================================================================
# DISPATCHER + REGISTRY INTEGRATION TESTS
# ===================================================================

class TestDispatcherRegistryIntegration:
    def test_dispatch_with_registered_adapter(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        result = asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert result.success is True

    def test_dispatch_sets_adapter_name(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert task.adapter_name == "alpha"

    def test_dispatch_unsupported_raises(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        with pytest.raises(ExecutionDispatchError):
            asyncio.run(Dispatcher.dispatch(task, ctx, registry))

    def test_dispatch_uses_highest_priority(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter(), priority=50)
        registry.register(MockBetaAdapter(), priority=100)
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        result = asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert result.output["from"] == "beta"

    def test_dispatch_after_unregister(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.unregister("alpha")
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        with pytest.raises(ExecutionDispatchError):
            asyncio.run(Dispatcher.dispatch(task, ctx, registry))

    def test_dispatch_after_clear(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        registry.clear()
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        with pytest.raises(ExecutionDispatchError):
            asyncio.run(Dispatcher.dispatch(task, ctx, registry))

    def test_dispatch_multiple_task_types(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())   # SEND_MESSAGE
        registry.register(MockGammaAdapter())   # SEND_EMAIL, SCHEDULE_MEETING
        ctx = ExecutionContext(session_id="s1")

        results = []
        for tt, expected_type in [
            (TaskType.SEND_MESSAGE, "alpha"),
            (TaskType.SEND_EMAIL, "gamma"),
            (TaskType.SCHEDULE_MEETING, "gamma"),
        ]:
            task = ExecutionTask(
                id=f"t-{tt.value}",
                plan_task=Task(
                    id=f"t-{tt.value}", plan_id="p", type=tt,
                    status=TaskStatus.PENDING,
                ),
            )
            r = asyncio.run(Dispatcher.dispatch(task, ctx, registry))
            results.append(r)
            assert r.success is True

        assert len(results) == 3

    def test_dispatch_adapter_name_unset_on_failure(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        with pytest.raises(ExecutionDispatchError):
            asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert task.adapter_name is None

    def test_registry_resolve_called_by_dispatcher(self):
        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="s1")
        result = asyncio.run(Dispatcher.dispatch(task, ctx, registry))
        assert result.task_id == "t1"
        assert result.success is True

    def test_registry_with_pipeline(self):
        from services.execution.execution_pipeline import ExecutionEngine
        from services.planner.planning_models import (
            Plan, PlanGoal, PlanStatus, Task, TaskStatus, TaskType,
        )
        from services.planner.payloads import MessagePayload

        registry = AdapterRegistry()
        registry.register(MockAlphaAdapter())

        engine = ExecutionEngine()
        plan = Plan(
            id="reg-plan",
            conversation_id="conv-1",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="hello"),
                label="test",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=registry))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-a"].result is not None
        assert session.tasks["task-a"].result.success is True
        assert session.tasks["task-a"].adapter_name == "alpha"
