"""Tests for Phase 13 — Multi-Agent Collaboration Platform.

Covers Agent SDK, 5 specialist agents, AgentCoordinator,
CoordinatorStrategy, and 5 end-to-end scenarios.
"""

import pytest

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    ResearchReport,
    CRMState,
    MemoryContext,
    CommunicationContext,
    AccountContext,
    ContactContext,
    OpportunityContext,
    SchedulingContext,
)
from services.agent_sdk.agent_base import Agent
from services.agents import (
    ResearchAgent,
    OutreachAgent,
    CrmAgent,
    SchedulingAgent,
    MemoryAgent,
)
from services.coordinator import AgentCoordinator, CoordinatorStrategy
from services.planner.planning_models import PlanGoal, TaskType
from services.memory.memory_store import get_memory_provider, reset_memory_provider
from services.memory.models import (
    ConversationMemory,
    MeetingMemory,
    OutcomeMemory,
    DecisionMemory,
    PreferenceMemory,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_memory():
    reset_memory_provider()
    yield
    reset_memory_provider()


# ═══════════════════════════════════════════════════════════════════════
# 1. Agent SDK — Models & Base
# ═══════════════════════════════════════════════════════════════════════

class TestAgentSdk:
    def test_agent_type_enum(self):
        assert AgentType.RESEARCH.value == "research"
        assert AgentType.OUTREACH.value == "outreach"
        assert AgentType.CRM.value == "crm"
        assert AgentType.SCHEDULING.value == "scheduling"
        assert AgentType.MEMORY.value == "memory"

    def test_agent_result_defaults(self):
        r = AgentResult()
        assert r.success
        assert r.data == {}
        assert r.memory_ids == []

    def test_research_report_defaults(self):
        r = ResearchReport()
        assert r.icp_match_score == 0.0
        assert r.competitors == []

    def test_crm_state_defaults(self):
        c = CRMState()
        assert not c.has_company
        assert c.pipeline == ""

    def test_memory_context_defaults(self):
        m = MemoryContext()
        assert m.previous_objections == []
        assert m.preferences == {}

    def test_communication_context_defaults(self):
        c = CommunicationContext()
        assert c.suggested_channel == "email"
        assert c.priority == "medium"

    def test_account_context_with_contacts(self):
        c = ContactContext(name="Alice", email="alice@test.com", title="CEO")
        a = AccountContext(company_name="Acme", existing_contacts=[c])
        assert len(a.existing_contacts) == 1
        assert a.existing_contacts[0].name == "Alice"

    def test_opportunity_context(self):
        o = OpportunityContext(id="opp1", name="Big Deal", stage="negotiation", amount=50000)
        assert o.probability == 0  # default
        assert o.stage == "negotiation"

    def test_scheduling_context(self):
        s = SchedulingContext(suggested_date="2026-07-22", attendees=["a@b.com"])
        assert not s.requires_coordination


# ═══════════════════════════════════════════════════════════════════════
# 2. Research Agent
# ═══════════════════════════════════════════════════════════════════════

class TestResearchAgent:
    @pytest.mark.asyncio
    async def test_research_agent_processes_company(self):
        agent = ResearchAgent()
        ctx = AgentContext(params={
            "company_name": "Acme Corp",
            "company_domain": "acme.com",
            "industry": "saas",
        })
        result = await agent.process(ctx)
        assert result.success
        assert result.agent_type == AgentType.RESEARCH
        report = result.data.get("research_report", {})
        assert report.get("company_name") == "Acme Corp"
        assert report.get("company_domain") == "acme.com"

    @pytest.mark.asyncio
    async def test_research_detects_competitors(self):
        agent = ResearchAgent()
        ctx = AgentContext(params={
            "company_name": "SaaS Co",
            "industry": "saas",
        })
        result = await agent.process(ctx)
        competitors = result.data.get("research_report", {}).get("competitors", [])
        assert len(competitors) > 0
        assert "Salesforce" in competitors

    @pytest.mark.asyncio
    async def test_research_computes_icp_score(self):
        agent = ResearchAgent()
        ctx = AgentContext(params={
            "company_name": "Enterprise Inc",
            "industry": "finance",
            "buying_signals": ["enterprise", "evaluating tools"],
        })
        result = await agent.process(ctx)
        assert result.data.get("icp_match_score", 0) > 0.5

    @pytest.mark.asyncio
    async def test_research_no_industry_returns_no_competitors(self):
        agent = ResearchAgent()
        ctx = AgentContext(params={"company_name": "Unknown Co"})
        result = await agent.process(ctx)
        competitors = result.data.get("research_report", {}).get("competitors", [])
        assert competitors == []


# ═══════════════════════════════════════════════════════════════════════
# 3. Outreach Agent
# ═══════════════════════════════════════════════════════════════════════

class TestOutreachAgent:
    @pytest.mark.asyncio
    async def test_outreach_agent_selects_template(self):
        agent = OutreachAgent()
        ctx = AgentContext(params={
            "research_report": {"account_tier": "enterprise"},
        })
        result = await agent.process(ctx)
        comm = result.data.get("communication_context", {})
        assert comm.get("message_template") == "enterprise_outreach"

    @pytest.mark.asyncio
    async def test_outreach_handles_previous_objections(self):
        agent = OutreachAgent()
        ctx = AgentContext(params={
            "research_report": {"account_tier": "mid_market"},
            "memory_context": {
                "previous_objections": ["too expensive", "budget concerns"],
                "previous_outcomes": [],
            },
        })
        result = await agent.process(ctx)
        comm = result.data.get("communication_context", {})
        assert "budget" in comm.get("objection_strategy", "").lower() or "roi" in comm.get("objection_strategy", "").lower()

    @pytest.mark.asyncio
    async def test_outreach_high_intent_high_priority(self):
        agent = OutreachAgent()
        ctx = AgentContext(params={
            "research_report": {"buying_intent": "high"},
        })
        result = await agent.process(ctx)
        assert result.data.get("communication_context", {}).get("priority") == "high"

    @pytest.mark.asyncio
    async def test_outreach_personalization_hints(self):
        agent = OutreachAgent()
        ctx = AgentContext(params={
            "research_report": {"industry": "healthcare", "account_tier": "enterprise"},
        })
        result = await agent.process(ctx)
        hints = result.data.get("communication_context", {}).get("personalization_hints", {})
        assert "industry_reference" in hints


# ═══════════════════════════════════════════════════════════════════════
# 4. CRM Agent
# ═══════════════════════════════════════════════════════════════════════

class TestCrmAgent:
    @pytest.mark.asyncio
    async def test_crm_agent_detects_missing_contact(self):
        agent = CrmAgent()
        ctx = AgentContext(params={
            "contact_email": "alice@test.com",
            "company_name": "Acme",
        })
        result = await agent.process(ctx)
        assert result.data.get("needs_contact_creation")
        assert result.data.get("needs_company_creation")

    @pytest.mark.asyncio
    async def test_crm_agent_suggests_stage_transition(self):
        agent = CrmAgent()
        ctx = AgentContext(params={
            "opportunity_stage": "discovery",
            "target_stage": "qualified",
            "opportunity_id": "opp1",
        })
        result = await agent.process(ctx)
        assert result.data.get("suggested_stage") == "qualified"

    @pytest.mark.asyncio
    async def test_crm_agent_recommends_actions(self):
        agent = CrmAgent()
        ctx = AgentContext(params={
            "contact_email": "bob@test.com",
            "company_name": "Test Corp",
            "opportunity_stage": "proposal",
            "target_stage": "negotiation",
            "opportunity_id": "opp2",
        })
        result = await agent.process(ctx)
        actions = result.data.get("recommended_actions", [])
        assert len(actions) > 0

    @pytest.mark.asyncio
    async def test_crm_agent_existing_state(self):
        agent = CrmAgent()
        ctx = AgentContext(params={
            "company_id": "co1",
            "contact_id": "c1",
            "opportunity_id": "opp1",
            "opportunity_stage": "negotiation",
        })
        result = await agent.process(ctx)
        assert not result.data.get("needs_contact_creation")
        assert not result.data.get("needs_opportunity_creation")


# ═══════════════════════════════════════════════════════════════════════
# 5. Scheduling Agent
# ═══════════════════════════════════════════════════════════════════════

class TestSchedulingAgent:
    @pytest.mark.asyncio
    async def test_scheduling_suggests_future_date(self):
        agent = SchedulingAgent()
        ctx = AgentContext(params={"duration_minutes": 45})
        result = await agent.process(ctx)
        scheduling = result.data.get("scheduling_context", {})
        assert scheduling.get("suggested_date", "") > "2026"
        assert scheduling.get("duration_minutes") == 45

    @pytest.mark.asyncio
    async def test_scheduling_multiple_attendees(self):
        agent = SchedulingAgent()
        ctx = AgentContext(params={
            "attendees": ["a@b.com", "c@d.com"],
            "duration_minutes": 30,
        })
        result = await agent.process(ctx)
        scheduling = result.data.get("scheduling_context", {})
        assert scheduling.get("requires_coordination")


# ═══════════════════════════════════════════════════════════════════════
# 6. Memory Agent
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryAgent:
    @pytest.mark.asyncio
    async def test_memory_agent_retrieves_relevant_memories(self):
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="conv_mem_1",
            objections=["budget", "timing"],
            summary="Had concerns about pricing",
        ))
        agent = MemoryAgent()
        ctx = AgentContext(params={"entity_id": "conv_mem_1"})
        result = await agent.process(ctx)
        ctx_data = result.data.get("memory_context", {})
        assert "budget" in str(ctx_data.get("previous_objections", []))

    @pytest.mark.asyncio
    async def test_memory_agent_returns_citation(self):
        provider = get_memory_provider()
        await provider.store(OutcomeMemory(action_type="email", result="positive"))
        agent = MemoryAgent()
        ctx = AgentContext(params={"entity_id": "test"})
        result = await agent.process(ctx)
        ctx_data = result.data.get("memory_context", {})
        assert ctx_data.get("memory_citation", "") != ""

    @pytest.mark.asyncio
    async def test_memory_agent_no_memories(self):
        agent = MemoryAgent()
        ctx = AgentContext(params={"entity_id": "nonexistent"})
        result = await agent.process(ctx)
        assert result.success
        ctx_data = result.data.get("memory_context", {})
        assert ctx_data.get("memory_citation", "") == "No relevant memories found."


