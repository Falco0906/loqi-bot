from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import (
    MessagePayload,
    AnalyzeReplyPayload,
    EscalatePayload,
    UpdateCRMPayload,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints, ApprovalRule


class EscalationStrategy(Strategy):
    _ID_ANALYZE = "escalation_analyze"
    _ID_ROUTE = "escalation_route"
    _ID_NOTIFY = "escalation_notify"
    _ID_HANDOFF = "escalation_handoff"

    @property
    def name(self) -> str:
        return "escalation"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("escalate", "request_human_review", "human_review"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "escalat" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")
        reason = context.get("escalation_reason", "Needs human judgment")

        return [
            Task(
                id=self._ID_ANALYZE,
                label=f"Identify escalation reason for {prospect}",
                type=TaskType.ANALYZE_REPLY,
                instructions=f"Identify the specific reason for escalation in the conversation with {prospect} at {company}. Reason: {reason}.",
                payload=AnalyzeReplyPayload(reason=reason),
                reasoning_trace="Strategy: escalation. Step 1: Identify escalation reason.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_ROUTE,
                label=f"Route {prospect} to human",
                type=TaskType.ESCALATE,
                instructions=f"Route the conversation with {prospect} at {company} to a human team member. Include full context and escalation reason.",
                payload=EscalatePayload(channel="internal", priority="high", reason=reason),
                reasoning_trace="Strategy: escalation. Step 2: Route to human.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_NOTIFY,
                label=f"Notify team about {prospect} escalation",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send an internal notification about the escalation for {prospect} at {company}. Include summary and reasoning.",
                payload=MessagePayload(channel="internal", template="escalation_notification"),
                reasoning_trace="Strategy: escalation. Step 3: Notify team.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_HANDOFF,
                label=f"Handoff {prospect} conversation",
                type=TaskType.UPDATE_CRM,
                instructions=f"Update the CRM record for {prospect} at {company} to reflect escalation status. Mark for human follow-up.",
                payload=UpdateCRMPayload(action="mark_escalated", status="needs_human"),
                reasoning_trace="Strategy: escalation. Step 4: Handoff to human.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_ANALYZE, self._ID_ROUTE),
            (self._ID_ROUTE, self._ID_NOTIFY),
            (self._ID_NOTIFY, self._ID_HANDOFF),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=False,
            min_delay_between_tasks=5,
            max_daily_tasks=10,
        )

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        return [
            ApprovalRule(
                task_type=TaskType.ESCALATE,
                condition="any_escalation",
                requirement="required",
                reason="Escalation requires approval before routing to human.",
            ),
        ]


escalation_strategy = EscalationStrategy()
