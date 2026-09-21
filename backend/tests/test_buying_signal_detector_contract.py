"""Characterization tests for the shared buying-signal detector outputs."""

from services.conversation_intelligence.buying_signal_detector import detect_signals
from services.conversation_intelligence.buying_signal_detector import extract_buying_signals


MESSAGE = "What's the pricing and how long does implementation take?"


def test_legacy_buying_signal_shape_and_order_are_preserved():
    signals = detect_signals(MESSAGE)

    assert [signal.signal for signal in signals] == [
        "asked_for_pricing",
        "asked_implementation_timeline",
    ]
    assert [signal.strength.value for signal in signals] == ["very_strong", "strong"]
    assert [signal.confidence for signal in signals] == [98, 86]
    assert signals[0].supporting_evidence == ["pricing"]
    assert signals[1].supporting_evidence == ["implement", "how long"]


def test_enhanced_buying_signal_projection_preserves_legacy_detection():
    signals = extract_buying_signals(MESSAGE)

    assert [signal.signal_type for signal in signals] == [
        "asked_for_pricing",
        "asked_implementation_timeline",
    ]
    assert [signal.strength.value for signal in signals] == ["very_strong", "strong"]
    assert [signal.confidence for signal in signals] == [0.98, 0.86]
    assert [signal.evidence for signal in signals] == [
        ["pricing"],
        ["implement", "how long"],
    ]
    assert all(signal.timestamp is not None for signal in signals)
