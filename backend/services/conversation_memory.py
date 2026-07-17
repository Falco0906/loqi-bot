"""Conversation Memory — structured fact storage.

Stores facts about the conversation, not raw messages.
Memory evolves after each analyzed message.
"""

from typing import Optional
from services.conversation_models import (
    ConversationMemory, ConversationMessage, IntentPrediction,
    BuyingSignal, ConversationStage, FollowupRecommendation,
)


class MemoryStore:
    """In-memory conversation store. Future: swap with DB persistence."""

    def __init__(self) -> None:
        self._store: dict[str, ConversationMemory] = {}

    def get(self, conversation_id: str) -> Optional[ConversationMemory]:
        return self._store.get(conversation_id)

    def update(self, conversation_id: str, memory: ConversationMemory) -> None:
        self._store[conversation_id] = memory

    def delete(self, conversation_id: str) -> None:
        self._store.pop(conversation_id, None)

    def list_ids(self) -> list[str]:
        return list(self._store.keys())


memory_store = MemoryStore()


def _extract_questions(text: str) -> list[str]:
    """Extract question-like sentences from text."""
    import re
    questions = []
    for line in re.split(r'[.!?\n]', text):
        if '?' in line and len(line.strip()) > 5:
            questions.append(line.strip())
    return questions[:5]


def _extract_pain_points(text: str) -> list[str]:
    """Extract potential pain points from text."""
    pain_indicators = [
        "struggling with", "challenge is", "difficult to", "problem with",
        "issue we have", "frustrating", "hard to", "not working",
        "broken", "inefficient", "too slow", "too many", "wasting",
        "not enough", "can't", "cannot",
    ]
    points = []
    ml = text.lower()
    for p in pain_indicators:
        if p in ml:
            idx = ml.index(p)
            start = max(0, idx - 20)
            end = min(len(text), idx + len(p) + 60)
            snippet = text[start:end].strip()
            points.append(snippet)
    return points[:3]


def create_or_update_memory(
    conversation_id: str,
    message: ConversationMessage,
    intents: list[IntentPrediction],
    buying_signals: list[BuyingSignal],
    stage: ConversationStage,
    stage_reasoning: str,
    followup_action: str = "",
    existing_memory: Optional[ConversationMemory] = None,
    decision_confidence: int = 0,
    urgency: str = "",
    top_objection: str = "",
) -> ConversationMemory:
    """Create or update conversation memory from an analyzed message."""
    if existing_memory:
        mem = existing_memory.model_copy(deep=True)
    else:
        mem = ConversationMemory(conversation_id=conversation_id)

    mem.current_stage = stage
    mem.summary = f"Message from {message.sender or 'unknown'}: {message.text[:100]}..."

    questions = _extract_questions(message.text)
    for q in questions:
        if q not in mem.open_questions:
            mem.open_questions.append(q)

    pains = _extract_pain_points(message.text)
    for p in pains:
        if p not in mem.pain_points:
            mem.pain_points.append(p)

    for intent in intents:
        if intent.intent.value == "budget_concern" and intent.intent.value not in mem.key_risks:
            mem.key_risks.append("Budget concern raised by lead")
        if intent.intent.value == "timing_concern" and "Timing delay risk" not in mem.key_risks:
            mem.key_risks.append("Timing delay risk")
        if intent.intent.value == "authority_concern" and "Authority concerns — may need multiple stakeholders" not in mem.key_risks:
            mem.key_risks.append("Authority concerns — may need multiple stakeholders")
        if intent.intent.value == "competitor_mention" and "Competitor evaluation in progress" not in mem.key_risks:
            mem.key_risks.append("Competitor evaluation in progress")

    for signal in buying_signals:
        sig_text = signal.signal.replace("_", " ").title()
        if sig_text not in mem.buying_signals:
            mem.buying_signals.append(sig_text)

    if followup_action and followup_action not in mem.last_followup:
        mem.last_followup = followup_action

    buying_signal_names = {s.signal for s in buying_signals}
    if "asked_for_pricing" in buying_signal_names:
        if "Pricing discussion" not in mem.key_opportunities:
            mem.key_opportunities.append("Pricing discussion")
    if "requested_demo" in buying_signal_names:
        if "Demo opportunity" not in mem.key_opportunities:
            mem.key_opportunities.append("Demo opportunity")
    if "requested_meeting" in buying_signal_names:
        if "Meeting opportunity" not in mem.key_opportunities:
            mem.key_opportunities.append("Meeting opportunity")

    if buying_signals:
        strengths = [s.strength.value for s in buying_signals]
        if "very_strong" in strengths or "strong" in strengths:
            mem.urgency = "high"
        elif "medium" in strengths:
            mem.urgency = "medium"
        else:
            mem.urgency = "low"

    mem.last_recommendation = stage_reasoning
    if top_objection:
        mem.top_objection = top_objection
    if decision_confidence:
        mem.decision_confidence = decision_confidence
    if urgency:
        mem.urgency = urgency
    memory_store.update(conversation_id, mem)
    return mem
