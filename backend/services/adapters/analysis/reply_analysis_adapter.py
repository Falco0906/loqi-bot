from __future__ import annotations

import json
import logging
from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult

logger = logging.getLogger(__name__)

REPLY_ANALYSIS_METADATA = AdapterMetadata(
    name="reply_analysis",
    display_name="Reply Analysis Adapter",
    version="1.0.0",
    description="Classifies inbound email replies into structured categories. "
    "Uses AI to determine reply sentiment, intent, and required action.",
    author="Loqi",
    supported_operations=("analyze_reply",),
    requires_auth=False,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("analysis", "reply", "classification"),
)

CLASSIFICATION_SYSTEM_PROMPT = """You are a reply classification system. Analyze the email reply below and classify it into exactly one of the following categories:

- POSITIVE: The recipient is interested, engaged, or providing favorable feedback.
- NEGATIVE: The recipient is dissatisfied, complaining, or expressing frustration.
- QUESTION: The recipient is asking a question that needs an answer.
- OBJECTION: The recipient is raising a concern or objection about pricing, timing, or fit.
- OUT_OF_OFFICE: Automatic out-of-office / vacation auto-reply.
- AUTO_REPLY: Automated response (e.g. "I'll get back to you soon", "Thank you for your email").
- UNSUBSCRIBE: The recipient explicitly asks to stop receiving emails.
- NOT_INTERESTED: The recipient is not interested in the offering.
- MEETING_ACCEPTED: The recipient accepted a meeting invitation.
- MEETING_DECLINED: The recipient declined a meeting invitation.

Respond in JSON format with these fields:
- "category": the category name as uppercase string
- "confidence": a float between 0.0 and 1.0
- "summary": a one-sentence explanation of why this classification was chosen
- "suggested_action": one of "reply", "wait", "escalate", "terminate", "schedule", "none"
- "extracted_entities": any relevant entities found (dates, names, etc.), as an object

Return ONLY the JSON object, no other text."""


class ReplyAnalysisAdapter(ExecutionAdapter):
    """Classifies inbound email replies using AI.

    Reads ``reply_text`` from ``context.params``, classifies the reply
    into a structured category, and returns the result as adapter output
    data.
    """

    @property
    def metadata(self) -> AdapterMetadata:
        return REPLY_ANALYSIS_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        reply_text = context.params.get("reply_text", "")
        subject = context.params.get("subject", "")
        from_address = context.params.get("from_address", "")

        if not reply_text:
            return AdapterResult.failure_result(
                error="Missing required param 'reply_text'",
                metadata={"error_type": "ValidationError"},
            )

        try:
            analysis = await self._classify(reply_text, subject, from_address)
            return AdapterResult.success_result(
                data={
                    "category": analysis["category"],
                    "confidence": analysis["confidence"],
                    "summary": analysis["summary"],
                    "suggested_action": analysis["suggested_action"],
                    "extracted_entities": analysis.get("extracted_entities", {}),
                    "original_reply": reply_text,
                },
                metadata={"analysis_provider": "openai"},
            )
        except Exception as e:
            logger.error("Reply analysis failed: %s", e, exc_info=True)
            return AdapterResult.failure_result(
                error=f"Reply analysis failed: {e}",
                metadata={"error_type": "AnalysisError"},
            )

    async def _classify(
        self,
        reply_text: str,
        subject: str,
        from_address: str,
    ) -> dict[str, Any]:
        """Call OpenAI to classify the reply text."""
        from services.ai import _send_openai_request, OpenAIError

        user_text = f"From: {from_address}\nSubject: {subject}\n\nBody:\n{reply_text}"
        raw = _send_openai_request(CLASSIFICATION_SYSTEM_PROMPT, user_text)

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse AI response as JSON: %s", raw[:200])
            parsed = self._fallback_classification(reply_text)

        # Validate required fields
        category = str(parsed.get("category", "UNKNOWN")).upper()
        if category not in _VALID_CATEGORIES:
            category = "UNKNOWN"

        return {
            "category": category,
            "confidence": float(parsed.get("confidence", 0.0)),
            "summary": str(parsed.get("summary", "")),
            "suggested_action": str(parsed.get("suggested_action", "none")),
            "extracted_entities": parsed.get("extracted_entities", {}),
        }

    @staticmethod
    def _fallback_classification(text: str) -> dict[str, Any]:
        """Simple heuristic fallback when AI response is unparseable."""
        lower = text.lower()
        if any(w in lower for w in ["unsubscribe", "stop sending", "remove me"]):
            return {"category": "UNSUBSCRIBE", "confidence": 0.7, "summary": "Unsubscribe request detected", "suggested_action": "terminate"}
        if any(w in lower for w in ["out of office", "vacation", "away from"]):
            return {"category": "OUT_OF_OFFICE", "confidence": 0.7, "summary": "Out-of-office auto-reply", "suggested_action": "wait"}
        if any(w in lower for w in ["not interested", "no thanks", "stop contacting"]):
            return {"category": "NOT_INTERESTED", "confidence": 0.6, "summary": "Recipient declined interest", "suggested_action": "terminate"}
        return {"category": "UNKNOWN", "confidence": 0.3, "summary": "Unable to classify", "suggested_action": "reply"}


_VALID_CATEGORIES = frozenset({
    "POSITIVE", "NEGATIVE", "QUESTION", "OBJECTION",
    "OUT_OF_OFFICE", "AUTO_REPLY", "UNSUBSCRIBE",
    "NOT_INTERESTED", "MEETING_ACCEPTED", "MEETING_DECLINED",
    "UNKNOWN",
})
