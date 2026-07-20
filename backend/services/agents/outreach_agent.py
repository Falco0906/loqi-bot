from __future__ import annotations

from typing import Any

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    CommunicationContext,
)
from services.agent_sdk.agent_base import Agent


class OutreachAgent(Agent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.OUTREACH

    @property
    def name(self) -> str:
        return "outreach_agent"

    @property
    def description(self) -> str:
        return "Plans messaging, personalization, and follow-up strategy."

    async def process(self, context: AgentContext) -> AgentResult:
        params = context.params
        research = params.get("research_report", {})
        crm_state = params.get("crm_state", {})
        memory = params.get("memory_context", {})

        previous_objections = memory.get("previous_objections", [])
        previous_outcomes = memory.get("previous_outcomes", [])
        account_tier = research.get("account_tier", "")
        buying_intent = research.get("buying_intent", "")

        follow_ups = _build_follow_up_suggestions(previous_objections, buying_intent)
        objection_strategy = _build_objection_strategy(previous_objections, account_tier)
        requires_approval = account_tier == "enterprise" or "proposal" in str(previous_outcomes)
        priority = "high" if buying_intent == "high" else "medium" if buying_intent == "medium" else "low"

        comm = CommunicationContext(
            suggested_channel="email",
            message_template=_select_template(account_tier, previous_outcomes),
            personalization_hints=_build_personalization_hints(research, memory),
            follow_up_suggestions=follow_ups,
            objection_strategy=objection_strategy,
            requires_approval=requires_approval,
            priority=priority,
        )

        return AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "communication_context": {
                    "suggested_channel": comm.suggested_channel,
                    "message_template": comm.message_template,
                    "personalization_hints": comm.personalization_hints,
                    "follow_up_suggestions": comm.follow_up_suggestions,
                    "objection_strategy": comm.objection_strategy,
                    "requires_approval": comm.requires_approval,
                    "priority": comm.priority,
                },
            },
        )


def _select_template(account_tier: str, previous_outcomes: list[str]) -> str:
    if any("meeting_booked" in o or "positive" in o for o in previous_outcomes):
        return "followup_value"
    if account_tier == "enterprise":
        return "enterprise_outreach"
    if account_tier == "mid_market":
        return "professional_outreach"
    return "cold_outreach"


def _build_personalization_hints(research: dict, memory: dict) -> dict:
    hints: dict[str, str] = {}
    industry = research.get("industry", "")
    if industry:
        hints["industry_reference"] = f"Reference {industry} industry challenges"
    tier = research.get("account_tier", "")
    if tier:
        hints["tier_approach"] = f"Use {tier} positioning"
    objections = memory.get("previous_objections", [])
    if objections:
        hints["objection_preemptive"] = f"Address previous concerns: {'; '.join(objections[:2])}"
    return hints


def _build_follow_up_suggestions(
    previous_objections: list[str],
    buying_intent: str,
) -> list[str]:
    suggestions = ["send_initial_outreach"]
    if "budget" in str(previous_objections).lower():
        suggestions.append("share_roi_case_study")
    if "timing" in str(previous_objections).lower():
        suggestions.append("offer_flexible_timing")
    if buying_intent == "high":
        suggestions.append("schedule_demo")
    elif buying_intent == "medium":
        suggestions.append("share_case_study")
    suggestions.append("follow_up_after_wait")
    return suggestions


def _build_objection_strategy(
    previous_objections: list[str],
    account_tier: str,
) -> str:
    if not previous_objections:
        return "proactive_value_proposition"
    obj_lower = [o.lower() for o in previous_objections]
    if "budget" in str(obj_lower) or "price" in str(obj_lower) or "expensive" in str(obj_lower):
        return "roi_focused_pricing"
    if "timing" in str(obj_lower):
        return "flexible_timing_and_urgency"
    if "competitor" in str(obj_lower):
        return "competitive_differentiation"
    return "value_first_approach"
