from __future__ import annotations
from typing import Any

from services.planner.planning_models import (
    PlanGoal, Task,
    TaskType,
)
from services.planner.payloads import (
    MessagePayload,
    AnalyzeReplyPayload,
)
from services.planner.strategies.strategy_base import Strategy


class GeneralEngagementStrategy(Strategy):
    _ID_REPLY = "general_engagement_reply"
    _ID_ANALYZE = "general_engagement_analyze"

    @property
    def name(self) -> str:
        return "general_engagement"

    def matches(self, goal: PlanGoal) -> float:
        return 0.1

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        return [
            Task(
                id=self._ID_REPLY,
                label=f"Send reply to {prospect}",
                type=TaskType.SEND_MESSAGE,
                instructions=f"Respond to the latest message from {prospect} at {company}. Address their question or comment directly.",
                payload=MessagePayload(channel="email", template="general_reply"),
                reasoning_trace="Strategy: general_engagement. Reply to latest message.",
                reasoning_goal=goal.target_action,
            ),
            Task(
                id=self._ID_ANALYZE,
                label=f"Analyze {prospect}'s response",
                type=TaskType.ANALYZE_REPLY,
                instructions=f"Analyze {prospect}'s reply for intent, buying signals, and next steps.",
                payload=AnalyzeReplyPayload(),
                reasoning_trace="Strategy: general_engagement. Analyze response for next action.",
                reasoning_goal=goal.target_action,
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [(self._ID_REPLY, self._ID_ANALYZE)]

    def approval_rules(self, tasks: list[Task]) -> list:
        return []


general_engagement_strategy = GeneralEngagementStrategy()
