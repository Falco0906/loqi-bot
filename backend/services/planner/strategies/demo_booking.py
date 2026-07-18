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


class DemoBookingStrategy(Strategy):
    _ID_INVITATION = "demo_booking_invitation"
    _ID_WAIT_REPLY = "demo_booking_wait_reply"
    _ID_CONFIRM = "demo_booking_confirm"
    _ID_REMIND = "demo_booking_remind"

    @property
    def name(self) -> str:
        return "demo_booking"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("book_meeting", "book_demo", "schedule_demo", "schedule_meeting"):
            return 0.95
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_INVITATION,
                label=f"Send demo invitation to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a demo invitation email to {prospect} at {company}. Include available time slots and a calendar link.",
                payload=MessagePayload(channel="email", template="demo_invitation"),
                reasoning_trace="Strategy: demo_booking. Step 1 of 4: Send initial demo invitation.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_WAIT_REPLY,
                label=f"Wait for {prospect}'s reply",
                type=TaskType.WAIT_FOR_REPLY,
                instructions=f"Wait for {prospect} to respond to the demo invitation. Timeout after 3 business days.",
                payload=WaitForReplyPayload(timeout="3d", fallback="send_followup"),
                reasoning_trace="Strategy: demo_booking. Step 2 of 4: Wait for prospect response.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_CONFIRM,
                label=f"Send demo confirmation to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a demo confirmation with the agreed date, time, and calendar link to {prospect} at {company}.",
                payload=MessagePayload(channel="email", template="demo_confirmation"),
                reasoning_trace="Strategy: demo_booking. Step 3 of 4: Confirm the scheduled demo.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_REMIND,
                label=f"Send reminder to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Send a reminder 24 hours before the scheduled demo to {prospect} at {company}.",
                payload=MessagePayload(channel="email", template="demo_reminder"),
                reasoning_trace="Strategy: demo_booking. Step 4 of 4: Send pre-demo reminder.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_INVITATION, self._ID_WAIT_REPLY),
            (self._ID_WAIT_REPLY, self._ID_CONFIRM),
            (self._ID_CONFIRM, self._ID_REMIND),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=30,
            max_daily_tasks=3,
        )

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        return [
            ApprovalRule(
                task_type=TaskType.SEND_MESSAGE,
                condition="first_outreach_to_executive",
                requirement="recommended",
                reason="First demo invitation to executive — recommend human review.",
            ),
        ]


demo_booking_strategy = DemoBookingStrategy()
