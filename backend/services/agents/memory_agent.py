from __future__ import annotations

from typing import Any

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    MemoryContext,
)
from services.agent_sdk.agent_base import Agent
from services.memory.memory_store import get_memory_provider
from services.memory.models import MemorySearch, MemoryType


class MemoryAgent(Agent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.MEMORY

    @property
    def name(self) -> str:
        return "memory_agent"

    @property
    def description(self) -> str:
        return "Retrieves relevant organizational memories and provides explainable context."

    async def process(self, context: AgentContext) -> AgentResult:
        params = context.params
        provider = get_memory_provider()
        entity_id = params.get("entity_id", "")
        company_name = params.get("company_name", "")
        contact_email = params.get("contact_email", "")
        contact_name = params.get("contact_name", "")

        memory_ids: list[str] = []
        previous_objections: list[str] = []
        previous_outcomes: list[str] = []
        preferences: dict[str, str] = {}
        meeting_history: list[dict] = []
        decision_history: list[dict] = []
        all_memories: list[dict] = []

        search_queries = [entity_id, company_name, contact_email, contact_name]
        for query in search_queries:
            if not query:
                continue
            search = MemorySearch(query=query, limit=30)
            result = await provider.search(search)
            for mem in result.memories:
                data = mem.__dict__.copy()
                data["_type"] = mem.memory_type.value
                data["_id"] = mem.id
                all_memories.append(data)
                memory_ids.append(mem.id)

                if mem.memory_type == MemoryType.CONVERSATION:
                    if hasattr(mem, "objections") and mem.objections:
                        previous_objections.extend(mem.objections)
                elif mem.memory_type == MemoryType.OUTCOME:
                    if hasattr(mem, "result") and mem.result:
                        previous_outcomes.append(f"{mem.action_type}:{mem.result}")
                elif mem.memory_type == MemoryType.PREFERENCE:
                    if hasattr(mem, "preference_key") and hasattr(mem, "preference_value"):
                        preferences[mem.preference_key] = mem.preference_value
                elif mem.memory_type == MemoryType.MEETING:
                    meeting_history.append({
                        "id": mem.id,
                        "summary": getattr(mem, "summary", ""),
                        "outcome": getattr(mem, "outcome", ""),
                    })
                elif mem.memory_type == MemoryType.DECISION:
                    decision_history.append({
                        "id": mem.id,
                        "context": getattr(mem, "context", ""),
                        "choice": getattr(mem, "choice", ""),
                    })

        memory_ctx = MemoryContext(
            relevant_memories=all_memories,
            previous_objections=list(set(previous_objections)),
            previous_outcomes=list(set(previous_outcomes)),
            preferences=preferences,
            meeting_history=meeting_history,
            decision_history=decision_history,
            memory_citation=_build_citation(memory_ids, all_memories),
        )

        return AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "memory_context": {
                    "relevant_memories": memory_ctx.relevant_memories,
                    "previous_objections": memory_ctx.previous_objections,
                    "previous_outcomes": memory_ctx.previous_outcomes,
                    "preferences": memory_ctx.preferences,
                    "meeting_history": memory_ctx.meeting_history,
                    "decision_history": memory_ctx.decision_history,
                    "memory_citation": memory_ctx.memory_citation,
                },
            },
            memory_ids=memory_ids,
        )


def _build_citation(memory_ids: list[str], memories: list[dict]) -> str:
    if not memories:
        return "No relevant memories found."
    by_type: dict[str, int] = {}
    for m in memories:
        t = m.get("_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    parts = [f"{k} ({v})" for k, v in sorted(by_type.items())]
    return f"Retrieved {len(memories)} memories: {'; '.join(parts)}."
