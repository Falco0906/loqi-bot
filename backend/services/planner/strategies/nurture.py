from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import (
    MessagePayload,
    WaitDurationPayload,
    AnalyzeReplyPayload,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints


class NurtureStrategy(Strategy):
    _ID_VALUE_ADD = "nurture_value_add"
    _ID_WAIT = "nurture_wait"
    _ID_CHECK_IN = "nurture_check_in"
    _ID_ANALYZE = "nurture_analyze"

    @property
    def name(self) -> str:
        return "nurture"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("continue_nurturing", "nurture", "keep_warm"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "nurture" in outcome_lower or "dormant" in outcome_lower:
            return 0.8
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_VALUE_ADD,
                label=f"Send value-add content to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Share a relevant article, case study, or insight with {prospect} at {company}. No CTA — pure value.",
                payload=MessagePayload(channel="email", template="nurture_value_add"),
                reasoning_trace="Strategy: nurture. Step 1: Send value-add content without CTA.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_WAIT,
                label=f"Wait before check-in with {prospect}",
                type=TaskType.WAIT_DURATION,
                instructions=f"Wait 5-7 business days before the next touchpoint with {prospect}.",
                payload=WaitDurationPayload(duration="7d"),
                reasoning_trace="Strategy: nurture. Step 2: Wait before check-in.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_CHECK_IN,
                label=f"Send check-in message to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a gentle check-in to {prospect} at {company}. Reference the previous value-add content and ask an open question.",
                payload=MessagePayload(channel="email", template="nurture_check_in"),
                reasoning_trace="Strategy: nurture. Step 3: Check-in with open question.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_ANALYZE,
                label=f"Analyze {prospect}'s reply for re-engagement signals",
                type=TaskType.ANALYZE_REPLY,
                instructions=f"Analyze {prospect}'s response for buying signals, objections, or interest indicators.",
                payload=AnalyzeReplyPayload(),
                reasoning_trace="Strategy: nurture. Step 4: Analyze response for next cycle.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_VALUE_ADD, self._ID_WAIT),
            (self._ID_WAIT, self._ID_CHECK_IN),
            (self._ID_CHECK_IN, self._ID_ANALYZE),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=1440,
            max_daily_tasks=1,
        )


nurture_strategy = NurtureStrategy()
