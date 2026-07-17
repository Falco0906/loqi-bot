"""Communication Intelligence — strongly typed Pydantic models.

Provider-agnostic. These models never know where the message came from.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4
from pydantic import BaseModel


class IntentCategory(str, Enum):
    INTERESTED = "interested"
    PRICING_REQUEST = "pricing_request"
    MEETING_REQUEST = "meeting_request"
    DEMO_REQUEST = "demo_request"
    TECHNICAL_QUESTION = "technical_question"
    IMPLEMENTATION_QUESTION = "implementation_question"
    COMPETITOR_MENTION = "competitor_mention"
    OBJECTION = "objection"
    BUDGET_CONCERN = "budget_concern"
    TIMING_CONCERN = "timing_concern"
    AUTHORITY_CONCERN = "authority_concern"
    NEED_MORE_INFO = "need_more_info"
    REFERRAL = "referral"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"
    FOLLOW_UP_LATER = "follow_up_later"
    POSITIVE_FEEDBACK = "positive_feedback"
    NEGATIVE_FEEDBACK = "negative_feedback"
    GENERAL_QUESTION = "general_question"


class SignalStrength(str, Enum):
    VERY_WEAK = "very_weak"
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class ConversationStage(str, Enum):
    INITIAL_OUTREACH = "initial_outreach"
    ENGAGED = "engaged"
    DISCOVERY = "discovery"
    EVALUATION = "evaluation"
    NEGOTIATION = "negotiation"
    DECISION = "decision"
    WON = "won"
    LOST = "lost"
    DORMANT = "dormant"


class FollowupAction(str, Enum):
    REPLY_IMMEDIATELY = "reply_immediately"
    WAIT = "wait"
    SCHEDULE_DEMO = "schedule_demo"
    SCHEDULE_MEETING = "schedule_meeting"
    SEND_PRICING = "send_pricing"
    ANSWER_OBJECTION = "answer_objection"
    GENERATE_TECHNICAL_RESPONSE = "generate_technical_response"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    CLOSE_CONVERSATION = "close_conversation"
    MARK_LOST = "mark_lost"
    CONTINUE_NURTURING = "continue_nurturing"


class TimelineEventType(str, Enum):
    LEAD_REPLIED = "lead_replied"
    PRICING_REQUESTED = "pricing_requested"
    MEETING_REQUESTED = "meeting_requested"
    COMPETITOR_MENTIONED = "competitor_mentioned"
    POSITIVE_BUYING_SIGNAL = "positive_buying_signal"
    STRONG_OBJECTION = "strong_objection"
    BUDGET_DISCUSSED = "budget_discussed"
    TIMELINE_DISCUSSED = "timeline_discussed"
    DECISION_MAKER_MENTIONED = "decision_maker_mentioned"
    FOLLOWUP_RECOMMENDED = "followup_recommended"
    STAGE_CHANGED = "stage_changed"
    OBJECTION_ANSWERED = "objection_answered"
    DEMO_REQUESTED = "demo_requested"
    MEETING_SCHEDULED = "meeting_scheduled"
    PROPOSAL_REQUESTED = "proposal_requested"
    CASE_STUDY_REQUESTED = "case_study_requested"
    COMPETITIVE_SITUATION = "competitive_situation"
    LOST_OPPORTUNITY = "lost_opportunity"
    WON_DEAL = "won_deal"
    DORMANT_PERIOD = "dormant_period"


class ConversationMessage(BaseModel):
    id: str = ""
    text: str
    sender: str = ""  # "lead" | "agent" | "system"
    timestamp: str = ""
    subject: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:8]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class IntentPrediction(BaseModel):
    intent: IntentCategory
    confidence: int  # 0-100
    reason: str
    supporting_evidence: list[str] = []


class BuyingSignal(BaseModel):
    signal: str
    strength: SignalStrength
    confidence: int  # 0-100
    reason: str
    supporting_evidence: list[str] = []


class ConversationSummary(BaseModel):
    executive_summary: str
    key_topics: list[str] = []
    lead_sentiment: str = ""  # positive | neutral | negative | mixed


class FollowupRecommendation(BaseModel):
    action: FollowupAction
    priority: str  # high | medium | low
    reason: str
    estimated_value: str = ""
    approval_required: bool = False


class ConversationTimelineEvent(BaseModel):
    event_type: TimelineEventType
    message: str
    timestamp: str = ""
    metadata: dict = {}

    def model_post_init(self, __context) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ConversationMemory(BaseModel):
    conversation_id: str = ""
    current_stage: ConversationStage = ConversationStage.INITIAL_OUTREACH
    summary: str = ""
    open_questions: list[str] = []
    outstanding_objections: list[str] = []
    pain_points: list[str] = []
    business_goals: list[str] = []
    competitor_mentioned: str = ""
    decision_makers: list[str] = []
    buying_signals: list[str] = []
    last_recommendation: str = ""
    last_followup: str = ""
    promised_actions: list[str] = []
    preferred_communication_style: str = ""
    key_risks: list[str] = []
    key_opportunities: list[str] = []
    urgency: str = ""  # low | medium | high | urgent
    decision_confidence: int = 0  # 0-100
    top_objection: str = ""

    def model_post_init(self, __context) -> None:
        if not self.conversation_id:
            self.conversation_id = str(uuid4())[:8]


class ReplyIntelligence(BaseModel):
    conversation_id: str = ""
    executive_summary: str = ""
    intents: list[IntentPrediction] = []
    buying_signals: list[BuyingSignal] = []
    conversation_stage: ConversationStage = ConversationStage.INITIAL_OUTREACH
    stage_reasoning: str = ""
    key_risks: list[str] = []
    key_opportunities: list[str] = []
    top_objection: str = ""
    decision_confidence: int = 0
    urgency: str = ""
    recommended_next_step: FollowupAction = FollowupAction.REPLY_IMMEDIATELY
    next_step_reasoning: str = ""
    human_approval_required: bool = False
    suggested_workflow_objective: str = ""

    def model_post_init(self, __context) -> None:
        if not self.conversation_id:
            self.conversation_id = str(uuid4())[:8]
