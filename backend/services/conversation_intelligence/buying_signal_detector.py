"""Canonical buying-signal detection and output projections.

Signal definitions remain in the knowledge layer. This module owns the one
matching algorithm and exposes both the legacy and enhanced result shapes.
"""

from __future__ import annotations
from datetime import datetime, timezone
from services.conversation_intelligence.legacy_models import BuyingSignal
from services.conversation_intelligence.intelligence_models import BuyingSignalResult, SignalStrength


def _get_definitions():
    from services.conversation_intelligence.knowledge.buying_signals import BUYING_SIGNAL_DEFINITIONS

    return BUYING_SIGNAL_DEFINITIONS


def detect_signals(message: str) -> list[BuyingSignal]:
    """Return legacy buying-signal models for all matching signal definitions."""
    message_lower = message.lower()
    results: list[BuyingSignal] = []

    for definition in _get_definitions():
        evidence = [keyword for keyword in definition["keywords"] if keyword in message_lower]
        if not evidence:
            continue
        results.append(BuyingSignal(
            signal=definition["name"],
            strength=definition["strength"],
            confidence=min(definition["base_confidence"] + (len(evidence) * 3), 99),
            reason=definition["reason"],
            supporting_evidence=evidence[:3],
        ))

    results.sort(key=lambda signal: signal.confidence, reverse=True)
    return results


def extract_buying_signals(message_body: str, subject: str = "") -> list[BuyingSignalResult]:
    """Extract buying signals from a message.
    Returns structured signals with strength, confidence, and evidence.
    """
    combined = f"{subject} {message_body}" if subject else message_body
    legacy_signals = detect_signals(combined)
    results: list[BuyingSignalResult] = []

    for signal in legacy_signals:
        strength = _map_strength(signal.strength.value)
        results.append(BuyingSignalResult(
            signal_type=signal.signal,
            strength=strength,
            confidence=signal.confidence / 100.0,
            evidence=signal.supporting_evidence,
            timestamp=datetime.now(timezone.utc),
        ))

    return results


def _map_strength(value: str) -> SignalStrength:
    mapping = {
        "very_strong": SignalStrength.VERY_STRONG,
        "strong": SignalStrength.STRONG,
        "medium": SignalStrength.MEDIUM,
        "weak": SignalStrength.WEAK,
        "very_weak": SignalStrength.VERY_WEAK,
    }
    return mapping.get(value, SignalStrength.WEAK)
