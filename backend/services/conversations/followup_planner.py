"""Follow-up Planner architecture.

Provider-independent planning layer.
Determines whether, when, and how to follow up.
Does NOT generate responses — only planning.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from services.conversations.conversation_models import Conversation, ConversationStatus, ReplyCategory


class FollowUpPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class FollowUpObjective(str, Enum):
    REENGAGE = "reengage"
    ANSWER_QUESTION = "answer_question"
    PROVIDE_PRICING = "provide_pricing"
    SCHEDULE_MEETING = "schedule_meeting"
    CONFIRM_INTEREST = "confirm_interest"
    OVERCOME_OBJECTION = "overcome_objection"
    CHECK_IN = "check_in"
    NUDGE = "nudge"


@dataclass
class FollowUpPlan:
    should_follow_up: bool = False
    priority: FollowUpPriority = FollowUpPriority.NONE
    objective: Optional[FollowUpObjective] = None
    suggested_timing: Optional[datetime] = None
    suggested_template: str = ""
    reason: str = ""
    confidence: float = 0.0
    context: dict = field(default_factory=dict)


class BaseFollowUpPlanner:
    """Abstract base for follow-up planners."""

    def plan(self, conversation: Conversation, context: dict = None) -> FollowUpPlan:
        raise NotImplementedError


class DefaultFollowUpPlanner(BaseFollowUpPlanner):
    """Rule-based follow-up planner.
    Serves as the default until AI planning is integrated.
    """

    def plan(self, conversation: Conversation, context: dict = None) -> FollowUpPlan:
        status = conversation.status
        now = datetime.now(timezone.utc)
        days_since_activity = (now - conversation.last_activity_at).days if conversation.last_activity_at else 0

        if status == ConversationStatus.SENT:
            if days_since_activity >= 3:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.MEDIUM,
                    objective=FollowUpObjective.CHECK_IN,
                    suggested_timing=now + timedelta(days=1),
                    reason="Sent but no engagement yet. Follow up to re-engage.",
                    confidence=0.6,
                )

        elif status == ConversationStatus.OPENED:
            if days_since_activity >= 2:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.HIGH,
                    objective=FollowUpObjective.REENGAGE,
                    suggested_timing=now + timedelta(hours=12),
                    reason="Prospect opened the email but didn't reply. Strike while interest is warm.",
                    confidence=0.7,
                )

        elif status == ConversationStatus.REPLIED:
            last_reply_class = conversation.metadata.get("last_reply_category", "")
            if last_reply_class == ReplyCategory.QUESTION.value:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.HIGH,
                    objective=FollowUpObjective.ANSWER_QUESTION,
                    suggested_timing=now + timedelta(hours=4),
                    reason="Prospect asked a question. Respond promptly.",
                    confidence=0.9,
                )
            elif last_reply_class == ReplyCategory.PRICING_REQUEST.value:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.HIGH,
                    objective=FollowUpObjective.PROVIDE_PRICING,
                    suggested_timing=now + timedelta(hours=4),
                    reason="Prospect requested pricing information. Provide details.",
                    confidence=0.9,
                )
            elif last_reply_class == ReplyCategory.MEETING_REQUEST.value:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.HIGH,
                    objective=FollowUpObjective.SCHEDULE_MEETING,
                    suggested_timing=now + timedelta(hours=2),
                    reason="Prospect requested a meeting. Schedule promptly.",
                    confidence=0.9,
                )
            elif last_reply_class == ReplyCategory.INTERESTED.value:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.HIGH,
                    objective=FollowUpObjective.CONFIRM_INTEREST,
                    suggested_timing=now + timedelta(hours=24),
                    reason="Prospect expressed interest. Nurture the lead.",
                    confidence=0.8,
                )
            else:
                if days_since_activity >= 5:
                    return FollowUpPlan(
                        should_follow_up=True,
                        priority=FollowUpPriority.MEDIUM,
                        objective=FollowUpObjective.REENGAGE,
                        suggested_timing=now + timedelta(days=2),
                        reason="Last reply was some time ago. Check in.",
                        confidence=0.5,
                    )

        elif status == ConversationStatus.FOLLOW_UP_SENT:
            if days_since_activity >= 5:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.LOW,
                    objective=FollowUpObjective.NUDGE,
                    suggested_timing=now + timedelta(days=3),
                    reason="Follow-up sent but no response. One more nudge before closing.",
                    confidence=0.4,
                )

        elif status == ConversationStatus.INTERESTED:
            if days_since_activity >= 7:
                return FollowUpPlan(
                    should_follow_up=True,
                    priority=FollowUpPriority.MEDIUM,
                    objective=FollowUpObjective.CHECK_IN,
                    suggested_timing=now + timedelta(days=3),
                    reason="Interested but quiet. Check in to keep momentum.",
                    confidence=0.6,
                )

        return FollowUpPlan(
            should_follow_up=False,
            priority=FollowUpPriority.NONE,
            reason="No follow-up needed at this time.",
            confidence=1.0,
        )


class FollowUpPlannerService:
    def __init__(self):
        self._default_planner = DefaultFollowUpPlanner()
        self._ai_planner: Optional[BaseFollowUpPlanner] = None

    def register_ai_planner(self, planner: BaseFollowUpPlanner) -> None:
        self._ai_planner = planner

    def plan(self, conversation: Conversation, context: dict = None) -> FollowUpPlan:
        if self._ai_planner:
            try:
                result = self._ai_planner.plan(conversation, context)
                if result.confidence >= 0.5:
                    return result
            except Exception:
                pass
        return self._default_planner.plan(conversation, context)


followup_planner_service = FollowUpPlannerService()
