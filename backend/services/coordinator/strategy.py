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
    CreateCompanyPayload,
    CreateContactPayload,
    CreateOpportunityPayload,
    CreateNotePayload,
    FindContactPayload,
    FindCompanyPayload,
    MessagePayload,
    StoreMemoryPayload,
    UpdateOpportunityPayload,
)
from services.planner.strategies.strategy_base import (
    ApprovalRule,
    SchedulingHints,
    Strategy,
)
from services.coordinator.coordinator import AgentCoordinator


class CoordinatorStrategy(Strategy):
    """Strategy that delegates planning to the AgentCoordinator.

    The coordinator selects the right pipeline, runs the required
    agents, merges their structured outputs, and the strategy
    translates the enriched context into concrete Tasks.
    """

    _ID = "coordinator"

    def __init__(self) -> None:
        self._coordinator = AgentCoordinator()

    @property
    def name(self) -> str:
        return "coordinator"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("coordinator", "multi_agent", "orchestrated"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "orchestrated" in outcome_lower or "coordinated" in outcome_lower:
            return 0.9
        if "agent" in outcome_lower and "pipeline" in outcome_lower:
            return 0.85
        return 0.0

    async def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        pipeline = self._coordinator.select_pipeline(
            goal.target_action, goal.outcome, context,
        )
        plan = await self._coordinator.orchestrate(pipeline, context)
        return _plan_to_tasks(plan, context)


def _plan_to_tasks(
    coordination: "CoordinationPlan",
    original_context: dict,
) -> list[Task]:
    from services.coordinator.coordinator import CoordinationPlan

    merged = coordination.merged_context
    tasks: list[Task] = []
    pipeline = coordination.pipeline_name
    id_base = "coord"

    if pipeline == "new_account_outreach":
        tasks.extend(_new_account_tasks(merged, id_base))
    elif pipeline == "reply_handler":
        tasks.extend(_reply_handler_tasks(merged, id_base))
    elif pipeline == "objection_handling":
        tasks.extend(_objection_handling_tasks(merged, id_base))
    elif pipeline == "meeting_complete":
        tasks.extend(_meeting_complete_tasks(merged, id_base))
    elif pipeline == "quick_memory_lookup":
        tasks.extend(_quick_memory_tasks(merged, id_base))

    for t in tasks:
        t.metadata["pipeline"] = pipeline
        t.metadata["agent_count"] = len(coordination.agent_sequence)
        t.metadata["memory_ids"] = coordination.memory_ids

        # Attach memory citation from any agent result
        for result in coordination.agent_results.values():
            data = (result.data or {})
            mem_ctx = data.get("memory_context", {})
            if mem_ctx and mem_ctx.get("memory_citation"):
                t.metadata["memory_citation"] = mem_ctx["memory_citation"]
                break

    return tasks


def _new_account_tasks(merged: dict, id_base: str) -> list[Task]:
    tasks: list[Task] = []
    crm = merged.get("crm_state", {})
    comm = merged.get("communication_context", {})
    research = merged.get("research_report", {})
    contact_name = crm.get("contact_name", merged.get("contact_name", "Prospect"))
    company_name = research.get("company_name", merged.get("company_name", ""))
    contact_email = crm.get("contact_email", merged.get("contact_email", ""))
    company_domain = research.get("company_domain", merged.get("company_domain", ""))

    needs_company = not crm.get("has_company", False)
    needs_contact = not crm.get("has_contact", False)
    needs_opp = not crm.get("has_opportunity", False)

    if needs_company:
        tasks.append(Task(
            id=f"{id_base}_find_company",
            type=TaskType.FIND_COMPANY,
            label=f"Find company: {company_name or company_domain}",
            instructions=f"Look up company record for {company_name or company_domain}.",
            payload=FindCompanyPayload(domain=company_domain, name=company_name),
            reasoning_trace="Coordinator: new account → find company",
            reasoning_goal="new_account_outreach",
        ))
        tasks.append(Task(
            id=f"{id_base}_create_company",
            type=TaskType.CREATE_COMPANY,
            label=f"Create company: {company_name}",
            instructions=f"Create company record for {company_name} in {research.get('industry', '')}.",
            payload=CreateCompanyPayload(
                name=company_name,
                domain=company_domain,
                industry=research.get("industry", ""),
                size=research.get("company_size", ""),
            ),
            dependencies=[f"{id_base}_find_company"],
            reasoning_trace="Coordinator: new account → create company",
            reasoning_goal="new_account_outreach",
        ))

    if needs_contact:
        deps = [f"{id_base}_create_company"] if needs_company else []
        tasks.append(Task(
            id=f"{id_base}_find_contact",
            type=TaskType.FIND_CONTACT,
            label=f"Find contact: {contact_email or contact_name}",
            instructions=f"Look up existing contact record for {contact_email or contact_name}.",
            payload=FindContactPayload(email=contact_email, name=contact_name),
            dependencies=deps,
            reasoning_trace="Coordinator: new account → find contact",
            reasoning_goal="new_account_outreach",
        ))
        tasks.append(Task(
            id=f"{id_base}_create_contact",
            type=TaskType.CREATE_CONTACT,
            label=f"Create contact: {contact_name}",
            instructions=f"Create contact record for {contact_name}.",
            payload=CreateContactPayload(
                email=contact_email,
                first_name=contact_name.split(" ")[0] if " " in contact_name else contact_name,
                last_name=contact_name.split(" ", 1)[-1] if " " in contact_name else "",
                title=crm.get("contact_title", ""),
                lifecycle_stage="lead",
            ),
            dependencies=[f"{id_base}_find_contact"],
            reasoning_trace="Coordinator: new account → create contact",
            reasoning_goal="new_account_outreach",
        ))

    if needs_opp:
        deps = [f"{id_base}_create_contact"] if needs_contact else []
        if needs_company:
            deps.append(f"{id_base}_create_company")
        tasks.append(Task(
            id=f"{id_base}_create_opp",
            type=TaskType.CREATE_OPPORTUNITY,
            label=f"Create opportunity for {company_name}",
            instructions=f"Create opportunity for {company_name} with research context.",
            payload=CreateOpportunityPayload(
                name=f"{company_name} - Coordinated Outreach",
                amount=0.0,
                stage="discovery",
                pipeline="default",
            ),
            dependencies=deps,
            reasoning_trace="Coordinator: new account → create opportunity",
            reasoning_goal="new_account_outreach",
        ))

    template = comm.get("message_template", "cold_outreach")
    follow_ups = comm.get("follow_up_suggestions", [])
    objection_strategy = comm.get("objection_strategy", "")
    priority = comm.get("priority", "medium")
    requires_approval = comm.get("requires_approval", False)

    outreach_deps = [f"{id_base}_create_opp"] if needs_opp else []
    instructions = f"Send outreach to {contact_name} at {company_name}."
    if objection_strategy:
        instructions += f" Strategy: {objection_strategy.replace('_', ' ')}."
    if follow_ups:
        instructions += f" Follow-up plan: {', '.join(follow_ups[:3])}."

    tasks.append(Task(
        id=f"{id_base}_outreach",
        type=TaskType.SEND_EMAIL,
        label=f"Coordinated outreach to {contact_name}",
        instructions=instructions,
        payload=MessagePayload(channel="email", template=template),
        dependencies=outreach_deps,
        approval=ApprovalRequirement.RECOMMENDED if requires_approval else ApprovalRequirement.NONE,
        reasoning_trace=f"Coordinator: outreach via {template} (priority: {priority})",
        reasoning_goal="new_account_outreach",
    ))

    tasks.append(Task(
        id=f"{id_base}_log",
        type=TaskType.CREATE_ACTIVITY,
        label=f"Log coordinated outreach for {contact_name}",
        instructions=f"Log the multi-agent coordinated outreach as a CRM activity.",
        payload=CreateActivityPayload(
            type="email",
            subject=f"Coordinated outreach to {contact_name}",
            body=instructions,
            contact_id=f"ref:{id_base}_find_contact" if needs_contact else "",
            company_id=f"ref:{id_base}_find_company" if needs_company else "",
            opportunity_id=f"ref:{id_base}_create_opp" if needs_opp else "",
        ),
        dependencies=[f"{id_base}_outreach"],
        reasoning_trace="Coordinator: log outreach activity",
        reasoning_goal="new_account_outreach",
    ))

    tasks.append(Task(
        id=f"{id_base}_store_memory",
        type=TaskType.STORE_MEMORY,
        label=f"Store memory of coordinated outreach to {company_name}",
        instructions="Store the outreach event as organizational memory.",
        payload=StoreMemoryPayload(
            memory_type="outcome",
            source="coordinator_outreach",
            tags=["outreach", "coordinated", "new_account_outreach"],
            metadata={"contact": contact_name, "company": company_name},
        ),
        dependencies=[f"{id_base}_outreach"],
        reasoning_trace="Coordinator: store outreach memory",
        reasoning_goal="new_account_outreach",
    ))

    return tasks


def _reply_handler_tasks(merged: dict, id_base: str) -> list[Task]:
    tasks: list[Task] = []
    comm = merged.get("communication_context", {})
    crm = merged.get("crm_state", {})
    scheduling = merged.get("scheduling_context", {})
    contact_name = crm.get("contact_name", merged.get("contact_name", "Contact"))
    company_name = crm.get("company_name", merged.get("company_name", ""))

    template = comm.get("message_template", "followup_value")
    tasks.append(Task(
        id=f"{id_base}_reply",
        type=TaskType.SEND_EMAIL,
        label=f"Respond to {contact_name}",
        instructions=f"Send a thoughtful reply to {contact_name} at {company_name}.",
        payload=MessagePayload(channel="email", template=template),
        reasoning_trace="Coordinator: reply handler → send response",
        reasoning_goal="reply_handler",
    ))

    if scheduling.get("suggested_date"):
        tasks.append(Task(
            id=f"{id_base}_schedule",
            type=TaskType.SCHEDULE_MEETING,
            label=f"Schedule meeting with {contact_name}",
            instructions=f"Schedule a meeting with {contact_name} suggested for {scheduling.get('suggested_date')}.",
            payload=MessagePayload(channel="email", template="meeting_request"),
            dependencies=[f"{id_base}_reply"],
            reasoning_trace="Coordinator: reply → schedule meeting",
            reasoning_goal="reply_handler",
        ))

    tasks.append(Task(
        id=f"{id_base}_log_reply",
        type=TaskType.CREATE_ACTIVITY,
        label=f"Log reply activity for {contact_name}",
        instructions=f"Log the reply handling as a CRM activity.",
        payload=CreateActivityPayload(
            type="email",
            subject=f"Reply to {contact_name}",
            body=f"Reply handled via coordinated pipeline.",
            contact_id=crm.get("contact_id", ""),
            company_id=crm.get("company_id", ""),
            opportunity_id=crm.get("opportunity_id", ""),
        ),
        dependencies=[f"{id_base}_reply"],
        reasoning_trace="Coordinator: log reply activity",
        reasoning_goal="reply_handler",
    ))

    return tasks


def _objection_handling_tasks(merged: dict, id_base: str) -> list[Task]:
    tasks: list[Task] = []
    comm = merged.get("communication_context", {})
    memory_ctx = merged.get("memory_context", {})
    contact_name = merged.get("contact_name", "Contact")
    company_name = merged.get("company_name", "")

    objections = memory_ctx.get("previous_objections", [])
    strategy = comm.get("objection_strategy", "value_first_approach")
    instructions = f"Address {contact_name}'s previous concerns"
    if objections:
        instructions += f": {'; '.join(objections[:3])}"
    instructions += f". Strategy: {strategy.replace('_', ' ')}."

    tasks.append(Task(
        id=f"{id_base}_objection_reply",
        type=TaskType.SEND_EMAIL,
        label=f"Address {contact_name}'s objection",
        instructions=instructions,
        payload=MessagePayload(channel="email", template="objection_response"),
        approval=ApprovalRequirement.RECOMMENDED,
        reasoning_trace=f"Coordinator: objection handling ({strategy})",
        reasoning_goal="objection_handling",
    ))

    tasks.append(Task(
        id=f"{id_base}_note",
        type=TaskType.CREATE_NOTE,
        label=f"Log objection handling for {company_name}",
        instructions=f"Record the objection handling approach.",
        payload=CreateNotePayload(
            body=f"Objection strategy: {strategy}. Previous objections: {objections}.",
            contact_id=merged.get("contact_id", ""),
            company_id=merged.get("company_id", ""),
        ),
        dependencies=[f"{id_base}_objection_reply"],
        reasoning_trace="Coordinator: log objection handling",
        reasoning_goal="objection_handling",
    ))

    return tasks


def _meeting_complete_tasks(merged: dict, id_base: str) -> list[Task]:
    tasks: list[Task] = []
    crm = merged.get("crm_state", {})
    comm = merged.get("communication_context", {})
    contact_name = crm.get("contact_name", merged.get("contact_name", "Contact"))
    company_name = crm.get("company_name", merged.get("company_name", ""))

    stage = crm.get("opportunity_stage", "discovery")
    suggested_stage = merged.get("suggested_stage", "qualified")

    if stage != suggested_stage:
        tasks.append(Task(
            id=f"{id_base}_update_stage",
            type=TaskType.UPDATE_OPPORTUNITY,
            label=f"Update opportunity stage to {suggested_stage}",
            instructions=f"Move {company_name} opportunity from {stage} to {suggested_stage}.",
            payload=UpdateOpportunityPayload(
                opportunity_id=crm.get("opportunity_id", ""),
                stage=suggested_stage,
                amount=crm.get("opportunity_amount", 0.0),
            ),
            reasoning_trace=f"Coordinator: meeting done → stage {stage} → {suggested_stage}",
            reasoning_goal="meeting_complete",
        ))

    nba_action = comm.get("follow_up_suggestions", ["send_follow_up"])[0]
    tasks.append(Task(
        id=f"{id_base}_nba",
        type=TaskType.CREATE_ACTIVITY,
        label=f"Next action for {contact_name}: {nba_action}",
        instructions=f"After meeting with {contact_name}, suggested next action is {nba_action}.",
        payload=CreateActivityPayload(
            type="email",
            subject=f"Post-meeting: {nba_action.replace('_', ' ').title()}",
            body=f"Post-meeting follow-up for {contact_name} at {company_name}.",
            contact_id=crm.get("contact_id", ""),
            company_id=crm.get("company_id", ""),
            opportunity_id=crm.get("opportunity_id", ""),
        ),
        dependencies=[f"{id_base}_update_stage"] if tasks else [],
        reasoning_trace="Coordinator: meeting done → next action",
        reasoning_goal="meeting_complete",
    ))

    return tasks


def _quick_memory_tasks(merged: dict, id_base: str) -> list[Task]:
    memory_ctx = merged.get("memory_context", {})
    return [
        Task(
            id=f"{id_base}_memory_result",
            type=TaskType.SEARCH_MEMORY,
            label="Retrieved organizational memory",
            instructions=f"Memory retrieval complete. Found {len(memory_ctx.get('relevant_memories', []))} memories.",
            params={"memory_citation": memory_ctx.get("memory_citation", "")},
            reasoning_trace="Coordinator: quick memory lookup",
            reasoning_goal="quick_memory_lookup",
        ),
    ]


coordinator_strategy = CoordinatorStrategy()

