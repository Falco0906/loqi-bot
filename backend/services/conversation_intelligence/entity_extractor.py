"""Entity extraction — extracts structured business entities from conversation messages.

This module contains ONLY extraction reasoning.
All business knowledge (patterns, lists, confidence values) comes from KnowledgeRegistry.

Entities are provider-independent and normalized.
"""

from __future__ import annotations
import re
from services.conversation_intelligence.intelligence_models import EntityResult, EntityType
from services.conversation_intelligence.knowledge.registry import get_registry


def extract_entities(message_body: str, subject: str = "") -> list[EntityResult]:
    """Extract structured business entities from message text."""
    combined = f"{subject} {message_body}" if subject else message_body
    text_lower = combined.lower()
    registry = get_registry()
    results: list[EntityResult] = []

    results.extend(_extract_people(text_lower, combined, registry))
    results.extend(_extract_companies(text_lower, combined, registry))
    results.extend(_extract_titles(text_lower, registry))
    results.extend(_extract_budget(text_lower, registry))
    results.extend(_extract_timelines(text_lower, registry))
    results.extend(_extract_meeting_dates(text_lower, registry))
    results.extend(_extract_technologies(text_lower, registry))

    deduplicated = _deduplicate(results)
    return deduplicated


def _extract_people(text_lower: str, original: str, registry) -> list[EntityResult]:
    results = []
    confidence = registry.get_confidence("PERSON_CONFIDENCE")
    for pattern in registry.get_person_patterns():
        matches = re.findall(pattern, original)
        for m in matches[:3]:
            results.append(EntityResult(
                entity_type=EntityType.PERSON,
                value=m.strip(),
                normalized_value=m.strip(),
                confidence=confidence,
                source_text=m,
            ))
    return results


def _extract_companies(text_lower: str, original: str, registry) -> list[EntityResult]:
    results = []
    indicators = registry.get_company_indicators()
    for pattern, base_conf in registry.get_company_patterns():
        matches = re.findall(pattern, original)
        for m in matches[:5]:
            words = m.split()
            if any(ind in m.lower() for ind in indicators) or len(words) >= 2:
                boost = registry.get_confidence("COMPANY_CONFIDENCE_BOOST_PER_WORD")
                max_conf = registry.get_confidence("COMPANY_MAX_CONFIDENCE")
                conf = min(base_conf + boost * len(words), max_conf)
                results.append(EntityResult(
                    entity_type=EntityType.COMPANY,
                    value=m.strip(),
                    normalized_value=m.strip(),
                    confidence=conf,
                    source_text=m,
                ))
    return results


def _extract_titles(text_lower: str, registry) -> list[EntityResult]:
    results = []
    title_conf = registry.get_confidence("TITLE_CONFIDENCE")
    dm_conf = registry.get_confidence("DECISION_MAKER_CONFIDENCE")
    for title in registry.get_decision_maker_titles():
        if title in text_lower:
            idx = text_lower.index(title)
            context = text_lower[max(0, idx - 30):idx + len(title) + 30]
            results.append(EntityResult(
                entity_type=EntityType.ROLE,
                value=title,
                normalized_value=title,
                confidence=title_conf,
                source_text=context[:80],
            ))
            results.append(EntityResult(
                entity_type=EntityType.DECISION_MAKER,
                value=title,
                normalized_value=title,
                confidence=dm_conf,
                source_text=context[:80],
            ))
    return results


def _extract_budget(text_lower: str, registry) -> list[EntityResult]:
    results = []
    explicit_conf = registry.get_confidence("BUDGET_EXPLICIT_CONFIDENCE")
    implicit_conf = registry.get_confidence("BUDGET_IMPLICIT_CONFIDENCE")
    for pattern, kind in registry.get_budget_patterns():
        matches = re.findall(pattern, text_lower)
        for m in matches[:2]:
            value = m[0] if isinstance(m, tuple) else m
            results.append(EntityResult(
                entity_type=EntityType.BUDGET,
                value=str(m),
                normalized_value=value,
                confidence=explicit_conf if kind == "explicit" else implicit_conf,
                source_text=str(m),
            ))
    return results


def _extract_timelines(text_lower: str, registry) -> list[EntityResult]:
    results = []
    date_conf = registry.get_confidence("TIMELINE_DATE_CONFIDENCE")
    other_conf = registry.get_confidence("TIMELINE_OTHER_CONFIDENCE")
    for pattern, kind in registry.get_timeline_patterns():
        matches = re.findall(pattern, text_lower)
        for m in matches[:2]:
            value = m[0] if isinstance(m, tuple) else m
            results.append(EntityResult(
                entity_type=EntityType.TIMELINE,
                value=str(m),
                normalized_value=value,
                confidence=date_conf if kind in ("date", "quarter") else other_conf,
                source_text=str(m),
            ))
    return results


def _extract_meeting_dates(text_lower: str, registry) -> list[EntityResult]:
    results = []
    confidence = registry.get_confidence("MEETING_CONFIDENCE")
    for pattern, kind in registry.get_meeting_patterns():
        matches = re.findall(pattern, text_lower)
        for m in matches[:2]:
            value = m[0] if isinstance(m, tuple) else m
            results.append(EntityResult(
                entity_type=EntityType.MEETING_DATE,
                value=str(m),
                normalized_value=value,
                confidence=confidence,
                source_text=str(m),
            ))
    return results


def _extract_technologies(text_lower: str, registry) -> list[EntityResult]:
    results = []
    confidence = registry.get_confidence("TECHNOLOGY_CONFIDENCE")
    for tech in registry.get_technologies():
        if tech in text_lower:
            results.append(EntityResult(
                entity_type=EntityType.TECHNOLOGY,
                value=tech,
                normalized_value=tech,
                confidence=confidence,
                source_text=tech,
            ))
    return results


def _deduplicate(entities: list[EntityResult]) -> list[EntityResult]:
    seen: set[str] = set()
    deduped: list[EntityResult] = []
    for e in entities:
        key = f"{e.entity_type.value}:{e.value.lower()}"
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped
