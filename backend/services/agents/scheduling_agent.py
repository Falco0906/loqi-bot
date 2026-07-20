from __future__ import annotations

from typing import Any

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    SchedulingContext,
)
from services.agent_sdk.agent_base import Agent


class SchedulingAgent(Agent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.SCHEDULING

    @property
    def name(self) -> str:
        return "scheduling_agent"

    @property
    def description(self) -> str:
        return "Determines calendar availability and coordinates meeting logistics."

    async def process(self, context: AgentContext) -> AgentResult:
        params = context.params
        attendees = params.get("attendees", [])
        preferred_date = params.get("preferred_date", "")
        preferred_time = params.get("preferred_time", "")
        duration = params.get("duration_minutes", 30)
        timezone = params.get("timezone", "UTC")

        scheduling = SchedulingContext(
            suggested_date=preferred_date or _suggest_date(),
            suggested_time=preferred_time or _suggest_time(),
            duration_minutes=duration,
            timezone=timezone,
            attendees=attendees,
            requires_coordination=len(attendees) > 1,
        )

        return AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "scheduling_context": {
                    "suggested_date": scheduling.suggested_date,
                    "suggested_time": scheduling.suggested_time,
                    "duration_minutes": scheduling.duration_minutes,
                    "timezone": scheduling.timezone,
                    "attendees": scheduling.attendees,
                    "requires_coordination": scheduling.requires_coordination,
                },
            },
        )


def _suggest_date() -> str:
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(days=3)
    return future.strftime("%Y-%m-%d")


def _suggest_time() -> str:
    return "10:00"