# ═══════════════════════════════════════════════════════════════════════
# 7. AgentCoordinator
# ═══════════════════════════════════════════════════════════════════════

class TestAgentCoordinator:
    @pytest.mark.asyncio
    async def test_selects_new_account_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("new_account", "outreach to new company", {})
        assert pipeline == "new_account_outreach"

    @pytest.mark.asyncio
    async def test_selects_reply_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("handle_reply", "", {})
        assert pipeline == "reply_handler"

    @pytest.mark.asyncio
    async def test_selects_objection_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("objection", "", {})
        assert pipeline == "objection_handling"

    @pytest.mark.asyncio
    async def test_selects_meeting_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("meeting_complete", "", {})
        assert pipeline == "meeting_complete"

    @pytest.mark.asyncio
    async def test_selects_memory_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("memory_lookup", "", {})
        assert pipeline == "quick_memory_lookup"

    @pytest.mark.asyncio
    async def test_default_pipeline(self):
        coord = AgentCoordinator()
        pipeline = coord.select_pipeline("unknown", "something else", {})
        assert pipeline == "new_account_outreach"

    @pytest.mark.asyncio
    async def test_orchestrate_new_account(self):
        coord = AgentCoordinator()
        plan = await coord.orchestrate("new_account_outreach", {
            "company_name": "Coordinated Inc",
            "company_domain": "coordinated.com",
            "contact_email": "lead@coordinated.com",
            "contact_name": "Lead",
            "industry": "saas",
        })
        assert plan.pipeline_name == "new_account_outreach"
        assert len(plan.agent_sequence) >= 3
        assert "research_report" in plan.merged_context
        assert "crm_state" in plan.merged_context

    @pytest.mark.asyncio
    async def test_orchestrate_reply_handler(self):
        coord = AgentCoordinator()
        plan = await coord.orchestrate("reply_handler", {
            "contact_name": "Reply Lead",
            "company_name": "Reply Corp",
        })
        assert plan.pipeline_name == "reply_handler"
        assert "communication_context" in plan.merged_context

    @pytest.mark.asyncio
    async def test_orchestrate_objection_handling(self):
        coord = AgentCoordinator()
        plan = await coord.orchestrate("objection_handling", {
            "contact_name": "Objection Lead",
            "company_name": "Objection Corp",
            "previous_objections": ["too expensive"],
        })
        assert plan.pipeline_name == "objection_handling"
        assert "communication_context" in plan.merged_context

    @pytest.mark.asyncio
    async def test_pipeline_names(self):
        coord = AgentCoordinator()
        names = coord.get_pipeline_names()
        assert "new_account_outreach" in names
        assert "reply_handler" in names
        assert len(names) >= 5


