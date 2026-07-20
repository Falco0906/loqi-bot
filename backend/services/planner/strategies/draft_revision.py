from __future__ import annotations

from typing import Any

from services.planner.planning_models import (
    ApprovalRequirement,
    PlanGoal,
    Task,
    TaskType,
)
from services.planner.payloads import MessagePayload
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    Strategy,
)


class DraftRevisionStrategy(Strategy):
    """Revises an existing draft based on reviewer feedback or reply context.

    Input (via context):
      - previous_draft: dict with subject, body_plain, body_html, etc.
      - reviewer_comments: text feedback from reviewer
      - reply_context: conversation context (optional)
      - thread_id, in_reply_to_message_id: for thread-aware revisions
      - recipients: list of recipient email addresses
    """

    _ID_REVISE = "draft_revise"
    _ID_APPROVE = "draft_approve"

    @property
    def name(self) -> str:
        return "draft_revision"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("revise_draft", "draft_revision", "update_draft"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "revise" in outcome_lower or "revision" in outcome_lower or "update draft" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        previous_draft = context.get("previous_draft", {})
        reviewer_comments = context.get("reviewer_comments", "")
        reply_context = context.get("reply_context", "")
        recipients = context.get("recipients", [])
        prospect = context.get("prospect_name", "Prospect")
        company = context.get("company", "")

        old_subject = previous_draft.get("subject", "")
        old_body = previous_draft.get("body_plain", previous_draft.get("body", ""))
        old_thread_id = previous_draft.get("thread_id", context.get("thread_id", ""))
        old_in_reply_to = previous_draft.get(
            "in_reply_to_message_id", context.get("in_reply_to_message_id", ""),
        )

        # Build revision instructions for the AI
        revision_prompt = f"Revise the draft below.\n"
        if reviewer_comments:
            revision_prompt += f"\nReviewer comments:\n{reviewer_comments}\n"
        if reply_context:
            revision_prompt += f"\nReply context:\n{reply_context}\n"

        task = Task(
            id=self._ID_REVISE,
            type=TaskType.SEND_EMAIL,
            label=f"Send revised draft to {prospect}",
            instructions=revision_prompt,
            payload=MessagePayload(
                channel="email",
                template="revised_draft",
            ),
            approval=ApprovalRequirement.REQUIRED,
            reasoning_trace="Draft revision: incorporate feedback and resend",
            reasoning_goal=goal.target_action,
        )
        # Set flat params after construction — payload.to_dict() in
        # __post_init__ overwrites any params passed to the constructor.
        task.params["to"] = recipients
        task.params["subject"] = old_subject
        task.params["body_plain"] = old_body
        task.params["thread_id"] = old_thread_id
        task.params["in_reply_to_message_id"] = old_in_reply_to
        task.params["is_revision"] = True
        task.params["reviewer_comments"] = reviewer_comments
        task.params["reply_context"] = reply_context
        return [task]

    def approval_rules(self, tasks: list[Task]) -> list:
        return [
            ApprovalRule(
                task_type=TaskType.SEND_EMAIL,
                condition="revised_draft",
                requirement="required",
                reason="Revised drafts require explicit approval before sending",
            ),
        ]


draft_revision_strategy = DraftRevisionStrategy()
