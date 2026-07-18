"""Goal Selection — determines the best objective from conversation intelligence.

Consumes ConversationIntelligence, produces a primary and alternative goal.
Pure reasoning — no execution.
"""

from __future__ import annotations
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import GoalType, GoalSelection


def select_goals(intelligence: ConversationIntelligence) -> GoalSelection:
    """Select primary and alternative goals based on conversation intelligence."""
    top_intents = [i.label.value for i in intelligence.intents[:3]]
    top_signals = [s.signal_type for s in intelligence.buying_signals[:3]]
    has_objections = len(intelligence.objections) > 0

    primary = _select_primary(top_intents, top_signals, has_objections)
    alternative = _select_alternative(primary, top_intents, top_signals)
    reasoning = _build_reasoning(primary, alternative, top_intents, top_signals, has_objections)

    return GoalSelection(primary=primary, alternative=alternative, reasoning=reasoning)


def _select_primary(intents: list[str], signals: list[str], has_objections: bool) -> GoalType:
    if "demo_request" in intents:
        return GoalType.BOOK_DEMO
    if "meeting_request" in intents:
        return GoalType.SCHEDULE_MEETING
    if "pricing_discussion" in intents or "budget_discussion" in intents:
        return GoalType.PROVIDE_PRICING
    if has_objections:
        return GoalType.OVERCOME_OBJECTION
    if "interested" in intents:
        return GoalType.CONFIRM_INTEREST
    if "information_request" in intents or "technical_question" in intents:
        return GoalType.QUALIFY_NEEDS
    if "not_interested" in intents:
        return GoalType.RE_ENGAGE
    for s in signals:
        if "pricing" in s or "budget" in s:
            return GoalType.PROVIDE_PRICING
        if "demo" in s:
            return GoalType.BOOK_DEMO
        if "meeting" in s:
            return GoalType.SCHEDULE_MEETING
    if not intents:
        return GoalType.GATHER_INFO
    return GoalType.KEEP_ALIVE


def _select_alternative(primary: GoalType, intents: list[str], signals: list[str]) -> GoalType:
    if primary == GoalType.BOOK_DEMO:
        if "pricing_discussion" in intents:
            return GoalType.PROVIDE_PRICING
        return GoalType.QUALIFY_NEEDS
    if primary == GoalType.PROVIDE_PRICING:
        return GoalType.BOOK_DEMO
    if primary == GoalType.OVERCOME_OBJECTION:
        if "pricing_discussion" in intents:
            return GoalType.PROVIDE_PRICING
        return GoalType.QUALIFY_NEEDS
    if primary == GoalType.CONFIRM_INTEREST:
        return GoalType.BOOK_DEMO
    if primary == GoalType.QUALIFY_NEEDS:
        return GoalType.CONFIRM_INTEREST
    if primary == GoalType.KEEP_ALIVE:
        return GoalType.GATHER_INFO
    if primary == GoalType.RE_ENGAGE:
        return GoalType.GATHER_INFO
    return GoalType.KEEP_ALIVE


def _build_reasoning(
    primary: GoalType,
    alternative: GoalType,
    intents: list[str],
    signals: list[str],
    has_objections: bool,
) -> list[str]:
    reasons = []
    reasons.append(f"Primary goal: {primary.value}.")
    reasons.append(f"Alternative goal: {alternative.value}.")
    if intents:
        reasons.append(f"Driving intents: {', '.join(intents[:3])}.")
    if has_objections:
        reasons.append("Active objections present — prioritize overcoming before advancing.")
    if signals:
        strong = [s for s in signals if "pricing" in s or "demo" in s or "meeting" in s]
        if strong:
            reasons.append(f"Strong buying signals: {', '.join(strong)}.")
    return reasons
