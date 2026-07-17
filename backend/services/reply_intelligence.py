"""Reply Intelligence — aggregates all conversation intelligence into one object.

This is the single source of truth consumed by the rest of Loqi (Copilot, Planner, etc.).
"""

from typing import Optional
from services.conversation_models import (
    ReplyIntelligence, ConversationMessage, IntentPrediction,
    BuyingSignal, ConversationStage, FollowupAction,
    ConversationMemory, FollowupRecommendation,
)
from services.intent_detector import detect_intents
from services.buying_signal import detect_signals
from services.conversation_classifier import classify_stage
from services.conversation_memory import create_or_update_memory
from services.followup_reasoner import recommend_followup
from services.reply_summary import generate_summary
from services.conversation_timeline import create_event
from services.conversation_models import TimelineEventType


def analyze_message(
    message: ConversationMessage,
    conversation_id: str = "",
    existing_memory: Optional[ConversationMemory] = None,
) -> tuple[ReplyIntelligence, ConversationMemory]:
    """Analyze a single message and produce full Reply Intelligence.

    Returns (reply_intelligence, updated_memory).
    """
    cid = conversation_id or message.id

    # 1. Intent detection
    intents = detect_intents(message.text)

    # 2. Buying signal detection
    buying_signals = detect_signals(message.text)

    # 3. Stage classification
    stage, stage_reasoning = classify_stage(buying_signals, message.text)

    # 4. Follow-up recommendation
    recommendation = recommend_followup(intents, buying_signals, stage)

    # 5. Generate summary
    summary = generate_summary(intents, buying_signals, recommendation)

    # 6. Pick top objection
    top_objection = ""
    for intent in intents:
        if intent.intent.value in ("objection", "budget_concern", "timing_concern", "authority_concern"):
            top_objection = intent.reason
            break

    # 7. Compute decision confidence
    decision_confidence = _compute_decision_confidence(buying_signals)

    # 8. Urgency
    urgency = _compute_urgency(intents, buying_signals)

    # 9. Update memory (now receives confidence, urgency, top_objection)
    memory = create_or_update_memory(
        conversation_id=cid,
        message=message,
        intents=intents,
        buying_signals=buying_signals,
        stage=stage,
        stage_reasoning=stage_reasoning,
        followup_action=recommendation.action.value,
        existing_memory=existing_memory,
        decision_confidence=decision_confidence,
        urgency=urgency,
        top_objection=top_objection,
    )

    # 10. Timeline event creation
    _create_timeline_events(cid, intents, buying_signals, stage, message)

    # 11. Key risks
    key_risks = memory.key_risks[:]

    # 12. Key opportunities
    key_opportunities = memory.key_opportunities[:]

    # 13. Suggested workflow objective
    suggested = _map_to_workflow_objective(recommendation.action, intents)

    # 14. Human approval
    human_approval = recommendation.approval_required

    intelligence = ReplyIntelligence(
        conversation_id=cid,
        executive_summary=summary,
        intents=intents,
        buying_signals=buying_signals,
        conversation_stage=stage,
        stage_reasoning=stage_reasoning,
        key_risks=key_risks,
        key_opportunities=key_opportunities,
        top_objection=top_objection,
        decision_confidence=decision_confidence,
        urgency=urgency,
        recommended_next_step=recommendation.action,
        next_step_reasoning=recommendation.reason,
        human_approval_required=human_approval,
        suggested_workflow_objective=suggested,
    )

    return intelligence, memory


def _create_timeline_events(
    cid: str,
    intents: list[IntentPrediction],
    buying_signals: list[BuyingSignal],
    stage: ConversationStage,
    message: ConversationMessage,
) -> None:
    """Create timeline events based on detected intents and signals."""
    create_event(cid, TimelineEventType.LEAD_REPLIED, "Lead replied")

    for intent in intents:
        if intent.intent.value == "pricing_request":
            create_event(cid, TimelineEventType.PRICING_REQUESTED, "Pricing requested")
        elif intent.intent.value == "meeting_request":
            create_event(cid, TimelineEventType.MEETING_REQUESTED, "Meeting requested")
        elif intent.intent.value == "demo_request":
            create_event(cid, TimelineEventType.DEMO_REQUESTED, "Demo requested")
        elif intent.intent.value == "competitor_mention":
            create_event(cid, TimelineEventType.COMPETITOR_MENTIONED, "Competitor mentioned")
        elif intent.intent.value in ("budget_concern",):
            create_event(cid, TimelineEventType.BUDGET_DISCUSSED, "Budget discussed")
        elif intent.intent.value in ("timing_concern",):
            create_event(cid, TimelineEventType.TIMELINE_DISCUSSED, "Timeline discussed")

    for signal in buying_signals:
        if signal.strength.value in ("very_strong", "strong"):
            create_event(cid, TimelineEventType.POSITIVE_BUYING_SIGNAL, signal.reason)

    if stage == ConversationStage.LOST:
        create_event(cid, TimelineEventType.LOST_OPPORTUNITY, "Opportunity lost")
    elif stage == ConversationStage.WON:
        create_event(cid, TimelineEventType.WON_DEAL, "Deal won")
    elif stage == ConversationStage.DORMANT:
        create_event(cid, TimelineEventType.DORMANT_PERIOD, "Lead went dormant")


def _compute_decision_confidence(buying_signals: list[BuyingSignal]) -> int:
    """Compute decision confidence (0-100) from buying signals."""
    if not buying_signals:
        return 0
    strengths = [s.strength.value for s in buying_signals]
    score = 0
    if "very_strong" in strengths:
        score += 40
    if "strong" in strengths:
        score += 25
    if "medium" in strengths:
        score += 15
    if "weak" in strengths:
        score += 5
    count_bonus = min(len(buying_signals) * 5, 20)
    score = min(score + count_bonus, 95)
    return score


def _compute_urgency(intents: list[IntentPrediction], buying_signals: list[BuyingSignal]) -> str:
    """Compute overall urgency."""
    intent_values = {i.intent.value for i in intents}
    if "meeting_request" in intent_values or "demo_request" in intent_values:
        return "high"
    if "pricing_request" in intent_values:
        return "high"
    if "budget_concern" in intent_values:
        return "medium"
    if any(s.strength.value in ("very_strong", "strong") for s in buying_signals):
        return "medium"
    if "timing_concern" in intent_values:
        return "low"
    return "medium"


def _map_to_workflow_objective(action: FollowupAction, intents: list[IntentPrediction]) -> str:
    """Map follow-up action to a workflow objective the Planner can consume."""
    mapping = {
        FollowupAction.SEND_PRICING: "Generate Pricing Email",
        FollowupAction.GENERATE_TECHNICAL_RESPONSE: "Prepare Technical Reply",
        FollowupAction.SCHEDULE_DEMO: "Schedule Demo",
        FollowupAction.SCHEDULE_MEETING: "Book Meeting",
        FollowupAction.ANSWER_OBJECTION: "Answer Security Questions",
        FollowupAction.REPLY_IMMEDIATELY: "Create Follow-up Sequence",
        FollowupAction.ESCALATE_TO_HUMAN: "Escalate to Human",
        FollowupAction.CONTINUE_NURTURING: "Create Follow-up Sequence",
        FollowupAction.CLOSE_CONVERSATION: "Close Conversation",
        FollowupAction.MARK_LOST: "Mark Lost",
        FollowupAction.WAIT: "Create Follow-up Sequence",
    }
    return mapping.get(action, "Create Follow-up Sequence")
