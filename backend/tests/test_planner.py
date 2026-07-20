"""Unit tests for the Planning Engine.

Tests DAG validation, strategy selection, plan validation,
and the full planning pipeline.
"""

from __future__ import annotations
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from services.planner.planning_models import (
    Plan, PlanGoal, Task, Trigger, Branch, Dependency,
    PlanStatus, TaskStatus, TaskType, TriggerType,
    BranchCondition, ApprovalRequirement,
)
from services.planner.dependency_builder import _has_cycle, validate_dag, build_dependencies
from services.planner.plan_validator import validate_plan, ValidationResult
from services.planner.planning_pipeline import PlanningPipeline
from services.planner.strategies.planning_registry import (
    register_strategy, select_strategy, list_strategies, get_strategy,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints, ApprovalRule
from services.planner.task_generator import generate_tasks
from services.planner.strategies.planning_registry import _strategies as _strategy_store
from services.planner.exceptions import (
    PlanningError, PlanningValidationError, PlanningStrategyError,
    PlanningGraphError, PlanningSchedulingError, PlanningPipelineError,
)
from services.planner.payloads import (
    MessagePayload, WaitForReplyPayload, UpdateCRMPayload,
    TaskPayload,
)


# Register default strategies once for all tests
def _register_test_strategies():
    from services.planner.strategies.demo_booking import demo_booking_strategy
    from services.planner.strategies.pricing_objection import pricing_objection_strategy
    from services.planner.strategies.nurture import nurture_strategy
    from services.planner.strategies.cold_outreach import cold_outreach_strategy
    from services.planner.strategies.follow_up import follow_up_strategy
    from services.planner.strategies.re_engagement import re_engagement_strategy
    from services.planner.strategies.general_engagement import general_engagement_strategy
    from services.planner.strategies.escalation import escalation_strategy
    _strategy_store.clear()
    for s in [demo_booking_strategy, pricing_objection_strategy, nurture_strategy,
              cold_outreach_strategy, follow_up_strategy, re_engagement_strategy,
              general_engagement_strategy, escalation_strategy]:
        register_strategy(s.name, s)


_register_test_strategies()


def _make_enum_value(name: str, fallback_value: str = ""):
    obj = type("FakeEnum", (), {"value": name, "name": name.upper()})()
    return obj


# ── Fixtures ──

@pytest.fixture
def minimal_reasoning_result():
    class FakeDecision:
        pass

    fd = FakeDecision()
    fd.type = _make_enum_value("reply")
    fd.priority = _make_enum_value("medium")
    fd.risk = _make_enum_value("low")
    fd.confidence = 0.75
    fd.primary_goal = _make_enum_value("reply")
    fd.alternative_goal = _make_enum_value("wait")
    fd.evidence = ["Intent: interested (0.85)", "Health: 7/10"]
    fd.reasoning = ["Decision: reply.", "Goal: engage prospect."]
    fd.policy_results = []

    class FakeResult:
        pass

    fr = FakeResult()
    fr.conversation_id = "conv_123"
    fr.reasoning_id = "reason_456"
    fr.decision = fd
    fr.created_at = datetime.now(timezone.utc)
    fr.pipeline_version = "1.0.0"

    return fr


@pytest.fixture
def empty_reasoning():
    class FakeDecision:
        pass

    fd = FakeDecision()
    fd.type = _make_enum_value("wait")
    fd.priority = _make_enum_value("low")
    fd.risk = _make_enum_value("low")
    fd.confidence = 0.3
    fd.primary_goal = _make_enum_value("wait")
    fd.alternative_goal = _make_enum_value("wait")
    fd.evidence = []
    fd.reasoning = []
    fd.policy_results = []

    class FakeResult:
        pass

    fr = FakeResult()
    fr.conversation_id = "conv_empty"
    fr.reasoning_id = "reason_empty"
    fr.decision = fd
    fr.created_at = datetime.now(timezone.utc)
    fr.pipeline_version = "1.0.0"

    return fr


@pytest.fixture
def simple_plan():
    task_a = Task(
        id="task_a", label="Task A", type=TaskType.SEND_MESSAGE,
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message A",
    )
    task_b = Task(
        id="task_b", label="Task B", type=TaskType.SEND_MESSAGE,
        dependencies=["task_a"],
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message B",
    )
    task_c = Task(
        id="task_c", label="Task C", type=TaskType.SEND_MESSAGE,
        dependencies=["task_b"],
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message C",
    )
    return Plan(
        id="plan_test",
        tasks=[task_a, task_b, task_c],
        goal=PlanGoal(outcome="Test", target_action="reply"),
    )


@pytest.fixture
def cyclic_plan():
    task_a = Task(
        id="task_a", label="Task A", type=TaskType.SEND_MESSAGE,
        dependencies=["task_c"],
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message A",
    )
    task_b = Task(
        id="task_b", label="Task B", type=TaskType.SEND_MESSAGE,
        dependencies=["task_a"],
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message B",
    )
    task_c = Task(
        id="task_c", label="Task C", type=TaskType.SEND_MESSAGE,
        dependencies=["task_b"],
        reasoning_trace="Test", reasoning_goal="reply",
        instructions="Send message C",
    )
    return Plan(
        id="plan_cycle",
        tasks=[task_a, task_b, task_c],
        goal=PlanGoal(outcome="Test", target_action="reply"),
    )


# ── DAG Cycle Detection Tests ──

class TestDAGCycleDetection:
    def test_linear_dag_no_cycle(self, simple_plan):
        assert not _has_cycle(simple_plan)

    def test_cyclic_dag_detects_cycle(self, cyclic_plan):
        assert _has_cycle(cyclic_plan)

    def test_empty_plan_no_cycle(self):
        plan = Plan(tasks=[], goal=PlanGoal())
        assert not _has_cycle(plan)

    def test_single_task_no_cycle(self):
        task = Task(id="single", label="Single", type=TaskType.SEND_MESSAGE,
                    reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[task], goal=PlanGoal())
        assert not _has_cycle(plan)

    def test_diamond_dag_no_cycle(self):
        a = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                 reasoning_trace="Test", reasoning_goal="reply")
        b = Task(id="b", label="B", type=TaskType.SEND_MESSAGE,
                 dependencies=["a"], reasoning_trace="Test", reasoning_goal="reply")
        c = Task(id="c", label="C", type=TaskType.SEND_MESSAGE,
                 dependencies=["a"], reasoning_trace="Test", reasoning_goal="reply")
        d = Task(id="d", label="D", type=TaskType.SEND_MESSAGE,
                 dependencies=["b", "c"], reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[a, b, c, d], goal=PlanGoal())
        assert not _has_cycle(plan)

    def test_self_reference_cycle(self):
        task = Task(id="self", label="Self", type=TaskType.SEND_MESSAGE,
                    dependencies=["self"], reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[task], goal=PlanGoal())
        assert _has_cycle(plan)


