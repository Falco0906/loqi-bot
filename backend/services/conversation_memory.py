"""Conversation Memory — structured fact storage.

Stores facts about the conversation, not raw messages.
Memory evolves after each analyzed message.
"""

from typing import Optional
from services.conversation_intelligence.legacy_models import ConversationMemory, ConversationMessage, IntentPrediction, BuyingSignal, ConversationStage
from services.conversations.intelligence_memory import build_legacy_memory


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
    """Compatibility wrapper that writes the retired process-local store.

    Production callers migrate to ``services.conversations.intelligence_memory``.
    This wrapper remains only while C5c test/runtime proof is completed.
    """
    mem = build_legacy_memory(
        conversation_id=conversation_id, message=message, intents=intents,
        buying_signals=buying_signals, stage=stage, stage_reasoning=stage_reasoning,
        followup_action=followup_action, existing_memory=existing_memory,
        decision_confidence=decision_confidence, urgency=urgency,
        top_objection=top_objection,
    )
    memory_store.update(conversation_id, mem)
    return mem
