"""Buying signal detection.

This module contains ONLY detection logic (wrapping the existing buying_signal module).
No embedded business knowledge — all signal definitions live in KnowledgeRegistry.
"""

from __future__ import annotations
from datetime import datetime, timezone
from services.buying_signal import detect_signals as _detect_signals
from services.conversation_intelligence.intelligence_models import BuyingSignalResult, SignalStrength


def extract_buying_signals(message_body: str, subject: str = "") -> list[BuyingSignalResult]:
    """Extract buying signals from a message.
    Returns structured signals with strength, confidence, and evidence.
    """
    combined = f"{subject} {message_body}" if subject else message_body
    legacy_signals = _detect_signals(combined)
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
