"""Buying Signal Detection — analyses messages for purchase intent signals.

Signal strength uses human labels (Very Weak → Very Strong).
All signal definitions come from the centralized Knowledge Layer.
"""

from services.conversation_models import BuyingSignal


def _get_definitions():
    from services.conversation_intelligence.knowledge.buying_signals import BUYING_SIGNAL_DEFINITIONS
    return BUYING_SIGNAL_DEFINITIONS


def detect_signals(message: str) -> list[BuyingSignal]:
    """Analyze a message for buying signals, returning all detected signals."""
    ml = message.lower()
    results: list[BuyingSignal] = []

    for definition in _get_definitions():
        name = definition["name"]
        patterns = definition["keywords"]
        strength = definition["strength"]
        reason = definition["reason"]
        base_conf = definition["base_confidence"]

        evidence = [p for p in patterns if p in ml]
        if evidence:
            confidence = min(base_conf + (len(evidence) * 3), 99)
            results.append(BuyingSignal(
                signal=name,
                strength=strength,
                confidence=confidence,
                reason=reason,
                supporting_evidence=evidence[:3],
            ))

    results.sort(key=lambda x: x.confidence, reverse=True)
    return results
