"""Characterization tests for the shared intent detector outputs."""

from services.conversation_intelligence.intent_extractor import extract_intents
from services.conversation_intelligence.intent_extractor import detect_intents


MESSAGE = "How much does this cost? I want a demo"


def test_legacy_intent_shape_order_and_top_n_are_preserved():
    intents = detect_intents(MESSAGE, top_n=5)

    assert [intent.intent.value for intent in intents] == [
        "pricing_request",
        "demo_request",
    ]
    assert [intent.confidence for intent in intents] == [95, 90]
    assert intents[0].supporting_evidence == ["cost", "how much"]
    assert intents[1].supporting_evidence == ["demo"]
    assert [intent.intent.value for intent in detect_intents(MESSAGE, top_n=1)] == [
        "pricing_request",
    ]


def test_enhanced_intent_projection_preserves_legacy_detection():
    intents = extract_intents(MESSAGE)

    assert [intent.label.value for intent in intents] == [
        "pricing_discussion",
        "demo_request",
    ]
    assert [intent.confidence for intent in intents] == [0.95, 0.9]
    assert [intent.evidence for intent in intents] == [
        ["cost", "how much"],
        ["demo"],
    ]
    assert all(intent.source == "rule" for intent in intents)
