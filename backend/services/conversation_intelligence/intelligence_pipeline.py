"""Intelligence pipeline — orchestrates all conversation intelligence analyzers.

Produces a unified ConversationIntelligence result from a message.
Every analyzer runs independently; failures in one do not block others.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from services.conversation_models import ReplyIntelligence
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.conversation_intelligence.intent_extractor import extract_intents
from services.conversation_intelligence.entity_extractor import extract_entities
from services.conversation_intelligence.buying_signal_detector import extract_buying_signals
from services.conversation_intelligence.objection_detector import detect_objections
from services.conversation_intelligence.conversation_summary import generate_summaries
from services.conversation_intelligence.conversation_memory import ConversationMemoryManager
from services.conversation_intelligence.conversation_scoring import score_conversation


logger = logging.getLogger(__name__)


class IntelligencePipeline:
    """Full-stack conversation intelligence pipeline.

    Usage:
        pipeline = IntelligencePipeline()
        result = pipeline.analyze_message(
            message_body="We're interested but need budget approval.",
            lead_id="lead_123",
            subject="Re: Your proposal",
        )
        print(result.health.score)
        print(result.summaries[0].content)  # short summary
    """

    def __init__(self):
        self._memory = ConversationMemoryManager()

    def analyze_message(
        self,
        message_body: str,
        lead_id: str,
        subject: str = "",
        existing_intel: Optional[ConversationIntelligence] = None,
        reply_intel: Optional[ReplyIntelligence] = None,
    ) -> ConversationIntelligence:
        """Run full intelligence pipeline on a message.

        Returns a ConversationIntelligence with all analyzer results.
        Each analyzer runs independently; partial results preserved on error.
        """
        intents = []
        entities = []
        buying_signals = []
        objections = []
        memory_facts = []
        summaries = []
        health = None

        # Phase 1: Extract — all analyzers run independently
        try:
            intents = extract_intents(message_body, subject)
        except Exception as e:
            logger.error("Intent extraction failed: %s", e)

        try:
            entities = extract_entities(message_body, subject)
        except Exception as e:
            logger.error("Entity extraction failed: %s", e)

        try:
            buying_signals = extract_buying_signals(message_body, subject)
        except Exception as e:
            logger.error("Buying signal detection failed: %s", e)

        try:
            objections = detect_objections(message_body, subject)
        except Exception as e:
            logger.error("Objection detection failed: %s", e)

        try:
            memory_facts = self._memory.extract_facts(message_body, lead_id, subject)
            entity_facts = self._memory.extract_from_intelligence(entities)
            memory_facts.extend(entity_facts)
        except Exception as e:
            logger.error("Memory extraction failed: %s", e)

        # Phase 2: Build intelligence container
        intel = ConversationIntelligence(
            conversation_id=lead_id,
            intents=intents,
            entities=entities,
            buying_signals=buying_signals,
            objections=objections,
            memory=memory_facts,
            analyzed_at=datetime.now(timezone.utc),
        )

        # Phase 3: Score + summarize
        try:
            health = score_conversation(intel)
            intel.health = health
        except Exception as e:
            logger.error("Scoring failed: %s", e)

        try:
            summaries = generate_summaries(intel, reply_intel)
            intel.summaries = summaries
        except Exception as e:
            logger.error("Summary generation failed: %s", e)

        return intel

    def merge(
        self,
        existing: ConversationIntelligence,
        new_message: ConversationIntelligence,
    ) -> ConversationIntelligence:
        """Merge new intelligence into existing conversation context."""
        existing.intents = new_message.intents or existing.intents
        existing.entities = list({e.value: e for e in existing.entities + new_message.entities}.values())
        existing.buying_signals = (existing.buying_signals + new_message.buying_signals)[-20:]
        existing.objections = (existing.objections + new_message.objections)[-10:]
        existing.memory = list({m.key: m for m in existing.memory + new_message.memory}.values())[-50:]

        if new_message.health:
            existing.health = new_message.health

        if new_message.summaries:
            existing.summaries = new_message.summaries

        return existing
