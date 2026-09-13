"""Contract coverage for the legacy communication executive-summary formatter."""

from services.communication.reply_summary import generate_summary
from services.conversation_models import (
    BuyingSignal,
    FollowupAction,
    FollowupRecommendation,
    IntentCategory,
    IntentPrediction,
    SignalStrength,
)


def _recommendation(*, priority: str = "medium") -> FollowupRecommendation:
    return FollowupRecommendation(
        action=FollowupAction.SEND_PRICING,
        priority=priority,
        reason="test recommendation",
    )


def test_generate_summary_preserves_empty_analysis_wording():
    assert generate_summary([], [], _recommendation()) == (
        "Message received. No significant intent or buying signals detected."
    )


def test_generate_summary_preserves_high_priority_signal_wording_and_order():
    result = generate_summary(
        [
            IntentPrediction(
                intent=IntentCategory.PRICING_REQUEST,
                confidence=95,
                reason="pricing requested",
                supporting_evidence=["What does this cost?"],
            )
        ],
        [
            BuyingSignal(
                signal="asked_for_pricing",
                strength=SignalStrength.STRONG,
                confidence=95,
                reason="Asked For Pricing",
                supporting_evidence=["What does this cost?"],
            ),
            BuyingSignal(
                signal="mentioned_budget",
                strength=SignalStrength.VERY_STRONG,
                confidence=90,
                reason="Budget mentioned",
                supporting_evidence=["budget"],
            ),
        ],
        _recommendation(priority="high"),
    )

    assert result == (
        "Lead is actively evaluating the product. "
        "Primary concern: asked for pricing "
        "Strong buying intent shown through 2 signals. "
        "Recommended action: Send Pricing today."
    )


def test_generate_summary_preserves_opt_out_wording():
    result = generate_summary(
        [
            IntentPrediction(
                intent=IntentCategory.UNSUBSCRIBE,
                confidence=100,
                reason="requested opt out",
                supporting_evidence=["unsubscribe"],
            )
        ],
        [],
        _recommendation(),
    )

    assert result == (
        "Lead is not interested or has opted out. "
        "Recommended action: Send Pricing."
    )
