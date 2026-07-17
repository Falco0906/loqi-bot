"""Conversation Stage Classification.

Determines where the lead is in the buying process.
Uses message content + conversation memory to classify stage.
"""

from services.conversation_models import ConversationStage, BuyingSignal


_STAGE_PATTERNS: list[tuple[ConversationStage, list[str], str]] = [
    (ConversationStage.INITIAL_OUTREACH, [
        "first touch", "just reaching", "saw my email", "cold outreach",
    ], "First contact — minimal engagement"),
    (ConversationStage.ENGAGED, [
        "thanks for", "helpful", "useful", "tell me more", "curious",
        "looks interesting", "sounds interesting", "more details",
        "questions", "i'd like to",
    ], "Lead is responding and asking questions — engaged"),
    (ConversationStage.DISCOVERY, [
        "what do you", "how does it", "what problem", "tell me about",
        "how it works", "who is it for", "use case",
        "what makes you different",
    ], "Discovery phase — understanding product fit"),
    (ConversationStage.EVALUATION, [
        "demo", "pricing", "compare", "versus", "vs ", "trial",
        "test it", "evaluate", "considering", "looking at options",
        "assessing", "checking",
    ], "Active evaluation — comparing options"),
    (ConversationStage.NEGOTIATION, [
        "discount", "better price", "can you do", "negotiate",
        "flexible", "terms", "contract length", "annual commitment",
        "custom pricing",
    ], "Negotiation — discussing terms and pricing"),
    (ConversationStage.DECISION, [
        "decision", "final", "ready to", "let's proceed", "move forward",
        "approve", "approved", "sign", "signing", "send over",
        "formal proposal", "ready",
    ], "Decision stage — ready to proceed"),
    (ConversationStage.WON, [
        "signed", "agreed", "partners", "onboarded", "started",
        "confirmed", "thank you for your business",
    ], "Won — deal closed"),
    (ConversationStage.LOST, [
        "went with", "chose", "selected", "not going with", "decided against",
        "going in a different direction", "not a fit right now",
    ], "Lost — prospect chose another path"),
    (ConversationStage.DORMANT, [
        "reach out later", "not now", "too busy", "not the right time",
        "someday", "next quarter", "not yet", "maybe later",
    ], "Dormant — no active engagement"),
]


def classify_stage(buying_signals: list[BuyingSignal], message: str) -> tuple[ConversationStage, str]:
    """Classify conversation stage based on current message and detected signals."""
    ml = message.lower()

    has_very_strong = any(s.strength.value == "very_strong" for s in buying_signals)
    has_strong = any(s.strength.value == "strong" for s in buying_signals)

    if any(s.signal == "won_deal" for s in buying_signals):
        return ConversationStage.WON, "Won signal detected in buying signals"

    if any(s.signal == "lost_opportunity" for s in buying_signals):
        return ConversationStage.LOST, "Lost signal detected in buying signals"

    if any(s.signal == "mentioned_contract" for s in buying_signals) and has_very_strong:
        return ConversationStage.DECISION, "Contract mentioned with strong buying signals"

    if any(s.signal in ("mentioned_budget", "asked_for_pricing") for s in buying_signals) and \
       any(s.signal == "mentioned_procurement" for s in buying_signals):
        return ConversationStage.NEGOTIATION, "Budget and procurement both mentioned"

    if any(s.signal in ("requested_demo", "asked_for_proposal") for s in buying_signals):
        return ConversationStage.EVALUATION, "Demo or proposal requested"

    if any(s.signal in ("asked_implementation_timeline", "asked_integration_questions") for s in buying_signals) and has_strong:
        return ConversationStage.EVALUATION, "Technical evaluation questions detected with strong signals"

    if any(s.signal == "mentioned_current_vendor" for s in buying_signals):
        return ConversationStage.DISCOVERY, "Competitive comparison — discovery phase"

    for stage, patterns, reason in _STAGE_PATTERNS:
        if any(p in ml for p in patterns):
            return stage, reason

    if not buying_signals:
        return ConversationStage.INITIAL_OUTREACH, "No buying signals or stage indicators detected"

    if has_very_strong:
        return ConversationStage.EVALUATION, "Strong buying signals indicate evaluation"

    return ConversationStage.ENGAGED, "Some engagement but no clear stage indicators"
