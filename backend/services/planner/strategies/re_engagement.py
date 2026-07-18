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
from services.planner.strategies.strategy_base import Strategy, SchedulingHints, ApprovalRule


class ReEngagementStrategy(Strategy):
    _ID_HOOK = "re_engagement_hook"
    _ID_VALUE = "re_engagement_value"
    _ID_OFFER = "re_engagement_offer"
    _ID_WAIT = "re_engagement_wait"

    @property
    def name(self) -> str:
        return "re_engagement"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("re_engage", "re_engagement", "win_back"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "re-engage" in outcome_lower or "reengage" in outcome_lower or "win back" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_HOOK,
                label=f"Send hook message to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a re-engagement hook to {prospect} at {company}. Lead with something new — a product update, industry shift, or new case study.",
                payload=MessagePayload(channel="email", template="re_engagement_hook"),
                reasoning_trace="Strategy: re_engagement. Step 1: Hook with something new.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_VALUE,
                label=f"Send value-focused message to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a value-focused message to {prospect} at {company}. Tie the value directly to their known needs or past interests.",
                payload=MessagePayload(channel="email", template="re_engagement_value"),
                reasoning_trace="Strategy: re_engagement. Step 2: Reinforce value.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_OFFER,
                label=f"Send offer/CTA to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a compelling offer or CTA to {prospect} at {company}. Include a time-bound element to encourage action.",
                payload=MessagePayload(channel="email", template="re_engagement_offer"),
                reasoning_trace="Strategy: re_engagement. Step 3: Offer with CTA.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_WAIT,
                label=f"Wait for {prospect}'s reply",
                type=TaskType.WAIT_FOR_REPLY,
                instructions=f"Wait for {prospect} to respond. Timeout after 7 business days.",
                payload=WaitForReplyPayload(timeout="7d", fallback="mark_dormant"),
                reasoning_trace="Strategy: re_engagement. Step 4: Wait for response.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_HOOK, self._ID_VALUE),
            (self._ID_VALUE, self._ID_OFFER),
            (self._ID_OFFER, self._ID_WAIT),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=2880,
            max_daily_tasks=1,
        )

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        return [
            ApprovalRule(
                task_type=TaskType.SEND_MESSAGE,
                condition="re_engagement_with_offer",
                requirement="recommended",
                reason="Re-engagement with offer — recommend review before sending.",
            ),
        ]


re_engagement_strategy = ReEngagementStrategy()
