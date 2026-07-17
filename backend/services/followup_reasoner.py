"""Follow-up Reasoner — recommends next action based on intent, signals, and stage.

Pure deterministic logic. No AI calls.
"""

from services.conversation_models import (
    IntentPrediction, BuyingSignal, ConversationStage,
    FollowupRecommendation, FollowupAction, SignalStrength,
)
from services.conversation_models import IntentCategory


def recommend_followup(
    intents: list[IntentPrediction],
    buying_signals: list[BuyingSignal],
    stage: ConversationStage,
) -> FollowupRecommendation:
    """Recommend next action based on analysis results."""
    intent_values = {i.intent.value for i in intents}
    signal_names = {s.signal for s in buying_signals}
    has_strong_signal = any(s.strength in (SignalStrength.STRONG, SignalStrength.VERY_STRONG) for s in buying_signals)

    # Lost → mark lost
    if stage == ConversationStage.LOST:
        return FollowupRecommendation(
            action=FollowupAction.MARK_LOST,
            priority="high",
            reason="Lead indicated they are not proceeding. Mark as lost and move on.",
            approval_required=True,
        )

    # Out of office → wait
    if IntentCategory.OUT_OF_OFFICE.value in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.WAIT,
            priority="low",
            reason="Lead is out of office. Wait for their return.",
        )

    # Not interested → close
    if IntentCategory.NOT_INTERESTED.value in intent_values or IntentCategory.UNSUBSCRIBE.value in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.CLOSE_CONVERSATION,
            priority="high",
            reason="Lead explicitly indicated no interest. Close the conversation.",
            approval_required=True,
        )

    # Demo request → schedule demo
    if "demo_request" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.SCHEDULE_DEMO,
            priority="high",
            reason="Lead requested a demo. Schedule promptly while interest is high.",
            estimated_value="High — direct pipeline opportunity",
            approval_required=False,
        )

    # Meeting request → schedule meeting
    if "meeting_request" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.SCHEDULE_MEETING,
            priority="high",
            reason="Lead requested a meeting. Book quickly to maintain momentum.",
            estimated_value="Medium — requires qualification",
            approval_required=False,
        )

    # Pricing request → send pricing
    if "pricing_request" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.SEND_PRICING,
            priority="high",
            reason="Lead asked about pricing. Respond with pricing and value proposition.",
            estimated_value="High — pricing request signals active evaluation",
            approval_required=False,
        )

    # Objection detected → answer objection
    if "objection" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.ANSWER_OBJECTION,
            priority="high",
            reason="Lead raised an objection. Address it directly before proceeding.",
            estimated_value="Medium — unblocking objection is critical",
            approval_required=False,
        )

    # Budget concern → answer with value
    if "budget_concern" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.SEND_PRICING,
            priority="high",
            reason="Lead has budget concerns. Respond with pricing and ROI justification.",
            estimated_value="High — budget discussion means active consideration",
            approval_required=False,
        )

    # Technical question → generate technical response
    if "technical_question" in intent_values or "implementation_question" in intent_values:
        if has_strong_signal:
            return FollowupRecommendation(
                action=FollowupAction.GENERATE_TECHNICAL_RESPONSE,
                priority="high",
                reason="Technical questions with strong buying signals indicates serious evaluation.",
                estimated_value="Medium — technical fit is critical",
                approval_required=False,
            )
        return FollowupRecommendation(
            action=FollowupAction.REPLY_IMMEDIATELY,
            priority="medium",
            reason="Lead has technical questions. Respond promptly to support evaluation.",
            estimated_value="Medium — answering technical questions builds trust",
            approval_required=False,
        )

    # Authority concern → escalate to human
    if "authority_concern" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.ESCALATE_TO_HUMAN,
            priority="medium",
            reason="Lead needs to involve others. Escalate to human for multi-stakeholder handling.",
            estimated_value="Medium — requires stakeholder management",
            approval_required=True,
        )

    # Competitor mention → reply with differentiation
    if "competitor_mention" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.REPLY_IMMEDIATELY,
            priority="medium",
            reason="Lead mentioned a competitor. Respond with differentiation.",
            estimated_value="Medium — competitive positioning opportunity",
            approval_required=False,
        )

    # Dormant → nurture
    if stage == ConversationStage.DORMANT:
        return FollowupRecommendation(
            action=FollowupAction.CONTINUE_NURTURING,
            priority="low",
            reason="Lead is dormant. Continue nurturing with relevant content.",
            estimated_value="Low — long-term pipeline building",
            approval_required=False,
        )

    # Positive buying signals → reply immediately
    if has_strong_signal:
        return FollowupRecommendation(
            action=FollowupAction.REPLY_IMMEDIATELY,
            priority="high",
            reason="Strong buying signals detected. Respond while interest peaks.",
            estimated_value="High — act on buying signals promptly",
            approval_required=False,
        )

    # General interest → reply
    if "interested" in intent_values or "need_more_info" in intent_values:
        return FollowupRecommendation(
            action=FollowupAction.REPLY_IMMEDIATELY,
            priority="medium",
            reason="Lead expressed interest or requested more information. Keep the conversation moving.",
            estimated_value="Medium — continue building interest",
            approval_required=False,
        )

    # Engaged stage → continue nurturing
    if stage in (ConversationStage.ENGAGED, ConversationStage.DISCOVERY):
        return FollowupRecommendation(
            action=FollowupAction.REPLY_IMMEDIATELY,
            priority="medium",
            reason="Lead is engaged in discovery. Continue conversation to uncover needs.",
            estimated_value="Medium — progressing lead",
            approval_required=False,
        )

    # Fallback
    return FollowupRecommendation(
        action=FollowupAction.REPLY_IMMEDIATELY,
        priority="medium",
        reason="Respond to keep the conversation moving.",
        estimated_value="Low — standard reply",
        approval_required=False,
    )
