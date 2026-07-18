"""Planning Pipeline — orchestrates all planning stages.

Pipeline:
  Reasoning Result
  → Goal Analysis
  → Strategy Selection
  → Task Generation
  → Dependency Resolution
  → Scheduling
  → Branching
  → Approval Annotation
  → Validation
  → Execution Plan

Each stage is independently testable.
The planner does not execute actions, generate replies, or call providers.

Validation failures fail fast and raise PlanningValidationError.
Other stage failures raise typed PlanningError subclasses with context.
"""

from __future__ import annotations
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from services.planner.exceptions import (
    PlanningError,
    PlanningValidationError,
    PlanningStrategyError,
    PlanningGraphError,
    PlanningSchedulingError,
    PlanningPipelineError,
)
from services.planner.planning_models import (
    Plan, PlanGoal, PlanStatus, Task,
    PLANNER_VERSION,
)
from services.planner.strategies.strategy_base import Strategy
from services.planner.strategies.planning_registry import (
    select_strategy,
    ensure_default_strategies_registered,
)
from services.planner.task_generator import generate_tasks
from services.planner.dependency_builder import build_dependencies
from services.planner.scheduling_engine import apply_scheduling
from services.planner.branching_engine import apply_branching
from services.planner.approval_engine import apply_approval_rules
from services.planner.plan_validator import validate_plan, ValidationResult

logger = logging.getLogger(__name__)


