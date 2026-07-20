from __future__ import annotations

from typing import Any

from services.planner.planning_models import (
    ApprovalRequirement,
    PlanGoal,
    Task,
    TaskType,
)
from services.planner.payloads import (
    CreateEventPayload,
    EscalatePayload,
    MessagePayload,
    UpdateCRMPayload,
    WaitDurationPayload,
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    Strategy,
    SchedulingHints,
)


class FollowUpV2Strategy(Strategy):
    """Plans the next action based on a reply analysis result.

    Input (via context):
      - reply_analysis: dict with category, confidence, suggested_action
      - conversation_id: the ongoing thread identifier
      - campaign_context: campaign metadata (optional)
      - thread_id, in_reply_to_message_id: for thread-aware replies
    """

    _ID_REPLY = "fuv2_reply"
    _ID_ESCALATE = "fuv2_escalate"
    _ID_WAIT = "fuv2_wait"
    _ID_TERMINATE = "fuv2_terminate"
    _ID_CALENDAR = "fuv2_calendar"
    _ID_ANALYZE = "fuv2_analyze"

    @property
    def name(self) -> str:
        return "adaptive_follow_up"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("handle_reply", "follow_up_reply", "manage_conversation"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "reply" in outcome_lower or "follow-up" in outcome_lower:
            return 0.8
        if "meeting accepted" in outcome_lower or "meeting declined" in outcome_lower:
            return 0.9
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        analysis = context.get("reply_analysis", {})
        category = (analysis.get("category") or "").upper()
        suggested_action = (analysis.get("suggested_action") or "").lower()

        thread_id = context.get("thread_id", "")
        in_reply_to = context.get("in_reply_to_message_id", "")
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        # Routing based on reply category
        route_map = {
            "POSITIVE": self._route_positive,
            "QUESTION": self._route_question,
            "OBJECTION": self._route_objection,
            "NEGATIVE": self._route_negative,
            "OUT_OF_OFFICE": self._route_ooo,
            "AUTO_REPLY": self._route_auto,
            "UNSUBSCRIBE": self._route_terminate,
            "NOT_INTERESTED": self._route_terminate,
            "MEETING_ACCEPTED": self._route_meeting_accepted,
            "MEETING_DECLINED": self._route_meeting_declined,
        }

        handler = route_map.get(category, self._route_default)
        tasks = handler(prospect, company, thread_id, in_reply_to, analysis, context)

        # Apply thread params to all SEND_EMAIL / SEND_MESSAGE tasks
        if thread_id:
            for t in tasks:
                if t.type in (TaskType.SEND_EMAIL, TaskType.SEND_MESSAGE):
                    t.params["thread_id"] = thread_id
                    if in_reply_to:
                        t.params["in_reply_to_message_id"] = in_reply_to

        return tasks

    def _route_positive(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Positive reply: schedule a meeting and confirm."""
        return [
            Task(
                id=self._ID_CALENDAR,
                type=TaskType.CALENDAR_CREATE_EVENT,
                label=f"Schedule meeting with {prospect}",
                instructions=f"Create a calendar event for {prospect} at {company}. "
                            f"Use the positive context from their reply to suggest times.",
                payload=CreateEventPayload(
                    summary=f"Meeting with {prospect}" + (f" - {company}" if company else ""),
                    description=analysis.get("summary", ""),
                ),
                approval=ApprovalRequirement.RECOMMENDED,
                reasoning_trace="Adaptive follow-up: positive reply → schedule meeting",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_question(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Question: answer and wait for follow-up."""
        return [
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Answer {prospect}'s question",
                instructions=f"Answer {prospect}'s question about {company}. "
                            f"Their message: {analysis.get('summary', '')}",
                payload=MessagePayload(channel="email", template="reply_answer"),
                reasoning_trace="Adaptive follow-up: question → answer then wait",
                reasoning_goal="handle_reply",
            ),
            Task(
                id=self._ID_ANALYZE,
                type=TaskType.ANALYZE_REPLY,
                label=f"Wait for {prospect}'s follow-up reply",
                instructions=f"Analyze {prospect}'s next reply to see if their question was answered.",
                params={"reason": f"Follow-up to answered question from {prospect}"},
                reasoning_trace="Adaptive follow-up: await next reply after answer",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_objection(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Objection: address concern and re-analyze."""
        return [
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Address {prospect}'s objection",
                instructions=f"Address {prospect}'s objection about {company}. "
                            f"Use the objection context: {analysis.get('summary', '')}",
                payload=MessagePayload(channel="email", template="objection_response"),
                approval=ApprovalRequirement.RECOMMENDED,
                reasoning_trace="Adaptive follow-up: objection → address concern",
                reasoning_goal="handle_reply",
            ),
            Task(
                id=self._ID_ANALYZE,
                type=TaskType.ANALYZE_REPLY,
                label=f"Analyze {prospect}'s response to objection",
                instructions=f"Check if {prospect}'s objection was resolved.",
                params={"reason": f"Objection response follow-up for {prospect}"},
                reasoning_trace="Adaptive follow-up: check objection resolution",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_negative(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Negative reply: escalate."""
        return [
            Task(
                id=self._ID_ESCALATE,
                type=TaskType.ESCALATE,
                label=f"Escalate {prospect}'s negative feedback",
                instructions=f"Escalate {prospect}'s negative feedback to the team. "
                            f"Details: {analysis.get('summary', '')}",
                payload=EscalatePayload(
                    channel="internal",
                    priority="medium",
                    reason=analysis.get("summary", "Negative reply received"),
                ),
                reasoning_trace="Adaptive follow-up: negative → escalate",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_ooo(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Out-of-office: wait and re-send."""
        return [
            Task(
                id=self._ID_WAIT,
                type=TaskType.WAIT_DURATION,
                label=f"Wait for {prospect}'s return",
                instructions=f"{prospect} is out of office. Wait before following up.",
                payload=WaitDurationPayload(duration="7d"),
                reasoning_trace="Adaptive follow-up: OOO → wait 7 days",
                reasoning_goal="handle_reply",
            ),
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Re-send follow-up to {prospect}",
                instructions=f"Re-send the follow-up message to {prospect} at {company} now that they are back.",
                payload=MessagePayload(channel="email", template="followup_context"),
                reasoning_trace="Adaptive follow-up: re-send after OOO wait",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_auto(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Auto-reply: short wait then re-send."""
        return [
            Task(
                id=self._ID_WAIT,
                type=TaskType.WAIT_DURATION,
                label=f"Wait before re-sending to {prospect}",
                instructions=f"Auto-reply from {prospect}. Wait and re-send follow-up.",
                payload=WaitDurationPayload(duration="1d"),
                reasoning_trace="Adaptive follow-up: auto-reply → wait 1 day",
                reasoning_goal="handle_reply",
            ),
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Re-send follow-up to {prospect}",
                instructions=f"Re-send the follow-up message to {prospect} at {company}.",
                payload=MessagePayload(channel="email", template="followup_value"),
                reasoning_trace="Adaptive follow-up: re-send after auto-reply wait",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_terminate(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Terminate: mark campaign as ended."""
        return [
            Task(
                id=self._ID_TERMINATE,
                type=TaskType.UPDATE_CRM,
                label=f"Terminate campaign for {prospect}",
                instructions=f"Mark {prospect} at {company} as not interested. "
                            f"Reason: {analysis.get('summary', '')}",
                payload=UpdateCRMPayload(
                    action="terminate_campaign",
                    status="not_interested",
                ),
                reasoning_trace="Adaptive follow-up: not interested → terminate campaign",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_meeting_accepted(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Meeting accepted: create calendar event and send confirmation."""
        event_summary = context.get("event_summary", f"Meeting with {prospect}")
        start_time = context.get("start_time", "")
        end_time = context.get("end_time", "")

        tasks = []
        if start_time and end_time:
            tasks.append(Task(
                id=self._ID_CALENDAR,
                type=TaskType.CALENDAR_CREATE_EVENT,
                label=f"Add {prospect}'s meeting to calendar",
                instructions=f"Create the calendar event for the accepted meeting with {prospect}.",
                payload=CreateEventPayload(
                    summary=event_summary,
                    start_time=start_time,
                    end_time=end_time,
                ),
                reasoning_trace="Adaptive follow-up: meeting accepted → create event",
                reasoning_goal="handle_reply",
            ))

        tasks.append(Task(
            id=self._ID_REPLY,
            type=TaskType.SEND_EMAIL,
            label=f"Send confirmation to {prospect}",
            instructions=f"Send a meeting confirmation email to {prospect} at {company}.",
            payload=MessagePayload(channel="email", template="meeting_confirmation"),
            reasoning_trace="Adaptive follow-up: meeting accepted → confirm",
            reasoning_goal="handle_reply",
        ))
        return tasks

    def _route_meeting_declined(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Meeting declined: suggest reschedule."""
        return [
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Reschedule with {prospect}",
                instructions=f"Politely acknowledge {prospect}'s decline and suggest alternative times. "
                            f"Keep the conversation open and professional.",
                payload=MessagePayload(channel="email", template="reschedule"),
                reasoning_trace="Adaptive follow-up: meeting declined → reschedule",
                reasoning_goal="handle_reply",
            ),
        ]

    def _route_default(
        self, prospect: str, company: str,
        thread_id: str, in_reply_to: str,
        analysis: dict, context: dict,
    ) -> list[Task]:
        """Default: send generic follow-up and analyze."""
        return [
            Task(
                id=self._ID_REPLY,
                type=TaskType.SEND_EMAIL,
                label=f"Follow up with {prospect}",
                instructions=f"Send a thoughtful follow-up to {prospect} at {company}. "
                            f"Reference their last message and add value.",
                payload=MessagePayload(channel="email", template="followup_value"),
                reasoning_trace="Adaptive follow-up: default → follow up then analyze",
                reasoning_goal="handle_reply",
            ),
            Task(
                id=self._ID_ANALYZE,
                type=TaskType.ANALYZE_REPLY,
                label=f"Analyze {prospect}'s next reply",
                instructions=f"Analyze {prospect}'s response to determine next action.",
                params={"reason": f"Default follow-up analysis for {prospect}"},
                reasoning_trace="Adaptive follow-up: await reply after follow-up",
                reasoning_goal="handle_reply",
            ),
        ]

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        pairs = []
        ids = [t.id for t in tasks]
        # sequential chain unless there's only one task
        for i in range(1, len(ids)):
            pairs.append((ids[i - 1], ids[i]))
        return pairs

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=0,
            max_daily_tasks=5,
        )

    def approval_rules(self, tasks: list[Task]) -> list:
        rules = []
        for t in tasks:
            if t.type == TaskType.SEND_EMAIL and t.approval == ApprovalRequirement.RECOMMENDED:
                rules.append(ApprovalRule(
                    task_type=t.type,
                    condition="external_communication",
                    requirement="recommended",
                    reason=f"Recommended approval for email to {t.label}",
                ))
        return rules


follow_up_v2_strategy = FollowUpV2Strategy()
