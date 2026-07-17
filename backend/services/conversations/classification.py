"""Reply classification architecture.

AI-independent classification layer.
The classifier produces a category with confidence scores.
AI integration plugs in here without changing the calling code.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from services.conversations.conversation_models import ReplyCategory


@dataclass
class ClassificationResult:
    category: ReplyCategory
    confidence: float = 0.0
    alternative_categories: list[tuple[ReplyCategory, float]] = field(default_factory=list)
    source: str = "rule"
    explanation: str = ""
    raw_response: dict = field(default_factory=dict)


class BaseClassifier:
    """Abstract base for reply classifiers.
    Subclasses implement either rule-based or AI-based classification.
    """

    def classify(self, message_body: str, subject: str = "", context: dict = None) -> ClassificationResult:
        raise NotImplementedError


class RuleClassifier(BaseClassifier):
    """Rule-based classifier using keyword/pattern matching.
    Serves as the fallback when AI is unavailable.
    """

    def __init__(self):
        self._rules: list[tuple[list[str], ReplyCategory, float]] = [
            # Interest signals
            (["interested", "looks great", "sign me up", "let's do it", "sounds good",
              "tell me more", "yes please"], ReplyCategory.INTERESTED, 0.7),
            # Not interested
            (["not interested", "unsubscribe", "stop emailing", "remove me",
              "don't contact", "not relevant", "no thanks"], ReplyCategory.NOT_INTERESTED, 0.8),
            # Questions
            (["how", "what", "when", "where", "why", "could you", "can you",
              "would you", "tell me about"], ReplyCategory.QUESTION, 0.5),
            # Pricing
            (["pricing", "price", "cost", "how much", "budget", "quote",
              "rates", "pricing page"], ReplyCategory.PRICING_REQUEST, 0.7),
            # Meeting requests
            (["meeting", "demo", "calendar", "schedule", "book", "call",
              "discuss further", "hop on a call", "zoom"], ReplyCategory.MEETING_REQUEST, 0.7),
            # Referrals
            (["refer", "colleague", "team member", "also interested",
              "forward"], ReplyCategory.REFERRAL, 0.5),
            # Out of office
            (["out of office", "vacation", "on leave", "away from",
              "will be back", "ooo", "not in the office"], ReplyCategory.OUT_OF_OFFICE, 0.9),
            # Bounce detection
            (["address rejected", "mailbox not found", "invalid", "undeliverable",
              "550", "permanently rejected", "no such user",
              "mailbox unavailable"], ReplyCategory.BOUNCE, 0.9),
            # Auto-reply
            (["auto-reply", "automatic reply", "automated response",
              "this is an automatic", "auto response"], ReplyCategory.AUTO_REPLY, 0.8),
        ]

    def classify(self, message_body: str, subject: str = "", context: dict = None) -> ClassificationResult:
        body_lower = (message_body or "").lower()
        subject_lower = (subject or "").lower()
        combined = f"{subject_lower} {body_lower}"

        best_category = ReplyCategory.UNKNOWN
        best_score = 0.0
        alternatives: list[tuple[ReplyCategory, float]] = []

        for keywords, category, base_confidence in self._rules:
            match_count = sum(1 for kw in keywords if kw in combined)
            if match_count > 0:
                confidence = base_confidence * min(1.0, match_count / 2)
                if confidence > best_score:
                    if best_score > 0:
                        alternatives.append((best_category, best_score))
                    best_score = confidence
                    best_category = category
                else:
                    alternatives.append((category, confidence))

        return ClassificationResult(
            category=best_category,
            confidence=best_score,
            alternative_categories=sorted(alternatives, key=lambda x: -x[1])[:3],
            source="rule",
        )


class ClassifierService:
    """Orchestrates classification with fallback chain.
    Future: try AI first, fall back to rules.
    """

    def __init__(self):
        self._rule_classifier = RuleClassifier()
        self._ai_classifier: Optional[BaseClassifier] = None

    def register_ai_classifier(self, classifier: BaseClassifier) -> None:
        self._ai_classifier = classifier

    def classify(self, message_body: str, subject: str = "", context: dict = None) -> ClassificationResult:
        if self._ai_classifier:
            try:
                result = self._ai_classifier.classify(message_body, subject, context)
                if result.confidence >= 0.5:
                    return result
            except Exception:
                pass
        return self._rule_classifier.classify(message_body, subject, context)


classifier_service = ClassifierService()
