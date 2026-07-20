"""Booking Strategy — produces a Plan with a calendar event creation
followed by a notification email.

Demonstrates that the Planner can naturally produce heterogeneous
multi-task Plans (CALENDAR_CREATE_EVENT → SEND_EMAIL) using the
existing Strategy infrastructure.
"""

from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import (
    CreateEventPayload,
    MessagePayload,
)
from services.planner.strategies.strategy_base import Strategy, SchedulingHints, ApprovalRule


class BookingStrategy(Strategy):
    _ID_CREATE_EVENT = "booking_create_event"
    _ID_SEND_NOTIFICATION = "booking_send_notification"

    @property
    def name(self) -> str:
        return "booking"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in (
            "schedule_event",
            "create_calendar_event",
        ):
            return 0.95
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        summary = context.get("summary", "Meeting")
        start_time = context.get("start_time", "")
        end_time = context.get("end_time", "")
        attendee_email = context.get("attendee_email", "")
        calendar_id = context.get("calendar_id", "primary")
        description = context.get("description", "")
        location = context.get("location", "")
        timezone = context.get("timezone", "UTC")

        create_task = Task(
            id=self._ID_CREATE_EVENT,
            label=f"Create calendar event: {summary}",
            type=TaskType.CALENDAR_CREATE_EVENT,
            instructions=f"Create a calendar event titled '{summary}' "
            f"from {start_time} to {end_time}.",
            payload=CreateEventPayload(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                calendar_id=calendar_id,
                description=description,
                location=location,
                timezone=timezone,
                attendees=(attendee_email,) if attendee_email else (),
            ),
            reasoning_trace="Strategy: booking. Step 1 of 2: Create the calendar event.",
            reasoning_goal=goal.target_action,
        )

        email_task = Task(
            id=self._ID_SEND_NOTIFICATION,
            label=f"Send notification about {summary}",
            type=TaskType.SEND_EMAIL,
            instructions=f"Send an email notification confirming the "
            f"scheduled event: {summary}.",
            payload=MessagePayload(
                channel="email",
                template="meeting_notification",
            ),
            reasoning_trace="Strategy: booking. Step 2 of 2: Send notification email.",
            reasoning_goal=goal.target_action,
        )

        recipient = attendee_email or context.get("recipient_email", "")
        email_task.params["to"] = [recipient] if recipient else []
        email_task.params["subject"] = f"Meeting Confirmed: {summary}"
        email_task.params["body_plain"] = (
            f"Hi,\n\n"
            f"Your meeting '{summary}' has been scheduled "
            f"from {start_time} to {end_time}.\n\n"
            f"Best,\nLoqi"
        )

        return [create_task, email_task]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [
            (self._ID_CREATE_EVENT, self._ID_SEND_NOTIFICATION),
        ]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=0,
            max_daily_tasks=10,
        )

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        return [
            ApprovalRule(
                task_type=TaskType.SEND_EMAIL,
                condition="external_notification",
                requirement="recommended",
                reason="Sending meeting notification to external attendee — recommend human review.",
            ),
        ]


booking_strategy = BookingStrategy()
