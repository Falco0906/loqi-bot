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
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    SchedulingHints,
    Strategy,
)

STAGE_TRANSITIONS: dict[str, list[str]] = {
    "discovery": ["qualified", "closed_lost"],
    "qualified": ["proposal", "closed_lost"],
    "proposal": ["negotiation", "closed_lost"],
    "negotiation": ["closed_won", "closed_lost"],
}

STAGE_ACTIONS: dict[str, str] = {
    "discovery": "Conduct discovery call/meeting to understand needs",
    "qualified": "Send proposal and relevant case studies",
    "proposal": "Present proposal and address stakeholder questions",
    "negotiation": "Handle negotiations, revise terms if needed",
}

STAGE_PROBABILITY: dict[str, int] = {
    "discovery": 10,
    "qualified": 25,
    "proposal": 50,
    "negotiation": 75,
    "closed_won": 100,
    "closed_lost": 0,
}


class OpportunityDevelopmentStrategy(Strategy):
    _ID = "opp_dev"

    @property
    def name(self) -> str:
        return "opportunity_development"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("develop_opportunity", "advance_opportunity", "opportunity_follow_up"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "opportunity" in outcome_lower and "advance" in outcome_lower:
            return 0.9
        if "stage" in outcome_lower and ("progression" in outcome_lower or "move" in outcome_lower):
            return 0.85
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        current_stage = context.get("current_stage", "discovery")
        target_stage = context.get("target_stage", "")
        opportunity_id = context.get("opportunity_id", "")
        contact_name = context.get("contact_name", "Contact")
        company_name = context.get("company_name", "")
        prospect_email = context.get("prospect_email", "")
        tasks: list[Task] = []

        if current_stage in ("closed_won", "closed_lost"):
            return tasks

        valid_targets = STAGE_TRANSITIONS.get(current_stage, [])
        if target_stage and target_stage not in valid_targets:
            target_stage = valid_targets[0] if valid_targets else ""

        next_stage = target_stage or (valid_targets[0] if valid_targets else "")

        action_description = STAGE_ACTIONS.get(current_stage, "Advance the opportunity")
        if next_stage == "closed_lost":
            action_description = f"Mark opportunity as closed-lost. Reason: {context.get('loss_reason', 'Not specified')}"

        tasks.append(Task(
            id=f"{self._ID}_action",
            type=TaskType.UPDATE_CRM,
            label=f"{action_description} for {company_name or contact_name}",
            instructions=f"{action_description}. Current stage: {current_stage}. "
                        f"Target stage: {next_stage}.",
            payload=MessagePayload(
                channel="email",
                template="opportunity_action",
            ),
            reasoning_trace=f"Opportunity development: moving {current_stage} → {next_stage}",
            reasoning_goal="develop_opportunity",
        ))

        if next_stage not in ("closed_won", "closed_lost"):
            tasks.append(Task(
                id=f"{self._ID}_update_stage",
                type=TaskType.UPDATE_OPPORTUNITY,
                label=f"Update opportunity stage to {next_stage}",
                instructions=f"Move the opportunity for {company_name} from {current_stage} to {next_stage}.",
                payload=UpdateOpportunityPayload(
                    opportunity_id=opportunity_id,
                    stage=next_stage,
                    amount=context.get("amount", 0.0),
                    close_date=context.get("close_date", ""),
                ),
                dependencies=[f"{self._ID}_action"],
                reasoning_trace=f"Opportunity development: stage update {current_stage} → {next_stage}",
                reasoning_goal="develop_opportunity",
            ))

            tasks.append(Task(
                id=f"{self._ID}_log_activity",
                type=TaskType.CREATE_ACTIVITY,
                label=f"Log stage progression activity for {contact_name}",
                instructions=f"Log the stage progression from {current_stage} to {next_stage} "
                            f"as a CRM activity for {contact_name} at {company_name}.",
                payload=CreateActivityPayload(
                    type="email",
                    subject=f"Stage progression: {current_stage} → {next_stage}",
                    body=f"Opportunity advanced from {current_stage} to {next_stage}. "
                        f"{action_description}",
                    contact_id=context.get("contact_id", ""),
                    company_id=context.get("company_id", ""),
                    opportunity_id=opportunity_id,
                ),
                dependencies=[f"{self._ID}_update_stage"],
                reasoning_trace="Opportunity development: log stage progression",
                reasoning_goal="develop_opportunity",
            ))

            if context.get("add_note", False):
                note_text = context.get("note_text", "")
                if note_text:
                    tasks.append(Task(
                        id=f"{self._ID}_add_note",
                        type=TaskType.CREATE_NOTE,
                        label=f"Add note to {company_name} opportunity",
                        instructions=f"Add a context note to the {company_name} opportunity.",
                        payload=CreateNotePayload(
                            body=note_text,
                            contact_id=context.get("contact_id", ""),
                            company_id=context.get("company_id", ""),
                            opportunity_id=opportunity_id,
                        ),
                        dependencies=[f"{self._ID}_update_stage"],
                        reasoning_trace="Opportunity development: add context note",
                        reasoning_goal="develop_opportunity",
                    ))
        else:
            tasks.append(Task(
                id=f"{self._ID}_close",
                type=TaskType.UPDATE_OPPORTUNITY,
                label=f"Close opportunity as {next_stage}",
                instructions=f"Mark the {company_name} opportunity as {next_stage}.",
                payload=UpdateOpportunityPayload(
                    opportunity_id=opportunity_id,
                    stage=next_stage,
                    amount=context.get("amount", 0.0),
                    close_date=context.get("close_date", ""),
                ),
                dependencies=[f"{self._ID}_action"],
                reasoning_trace=f"Opportunity development: close as {next_stage}",
                reasoning_goal="develop_opportunity",
            ))

        return tasks

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [(dep, t.id) for t in tasks for dep in t.dependencies]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=10,
            max_daily_tasks=3,
        )

    def approval_rules(self, tasks: list[Task]) -> list:
        rules = []
        for t in tasks:
            if t.type == TaskType.UPDATE_OPPORTUNITY:
                rules.append(ApprovalRule(
                    task_type=t.type,
                    condition="stage_change",
                    requirement="recommended",
                    reason=f"Opportunity stage change: {t.label}",
                ))
        return rules


opportunity_development_strategy = OpportunityDevelopmentStrategy()
