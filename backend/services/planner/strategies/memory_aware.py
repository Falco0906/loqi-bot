from __future__ import annotations

from typing import Any

from services.memory.memory_store import get_memory_provider
from services.memory.models import (
    Memory,
    MemorySearch,
    MemoryCitation,
    MemoryEvidence,
    MemoryType,
)
from services.planner.strategies.strategy_base import Strategy


class MemoryAwareStrategy(Strategy):
    """Base for strategies that augment planning with organizational memory.

    Subclasses call ``retrieve_memories()`` or ``enrich_context()``
    inside ``generate_tasks()`` to pull relevant historical context.

    ``enrich_context()`` wraps context retrieval into a standard dict
    that downstream strategies can consume.

    ``citations`` tracks which memories influenced the plan.
    """

    @property
    def _provider(self):
        return get_memory_provider()

    async def retrieve_memories(
        self,
        search: MemorySearch,
    ) -> list[Memory]:
        result = await self._provider.search(search)
        return result.memories

    async def retrieve_by_entity(
        self,
        entity_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        search = MemorySearch(
            entity_id=entity_id,
            memory_type=memory_type,
            limit=limit,
        )
        return await self.retrieve_memories(search)

    async def retrieve_account_memories(
        self, company_id: str = "", company_name: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.ACCOUNT,
            query=company_name or company_id,
            entity_id=company_id or company_name,
            limit=20,
        )
        return await self.retrieve_memories(search)

    async def retrieve_contact_memories(
        self, contact_id: str = "", email: str = "", name: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.CONTACT,
            query=email or name or contact_id,
            entity_id=contact_id or email or name,
            limit=20,
        )
        return await self.retrieve_memories(search)

    async def retrieve_conversation_memories(
        self, conversation_id: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.CONVERSATION,
            entity_id=conversation_id,
            limit=50,
        )
        return await self.retrieve_memories(search)

    async def retrieve_opportunity_memories(
        self, opportunity_id: str = "", company_id: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.OPPORTUNITY,
            entity_id=opportunity_id or company_id,
            limit=20,
        )
        return await self.retrieve_memories(search)

    async def retrieve_outcome_memories(
        self, entity_id: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.OUTCOME,
            entity_id=entity_id,
            limit=20,
        )
        return await self.retrieve_memories(search)

    async def retrieve_preference_memories(
        self, entity_type: str = "", entity_id: str = "",
    ) -> list[Memory]:
        search = MemorySearch(
            memory_type=MemoryType.PREFERENCE,
            entity_id=entity_id,
            limit=10,
        )
        return await self.retrieve_memories(search)

    async def enrich_context(
        self,
        context: dict[str, Any],
        memory_types: list[MemoryType] | None = None,
    ) -> dict[str, Any]:
        """Enrich a planning context with relevant memories.

        Returns a new dict with ``relevant_memories`` and
        ``memory_citation`` keys added.  Uses entity identifiers
        already present in *context* to drive retrieval.
        """
        enriched = dict(context)
        memories: list[Memory] = []
        evidence_list: list[MemoryEvidence] = []

        company_id = context.get("company_id", "") or context.get("company_name", "")
        contact_id = context.get("contact_id", "") or context.get("contact_name", "")
        opportunity_id = context.get("opportunity_id", "")
        conversation_id = context.get("conversation_id", "")

        memory_types = memory_types or list(MemoryType)

        for mt in memory_types:
            if mt == MemoryType.ACCOUNT and company_id:
                mems = await self.retrieve_account_memories(
                    company_id=company_id,
                    company_name=context.get("company_name", ""),
                )
                for m in mems:
                    _add_evidence(evidence_list, m, "account history")
                memories.extend(mems)

            elif mt == MemoryType.CONTACT and (contact_id or company_id):
                mems = await self.retrieve_contact_memories(
                    contact_id=contact_id,
                    email=context.get("prospect_email", ""),
                    name=context.get("prospect_name", ""),
                )
                for m in mems:
                    _add_evidence(evidence_list, m, "contact history")
                memories.extend(mems)

            elif mt == MemoryType.CONVERSATION and conversation_id:
                mems = await self.retrieve_conversation_memories(
                    conversation_id=conversation_id,
                )
                for m in mems:
                    _add_evidence(evidence_list, m, "conversation history")
                memories.extend(mems)

            elif mt == MemoryType.OPPORTUNITY and (opportunity_id or company_id):
                mems = await self.retrieve_opportunity_memories(
                    opportunity_id=opportunity_id,
                    company_id=company_id,
                )
                for m in mems:
                    _add_evidence(evidence_list, m, "opportunity history")
                memories.extend(mems)

            elif mt == MemoryType.OUTCOME and (company_id or contact_id):
                mems = await self.retrieve_outcome_memories(
                    entity_id=company_id or contact_id,
                )
                for m in mems:
                    _add_evidence(evidence_list, m, "previous outcome")
                memories.extend(mems)

            elif mt == MemoryType.PREFERENCE:
                if contact_id:
                    mems = await self.retrieve_preference_memories(
                        entity_type="contact", entity_id=contact_id,
                    )
                    for m in mems:
                        _add_evidence(evidence_list, m, "contact preference")
                    memories.extend(mems)
                if company_id:
                    mems = await self.retrieve_preference_memories(
                        entity_type="account", entity_id=company_id,
                    )
                    for m in mems:
                        _add_evidence(evidence_list, m, "account preference")
                    memories.extend(mems)

        enriched["relevant_memories"] = memories
        enriched["memory_citation"] = MemoryCitation(
            memory_ids=[m.id for m in memories],
            evidence=evidence_list,
            explanation=_build_explanation(evidence_list),
        )

        return enriched


def _add_evidence(
    evidence_list: list[MemoryEvidence],
    memory: Memory,
    category: str,
) -> None:
    evidence_list.append(MemoryEvidence(
        memory_id=memory.id,
        memory_type=memory.memory_type,
        summary=f"{category}: {memory.source} ({memory.timestamp.strftime('%Y-%m-%d') if hasattr(memory.timestamp, 'strftime') else memory.timestamp})",
        relevance_score=memory.confidence,
        excerpt=str(memory.__dict__)[:200],
    ))


def _build_explanation(evidence: list[MemoryEvidence]) -> str:
    if not evidence:
        return "No relevant memories found"
    categories: dict[str, int] = {}
    for e in evidence:
        label = e.summary.split(":")[0] if ":" in e.summary else "other"
        categories[label] = categories.get(label, 0) + 1
    parts = [f"{k} ({v})" for k, v in sorted(categories.items())]
    return f"This plan was influenced by {len(evidence)} relevant memories: {'; '.join(parts)}."
