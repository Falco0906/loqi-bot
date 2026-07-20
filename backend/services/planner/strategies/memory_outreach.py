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
    CreateContactPayload,
    CreateOpportunityPayload,
    FindContactPayload,
    FindCompanyPayload,
    MessagePayload,
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    SchedulingHints,
)
from services.planner.strategies.memory_aware import MemoryAwareStrategy


class MemoryOutreachStrategy(MemoryAwareStrategy):
    """Pipeline outreach enriched with organizational memory.

    Before generating tasks, retrieves past account interactions,
    previous objections, and outcome history to tailor the outreach.
    """

    _ID = "memory_outreach"

    @property
    def name(self) -> str:
        return "memory_outreach"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("memory_outreach", "intelligent_outreach", "contextual_outreach"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "memory" in outcome_lower and "outreach" in outcome_lower:
            return 0.9
        if "previous" in outcome_lower and ("objection" in outcome_lower or "outcome" in outcome_lower):
            return 0.85
        return 0.0

    async def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        enriched = await self.enrich_context(context)
        prospect_email = enriched.get("prospect_email", "")
        prospect_name = enriched.get("prospect_name", "Prospect")
        company_name = enriched.get("company_name", "")
        company_domain = enriched.get("company_domain", "")
        memories = enriched.get("relevant_memories", [])
        citation = enriched.get("memory_citation", None)

        previous_objections = _extract_objections(memories)
        previous_outcomes = _extract_outcomes(memories)
        instructions_parts = [f"Outreach to {prospect_name} at {company_name}."]
        if previous_objections:
            instructions_parts.append(
                f"Previous objections raised: {'; '.join(previous_objections)}. "
                f"Address these proactively."
            )
        if previous_outcomes:
            instructions_parts.append(
                f"Previous outreach outcomes: {'; '.join(previous_outcomes)}."
            )

        tasks: list[Task] = []
        task_id_base = self._ID

        tasks.append(Task(
            id=f"{task_id_base}_find_company",
            type=TaskType.FIND_COMPANY,
            label=f"Find company: {company_name or company_domain}",
            instructions=f"Look up company record for {company_name or company_domain}.",
            payload=FindCompanyPayload(domain=company_domain, name=company_name),
            reasoning_trace="Memory outreach: locate company",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_find_contact",
            type=TaskType.FIND_CONTACT,
            label=f"Find contact: {prospect_email or prospect_name}",
            instructions=f"Look up existing contact record for {prospect_email or prospect_name}.",
            payload=FindContactPayload(
                email=prospect_email, company_domain=company_domain, name=prospect_name,
            ),
            dependencies=[f"{task_id_base}_find_company"],
            reasoning_trace="Memory outreach: locate contact",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_create_contact",
            type=TaskType.CREATE_CONTACT,
            label=f"Create contact: {prospect_name}",
            instructions=f"Create contact record for {prospect_name} at {company_name}.",
            payload=CreateContactPayload(
                email=prospect_email,
                first_name=prospect_name.split(" ")[0] if " " in prospect_name else prospect_name,
                last_name=prospect_name.split(" ", 1)[-1] if " " in prospect_name else "",
                title=context.get("prospect_title", ""),
                company_id=f"ref:{task_id_base}_find_company",
                lifecycle_stage="lead",
            ),
            dependencies=[f"{task_id_base}_find_contact"],
            reasoning_trace="Memory outreach: create contact",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_create_opp",
            type=TaskType.CREATE_OPPORTUNITY,
            label=f"Create opportunity for {company_name}",
            instructions=f"Create opportunity for {company_name} with {prospect_name}.",
            payload=CreateOpportunityPayload(
                name=f"{company_name} - Memory Outreach",
                company_id=f"ref:{task_id_base}_find_company",
                contact_id=f"ref:{task_id_base}_find_contact",
                amount=0.0, stage="discovery", pipeline="default",
            ),
            dependencies=[f"{task_id_base}_create_contact"],
            reasoning_trace="Memory outreach: create opportunity",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_outreach",
            type=TaskType.SEND_EMAIL,
            label=f"Contextual outreach to {prospect_name}",
            instructions=" ".join(instructions_parts),
            payload=MessagePayload(channel="email", template="cold_outreach"),
            dependencies=[f"{task_id_base}_create_opp"],
            reasoning_trace=f"Memory outreach: {citation.explanation if citation else 'no memories'}",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_log",
            type=TaskType.CREATE_ACTIVITY,
            label=f"Log outreach for {prospect_name}",
            instructions=f"Log the memory-aware outreach as a CRM activity.",
            payload=CreateActivityPayload(
                type="email",
                subject=f"Memory-aware outreach to {prospect_name}",
                body=" ".join(instructions_parts),
                contact_id=f"ref:{task_id_base}_find_contact",
                company_id=f"ref:{task_id_base}_find_company",
                opportunity_id=f"ref:{task_id_base}_create_opp",
            ),
            dependencies=[f"{task_id_base}_outreach"],
            reasoning_trace="Memory outreach: log activity",
            reasoning_goal="memory_outreach",
        ))
        tasks.append(Task(
            id=f"{task_id_base}_wait",
            type=TaskType.WAIT_FOR_REPLY,
            label=f"Wait for {prospect_name}'s reply",
            instructions=f"Wait up to 3 days for {prospect_name} to respond.",
            params={"timeout": "3d"},
            dependencies=[f"{task_id_base}_log"],
            reasoning_trace="Memory outreach: wait for response",
            reasoning_goal="memory_outreach",
        ))

        if citation:
            for t in tasks:
                t.metadata["memory_citation"] = citation.explanation
                t.metadata["memory_ids"] = citation.memory_ids

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
                    reason=f"Memory-aware outreach: {t.label}",
                ))
        return rules


def _extract_objections(memories: list) -> list[str]:
    objections: list[str] = []
    for m in memories:
        if hasattr(m, "objections") and m.objections:
            objections.extend(m.objections)  # type: ignore
        if hasattr(m, "details"):
            details = getattr(m, "details", "")
            if details and isinstance(details, str):
                for kw in ["budget", "timing", "competitor", "pricing", "not interested"]:
                    if kw in details.lower():
                        objections.append(kw)
    return list(set(objections))


def _extract_outcomes(memories: list) -> list[str]:
    outcomes: list[str] = []
    for m in memories:
        if hasattr(m, "result"):
            result = getattr(m, "result", "")
            if result:
                outcomes.append(str(result))
        if hasattr(m, "outcome") and getattr(m, "outcome", ""):
            outcomes.append(str(getattr(m, "outcome", "")))
    return list(set(outcomes))


memory_outreach_strategy = MemoryOutreachStrategy()
