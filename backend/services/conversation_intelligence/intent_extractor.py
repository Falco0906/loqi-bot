"""Intent extraction.

Wraps the existing intent_detector and maps to the enhanced IntentLabel enum.
No embedded business knowledge — the intent label map is the only mapping.
"""

from __future__ import annotations
from services.intent_detector import detect_intents as _detect_intents
from services.conversation_intelligence.intelligence_models import IntentLabel, IntentResult


_INTENT_MAP: dict[str, IntentLabel] = {
    "pricing_request": IntentLabel.PRICING_DISCUSSION,
    "meeting_request": IntentLabel.MEETING_REQUEST,
    "demo_request": IntentLabel.DEMO_REQUEST,
    "technical_question": IntentLabel.TECHNICAL_QUESTION,
    "implementation_question": IntentLabel.INFORMATION_REQUEST,
    "competitor_mention": IntentLabel.INFORMATION_REQUEST,
    "objection": IntentLabel.OBJECTION,
    "budget_concern": IntentLabel.BUDGET_DISCUSSION,
    "timing_concern": IntentLabel.TIMELINE_DISCUSSION,
    "authority_concern": IntentLabel.INFORMATION_REQUEST,
    "need_more_info": IntentLabel.INFORMATION_REQUEST,
    "referral": IntentLabel.REFERRAL,
    "not_interested": IntentLabel.NOT_INTERESTED,
    "unsubscribe": IntentLabel.NOT_INTERESTED,
    "out_of_office": IntentLabel.UNKNOWN,
    "follow_up_later": IntentLabel.FOLLOW_UP,
    "positive_feedback": IntentLabel.INTERESTED,
    "negative_feedback": IntentLabel.OBJECTION,
    "interested": IntentLabel.INTERESTED,
    "general_question": IntentLabel.INFORMATION_REQUEST,
}


def extract_intents(message_body: str, subject: str = "") -> list[IntentResult]:
    """Extract structured intents from a message.
    Returns all detected intents with confidence scores and evidence.
    """
    combined = f"{subject} {message_body}" if subject else message_body
    predictions = _detect_intents(combined, top_n=5)
    results: list[IntentResult] = []
    for pred in predictions:
        label = _INTENT_MAP.get(pred.intent.value, IntentLabel.UNKNOWN)
        results.append(IntentResult(
            label=label,
            confidence=pred.confidence / 100.0,
            evidence=pred.supporting_evidence,
            source="rule",
            raw_text=pred.reason,
        ))
    results.sort(key=lambda r: -r.confidence)
    return results
