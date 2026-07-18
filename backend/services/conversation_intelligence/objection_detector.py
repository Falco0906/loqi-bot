"""Objection detection — identifies and categorizes prospect objections.

This module contains ONLY detection reasoning.
All objection patterns, severity, and confidence defaults come from KnowledgeRegistry.
"""

from __future__ import annotations
from services.conversation_intelligence.intelligence_models import ObjectionResult
from services.conversation_intelligence.knowledge.registry import get_registry


def detect_objections(message_body: str, subject: str = "") -> list[ObjectionResult]:
    """Detect and categorize objections in a message.
    Returns structured objection results with severity and confidence.
    """
    combined = (f"{subject} {message_body}" if subject else message_body).lower()
    registry = get_registry()
    boost = registry.get_confidence("OBJECTION_EVIDENCE_BOOST")
    max_conf = registry.get_confidence("OBJECTION_MAX_CONFIDENCE")
    results: list[ObjectionResult] = []

    for definition in registry.get_objection_definitions():
        category = definition["category"]
        patterns = definition["keywords"]
        severity = definition["severity"]
        base_confidence = definition["base_confidence"]

        evidence = [p for p in patterns if p in combined]
        if evidence:
            confidence = min(base_confidence + (len(evidence) * boost), max_conf)
            results.append(ObjectionResult(
                category=category,
                severity=severity,
                confidence=confidence,
                evidence=evidence,
                source="rule",
            ))

    results.sort(key=lambda r: (-r.confidence, -len(r.evidence)))
    return results
