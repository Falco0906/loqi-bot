"""Conversation memory manager — extracts and persists conversation facts.

This module contains ONLY extraction reasoning.
All patterns, role lists, and confidence values come from KnowledgeRegistry.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Optional
from services.conversation_intelligence.intelligence_models import ConversationMemoryEntry, EntityType
from services.conversation_intelligence.knowledge.registry import get_registry


class ConversationMemoryManager:
    """Manages conversation-level fact extraction and retrieval.

    Stores extracted facts per lead_id with confidence scoring.
    Deduplicates by key+value within the same lead.
    """

    def __init__(self):
        self._facts: dict[str, ConversationMemoryEntry] = {}

    def extract_facts(
        self,
        message_body: str,
        lead_id: str,
        subject: str = "",
    ) -> list[ConversationMemoryEntry]:
        """Extract conversation facts from a message."""
        combined = f"{subject} {message_body}" if subject else message_body
        registry = get_registry()
        facts: list[ConversationMemoryEntry] = []

        person_name = self._extract_name(combined, registry)
        if person_name:
            conf = registry.get_confidence("MEMORY_NAME_CONFIDENCE")
            fact = self._add_fact("prospect_name", person_name, conf, EntityType.PERSON, lead_id)
            if fact:
                facts.append(fact)

        company = self._extract_company(combined, registry)
        if company:
            conf = registry.get_confidence("MEMORY_COMPANY_CONFIDENCE")
            fact = self._add_fact("prospect_company", company, conf, EntityType.COMPANY, lead_id)
            if fact:
                facts.append(fact)

        role = self._extract_role(combined, registry)
        if role:
            conf = registry.get_confidence("MEMORY_ROLE_CONFIDENCE")
            fact = self._add_fact("prospect_role", role, conf, EntityType.ROLE, lead_id)
            if fact:
                facts.append(fact)

        budget = self._extract_budget(combined)
        if budget:
            conf = registry.get_confidence("MEMORY_BUDGET_CONFIDENCE")
            fact = self._add_fact("budget", budget, conf, EntityType.BUDGET, lead_id)
            if fact:
                facts.append(fact)

        needs = self._extract_needs(combined, registry)
        if needs:
            conf = registry.get_confidence("MEMORY_NEED_CONFIDENCE")
            for need in needs:
                fact = self._add_fact("identified_need", need, conf, EntityType.TECHNOLOGY, lead_id)
                if fact:
                    facts.append(fact)

        return facts

    def get_conversation_facts(self, lead_id: str, limit: int = 20) -> list[ConversationMemoryEntry]:
        """Retrieve all stored facts for a lead."""
        prefix = f"{lead_id}:"
        facts = [
            f for key, f in self._facts.items()
            if key.startswith(prefix)
        ]
        facts.sort(
            key=lambda f: (f.confidence, f.updated_at or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        return facts[:limit]

    def extract_from_intelligence(self, entities: list) -> list[ConversationMemoryEntry]:
        """Extract memory facts from extracted entities."""
        registry = get_registry()
        min_conf = registry.get_confidence("MEMORY_ENTITY_MIN_CONFIDENCE")
        return [
            ConversationMemoryEntry(
                key=f"entity_{e.entity_type.value}",
                value=e.value,
                entity_type=e.entity_type,
                confidence=e.confidence,
                updated_at=datetime.now(timezone.utc),
                source_message_id="",
            )
            for e in entities
            if e.confidence >= min_conf
        ]

    def _add_fact(
        self, key: str, value: str, confidence: float,
        entity_type: EntityType, lead_id: str,
    ) -> Optional[ConversationMemoryEntry]:
        fact_key = f"{lead_id}:{key}"
        if fact_key in self._facts and self._facts[fact_key].value == value:
            return None
        fact = ConversationMemoryEntry(
            entity_type=entity_type,
            key=key,
            value=value,
            confidence=confidence,
            updated_at=datetime.now(timezone.utc),
            source_message_id=f"lead:{lead_id}",
        )
        self._facts[fact_key] = fact
        return fact

    def _extract_name(self, text: str, registry) -> Optional[str]:
        for pattern in registry.get_person_self_identification_patterns():
            matches = re.findall(pattern, text)
            if matches:
                return matches[0].strip()
        return None

    def _extract_company(self, text: str, registry) -> Optional[str]:
        exceptions = registry.get_company_indicator_exceptions()
        for pattern, _ in registry.get_company_patterns():
            matches = re.findall(pattern, text)
            if matches:
                filtered = [
                    m for m in matches
                    if not any(m.lower().startswith(ex) for ex in exceptions)
                ]
                if filtered:
                    return filtered[0].strip()
        return None

    def _extract_role(self, text: str, registry) -> Optional[str]:
        for title in registry.get_decision_maker_titles():
            if title in text.lower():
                return title
        return None

    def _extract_budget(self, text: str) -> Optional[str]:
        matches = re.findall(r"\$(\d+[kKmbMB])", text)
        return matches[0] if matches else None

    def _extract_needs(self, text: str, registry) -> list[str]:
        needs = []
        for pattern, _ in registry.get_need_patterns():
            matches = re.findall(pattern, text.lower())
            for m in matches[:3]:
                cleaned = m.strip()
                if cleaned and len(cleaned) > 3:
                    needs.append(cleaned)
        return needs
