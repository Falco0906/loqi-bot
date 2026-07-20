from __future__ import annotations

from typing import Any

from services.planner.planning_models import (
    ApprovalRequirement,
    PlanGoal,
    Task,
    TaskType,
)
from services.planner.payloads import (
    CreateActivityPayload,
    CreateNotePayload,
    MessagePayload,
    UpdateOpportunityPayload,
    UpdateContactPayload,
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    SchedulingHints,
    Strategy,
)

ACTION_SCORES: dict[str, float] = {
    "send_follow_up": 0.9,
    "schedule_demo": 0.85,
    "send_proposal": 0.8,
    "check_in": 0.7,
    "share_case_study": 0.65,
    "request_referral": 0.5,
    "send_newsletter": 0.3,
}

STAGE_WEIGHTS: dict[str, dict[str, float]] = {
    "discovery": {
        "send_follow_up": 0.9,
        "schedule_demo": 0.8,
        "share_case_study": 0.7,
        "check_in": 0.6,
    },
    "qualified": {
        "schedule_demo": 0.95,
        "send_proposal": 0.85,
        "share_case_study": 0.8,
        "send_follow_up": 0.6,
    },
    "proposal": {
        "send_proposal": 0.9,
        "schedule_demo": 0.8,
        "check_in": 0.7,
        "request_referral": 0.5,
    },
    "negotiation": {
        "check_in": 0.9,
        "send_follow_up": 0.8,
        "request_referral": 0.6,
    },
    "closed_won": {
        "request_referral": 0.8,
        "check_in": 0.7,
        "send_newsletter": 0.5,
    },
    "closed_lost": {
        "check_in": 0.6,
        "send_newsletter": 0.4,
    },
}


def _compute_action_scores(context: dict) -> list[tuple[str, float]]:
    stage = context.get("current_stage", "discovery")
    last_action = context.get("last_action_type", "")
    days_since_last = context.get("days_since_last_contact", 30)
    engagement_score = context.get("engagement_score", 0.5)

    stage_weights = STAGE_WEIGHTS.get(stage, STAGE_WEIGHTS["discovery"])
    scored: list[tuple[str, float]] = []

    for action, base_score in ACTION_SCORES.items():
        stage_weight = stage_weights.get(action, 0.5)
        recency_penalty = max(0.0, 1.0 - (days_since_last / 90))
        score = base_score * stage_weight * (0.5 + 0.5 * recency_penalty)

        if action == last_action:
            score *= 0.5
        if engagement_score < 0.3 and action in ("send_proposal", "request_referral"):
            score *= 0.6

        scored.append((action, score))

    scored.sort(key=lambda x: -x[1])
    return scored


