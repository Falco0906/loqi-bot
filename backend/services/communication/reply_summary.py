"""Reply Summary — generates concise executive summaries of conversation analysis.

Designed for Mission Control dashboards and Copilot awareness.
"""

from services.conversation_models import (
    IntentPrediction, BuyingSignal, FollowupRecommendation,
    SignalStrength,
)


def generate_summary(
    intents: list[IntentPrediction],
    buying_signals: list[BuyingSignal],
    recommendation: FollowupRecommendation,
) -> str:
    """Generate a concise executive summary of the conversation analysis.

    Designed for quick scan by SDRs and Copilot.
    """
    parts = []

    if not intents and not buying_signals:
        return "Message received. No significant intent or buying signals detected."

    # Lead status
    has_strong_buying = any(s.strength in (SignalStrength.STRONG, SignalStrength.VERY_STRONG) for s in buying_signals)
    has_weak = any(s.strength == SignalStrength.VERY_WEAK for s in buying_signals)
    not_interested = any(i.intent.value in ("not_interested", "unsubscribe") for i in intents)

    if not_interested:
        parts.append("Lead is not interested or has opted out.")
    elif has_strong_buying:
        parts.append("Lead is actively evaluating the product.")
    elif has_weak:
        parts.append("Lead has shown minimal engagement.")
    elif intents:
        top = intents[0]
        parts.append(f"Lead expressed {top.intent.value.replace('_', ' ')}.")

    # Primary intent detail
    top_signal = buying_signals[0] if buying_signals else None
    if top_signal:
        parts.append(f"Primary concern: {top_signal.reason.lower()}")

    # Buying intent
    if has_strong_buying:
        count = sum(1 for s in buying_signals if s.strength in (SignalStrength.STRONG, SignalStrength.VERY_STRONG))
        parts.append(f"Strong buying intent shown through {count} signal{'s' if count > 1 else ''}.")

    # Decision confidence
    if top_signal:
        if top_signal.strength in (SignalStrength.STRONG, SignalStrength.VERY_STRONG):
            pass  # already covered
        elif top_signal.strength == SignalStrength.MEDIUM:
            parts.append("Moderate buying interest detected.")
        else:
            parts.append("Early stage — minimal buying signals.")

    # Recommended action
    action_label = recommendation.action.value.replace("_", " ").title()
    if recommendation.priority == "high":
        parts.append(f"Recommended action: {action_label} today.")
    else:
        parts.append(f"Recommended action: {action_label}.")

    return " ".join(parts)