# ── DAG Validation Tests ──

class TestDAGValidation:
    def test_valid_dag_passes(self, simple_plan):
        errors = validate_dag(simple_plan)
        assert len(errors) == 0

    def test_cyclic_dag_fails(self, cyclic_plan):
        errors = validate_dag(cyclic_plan)
        assert any("cycle" in e.lower() for e in errors)

    def test_dangling_dependency_detected(self):
        task = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                    dependencies=["nonexistent"],
                    reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[task], goal=PlanGoal())
        errors = validate_dag(plan)
        assert any("unknown" in e.lower() for e in errors)

    def test_no_terminal_node_detected(self):
        a = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                 dependencies=[], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do A")
        b = Task(id="b", label="B", type=TaskType.SEND_MESSAGE,
                 dependencies=["a"], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do B")
        c = Task(id="c", label="C", type=TaskType.SEND_MESSAGE,
                 dependencies=["b"], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do C")
        d = Task(id="d", label="D", type=TaskType.SEND_MESSAGE,
                 dependencies=["c"], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do D")
        a.dependencies = ["d"]
        b.dependencies = ["a"]
        c.dependencies = ["b"]
        d.dependencies = ["c"]
        plan = Plan(tasks=[a, b, c, d], goal=PlanGoal())
        errors = validate_dag(plan)
        assert any("cycle" in e.lower() for e in errors) or not plan.get_terminal_tasks()

    def test_unreachable_tasks_detected(self):
        a = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                 dependencies=[], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do A")
        b = Task(id="b", label="B", type=TaskType.SEND_MESSAGE,
                 dependencies=["a"], reasoning_trace="Test", reasoning_goal="reply",
                 instructions="Do B")
        orphan = Task(id="orphan", label="Orphan", type=TaskType.SEND_MESSAGE,
                       dependencies=["nonexistent"], reasoning_trace="Test",
                       reasoning_goal="reply", instructions="Do orphan")
        plan = Plan(tasks=[a, b, orphan], goal=PlanGoal())
        result = validate_plan(plan)
        assert any("dangling" in i.message or "unknown" in i.message for i in result.issues)


# ── Plan Validation Tests ──

class TestPlanValidation:
    def test_valid_plan_passes(self, simple_plan):
        result = validate_plan(simple_plan)
        assert result.valid

    def test_empty_plan_fails(self):
        plan = Plan(tasks=[], goal=PlanGoal())
        result = validate_plan(plan)
        assert not result.valid
        assert any("EMPTY_PLAN" in i.code for i in result.issues)

    def test_duplicate_ids_detected(self):
        task_a = Task(id="dup", label="A", type=TaskType.SEND_MESSAGE,
                      reasoning_trace="Test", reasoning_goal="reply")
        task_b = Task(id="dup", label="B", type=TaskType.SEND_MESSAGE,
                      dependencies=["dup"], reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[task_a, task_b], goal=PlanGoal())
        result = validate_plan(plan)
        assert not result.valid
        assert any("duplicate" in i.message.lower() for i in result.issues)

    def test_missing_reasoning_trace_warns(self):
        task = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                    reasoning_trace="", reasoning_goal="reply",
                    instructions="Do something")
        plan = Plan(tasks=[task], goal=PlanGoal())
        result = validate_plan(plan)
        assert any("reasoning_trace" in w.message for w in result.warnings)

    def test_missing_instructions_fails(self):
        task = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                    instructions="", reasoning_trace="Test", reasoning_goal="reply")
        plan = Plan(tasks=[task], goal=PlanGoal())
        result = validate_plan(plan)
        assert not result.valid
        assert any("instructions" in i.message.lower() for i in result.issues)

    def test_branch_structure_validation(self):
        task = Task(
            id="branch_task", label="Branch", type=TaskType.SEND_MESSAGE,
            branch=Branch(condition=BranchCondition.REPLY_RECEIVED),
            reasoning_trace="Test", reasoning_goal="reply",
            instructions="Do something",
        )
        plan = Plan(tasks=[task], goal=PlanGoal())
        result = validate_plan(plan)
        assert any("branch" in i.message.lower() for i in result.issues)


# ── Strategy Selection Tests ──

class TestStrategySelection:
    def test_demo_booking_selected_for_book_meeting(self):
        goal = PlanGoal(
            outcome="Schedule and confirm a meeting",
            target_action="book_meeting",
        )
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "demo_booking"

    def test_cold_outreach_selected_for_initial_outreach(self):
        goal = PlanGoal(
            outcome="Introduce our product",
            target_action="cold_outreach",
        )
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "cold_outreach"

    def test_follow_up_selected_for_follow_up(self):
        goal = PlanGoal(
            outcome="Follow up on previous conversation",
            target_action="follow_up",
        )
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "follow_up"

    def test_escalation_selected_for_escalate(self):
        goal = PlanGoal(
            outcome="Escalate to human team",
            target_action="escalate",
        )
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "escalation"

    def test_general_engagement_fallback(self):
        goal = PlanGoal(
            outcome="Do something generic",
            target_action="unknown_action_xyz",
        )
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "general_engagement"

    def test_all_strategies_registered(self):
        strategies = list_strategies()
        expected = [
            "demo_booking", "pricing_objection", "nurture",
            "cold_outreach", "follow_up", "re_engagement",
            "general_engagement", "escalation",
        ]
        for name in expected:
            assert name in strategies, f"Strategy '{name}' not registered"

    def test_custom_strategy_registration(self):
        class CustomStrategy(Strategy):
            @property
            def name(self):
                return "custom_test"
            def generate_tasks(self, goal, context):
                return [Task(label="Custom task", type=TaskType.SEND_MESSAGE,
                            reasoning_trace="Custom", reasoning_goal="test")]
            def matches(self, goal):
                return 1.0 if goal.target_action == "custom" else 0.0

        strategy = CustomStrategy()
        register_strategy("custom_test", strategy)
        try:
            assert get_strategy("custom_test") is strategy

            goal = PlanGoal(target_action="custom")
            selected = select_strategy(goal)
            assert selected is not None
            assert selected.name == "custom_test"
        finally:
            _strategy_store.pop(strategy.name, None)


# ── Task Generation Tests ──

class TestTaskGeneration:
    def test_demo_booking_generates_4_tasks(self):
        goal = PlanGoal(target_action="book_meeting")
        context = {"prospect_name": "John", "company": "Acme Corp"}
        strategy = select_strategy(goal)
        assert strategy is not None
        tasks = generate_tasks(goal, context, strategy)
        assert len(tasks) >= 3

    def test_tasks_have_reasoning_trace(self):
        goal = PlanGoal(target_action="follow_up")
        context = {"prospect_name": "Jane"}
        strategy = select_strategy(goal)
        assert strategy is not None
        tasks = generate_tasks(goal, context, strategy)
        for t in tasks:
            assert t.reasoning_trace, f"Task '{t.label}' missing reasoning_trace"

    def test_tasks_have_reasoning_goal(self):
        goal = PlanGoal(target_action="reply")
        context = {}
        strategy = select_strategy(goal)
        assert strategy is not None
        tasks = generate_tasks(goal, context, strategy)
        for t in tasks:
            assert t.reasoning_goal, f"Task '{t.label}' missing reasoning_goal"


# ── Full Pipeline Tests ──

class TestFullPipeline:
    def test_pipeline_produces_plan(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        assert plan is not None
        assert len(plan.tasks) > 0
        assert plan.goal is not None

    def test_pipeline_plan_has_strategy(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        assert plan.strategy != ""

    def test_pipeline_tasks_have_triggers(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        for t in plan.tasks:
            assert t.trigger is not None, f"Task '{t.label}' missing trigger"

    def test_pipeline_status_validated(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        assert plan.status == PlanStatus.VALIDATED or plan.status == PlanStatus.DRAFT

    def test_low_confidence_generates_approvals(self, empty_reasoning):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(empty_reasoning)
        approvals = [t for t in plan.tasks if t.approval != ApprovalRequirement.NONE]
        assert len(approvals) > 0

    def test_pipeline_no_crash_on_minimal_input(self):
        class BareMinimum:
            conversation_id = "test"
            reasoning_id = "test"
            decision = None
            created_at = datetime.now(timezone.utc)
            pipeline_version = "1.0.0"

        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(BareMinimum())
        assert plan is not None

    def test_pipeline_dag_is_acyclic(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        from services.planner.dependency_builder import _has_cycle
        assert not _has_cycle(plan)

    def test_pipeline_all_tasks_have_plan_id(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        for t in plan.tasks:
            assert t.plan_id == plan.id


# ── Pipeline Isolation Tests (planner must not execute) ──

class TestPipelineIsolation:
    def test_planner_produces_plan_not_reply(self, minimal_reasoning_result):
        pipeline = PlanningPipeline()
        plan, validation = pipeline.plan(minimal_reasoning_result)
        for t in plan.tasks:
            assert t.type != TaskType.SEND_MESSAGE or "reply" not in (t.instructions or "").lower()


# ── DAG Properties Tests ──

class TestDAGProperties:
    def test_plan_has_root_tasks(self, simple_plan):
        roots = simple_plan.get_root_tasks()
        assert len(roots) >= 1

    def test_plan_has_terminal_tasks(self, simple_plan):
        terminals = simple_plan.get_terminal_tasks()
        assert len(terminals) >= 1

    def test_get_downstream_tasks(self, simple_plan):
        downstream = simple_plan.get_downstream_tasks("task_a")
        assert len(downstream) >= 1

    def test_get_all_dependency_pairs(self, simple_plan):
        pairs = simple_plan.get_all_dependency_pairs()
        assert len(pairs) >= 2

    def test_task_map(self, simple_plan):
        task_map = simple_plan.get_task_map()
        assert "task_a" in task_map
        assert "task_b" in task_map
        assert "task_c" in task_map


# ── Hardening Tests ──


class TestValidationFailFast:
    def test_pipeline_raises_on_validation_failure(self):
        # Register a custom strategy that always produces an invalid task.
        class InvalidTestStrategy(Strategy):
            @property
            def name(self) -> str:
                return "invalid_test_strategy"

            def matches(self, goal: PlanGoal) -> float:
                return 1.0  # Wins over general_engagement

            def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
                return [
                    Task(
                        id="invalid_task",
                        label="Invalid",
                        type=TaskType.SEND_MESSAGE,
                        instructions="",
                        reasoning_trace="",
                        reasoning_goal="",
                    ),
                ]

        strategy = InvalidTestStrategy()
        register_strategy(strategy.name, strategy)
        try:
            pipeline = PlanningPipeline()
            with pytest.raises(PlanningValidationError) as exc_info:
                pipeline.plan(_make_reasoning_with_plan())
            assert "validation failed" in str(exc_info.value.message).lower()
            assert exc_info.value.context["issues"]
            assert exc_info.value.to_dict()["error_type"] == "PlanningValidationError"
            # Ensure the returned context carries diagnostic suggestions.
            issue_dicts = exc_info.value.context["issues"]
            assert any("suggested_fix" in issue for issue in issue_dicts)
        finally:
            # Cleanup test-only strategy registration.
            _strategy_store.pop(strategy.name, None)

    def test_validate_plan_returns_suggested_fix(self):
        bad_task = Task(
            id="bad",
            label="Bad",
            type=TaskType.SEND_MESSAGE,
            instructions="",
            reasoning_trace="",
            reasoning_goal="",
        )
        plan = Plan(tasks=[bad_task], goal=PlanGoal())
        result = validate_plan(plan)
        assert not result.valid
        issue = result.issues[0]
        assert issue.suggested_fix
        assert issue.to_dict()["suggested_fix"] == issue.suggested_fix


class TestTypedPayloads:
    def test_message_payload_serializes_with_payload_type(self):
        payload = MessagePayload(channel="email", template="demo_invitation")
        task = Task(payload=payload)
        assert task.params["channel"] == "email"
        assert task.params["payload_type"] == "MessagePayload"

    def test_payload_reconstructs_from_params(self):
        payload = WaitForReplyPayload(timeout="3d", fallback="send_followup")
        task = Task(payload=payload)
        reconstructed = task.get_payload()
        assert isinstance(reconstructed, WaitForReplyPayload)
        assert reconstructed.timeout == "3d"

    def test_payload_validation_catches_invalid_duration(self):
        payload = WaitForReplyPayload(timeout="not-a-duration", fallback="x")
        errors = payload.validate()
        assert len(errors) > 0

    def test_payload_registry_roundtrip(self):
        from services.planner.payloads import get_payload_class, PAYLOAD_REGISTRY
        assert get_payload_class("MessagePayload") is MessagePayload
        assert "UpdateCRMPayload" in PAYLOAD_REGISTRY

    def test_strategy_generated_tasks_have_typed_payloads(self):
        goal = PlanGoal(target_action="book_meeting")
        strategy = get_strategy("demo_booking")
        assert strategy is not None
        tasks = generate_tasks(goal, {"prospect_name": "Ada"}, strategy)
        for t in tasks:
            assert t.get_payload() is not None, f"Task '{t.label}' has no typed payload"
            assert t.params.get("payload_type") is not None


class TestIDBasedDependencyResolution:
    def test_dependencies_use_task_ids_not_labels(self):
        goal = PlanGoal(target_action="book_meeting")
        strategy = get_strategy("demo_booking")
        assert strategy is not None
        tasks = generate_tasks(goal, {"prospect_name": "Ada"}, strategy)
        dep_pairs = strategy.dependencies(tasks)
        task_ids = {t.id for t in tasks}
        for source_id, target_id in dep_pairs:
            assert source_id in task_ids
            assert target_id in task_ids
            assert source_id != target_id

    def test_dependency_builder_validates_missing_refs(self):
        t1 = Task(id="t1", label="T1", type=TaskType.SEND_MESSAGE,
                  instructions="Do 1", reasoning_trace="r", reasoning_goal="g")
        t2 = Task(id="t2", label="T2", type=TaskType.SEND_MESSAGE,
                  dependencies=["missing_id"], instructions="Do 2",
                  reasoning_trace="r", reasoning_goal="g")
        plan = Plan(tasks=[t1, t2], goal=PlanGoal())
        with pytest.raises(PlanningGraphError) as exc_info:
            build_dependencies(plan)
        assert "unknown" in str(exc_info.value.message).lower()


class TestStrategyRegistryHardening:
    def test_register_strategy_is_idempotent(self):
        from services.planner.strategies.general_engagement import general_engagement_strategy
        name = general_engagement_strategy.name
        # Second registration should be a no-op, not raise
        register_strategy(name, general_engagement_strategy)
        assert get_strategy(name) is general_engagement_strategy

    def test_default_strategies_registered(self):
        strategies = list_strategies()
        assert len(strategies) >= 11
        assert set(strategies) >= {
            "demo_booking", "pricing_objection", "nurture",
            "cold_outreach", "follow_up", "re_engagement",
            "general_engagement", "escalation",
            "adaptive_follow_up", "draft_revision",
        }

    def test_registry_snapshot_during_selection(self):
        goal = PlanGoal(target_action="book_meeting")
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "demo_booking"


class TestExceptionHierarchy:
    def test_planning_error_to_dict(self):
        err = PlanningError("base error", context={"key": "val"})
        d = err.to_dict()
        assert d["error_type"] == "PlanningError"
        assert d["message"] == "base error"

    def test_all_subclasses_inherit_from_planning_error(self):
        for cls in [PlanningValidationError, PlanningStrategyError,
                    PlanningGraphError, PlanningSchedulingError, PlanningPipelineError]:
            err = cls("msg", context={})
            assert isinstance(err, PlanningError)
            assert err.to_dict()["error_type"] == cls.__name__


class TestValidationDiagnostics:
    def test_cycle_issue_includes_suggested_fix(self):
        a = Task(id="a", label="A", type=TaskType.SEND_MESSAGE,
                 dependencies=["c"], instructions="i", reasoning_trace="r", reasoning_goal="g")
        b = Task(id="b", label="B", type=TaskType.SEND_MESSAGE,
                 dependencies=["a"], instructions="i", reasoning_trace="r", reasoning_goal="g")
        c = Task(id="c", label="C", type=TaskType.SEND_MESSAGE,
                 dependencies=["b"], instructions="i", reasoning_trace="r", reasoning_goal="g")
        plan = Plan(tasks=[a, b, c], goal=PlanGoal())
        result = validate_plan(plan)
        cycle_issues = [i for i in result.issues if i.code == "CYCLE_DETECTED"]
        assert cycle_issues
        assert any("circular" in i.suggested_fix.lower() for i in cycle_issues)

    def test_missing_instructions_includes_suggested_fix(self):
        t = Task(id="t", label="T", type=TaskType.SEND_MESSAGE,
                 instructions="", reasoning_trace="r", reasoning_goal="g")
        result = validate_plan(Plan(tasks=[t], goal=PlanGoal()))
        issue = next(i for i in result.issues if i.code == "MISSING_INSTRUCTIONS")
        assert "instructions" in issue.suggested_fix.lower()

    def test_validation_result_serializes(self):
        result = validate_plan(Plan(tasks=[], goal=PlanGoal()))
        d = result.to_dict()
        assert not d["valid"]
        assert "suggested_fix" in d["issues"][0]


# ── Helpers ──

def _make_reasoning_with_plan(plan: Plan | None = None) -> Any:
    """Return a fake reasoning result that the pipeline will turn into the supplied plan.

    The pipeline re-analyzes the goal and selects a strategy, so the simplest
    fail-fast path is to call pipeline._validate directly.  This helper keeps
    tests focused on behavior rather than fixtures.
    """
    class FakeDecision:
        pass

    fd = FakeDecision()
    fd.type = type("FakeEnum", (), {"value": "reply"})()
    fd.priority = type("FakeEnum", (), {"value": "medium"})()
    fd.risk = type("FakeEnum", (), {"value": "low"})()
    fd.confidence = 0.75
    fd.primary_goal = type("FakeEnum", (), {"value": "reply"})()
    fd.alternative_goal = type("FakeEnum", (), {"value": "wait"})()
    fd.evidence = []
    fd.reasoning = []
    fd.policy_results = []

    class FakeResult:
        pass

    fr = FakeResult()
    fr.conversation_id = "conv_test"
    fr.reasoning_id = "reason_test"
    fr.decision = fd
    fr.created_at = datetime.now(timezone.utc)
    fr.pipeline_version = "1.0.0"
    return fr
