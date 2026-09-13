"""Contract coverage for the legacy sales-stage classification API."""

from services.conversation_intelligence.stage_classifier import classify_stage
from services.conversation_models import BuyingSignal, ConversationStage, SignalStrength


def _signal(name: str, strength: SignalStrength = SignalStrength.STRONG) -> BuyingSignal:
    return BuyingSignal(
        signal=name,
        strength=strength,
        confidence=90,
        reason="test signal",
        supporting_evidence=[name],
    )


def test_classify_stage_preserves_initial_outreach_contract():
    assert classify_stage([], "Hello") == (
        ConversationStage.INITIAL_OUTREACH,
        "No buying signals or stage indicators detected",
    )


def test_classify_stage_preserves_signal_priority_and_reason_contract():
    assert classify_stage(
        [_signal("asked_for_pricing"), _signal("mentioned_procurement")],
        "Could you share a price?",
    ) == (
        ConversationStage.NEGOTIATION,
        "Budget and procurement both mentioned",
    )


def test_classify_stage_preserves_message_pattern_contract():
    assert classify_stage([], "This is not the right time") == (
        ConversationStage.DORMANT,
        "Dormant — no active engagement",
    )