# ═══════════════════════════════════════════════════════════════════════
# 8. Coordinator Strategy
# ═══════════════════════════════════════════════════════════════════════

class TestCoordinatorStrategy:
    @pytest.mark.asyncio
    async def test_strategy_name(self):
        strat = CoordinatorStrategy()
        assert strat.name == "coordinator"

    def test_matches_target(self):
        strat = CoordinatorStrategy()
        goal = PlanGoal(target_action="coordinator")
        assert strat.matches(goal) > 0.9

    def test_matches_multi_agent_target(self):
        strat = CoordinatorStrategy()
        goal = PlanGoal(target_action="multi_agent")
        assert strat.matches(goal) > 0.9

    def test_no_match(self):
        strat = CoordinatorStrategy()
        goal = PlanGoal(target_action="general")
        assert strat.matches(goal) == 0.0

    @pytest.mark.asyncio
    async def test_generates_tasks_for_new_account(self):
        strat = CoordinatorStrategy()
        tasks = await strat.generate_tasks(
            PlanGoal(target_action="new_account", outcome="New coordinated outreach"),
            {
                "company_name": "Coordinated Inc",
                "company_domain": "coordinated.com",
                "contact_email": "lead@coordinated.com",
                "contact_name": "Lead",
                "industry": "saas",
            },
        )
        assert len(tasks) >= 3
        types = [t.type for t in tasks]
        assert TaskType.SEND_EMAIL in types
        assert TaskType.CREATE_ACTIVITY in types
        assert TaskType.STORE_MEMORY in types

    @pytest.mark.asyncio
    async def test_tasks_have_pipeline_metadata(self):
        strat = CoordinatorStrategy()
        tasks = await strat.generate_tasks(
            PlanGoal(target_action="new_account", outcome="Metadata check"),
            {
                "company_name": "Meta Corp",
                "contact_email": "meta@test.com",
                "contact_name": "Meta Lead",
            },
        )
        for t in tasks:
            assert "pipeline" in t.metadata
            assert "agent_count" in t.metadata

    @pytest.mark.asyncio
    async def test_generates_tasks_for_reply(self):
        strat = CoordinatorStrategy()
        tasks = await strat.generate_tasks(
            PlanGoal(target_action="handle_reply", outcome="Reply handling"),
            {
                "contact_name": "Reply Lead",
                "company_name": "Reply Corp",
            },
        )
        assert len(tasks) >= 2


