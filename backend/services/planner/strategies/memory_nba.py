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
)
from services.planner.strategies.memory_aware import MemoryAwareStrategy

MEMORY_BOOST: dict[str, float] = {
    "send_follow_up": 1.2,
    "schedule_demo": 1.3,
    "send_proposal": 1.1,
    "check_in": 0.9,
    "share_case_study": 1.15,
    "request_referral": 0.8,
    "send_newsletter": 0.7,
}


class MemoryNextBestActionStrategy(MemoryAwareStrategy):
    """Next best action enriched with organizational memory.

    Retrieves past meeting outcomes, successful approaches,
    and preferences to score actions more accurately.
    """

    _ID = "memory_nba"

    @property
    def name(self) -> str:
        return "memory_nba"

    def matches(self, goal: PlanGoal) -> float:
        target = goal.target_action.lower()
        if target in ("memory_nba", "intelligent_nba", "memory_next_best"):
            return 0.95
        outcome_lower = goal.outcome.lower()
        if "memory" in outcome_lower and "next" in outcome_lower:
            return 0.9
        if "learned" in outcome_lower and "action" in outcome_lower:
            return 0.85
        if "meeting" in outcome_lower and "influence" in outcome_lower:
            return 0.8
        return 0.0

    async def generate_tasks(self, goal: PlanGoal, context: dict[str, Any]) -> list[Task]:
        enriched = await self.enrich_context(context)
        memories = enriched.get("relevant_memories", [])
        citation = enriched.get("memory_citation", None)

        contact_name = enriched.get("contact_name", "Contact")
        company_name = enriched.get("company_name", "")
        opportunity_id = enriched.get("opportunity_id", "")
        contact_id = enriched.get("contact_id", "")
        current_stage = enriched.get("current_stage", "discovery")

        scored_actions = _compute_memory_boosted_scores(enriched, memories)
        if not scored_actions:
            return []

        best_action = scored_actions[0][0]
        tasks: list[Task] = []

        action_templates: dict[str, dict] = {
            "send_follow_up": {
                "type": TaskType.SEND_EMAIL,
                "label": f"Memory-informed follow-up to {contact_name}",
                "instructions": f"Send follow-up to {contact_name} at {company_name}, informed by past interactions.",
                "payload": MessagePayload(channel="email", template="followup_value"),
            },
            "schedule_demo": {
                "type": TaskType.SCHEDULE_MEETING,
                "label": f"Schedule demo with {contact_name}",
                "instructions": f"Reach out to {contact_name} at {company_name} to schedule a demo. Past interactions suggest timing.",
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
                "label": f"Check in with {contact_name} after past interactions",
                "instructions": f"Gentle check-in with {contact_name} at {company_name}.",
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
        action_task = Task(
            id=f"{self._ID}_action",
            type=template["type"],
            label=template["label"],
            instructions=template["instructions"],
            payload=template["payload"],
            approval=approval,
            reasoning_trace=f"Memory NBA: {best_action} (score: {scored_actions[0][1]:.2f}, memories: {len(memories)})",
            reasoning_goal="memory_nba",
        )
        if citation:
            action_task.metadata["memory_citation"] = citation.explanation
            action_task.metadata["memory_ids"] = citation.memory_ids
        tasks.append(action_task)

        if opportunity_id:
            tasks.append(Task(
                id=f"{self._ID}_log",
                type=TaskType.CREATE_ACTIVITY,
                label=f"Log {best_action} for {contact_name}",
                instructions=f"Log the memory-informed {best_action} as a CRM activity for {contact_name}.",
                payload=CreateActivityPayload(
                    type="email",
                    subject=f"Memory NBA: {best_action.replace('_', ' ').title()}",
                    body=f"Next best action '{best_action}' for {contact_name} at {company_name}, "
                        f"informed by {len(memories)} historical memories.",
                    contact_id=contact_id,
                    company_id=enriched.get("company_id", ""),
                    opportunity_id=opportunity_id,
                ),
                dependencies=[f"{self._ID}_action"],
                reasoning_trace="Memory NBA: log activity",
                reasoning_goal="memory_nba",
            ))

        alt_text = "; ".join(f"{a} ({s:.2f})" for a, s in scored_actions[1:4])
        if alt_text:
            note_body = (
                f"Memory-Informed Next Best Action Analysis:\n"
                f"- Chosen: {best_action} ({scored_actions[0][1]:.2f})\n"
                f"- Alternatives: {alt_text}\n"
                f"- Stage: {current_stage}\n"
                f"- Memories consulted: {len(memories)}\n"
            )
            if citation:
                note_body += f"- Explanation: {citation.explanation}\n"
            tasks.append(Task(
                id=f"{self._ID}_note",
                type=TaskType.CREATE_NOTE,
                label=f"Record memory-NBA analysis for {company_name}",
                instructions=f"Record the memory-informed NBA analysis.",
                payload=CreateNotePayload(
                    body=note_body,
                    contact_id=contact_id,
                    company_id=enriched.get("company_id", ""),
                    opportunity_id=opportunity_id,
                ),
                dependencies=[f"{self._ID}_action"],
                reasoning_trace="Memory NBA: record analysis",
                reasoning_goal="memory_nba",
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
                    condition="memory_nba_action",
                    requirement=t.approval.value,
                    reason=f"Memory-informed NBA: {t.label}",
                ))
        return rules


def _compute_memory_boosted_scores(
    context: dict, memories: list,
) -> list[tuple[str, float]]:
    stage = context.get("current_stage", "discovery")
    last_action = context.get("last_action_type", "")
    days_since_last = context.get("days_since_last_contact", 30)
    engagement_score = context.get("engagement_score", 0.5)

    stage_weights = {
        "discovery": {"send_follow_up": 0.9, "schedule_demo": 0.8, "share_case_study": 0.7, "check_in": 0.6},
        "qualified": {"schedule_demo": 0.95, "send_proposal": 0.85, "share_case_study": 0.8, "send_follow_up": 0.6},
        "proposal": {"send_proposal": 0.9, "schedule_demo": 0.8, "check_in": 0.7, "request_referral": 0.5},
        "negotiation": {"check_in": 0.9, "send_follow_up": 0.8, "request_referral": 0.6},
        "closed_won": {"request_referral": 0.8, "check_in": 0.7, "send_newsletter": 0.5},
        "closed_lost": {"check_in": 0.6, "send_newsletter": 0.4},
    }.get(stage, {"send_follow_up": 0.5})

    base_scores = {
        "send_follow_up": 0.9, "schedule_demo": 0.85, "send_proposal": 0.8,
        "check_in": 0.7, "share_case_study": 0.65, "request_referral": 0.5,
        "send_newsletter": 0.3,
    }

    memory_boost = _calculate_memory_boost(memories)
    scored: list[tuple[str, float]] = []
    for action, base in base_scores.items():
        stage_weight = stage_weights.get(action, 0.5)
        recency = max(0.0, 1.0 - (days_since_last / 90))
        boost = memory_boost.get(action, 1.0)
        score = base * stage_weight * (0.5 + 0.5 * recency) * boost
        if action == last_action:
            score *= 0.5
        if engagement_score < 0.3 and action in ("send_proposal", "request_referral"):
            score *= 0.6
        scored.append((action, score))

    scored.sort(key=lambda x: -x[1])
    return scored


def _calculate_memory_boost(memories: list) -> dict[str, float]:
    boost: dict[str, float] = {a: 1.0 for a in MEMORY_BOOST}
    for m in memories:
        memory_type = m.memory_type.value if hasattr(m.memory_type, "value") else str(m.memory_type)
        if memory_type == "meeting":
            boost["schedule_demo"] *= 1.3
            boost["send_follow_up"] *= 1.1
        elif memory_type == "outcome":
            result = getattr(m, "result", "")
            if "won" in str(result).lower() or "positive" in str(result).lower():
                boost["send_proposal"] *= 1.2
                boost["request_referral"] *= 1.15
            elif "lost" in str(result).lower():
                boost["check_in"] *= 1.3
                boost["share_case_study"] *= 1.2
        elif memory_type == "preference":
            key = getattr(m, "preference_key", "")
            value = getattr(m, "preference_value", "")
            if "demo" in str(key).lower() and "yes" in str(value).lower():
                boost["schedule_demo"] *= 1.4
            if "referral" in str(key).lower() and "yes" in str(value).lower():
                boost["request_referral"] *= 1.3
            if "newsletter" in str(key).lower() and "no" in str(value).lower():
                boost["send_newsletter"] *= 0.5
        elif memory_type == "conversation":
            objections = getattr(m, "objections", [])
            if any("pricing" in str(o).lower() for o in objections):
                boost["share_case_study"] *= 1.2
                boost["schedule_demo"] *= 1.1
    return boost


memory_nba_strategy = MemoryNextBestActionStrategy()
