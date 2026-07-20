from __future__ import annotations

from typing import Any

from services.planner.planning_models import (
    ApprovalRequirement,
    PlanGoal,
    Task,
    TaskType,
    Trigger,
    TriggerType,
)
from services.planner.payloads import (
    CreateActivityPayload,
    CreateContactPayload,
    CreateOpportunityPayload,
    CreateNotePayload,
    FindContactPayload,
    FindCompanyPayload,
    MessagePayload,
    UpdateOpportunityPayload,
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    SchedulingHints,
    Strategy,
)


class PipelineOutreachStrategy(Strategy):
    _ID = "pipeline_outreach"

    @property
    def name(self) -> str:
        return "pipeline_outreach"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("pipeline_outreach", "crm_campaign", "outreach_sequence"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "pipeline" in outcome_lower and "outreach" in outcome_lower:
            return 0.9
        if "sequence" in outcome_lower and "crm" in outcome_lower:
            return 0.85
        if "contact" in outcome_lower and "company" in outcome_lower:
            return 0.7
        return 0.0

    def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        prospect_email = context.get("prospect_email", "")
        prospect_name = context.get("prospect_name", "Prospect")
        company_name = context.get("company_name", "")
        company_domain = context.get("company_domain", "")
        industry = context.get("industry", "")
        tasks: list[Task] = []

        tasks.append(Task(
            id=f"{self._ID}_find_company",
            type=TaskType.FIND_COMPANY,
            label=f"Find or create company: {company_name or company_domain}",
            instructions=f"Look up existing company record for {company_name or company_domain}.",
            payload=FindCompanyPayload(
                domain=company_domain,
                name=company_name,
            ),
            reasoning_trace="Pipeline outreach: locate company in CRM",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_find_contact",
            type=TaskType.FIND_CONTACT,
            label=f"Find contact: {prospect_email or prospect_name}",
            instructions=f"Look up existing contact record for {prospect_email or prospect_name}.",
            payload=FindContactPayload(
                email=prospect_email,
                company_domain=company_domain,
                name=prospect_name,
            ),
            dependencies=[f"{self._ID}_find_company"],
            reasoning_trace="Pipeline outreach: locate contact in CRM",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_create_contact",
            type=TaskType.CREATE_CONTACT,
            label=f"Create contact: {prospect_name}",
            instructions=f"Create a new contact record for {prospect_name} at {company_name}.",
            payload=CreateContactPayload(
                email=prospect_email,
                first_name=prospect_name.split(" ")[0] if " " in prospect_name else prospect_name,
                last_name=prospect_name.split(" ", 1)[-1] if " " in prospect_name else "",
                title=context.get("prospect_title", ""),
                company_id=f"ref:{self._ID}_find_company",
                lifecycle_stage="lead",
            ),
            dependencies=[f"{self._ID}_find_contact"],
            reasoning_trace="Pipeline outreach: create contact if not found",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_create_opp",
            type=TaskType.CREATE_OPPORTUNITY,
            label=f"Create opportunity for {company_name}",
            instructions=f"Create a new opportunity for {company_name} with {prospect_name}.",
            payload=CreateOpportunityPayload(
                name=f"{company_name} - Outreach",
                company_id=f"ref:{self._ID}_find_company",
                contact_id=f"ref:{self._ID}_find_contact",
                amount=0.0,
                stage="discovery",
                pipeline="default",
            ),
            dependencies=[f"{self._ID}_create_contact"],
            reasoning_trace="Pipeline outreach: create new opportunity",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_first_outreach",
            type=TaskType.SEND_EMAIL,
            label=f"First outreach to {prospect_name}",
            instructions=f"Send the initial outreach email to {prospect_name} at {company_name}.",
            payload=MessagePayload(
                channel="email",
                template="cold_outreach",
            ),
            dependencies=[f"{self._ID}_create_opp"],
            reasoning_trace="Pipeline outreach: send first outreach email",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_log_activity",
            type=TaskType.CREATE_ACTIVITY,
            label=f"Log outreach activity for {prospect_name}",
            instructions=f"Log the outreach email as an activity in the CRM for {prospect_name}.",
            payload=CreateActivityPayload(
                type="email",
                subject=f"Initial outreach to {prospect_name}",
                body=f"First outreach email sent to {prospect_name} at {company_name}.",
                contact_id=f"ref:{self._ID}_find_contact",
                company_id=f"ref:{self._ID}_find_company",
                opportunity_id=f"ref:{self._ID}_create_opp",
            ),
            dependencies=[f"{self._ID}_first_outreach"],
            reasoning_trace="Pipeline outreach: log activity to CRM",
            reasoning_goal="pipeline_outreach",
        ))

        tasks.append(Task(
            id=f"{self._ID}_wait",
            type=TaskType.WAIT_FOR_REPLY,
            label=f"Wait for {prospect_name}'s reply",
            instructions=f"Wait up to 3 days for {prospect_name} to respond.",
            params={"timeout": "3d"},
            dependencies=[f"{self._ID}_log_activity"],
            reasoning_trace="Pipeline outreach: wait for prospect response",
            reasoning_goal="pipeline_outreach",
        ))

        return tasks

    def dependencies(self, tasks: list[Task]) -> list[tuple[str, str]]:
        return [(dep, t.id) for t in tasks for dep in t.dependencies]

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        return SchedulingHints(
            business_hours_only=True,
            min_delay_between_tasks=15,
            max_daily_tasks=5,
        )

    def approval_rules(self, tasks: list[Task]) -> list:
        rules = []
        for t in tasks:
            if t.type == TaskType.SEND_EMAIL:
                rules.append(ApprovalRule(
                    task_type=t.type,
                    condition="external_communication",
                    requirement="recommended",
                    reason=f"Pipeline outreach email: {t.label}",
                ))
            if t.type == TaskType.CREATE_OPPORTUNITY:
                rules.append(ApprovalRule(
                    task_type=t.type,
                    condition="new_opportunity",
                    requirement="recommended",
                    reason=f"Pipeline outreach: new opportunity {t.label}",
                ))
        return rules


pipeline_outreach_strategy = PipelineOutreachStrategy()