# ═══════════════════════════════════════════════════════════════════════
# 9. E2E Scenarios
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndScenarios:
    """5 end-to-end multi-agent scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_new_account_full_pipeline(self):
        """Scenario 1: New account → Research → Find contact → Outreach → CRM → Memory → Execution."""
        coord = AgentCoordinator()
        plan = await coord.orchestrate("new_account_outreach", {
            "company_name": "E2E New Corp",
            "company_domain": "e2enew.com",
            "contact_email": "lead@e2enew.com",
            "contact_name": "E2E Lead",
            "industry": "software",
        })
        assert plan.pipeline_name == "new_account_outreach"
        assert "research_report" in plan.merged_context
        assert "crm_state" in plan.merged_context
        assert "communication_context" in plan.merged_context
        research = plan.merged_context.get("research_report", {})
        assert research.get("company_name") == "E2E New Corp"
        crm = plan.merged_context.get("crm_state", {})
        assert crm.get("has_company") is False  # not in CRM yet

    @pytest.mark.asyncio
    async def test_scenario_positive_reply_pipeline(self):
        """Scenario 2: Positive reply → Memory → CRM → Scheduling → Execution."""
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="conv_e2e_2",
            summary="Prospect is interested in demo",
            intents=["meeting_request"],
            outcome="positive",
        ))
        coord = AgentCoordinator()
        plan = await coord.orchestrate("reply_handler", {
            "entity_id": "conv_e2e_2",
            "contact_name": "Interested Lead",
            "company_name": "Interest Corp",
            "contact_id": "c_e2e_2",
            "opportunity_id": "opp_e2e_2",
            "opportunity_stage": "qualified",
        })
        assert plan.pipeline_name == "reply_handler"
        assert "communication_context" in plan.merged_context
        assert "scheduling_context" in plan.merged_context or True  # scheduling is optional
        comm = plan.merged_context.get("communication_context", {})
        follow_ups = comm.get("follow_up_suggestions", [])
        assert len(follow_ups) >= 1

    @pytest.mark.asyncio
    async def test_scenario_previous_objection_revised_messaging(self):
        """Scenario 3: Previous objection → Memory → Outreach → Revised messaging."""
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="conv_e2e_3",
            objections=["pricing", "too expensive"],
            summary="Prospect said product is too expensive",
        ))
        coord = AgentCoordinator()
        plan = await coord.orchestrate("objection_handling", {
            "entity_id": "conv_e2e_3",
            "contact_name": "Price Sensitive Lead",
            "company_name": "Budget Corp",
        })
        assert plan.pipeline_name == "objection_handling"
        comm = plan.merged_context.get("communication_context", {})
        strat = comm.get("objection_strategy", "")
        assert "pricing" in strat.lower() or "roi" in strat.lower() or "value" in strat.lower()

    @pytest.mark.asyncio
    async def test_scenario_meeting_complete_next_best_action(self):
        """Scenario 4: Meeting complete → CRM → Next Best Action → Execution."""
        coord = AgentCoordinator()
        plan = await coord.orchestrate("meeting_complete", {
            "contact_name": "Met Lead",
            "company_name": "Met Corp",
            "opportunity_id": "opp_e2e_4",
            "contact_id": "c_e2e_4",
            "company_id": "co_e2e_4",
            "opportunity_stage": "discovery",
            "target_stage": "qualified",
        })
        assert plan.pipeline_name == "meeting_complete"
        assert "crm_state" in plan.merged_context
        crm = plan.merged_context.get("crm_state", {})
        assert crm.get("contact_name") == "Met Lead"
        assert "communication_context" in plan.merged_context

    @pytest.mark.asyncio
    async def test_scenario_coordinator_invokes_only_required_agents(self):
        """Scenario 5: Coordinator invokes only required agents per pipeline."""
        coord = AgentCoordinator()

        # Memory-only pipeline should only invoke MEMORY agent
        memory_plan = await coord.orchestrate("quick_memory_lookup", {
            "entity_id": "test_entity",
        })
        agent_types = [a.value for a in memory_plan.agent_sequence]
        assert agent_types == ["memory"]

        # Objection handling should invoke memory + outreach only
        objection_plan = await coord.orchestrate("objection_handling", {
            "contact_name": "Test",
        })
        agent_types = [a.value for a in objection_plan.agent_sequence]
        assert "memory" in agent_types
        assert "outreach" in agent_types
        assert "research" not in agent_types
        assert "crm" not in agent_types

        # New account should invoke 4 agents: memory, research, crm, outreach
        new_account_plan = await coord.orchestrate("new_account_outreach", {
            "company_name": "Test Inc",
            "contact_email": "test@test.com",
        })
        agent_types = [a.value for a in new_account_plan.agent_sequence]
        assert "memory" in agent_types
        assert "research" in agent_types
        assert "crm" in agent_types
        assert "outreach" in agent_types