class NextBestActionStrategy(Strategy):
    _ID = "nba"

    @property
    def name(self) -> str:
        return "next_best_action"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("next_best_action", "nba", "recommend_action", "what_next"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "next action" in outcome_lower or "best action" in outcome_lower:
            return 0.9
        if "recommend" in outcome_lower and "engagement" in outcome_lower:
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        contact_name = context.get("contact_name", "Contact")
        company_name = context.get("company_name", "")
        opportunity_id = context.get("opportunity_id", "")
        contact_id = context.get("contact_id", "")
        scored_actions = _compute_action_scores(context)

        if not scored_actions:
            return []

        best_action = scored_actions[0][0]
        tasks: list[Task] = []

        action_templates: dict[str, dict] = {
            "send_follow_up": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Send follow-up to {contact_name}",
                "instructions": f"Send a thoughtful follow-up to {contact_name} at {company_name}.",
                "payload": MessagePayload(channel="email", template="followup_value"),
            },
            "schedule_demo": {
                "type": TaskType.SCHEDULE_MEETING,
                "label": f"Schedule demo with {contact_name}",
                "instructions": f"Reach out to {contact_name} at {company_name} to schedule a demo.",
                "payload": MessagePayload(channel="email", template="demo_request"),
            },
            "send_proposal": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Send proposal to {contact_name}",
                "instructions": f"Prepare and send the proposal to {contact_name} at {company_name}.",
                "payload": MessagePayload(channel="email", template="proposal"),
                "approval": ApprovalRequirement.REQUIRED,
            },
            "check_in": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Check in with {contact_name}",
                "instructions": f"Send a gentle check-in to {contact_name} at {company_name}.",
                "payload": MessagePayload(channel="email", template="check_in"),
            },
            "share_case_study": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Share case study with {contact_name}",
                "instructions": f"Share a relevant case study with {contact_name} at {company_name}.",
                "payload": MessagePayload(channel="email", template="case_study"),
            },
            "request_referral": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Ask {contact_name} for referral",
                "instructions": f"Politely ask {contact_name} at {company_name} for a referral.",
                "payload": MessagePayload(channel="email", template="referral_request"),
                "approval": ApprovalRequirement.RECOMMENDED,
            },
            "send_newsletter": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Send newsletter to {contact_name}",
                "instructions": f"Share the latest newsletter with {contact_name}.",
                "payload": MessagePayload(channel="email", template="newsletter"),
            },
        }

        template = action_templates.get(best_action)
        if not template:
            return []

        approval = template.get("approval", ApprovalRequirement.NONE)
        tasks.append(Task(
            id=f"{self._ID}_action",
            type=template["type"],
            label=template["label"],
            instructions=template["instructions"],
            payload=template["payload"],
            approval=approval,
            reasoning_trace=f"Next best action: {best_action} (score: {scored_actions[0][1]:.2f})",
            reasoning_goal="next_best_action",
        ))

        if opportunity_id:
            stage = context.get("current_stage", "discovery")
            if stage != "closed_lost":
                tasks.append(Task(
                    id=f"{self._ID}_log",
                    type=TaskType.CREATE_ACTIVITY,
                    label=f"Log {best_action} activity for {contact_name}",
                    instructions=f"Log the {best_action} action as a CRM activity for {contact_name}.",
                    payload=CreateActivityPayload(
                        type="email",
                        subject=f"NBA: {best_action.replace('_', ' ').title()}",
                        body=f"Next best action '{best_action}' performed for {contact_name} "
                            f"at {company_name}.",
                        contact_id=contact_id,
                        company_id=context.get("company_id", ""),
                        opportunity_id=opportunity_id,
                    ),
                    dependencies=[f"{self._ID}_action"],
                    reasoning_trace="Next best action: log activity",
                    reasoning_goal="next_best_action",
                ))

        alt_actions_text = "; ".join(
            f"{a} ({s:.2f})" for a, s in scored_actions[1:4]
        )
        if alt_actions_text:
            tasks.append(Task(
                id=f"{self._ID}_note",
                type=TaskType.CREATE_NOTE,
                label=f"Record next best action analysis for {company_name}",
                instructions=f"Record the NBA analysis for {company_name}: chosen '{best_action}', "
                            f"alternatives: {alt_actions_text}.",
                payload=CreateNotePayload(
                    body=f"Next Best Action Analysis:\n"
                        f"- Chosen: {best_action} ({scored_actions[0][1]:.2f})\n"
                        f"- Alternatives: {alt_actions_text}\n"
                        f"- Stage: {context.get('current_stage', 'unknown')}\n"
                        f"- Days since last contact: {context.get('days_since_last_contact', 'unknown')}",
                    contact_id=contact_id,
                    company_id=context.get("company_id", ""),
                    opportunity_id=opportunity_id,
                ),
                dependencies=[f"{self._ID}_action"],
                reasoning_trace="Next best action: record analysis notes",
                reasoning_goal="next_best_action",
            ))

        return tasks

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [(dep, t.id) for t in tasks for dep in t.dependencies]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=5,
            max_daily_tasks=10,
        )

    def approval_rules(self, tasks: list[Task]) -> list:
        rules = []
        for t in tasks:
            if t.approval != ApprovalRequirement.NONE:
                rules.append(ApprovalRule(
                    task_type=t.type,
                    condition="next_best_action",
                    requirement=t.approval.value,
                    reason=f"NBA recommended action: {t.label}",
                ))
        return rules


next_best_action_strategy = NextBestActionStrategy()
