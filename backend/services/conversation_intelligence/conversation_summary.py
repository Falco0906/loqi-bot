"""Multi-level conversation summary generation.

Generates four summary levels:
- Short: 1-sentence snapshot
- Medium: 2-3 paragraph overview
- Executive: Decision-maker focused summary
- Action: Next-step action summary

Each summary serves a different consumer.
AI integration plugs in here; fallback is template-based.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from services.conversation_models import ReplyIntelligence
from services.conversation_intelligence.intelligence_models import (
    SummaryLevel, ConversationSummaryResult,
    ConversationIntelligence, EntityType,
)


def generate_summaries(
    intelligence: ConversationIntelligence,
    reply_intel: Optional[ReplyIntelligence] = None,
) -> list[ConversationSummaryResult]:
    """Generate multi-level summaries from conversation intelligence."""
    now = datetime.now(timezone.utc)
    return [
        ConversationSummaryResult(
            level=SummaryLevel.SHORT,
            content=_generate_short_summary(intelligence, reply_intel),
            generated_at=now,
        ),
        ConversationSummaryResult(
            level=SummaryLevel.MEDIUM,
            content=_generate_medium_summary(intelligence, reply_intel),
            generated_at=now,
        ),
        ConversationSummaryResult(
            level=SummaryLevel.EXECUTIVE,
            content=_generate_executive_summary(intelligence, reply_intel),
            generated_at=now,
        ),
        ConversationSummaryResult(
            level=SummaryLevel.ACTION,
            content=_generate_action_summary(intelligence, reply_intel),
            generated_at=now,
        ),
    ]


def _get_primary_intent(intelligence: ConversationIntelligence) -> str:
    if intelligence.intents:
        return intelligence.intents[0].label.value.replace("_", " ")
    return "unknown"


def _get_top_objection(intelligence: ConversationIntelligence) -> str:
    if intelligence.objections:
        return intelligence.objections[0].category.value.replace("_", " ")
    return ""


def _get_key_entities(intelligence: ConversationIntelligence, entity_type: EntityType) -> list[str]:
    return [e.value for e in intelligence.entities if e.entity_type == entity_type]


def _generate_short_summary(intelligence: ConversationIntelligence, reply_intel: Optional[ReplyIntelligence] = None) -> str:
    intent = _get_primary_intent(intelligence)
    contacts = _get_key_entities(intelligence, EntityType.PERSON)
    companies = _get_key_entities(intelligence, EntityType.COMPANY)
    contact_str = contacts[0] if contacts else ""
    company_str = companies[0] if companies else ""
    parts = [f"Intent: {intent}"]
    if contact_str:
        parts.append(f"Contact: {contact_str}")
    if company_str:
        parts.append(f"Company: {company_str}")
    if intelligence.health:
        parts.append(f"Health: {intelligence.health.score}/{intelligence.health.max_score}")
    return " | ".join(parts)


def _generate_medium_summary(intelligence: ConversationIntelligence, reply_intel: Optional[ReplyIntelligence] = None) -> str:
    lines = []
    intent = _get_primary_intent(intelligence)
    lines.append(f"Primary intent: {intent}.")

    if intelligence.buying_signals:
        strong_signals = [s for s in intelligence.buying_signals if s.strength.value in ("very_strong", "strong")]
        if strong_signals:
            signals_str = ", ".join(s.signal_type for s in strong_signals[:3])
            lines.append(f"Strong buying signals detected: {signals_str}.")

    if intelligence.objections:
        top = intelligence.objections[0]
        lines.append(f"Objection: {top.category.value} (severity: {top.severity.value}).")

    if intelligence.memory:
        facts = [f"{m.key}: {m.value}" for m in intelligence.memory[:5]]
        if facts:
            lines.append("Key facts: " + "; ".join(facts) + ".")

    return " ".join(lines)


def _generate_executive_summary(intelligence: ConversationIntelligence, reply_intel: Optional[ReplyIntelligence] = None) -> str:
    lines = []
    contacts = _get_key_entities(intelligence, EntityType.PERSON)
    companies = _get_key_entities(intelligence, EntityType.COMPANY)
    roles = _get_key_entities(intelligence, EntityType.ROLE)
    name = contacts[0] if contacts else "Prospect"
    company = companies[0] if companies else "the company"

    lines.append(f"{name} ({company})")

    intent = _get_primary_intent(intelligence)
    if intent != "unknown":
        lines.append(f"Primary interest: {intent}.")

    if intelligence.objections:
        top = intelligence.objections[0]
        lines.append(f"Key concern: {top.category.value}.")

    if roles:
        lines.append(f"Contact role: {roles[0]}.")

    if intelligence.health:
        lines.append(f"Conversation health: {intelligence.health.score}/100.")
        if intelligence.health.reasoning:
            lines.append(f"Assessment: {intelligence.health.reasoning[0]}.")

    return "\n".join(lines)


def _generate_action_summary(intelligence: ConversationIntelligence, reply_intel: Optional[ReplyIntelligence] = None) -> str:
    lines = []

    if intelligence.intents:
        top = intelligence.intents[0]
        if top.label.value == "pricing_discussion":
            lines.append("Send pricing information.")
        elif top.label.value == "demo_request":
            lines.append("Schedule product demo.")
        elif top.label.value == "meeting_request":
            lines.append("Confirm meeting time.")
        elif top.label.value == "technical_question":
            lines.append("Provide technical documentation.")
        elif top.label.value == "objection":
            lines.append("Address objection with relevant case studies.")
        elif top.label.value == "interested":
            lines.append("Nurture with relevant content.")

    if intelligence.health and intelligence.health.score < 40:
        lines.append("Consider re-engagement sequence.")

    if not lines:
        lines.append("Monitor for next reply.")

    return " | ".join(lines)