class PlanningPipeline:
    def __init__(self):
        ensure_default_strategies_registered()

    def plan(
        self,
        reasoning_result: Any,
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[Plan, ValidationResult]:
        context = context or {}

        conversation_id = getattr(reasoning_result, "conversation_id", "")
        reasoning_id = getattr(reasoning_result, "reasoning_id", "") or reasoning_id_from_reasoning(reasoning_result)

        try:
            goal = self._analyze_goal(reasoning_result)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningPipelineError(
                f"Goal analysis failed: {e}",
                context={"conversation_id": conversation_id, "reasoning_id": reasoning_id},
            ) from e

        try:
            strategy = self._select_strategy_or_fallback(goal)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningStrategyError(
                f"Strategy selection failed: {e}",
                context={"conversation_id": conversation_id, "goal": goal.target_action},
            ) from e

        try:
            tasks = self._generate_tasks(goal, strategy, context)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningStrategyError(
                f"Task generation failed: {e}",
                context={
                    "conversation_id": conversation_id,
                    "strategy": strategy.name if strategy else None,
                    "goal": goal.target_action,
                },
            ) from e

        plan = Plan(
            conversation_id=conversation_id,
            reasoning_id=reasoning_id,
            goal=goal,
            strategy=strategy.name if strategy else "",
            status=PlanStatus.DRAFT,
        )
        for task in tasks:
            task.plan_id = plan.id
        plan.tasks = tasks

        try:
            self._resolve_dependencies(plan, strategy)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningGraphError(
                f"Dependency resolution failed: {e}",
                context={"plan_id": plan.id, "task_count": len(plan.tasks)},
            ) from e

        try:
            self._apply_scheduling(plan, strategy)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningSchedulingError(
                f"Scheduling failed: {e}",
                context={"plan_id": plan.id},
            ) from e

        try:
            self._apply_branching(plan)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningGraphError(
                f"Branching failed: {e}",
                context={"plan_id": plan.id},
            ) from e

        try:
            reasoning_confidence = self._get_confidence(reasoning_result)
            risk_level = self._get_risk_level(reasoning_result)
            self._apply_approvals(plan, strategy, reasoning_confidence, risk_level)
        except PlanningError:
            raise
        except Exception as e:
            raise PlanningPipelineError(
                f"Approval annotation failed: {e}",
                context={"plan_id": plan.id},
            ) from e

        validation_result = self._validate(plan)

        if not validation_result.valid:
            issue_dicts = [i.to_dict() for i in validation_result.issues]
            logger.error(
                "Plan '%s' validation failed with %d error(s): %s",
                plan.id,
                len(validation_result.issues),
                ", ".join(i.code for i in validation_result.issues),
            )
            raise PlanningValidationError(
                f"Plan validation failed with {len(validation_result.issues)} issue(s)",
                context={
                    "plan_id": plan.id,
                    "conversation_id": plan.conversation_id,
                    "issues": issue_dicts,
                },
            )

        plan.status = PlanStatus.VALIDATED
        plan.validated_at = datetime.now(timezone.utc)
        logger.info(
            "Plan '%s' validated successfully (%d tasks, strategy=%s)",
            plan.id,
            len(plan.tasks),
            strategy.name if strategy else "none",
        )
        return plan, validation_result

    def plan_or_none(
        self,
        reasoning_result: Any,
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[Plan | None, Optional[ValidationResult]]:
        """Backwards-compatible helper: returns (None, None) on planning errors.

        New callers should prefer plan() and handle PlanningError explicitly.
        """
        try:
            return self.plan(reasoning_result, context)
        except PlanningValidationError as e:
            logger.warning("Plan validation failed (returned None): %s", e.message)
            return None, None
        except PlanningError as e:
            logger.error("Planning failed (returned None): %s", e.message)
            return None, None

    def _analyze_goal(self, reasoning_result: Any) -> PlanGoal:
        decision = getattr(reasoning_result, "decision", None)
        if decision is None:
            return self._make_fallback_goal()

        decision_type = getattr(decision, "type", None)
        decision_type_str = str(decision_type.value) if hasattr(decision_type, "value") else str(decision_type or "reply")

        outcome, target_action = self._decision_to_goal(decision_type_str)

        success_criteria = self._build_success_criteria(target_action)

        confidence = getattr(decision, "confidence", 0.5)
        if isinstance(confidence, float):
            priority = self._confidence_to_priority(confidence)
        else:
            priority = "medium"

        constraints = []
        risk = getattr(decision, "risk", None)
        if risk:
            risk_str = str(risk.value) if hasattr(risk, "value") else str(risk)
            if risk_str in ("high", "critical"):
                constraints.append("requires_human_review")

        policy_results = getattr(decision, "policy_results", None) or []
        for pr in policy_results:
            pr_result = getattr(pr, "result", None)
            if pr_result:
                pr_str = str(pr_result.value) if hasattr(pr_result, "value") else str(pr_result)
                if pr_str in ("failed", "requires_review"):
                    constraints.append("policy_mandated_review")

        return PlanGoal(
            outcome=outcome,
            target_action=target_action,
            success_criteria=success_criteria,
            priority=priority,
            constraints=constraints,
        )

    def _make_fallback_goal(self) -> PlanGoal:
        return PlanGoal(
            outcome="Engage with prospect",
            target_action="reply",
            success_criteria=["Message sent successfully"],
            priority="medium",
        )

    def _decision_to_goal(self, decision_type: str) -> tuple[str, str]:
        mapping = {
            "book_meeting": ("Schedule and confirm a meeting", "book_meeting"),
            "schedule_follow_up": ("Schedule follow-up communication", "schedule_follow_up"),
            "request_human_review": ("Escalate for human review", "request_human_review"),
            "escalate": ("Escalate to human team", "escalate"),
            "wait": ("Wait for prospect response or timing", "wait"),
            "close_conversation": ("Close the conversation gracefully", "close_conversation"),
            "stop_outreach": ("Stop outreach for this prospect", "stop_outreach"),
            "continue_nurturing": ("Continue nurturing the prospect", "continue_nurturing"),
            "request_more_info": ("Request more information from prospect", "request_more_info"),
        }
        if decision_type in mapping:
            return mapping[decision_type]
        return ("Respond to the prospect", "reply")

    def _build_success_criteria(self, target_action: str) -> list[str]:
        base = ["Message sent successfully"]
        action_map = {
            "book_meeting": ["Meeting confirmed with date and time"],
            "schedule_follow_up": ["Follow-up scheduled and sent"],
            "request_human_review": ["Human team notified with full context"],
            "escalate": ["Escalation completed and acknowledged"],
            "close_conversation": ["Conversation closed professionally"],
        }
        extra = action_map.get(target_action, [])
        return base + extra

    def _confidence_to_priority(self, confidence: float) -> str:
        if confidence >= 0.8:
            return "high"
        elif confidence >= 0.5:
            return "medium"
        else:
            return "low"

    def _select_strategy_or_fallback(self, goal: PlanGoal) -> Optional[Strategy]:
        return select_strategy(goal)

    def _generate_tasks(
        self,
        goal: PlanGoal,
        strategy: Optional[Strategy],
        context: dict[str, Any],
    ) -> list[Task]:
        try:
            return generate_tasks(goal, context, strategy)
        except Exception as e:
            raise PlanningStrategyError(
                f"Task generation failed: {e}",
                context={
                    "strategy": strategy.name if strategy else None,
                    "goal": goal.target_action,
                },
            ) from e

    def _resolve_dependencies(
        self,
        plan: Plan,
        strategy: Optional[Strategy],
    ) -> None:
        try:
            build_dependencies(plan, strategy)
        except Exception as e:
            raise PlanningGraphError(
                f"Dependency resolution failed: {e}",
                context={"plan_id": plan.id},
            ) from e

    def _apply_scheduling(
        self,
        plan: Plan,
        strategy: Optional[Strategy],
    ) -> None:
        try:
            apply_scheduling(plan, strategy)
        except Exception as e:
            raise PlanningSchedulingError(
                f"Scheduling failed: {e}",
                context={"plan_id": plan.id},
            ) from e

    def _apply_branching(self, plan: Plan) -> None:
        try:
            apply_branching(plan)
        except Exception as e:
            raise PlanningGraphError(
                f"Branching failed: {e}",
                context={"plan_id": plan.id},
            ) from e

    def _apply_approvals(
        self,
        plan: Plan,
        strategy: Optional[Strategy],
        confidence: float,
        risk_level: str,
    ) -> None:
        try:
            apply_approval_rules(plan, strategy, confidence, risk_level)
        except Exception as e:
            raise PlanningPipelineError(
                f"Approval annotation failed: {e}",
                context={"plan_id": plan.id},
            ) from e

    def _validate(self, plan: Plan) -> ValidationResult:
        try:
            return validate_plan(plan)
        except PlanningValidationError:
            raise
        except Exception as e:
            raise PlanningValidationError(
                f"Validation stage threw an unexpected exception: {e}",
                context={"plan_id": plan.id},
            ) from e

    def _get_confidence(self, reasoning_result: Any) -> float:
        decision = getattr(reasoning_result, "decision", None)
        if decision:
            return getattr(decision, "confidence", 0.5)
        return 0.5

    def _get_risk_level(self, reasoning_result: Any) -> str:
        decision = getattr(reasoning_result, "decision", None)
        if decision:
            risk = getattr(decision, "risk", None)
            if risk:
                return str(risk.value) if hasattr(risk, "value") else str(risk)
        return "low"


def reasoning_id_from_reasoning(reasoning_result: Any) -> str:
    """Extract a stable reasoning id if available."""
    return getattr(reasoning_result, "reasoning_id", "") or getattr(
        reasoning_result, "id", ""
    )


_default_pipeline: Optional[PlanningPipeline] = None
_default_pipeline_lock = threading.Lock()


def get_pipeline() -> PlanningPipeline:
    global _default_pipeline
    if _default_pipeline is None:
        with _default_pipeline_lock:
            if _default_pipeline is None:
                _default_pipeline = PlanningPipeline()
    return _default_pipeline


def generate_plan(
    reasoning_result: Any,
    context: Optional[dict[str, Any]] = None,
) -> tuple[Plan, ValidationResult]:
    pipeline = get_pipeline()
    return pipeline.plan(reasoning_result, context)
