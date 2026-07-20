from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from services.agent_sdk.models import (
    AgentContext,
    AgentResult,
    AgentType,
)
from services.agents.research_agent import ResearchAgent
from services.agents.outreach_agent import OutreachAgent
from services.agents.crm_agent import CrmAgent
from services.agents.scheduling_agent import SchedulingAgent
from services.agents.memory_agent import MemoryAgent

log = logging.getLogger("coordinator")


@dataclass
class CoordinationPlan:
    pipeline_name: str = ""
    agent_sequence: list[AgentType] = field(default_factory=list)
    merged_context: dict[str, Any] = field(default_factory=dict)
    agent_results: dict[str, AgentResult] = field(default_factory=dict)
    memory_ids: list[str] = field(default_factory=list)


COORDINATION_PIPELINES: dict[str, dict] = {
    "new_account_outreach": {
        "agents": [
            AgentType.MEMORY,
            AgentType.RESEARCH,
            AgentType.CRM,
            AgentType.OUTREACH,
        ],
        "description": "New account: memory → research → CRM → outreach",
    },
    "reply_handler": {
        "agents": [
            AgentType.MEMORY,
            AgentType.CRM,
            AgentType.SCHEDULING,
            AgentType.OUTREACH,
        ],
        "description": "Positive reply: memory → CRM → scheduling → outreach",
    },
    "objection_handling": {
        "agents": [
            AgentType.MEMORY,
            AgentType.OUTREACH,
        ],
        "description": "Previous objection: memory → revised outreach",
    },
    "meeting_complete": {
        "agents": [
            AgentType.CRM,
            AgentType.MEMORY,
            AgentType.OUTREACH,
        ],
        "description": "Meeting done: CRM update → memory → next best action",
    },
    "quick_memory_lookup": {
        "agents": [
            AgentType.MEMORY,
        ],
        "description": "Quick memory retrieval only",
    },
}


AGENT_MAP: dict[AgentType, Any] = {
    AgentType.RESEARCH: ResearchAgent(),
    AgentType.OUTREACH: OutreachAgent(),
    AgentType.CRM: CrmAgent(),
    AgentType.SCHEDULING: SchedulingAgent(),
    AgentType.MEMORY: MemoryAgent(),
}


class AgentCoordinator:

    def __init__(self) -> None:
        self._agents = AGENT_MAP

    def select_pipeline(self, goal_action: str, outcome: str, context: dict) -> str:
        target = goal_action.lower()
        outcome_lower = outcome.lower()

        if target in ("new_account", "new_prospect", "fresh_outreach"):
            return "new_account_outreach"
        if target in ("handle_reply", "positive_reply", "reply_received", "meeting_accepted"):
            return "reply_handler"
        if target in ("handle_objection", "objection", "overcome_objection"):
            return "objection_handling"
        if target in ("meeting_complete", "post_meeting", "meeting_done"):
            return "meeting_complete"
        if target in ("memory_lookup", "quick_memory", "retrieve_context"):
            return "quick_memory_lookup"

        if "objection" in outcome_lower:
            return "objection_handling"
        if "meeting" in outcome_lower and ("complete" in outcome_lower or "done" in outcome_lower):
            return "meeting_complete"
        if "reply" in outcome_lower or "positive" in outcome_lower:
            return "reply_handler"
        if "new" in outcome_lower and ("account" in outcome_lower or "prospect" in outcome_lower):
            return "new_account_outreach"

        return "new_account_outreach"

    async def orchestrate(
        self,
        pipeline_name: str,
        context: dict[str, Any],
    ) -> CoordinationPlan:
        pipeline_config = COORDINATION_PIPELINES.get(pipeline_name)
        if not pipeline_config:
            pipeline_config = COORDINATION_PIPELINES["new_account_outreach"]

        agent_sequence = pipeline_config["agents"]
        merged = dict(context)
        results: dict[str, AgentResult] = {}
        all_memory_ids: list[str] = []

        for agent_type in agent_sequence:
            agent = self._agents.get(agent_type)
            if not agent:
                log.warning("No agent registered for %s", agent_type)
                continue

            agent_ctx = AgentContext(
                goal=pipeline_name,
                entity_id=context.get("entity_id", ""),
                user_id=context.get("user_id", ""),
                params=merged,
            )

            try:
                result = await agent.process(agent_ctx)
            except Exception as e:
                log.exception("Agent %s failed", agent_type.value)
                result = AgentResult(
                    success=False,
                    agent_type=agent_type,
                    error=str(e),
                )

            results[agent_type.value] = result
            if result.success:
                merged.update(result.data)
            all_memory_ids.extend(result.memory_ids)

        return CoordinationPlan(
            pipeline_name=pipeline_name,
            agent_sequence=agent_sequence,
            merged_context=merged,
            agent_results=results,
            memory_ids=all_memory_ids,
        )

    def get_pipeline_names(self) -> list[str]:
        return list(COORDINATION_PIPELINES.keys())
