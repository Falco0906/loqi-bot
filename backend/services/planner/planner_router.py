"""PlannerRouter — routes conversation intents through the Planner.

When a PlanGoal matches an existing Strategy with sufficient confidence,
the router generates tasks, builds a validated Plan, and executes it
through the ExecutionEngine.

If no strategy matches (or execution fails), the router returns None
so the caller can fall back to the legacy run_workflow() path.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4

from services.planner.planning_models import Plan, PlanGoal, PlanStatus
from services.planner.strategies.planning_registry import (
    ensure_default_strategies_registered,
    select_strategy,
)

logger = logging.getLogger(__name__)

# Minimum match score to consider a strategy viable
_MIN_MATCH_SCORE = 0.5

_SCHEDULE_KEYWORDS = frozenset({
    "schedule", "calendar", "meeting", "event",
    "book", "appointment", "reschedule", "cancel",
})


def is_schedule_intent(text: str) -> bool:
    """Check if user text expresses scheduling intent."""
    lowered = text.lower().strip()
    return any(kw in lowered for kw in _SCHEDULE_KEYWORDS)


class PlannerRouter:
    """Routes intents through the Planner when a matching strategy exists.

    Usage:
        router = PlannerRouter()
        result = router.route(goal, context, resolver=my_resolver)
        if result is not None:
            # use Planner result
        else:
            # fall back to legacy path
    """

    def __init__(self) -> None:
        ensure_default_strategies_registered()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        goal: PlanGoal,
        context: dict[str, Any],
        resolver: Any = None,
    ) -> dict | None:
        """Try to route *goal* through the Planner.

        Args:
            goal: The PlanGoal derived from the user's intent.
            context: Enriched context dict (user, session, extracted fields).
            resolver: An optional adapter resolver for ExecutionEngine.
                      If omitted, the router attempts auto-resolution.

        Returns:
            A workflow-compatible result dict on success, or *None* when
            no strategy matches, task generation produces no tasks, or
            execution fails for any recoverable reason.
        """
        strategy = select_strategy(goal)
        if strategy is None:
            logger.debug("No strategy selected for goal '%s'", goal.target_action)
            return None

        match_score = strategy.matches(goal)
        if match_score < _MIN_MATCH_SCORE:
            logger.debug(
                "Strategy '%s' match score %.2f below threshold %.2f",
                strategy.name, match_score, _MIN_MATCH_SCORE,
            )
            return None

        logger.info(
            "Routing goal '%s' through strategy '%s' (score=%.2f)",
            goal.target_action, strategy.name, match_score,
        )

        plan = self._build_plan(goal, context, strategy)
        if plan is None:
            return None

        session = self._execute_plan(plan, resolver)
        if session is None:
            return None

        return self._session_to_result(session, strategy.name, plan)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_plan(
        self,
        goal: PlanGoal,
        context: dict[str, Any],
        strategy: Any,
    ) -> Plan | None:
        """Generate tasks, apply dependencies, produce a validated Plan."""
        tasks = strategy.generate_tasks(goal, context)
        if not tasks:
            logger.warning("Strategy '%s' generated zero tasks", strategy.name)
            return None

        # Inject credential context into every task so the global
        # credentials_factory can resolve per-user credentials at
        # dispatch time without per-request adapter construction.
        user_id = context.get("user_id")
        if user_id:
            for task in tasks:
                if "credential_user_id" not in task.params:
                    task.params["credential_user_id"] = user_id

        plan = Plan(
            id=f"plan-{uuid4()}",
            conversation_id=context.get("conversation_id", ""),
            goal=goal,
            strategy=strategy.name,
            tasks=tasks,
            status=PlanStatus.VALIDATED,
        )
        for task in tasks:
            task.plan_id = plan.id

        try:
            from services.planner.dependency_builder import build_dependencies
            build_dependencies(plan, strategy)
        except Exception as e:
            logger.error("Dependency resolution failed: %s", e)
            return None

        try:
            from services.planner.plan_validator import validate_plan
            result = validate_plan(plan)
            if not result.valid:
                codes = [i.code for i in result.issues]
                logger.warning("Plan validation failed: %s", codes)
                return None
            plan.status = PlanStatus.VALIDATED
        except Exception as e:
            logger.error("Plan validation threw: %s", e)
            return None

        return plan

    def _execute_plan(
        self,
        plan: Plan,
        resolver: Any = None,
    ) -> Any | None:
        """Execute the plan through the ExecutionEngine.

        When *resolver* is None the method attempts auto-resolution.
        If neither is available the plan cannot execute and None is returned.
        """
        from services.execution.execution_pipeline import get_pipeline
        from workflows import _run_async

        actual_resolver = resolver if resolver is not None else self._auto_resolver(plan)
        if actual_resolver is None:
            logger.warning("No resolver available — cannot execute plan")
            return None

        engine = get_pipeline()
        try:
            session = _run_async(engine.execute(plan, resolver=actual_resolver))
        except NotImplementedError:
            logger.warning("Execution engine raised NotImplementedError (no resolver)")
            return None
        except Exception as e:
            logger.error("Plan execution failed: %s", e)
            return None

        return session

    def _auto_resolver(self, plan: Plan) -> Any | None:
        """Attempt to resolve adapters from the global planner registry.

        Delegates to ``get_planner_resolver()`` which wraps the
        ``AdapterRegistry`` populated at application startup.

        Returns *None* when the registry has not been initialised
        (pre-startup or tests), preserving the fallback-to-legacy
        behaviour.
        """
        from services.execution.adapter_registry_resolver import get_planner_resolver
        return get_planner_resolver()

    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------

    def _session_to_result(
        self,
        session: Any,
        strategy_name: str,
        plan: Plan,
    ) -> dict:
        """Convert an ExecutionSession to a workflow-compatible dict.

        The output dict follows the same conventions as
        ``run_workflow()`` so that callers can use
        ``_render_workflow_result()`` unchanged.
        """
        all_succeeded = True
        task_details: list[dict[str, Any]] = []
        for pt in plan.tasks:
            et = session.tasks.get(pt.id)
            success = et is not None and et.result is not None and et.result.success
            if not success:
                all_succeeded = False
            task_details.append({
                "task_id": pt.id,
                "type": pt.type.value,
                "label": pt.label,
                "status": et.status.value if et is not None else "unknown",
                "success": success,
                "output": et.result.output if et is not None and et.result else {},
            })

        message = self._format_message(strategy_name, plan.tasks, session)

        return {
            "ok": all_succeeded,
            "type": "planner_result",
            "message": message,
            "result": {
                "plan_id": session.plan_id,
                "strategy": strategy_name,
                "tasks": task_details,
            },
        }

    @staticmethod
    def _format_message(strategy_name: str, tasks: list, session: Any) -> str:
        """Produce a human-readable summary of plan execution."""
        if strategy_name == "booking":
            parts: list[str] = []
            for pt in tasks:
                et = session.tasks.get(pt.id)
                if et is not None and et.result is not None and et.result.success:
                    if pt.type.value == "calendar_create_event":
                        parts.append("Calendar event created.")
                    elif pt.type.value == "send_email":
                        parts.append("Notification email sent.")
                else:
                    parts.append(f"{pt.label}: failed.")
            return "\n".join(parts) if parts else "Scheduling completed."

        done = sum(
            1 for pt in tasks
            if session.tasks.get(pt.id) is not None
            and session.tasks[pt.id].result is not None
            and session.tasks[pt.id].result.success
        )
        return f"Plan executed: {done}/{len(tasks)} tasks completed."
