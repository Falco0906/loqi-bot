from __future__ import annotations

from typing import Any

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    CRMState,
    OpportunityContext,
)
from services.agent_sdk.agent_base import Agent


STAGE_PROBABILITY: dict[str, int] = {
    "discovery": 10,
    "qualified": 25,
    "proposal": 50,
    "negotiation": 75,
    "closed_won": 100,
    "closed_lost": 0,
}

STAGE_TRANSITIONS: dict[str, list[str]] = {
    "discovery": ["qualified", "closed_lost"],
    "qualified": ["proposal", "closed_lost"],
    "proposal": ["negotiation", "closed_lost"],
    "negotiation": ["closed_won", "closed_lost"],
}


class CrmAgent(Agent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.CRM

    @property
    def name(self) -> str:
        return "crm_agent"

    @property
    def description(self) -> str:
        return "Manages opportunity lifecycle, account state, and pipeline progression."

    async def process(self, context: AgentContext) -> AgentResult:
        params = context.params
        current_stage = params.get("opportunity_stage", "discovery")
        target_stage = params.get("target_stage", "")

        state = CRMState(
            has_company=bool(params.get("company_id")),
            company_id=params.get("company_id", ""),
            has_contact=bool(params.get("contact_id")),
            contact_id=params.get("contact_id", ""),
            contact_name=params.get("contact_name", ""),
            contact_email=params.get("contact_email", ""),
            contact_title=params.get("contact_title", ""),
            has_opportunity=bool(params.get("opportunity_id")),
            opportunity_id=params.get("opportunity_id", ""),
            opportunity_stage=current_stage,
            opportunity_amount=params.get("opportunity_amount", 0.0),
            pipeline=params.get("pipeline", "default"),
        )

        suggested_stage = _suggest_stage_progression(current_stage, target_stage, params)
        needs_contact_creation = not state.has_contact and bool(params.get("contact_email"))
        needs_company_creation = not state.has_company and bool(params.get("company_name"))
        needs_opportunity_creation = not state.has_opportunity and needs_contact_creation

        return AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "crm_state": {
                    "has_company": state.has_company,
                    "company_id": state.company_id,
                    "has_contact": state.has_contact,
                    "contact_id": state.contact_id,
                    "contact_name": state.contact_name,
                    "contact_email": state.contact_email,
                    "has_opportunity": state.has_opportunity,
                    "opportunity_id": state.opportunity_id,
                    "opportunity_stage": state.opportunity_stage,
                    "opportunity_amount": state.opportunity_amount,
                    "pipeline": state.pipeline,
                },
                "suggested_stage": suggested_stage,
                "suggested_probability": STAGE_PROBABILITY.get(suggested_stage, 10),
                "needs_contact_creation": needs_contact_creation,
                "needs_company_creation": needs_company_creation,
                "needs_opportunity_creation": needs_opportunity_creation,
                "recommended_actions": _recommend_actions(state, suggested_stage, params),
            },
        )


def _suggest_stage_progression(
    current_stage: str,
    target_stage: str,
    params: dict,
) -> str:
    valid_transitions = STAGE_TRANSITIONS.get(current_stage, [])
    if target_stage and target_stage in valid_transitions:
        return target_stage
    if valid_transitions:
        return valid_transitions[0]
    return current_stage


def _recommend_actions(state: CRMState, suggested_stage: str, params: dict) -> list[dict]:
    actions: list[dict] = []
    if not state.has_company and params.get("company_name"):
        actions.append({"type": "create_company", "priority": "high"})
    if not state.has_contact and params.get("contact_email"):
        actions.append({"type": "create_contact", "priority": "high"})
    if not state.has_opportunity and params.get("company_name"):
        actions.append({"type": "create_opportunity", "priority": "high"})
    if state.opportunity_stage != suggested_stage and suggested_stage:
        actions.append({"type": "update_opportunity_stage", "priority": "medium"})
    return actions
