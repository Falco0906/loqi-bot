from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import (
    MessagePayload,
    WaitForReplyPayload,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints


class FollowUpStrategy(Strategy):
    _ID_CONTEXT = "follow_up_context"
    _ID_VALUE = "follow_up_value"
    _ID_CTA_WAIT = "follow_up_cta_wait"

    @property
    def name(self) -> str:
        return "follow_up"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("follow_up", "send_followup", "schedule_follow_up"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "follow" in outcome_lower and "up" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_CONTEXT,
                label=f"Reference previous conversation with {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a message to {prospect} at {company} referencing the previous conversation context. Show you remember the discussion.",
                payload=MessagePayload(channel="email", template="followup_context"),
                reasoning_trace="Strategy: follow_up. Step 1: Reference previous context.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_VALUE,
                label=f"Add value for {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a message to {prospect} at {company} with new value — a relevant article, case study, or insight tied to their situation.",
                payload=MessagePayload(channel="email", template="followup_value"),
                reasoning_trace="Strategy: follow_up. Step 2: Deliver value.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_CTA_WAIT,
                label=f"Send CTA to {prospect} and wait",
                type=TaskType.WAIT_FOR_REPLY,
                instructions=f"Send a clear CTA to {prospect} at {company}. Wait for their response with a 5-day timeout.",
                payload=WaitForReplyPayload(timeout="5d", fallback="schedule_followup"),
                reasoning_trace="Strategy: follow_up. Step 3: CTA and wait.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_CONTEXT, self._ID_VALUE),
            (self._ID_VALUE, self._ID_CTA_WAIT),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=1440,
            max_daily_tasks=1,
        )


follow_up_strategy = FollowUpStrategy()
