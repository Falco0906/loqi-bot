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


class PricingObjectionStrategy(Strategy):
    _ID_ACKNOWLEDGE = "pricing_objection_acknowledge"
    _ID_VALUE = "pricing_objection_value"
    _ID_CTA_WAIT = "pricing_objection_cta_wait"

    @property
    def name(self) -> str:
        return "pricing_objection"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("overcome_objection", "address_pricing", "send_proposal"):
            return 0.9
        outcome_lower = goal.outcome.lower()
        if "pricing" in outcome_lower or "objection" in outcome_lower or "budget" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_ACKNOWLEDGE,
                label=f"Acknowledge {prospect}'s pricing concern",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a message to {prospect} at {company} acknowledging their pricing concern. Validate their perspective before presenting value.",
                payload=MessagePayload(channel="email", template="pricing_acknowledgment"),
                reasoning_trace="Strategy: pricing_objection. Step 1: Acknowledge the objection to build rapport.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_VALUE,
                label=f"Present value proposition to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a message to {prospect} at {company} addressing the pricing objection with ROI data and value justification.",
                payload=MessagePayload(channel="email", template="pricing_value_proposition"),
                reasoning_trace="Strategy: pricing_objection. Step 2: Address objection with value proposition.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_CTA_WAIT,
                label=f"Send CTA and wait for {prospect}'s response",
                type=TaskType.WAIT_FOR_REPLY,
                instructions=f"Send a call-to-action to {prospect} at {company}. Wait for their response with a 5-day timeout.",
                payload=WaitForReplyPayload(timeout="5d", fallback="schedule_followup"),
                reasoning_trace="Strategy: pricing_objection. Step 3: CTA with wait for response.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_ACKNOWLEDGE, self._ID_VALUE),
            (self._ID_VALUE, self._ID_CTA_WAIT),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=60,
            max_daily_tasks=2,
        )


pricing_objection_strategy = PricingObjectionStrategy()
