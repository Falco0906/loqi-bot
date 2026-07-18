from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import MessagePayload
from services.planner.strategies.strategy_base import Strategy, SchedulingHints, ApprovalRule


class ColdOutreachStrategy(Strategy):
    _ID_INITIAL = "cold_outreach_initial"
    _ID_FOLLOWUP1 = "cold_outreach_followup_1"
    _ID_FOLLOWUP2 = "cold_outreach_followup_2"
    _ID_FINAL = "cold_outreach_final"

    @property
    def name(self) -> str:
        return "cold_outreach"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("cold_outreach", "initial_outreach", "first_contact"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "introduce" in outcome_lower or "outreach" in outcome_lower:
            return 0.8
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_INITIAL,
                label=f"Send initial outreach to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a personalized cold outreach message to {prospect} at {company}. Reference their role and company context.",
                payload=MessagePayload(channel="email", template="cold_outreach_initial"),
                reasoning_trace="Strategy: cold_outreach. Step 1 of 4: Initial outreach.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_FOLLOWUP1,
                label=f"Send follow-up 1 to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send first follow-up to {prospect} at {company}. Add value — share an insight or relevant case study.",
                payload=MessagePayload(channel="email", template="cold_outreach_followup1"),
                reasoning_trace="Strategy: cold_outreach. Step 2 of 4: First follow-up.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_FOLLOWUP2,
                label=f"Send follow-up 2 to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send second follow-up to {prospect} at {company}. Include a social proof element or testimonial.",
                payload=MessagePayload(channel="email", template="cold_outreach_followup2"),
                reasoning_trace="Strategy: cold_outreach. Step 3 of 4: Second follow-up.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_FINAL,
                label=f"Send final outreach to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send final outreach to {prospect} at {company}. Clear CTA with an expiration or deadline to create urgency.",
                payload=MessagePayload(channel="email", template="cold_outreach_final"),
                reasoning_trace="Strategy: cold_outreach. Step 4 of 4: Final outreach with urgency.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_INITIAL, self._ID_FOLLOWUP1),
            (self._ID_FOLLOWUP1, self._ID_FOLLOWUP2),
            (self._ID_FOLLOWUP2, self._ID_FINAL),
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
                condition="first_outreach",
                requirement="recommended",
                reason="Cold outreach content — recommend human review before sending.",
            ),
        ]


cold_outreach_strategy = ColdOutreachStrategy()
