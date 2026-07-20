"""Tests for Phase 11 — Sales Intelligence Platform.

Covers CRM adapter SDK, CRM intelligence modules, and
CRM-aware planning strategies.
"""

import pytest

from services.planner.planning_models import TaskType, PlanGoal
from services.planner.payloads import (
    FindContactPayload,
    CreateContactPayload,
    UpdateContactPayload,
    FindCompanyPayload,
    CreateCompanyPayload,
    CreateOpportunityPayload,
    UpdateOpportunityPayload,
    CreateActivityPayload,
    CreateNotePayload,
    AssignOwnerPayload,
)
from services.adapters.crm import CrmAdapter
from services.adapters.crm.models import (
    Contact,
    Company,
    Opportunity,
    Activity,
    Note,
    CrmOwner,
    ContactSearchResult,
    CompanySearchResult,
)
from services.intelligence.account_intelligence import generate_account_intelligence
from services.intelligence.contact_intelligence import generate_contact_intelligence
from services.intelligence.activity_intelligence import (
    suggest_next_activity_type,
    infer_activity_priority,
    should_log_activity,
    build_activity_summary,
)
from services.planner.strategies.pipeline_outreach import pipeline_outreach_strategy
from services.planner.strategies.opportunity_development import opportunity_development_strategy
from services.planner.strategies.next_best_action import next_best_action_strategy


# ═══════════════════════════════════════════════════════════════════════
# 1. CRM Adapter Models
# ═══════════════════════════════════════════════════════════════════════

class TestCrmModels:
    def test_contact_full_name(self):
        c = Contact(first_name="John", last_name="Doe")
        assert c.full_name == "John Doe"

    def test_contact_empty_name(self):
        c = Contact()
        assert c.full_name == ""

    def test_contact_default_lifecycle(self):
        c = Contact(email="test@example.com")
        assert c.lifecycle_stage == "lead"

    def test_opportunity_defaults(self):
        opp = Opportunity(name="Test Deal")
        assert opp.stage == "discovery"
        assert opp.pipeline == "default"
        assert opp.probability == 10

    def test_search_result_empty(self):
        result = ContactSearchResult()
        assert result.contacts == []
        assert result.total == 0

    def test_company_search_result(self):
        result = CompanySearchResult(companies=[Company(name="Acme")], total=1, query="acme")
        assert len(result.companies) == 1
        assert result.total == 1
        assert result.query == "acme"


# ═══════════════════════════════════════════════════════════════════════
# 2. CRM Payloads
# ═══════════════════════════════════════════════════════════════════════

class TestCrmPayloads:
    def test_find_contact_payload(self):
        p = FindContactPayload(email="test@example.com")
        assert p.email == "test@example.com"
        assert p.validate() == []

    def test_find_contact_no_criteria(self):
        p = FindContactPayload()
        errors = p.validate()
        assert errors

    def test_create_contact_valid(self):
        p = CreateContactPayload(email="new@example.com", first_name="Jane")
        assert p.validate() == []

    def test_create_contact_no_email(self):
        p = CreateContactPayload()
        errors = p.validate()
        assert errors

    def test_update_contact(self):
        p = UpdateContactPayload(contact_id="123", fields={"title": "CEO"})
        assert p.validate() == []

    def test_update_contact_no_id(self):
        p = UpdateContactPayload()
        errors = p.validate()
        assert errors

    def test_find_company_payload(self):
        p = FindCompanyPayload(domain="acme.com")
        assert p.domain == "acme.com"
        assert p.validate() == []

    def test_find_company_no_criteria(self):
        p = FindCompanyPayload()
        errors = p.validate()
        assert errors

    def test_create_company_payload(self):
        p = CreateCompanyPayload(name="Acme Corp", domain="acme.com")
        assert p.validate() == []

    def test_create_company_no_name(self):
        p = CreateCompanyPayload()
        errors = p.validate()
        assert errors

    def test_create_opportunity_valid(self):
        p = CreateOpportunityPayload(name="Big Deal", company_id="c1", amount=50000)
        assert p.validate() == []

    def test_create_opportunity_no_name(self):
        p = CreateOpportunityPayload()
        errors = p.validate()
        assert errors

    def test_update_opportunity(self):
        p = UpdateOpportunityPayload(opportunity_id="opp1", stage="negotiation")
        assert p.validate() == []

    def test_create_activity_valid(self):
        p = CreateActivityPayload(subject="Check-in", type="email")
        assert p.validate() == []

    def test_create_activity_no_subject(self):
        p = CreateActivityPayload()
        errors = p.validate()
        assert errors

    def test_create_note_valid(self):
        p = CreateNotePayload(body="Great call", contact_id="c1")
        assert p.validate() == []

    def test_create_note_no_target(self):
        p = CreateNotePayload(body="Note text")
        errors = p.validate()
        assert errors

    def test_create_note_no_body(self):
        p = CreateNotePayload(contact_id="c1")
        errors = p.validate()
        assert errors

    def test_assign_owner_valid(self):
        p = AssignOwnerPayload(owner_email="alice@co.com", contact_id="c1")
        assert p.validate() == []

    def test_assign_owner_no_email(self):
        p = AssignOwnerPayload(contact_id="c1")
        errors = p.validate()
        assert errors

    def test_assign_owner_no_target(self):
        p = AssignOwnerPayload(owner_email="alice@co.com")
        errors = p.validate()
        assert errors

    def test_payload_type_name(self):
        assert FindContactPayload().payload_type == "FindContactPayload"
        assert CreateOpportunityPayload().payload_type == "CreateOpportunityPayload"


# ═══════════════════════════════════════════════════════════════════════
# 3. CRM Adapter
# ═══════════════════════════════════════════════════════════════════════

class TestCrmAdapter:
    def test_adapter_metadata(self):
        adapter = CrmAdapter()
        meta = adapter.metadata
        assert meta.name == "crm"
        assert meta.version == "1.0.0"
        assert "find_contact" in meta.supported_operations
        assert "create_contact" in meta.supported_operations
        assert "create_opportunity" in meta.supported_operations

    def test_adapter_tags(self):
        adapter = CrmAdapter()
        assert "crm" in adapter.metadata.tags
        assert "sales" in adapter.metadata.tags

    async def _run(self, adapter, action, params):
        from services.adapters.adapter_context import AdapterContext
        ctx = AdapterContext.build(
            execution_session_id="test",
            execution_task_id="t1",
            action=action,
            params=params,
        )
        return await adapter.execute(ctx)

    @pytest.mark.asyncio
    async def test_find_contact_empty(self):
        adapter = CrmAdapter()
        result = await self._run(adapter, "find_contact", {"email": "none@x.com"})
        assert result.success
        assert result.data["total"] == 0
        assert result.data["ok"]

    @pytest.mark.asyncio
    async def test_create_contact(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("create_contact", {
            "email": "jane@example.com",
            "first_name": "Jane",
            "last_name": "Doe",
        }))
        assert result.success
        assert result.data["ok"]
        assert result.data["contact"]["email"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_update_contact(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("update_contact", {
            "contact_id": "c1",
            "fields": {"title": "CEO"},
        }))
        assert result.success
        assert result.data["updated_fields"]["title"] == "CEO"

    @pytest.mark.asyncio
    async def test_find_company_empty(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("find_company", {"domain": "unknown.com"}))
        assert result.success
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_create_company(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("create_company", {
            "name": "Acme Corp",
            "domain": "acme.com",
        }))
        assert result.success
        assert result.data["company"]["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_create_opportunity(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("create_opportunity", {
            "name": "Big Deal",
            "amount": 50000.0,
            "stage": "discovery",
        }))
        assert result.success
        assert result.data["opportunity"]["name"] == "Big Deal"
        assert result.data["opportunity"]["amount"] == 50000.0

    @pytest.mark.asyncio
    async def test_update_opportunity(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("update_opportunity", {
            "opportunity_id": "opp1",
            "stage": "negotiation",
        }))
        assert result.success
        assert result.data["stage"] == "negotiation"

    @pytest.mark.asyncio
    async def test_create_activity(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("create_activity", {
            "type": "email",
            "subject": "Follow-up",
            "body": "Great call today",
        }))
        assert result.success
        assert result.data["activity"]["subject"] == "Follow-up"

    @pytest.mark.asyncio
    async def test_create_note(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("create_note", {
            "body": "Key insight from call",
            "contact_id": "c1",
        }))
        assert result.success
        assert result.data["note"]["body"] == "Key insight from call"

    @pytest.mark.asyncio
    async def test_assign_owner(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("assign_owner", {
            "owner_email": "alice@co.com",
            "contact_id": "c1",
        }))
        assert result.success
        assert result.data["owner_email"] == "alice@co.com"

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        adapter = CrmAdapter()
        result = await adapter.execute(self._ctx("bogus_action", {}))
        assert not result.success

    def _ctx(self, action, params):
        from services.adapters.adapter_context import AdapterContext
        return AdapterContext.build(
            execution_session_id="test",
            execution_task_id="t1",
            action=action,
            params=params,
        )


# ═══════════════════════════════════════════════════════════════════════
# 4. Account Intelligence
# ═══════════════════════════════════════════════════════════════════════

class TestAccountIntelligence:
    def test_enterprise_tier_keywords(self):
        result = generate_account_intelligence({
            "name": "Big Corp",
            "industry": "Finance",
            "buying_signals": ["enterprise"],
        })
        assert result["account_tier"] == "enterprise"

    def test_mid_market_by_size(self):
        result = generate_account_intelligence({
            "name": "Growth Co",
            "size": "5,000",
        })
        assert result["account_tier"] in ("mid_market", "enterprise")

    def test_smb_by_size(self):
        result = generate_account_intelligence({
            "name": "Startup Inc",
            "size": "100",
        })
        assert result["account_tier"] in ("smb",)

    def test_unknown_tier(self):
        result = generate_account_intelligence({"name": "Unknown"})
        assert result["account_tier"] == "unknown"

    def test_high_buying_intent(self):
        result = generate_account_intelligence({
            "name": "Hot Prospect",
            "recent_events": ["evaluating tools", "rfp"],
        })
        assert result["buying_intent"] == "high"

    def test_no_signals(self):
        result = generate_account_intelligence({"name": "Quiet Co"})
        assert result["buying_intent"] == "unknown"

    def test_summary_contains_name(self):
        result = generate_account_intelligence({
            "name": "Acme",
            "industry": "Tech",
        })
        assert "Acme" in result["summary"]
        assert "Tech" in result["summary"]


# ═══════════════════════════════════════════════════════════════════════
# 5. Contact Intelligence
# ═══════════════════════════════════════════════════════════════════════

class TestContactIntelligence:
    def test_c_level_authority(self):
        result = generate_contact_intelligence({"title": "CEO"})
        assert result["decision_authority"] == "c_level"

    def test_vp_authority(self):
        result = generate_contact_intelligence({"title": "VP of Sales"})
        assert result["decision_authority"] == "vp_director"

    def test_manager_authority(self):
        result = generate_contact_intelligence({"title": "Marketing Manager"})
        assert result["decision_authority"] == "manager"

    def test_ic_authority(self):
        result = generate_contact_intelligence({"title": "Software Engineer"})
        assert result["decision_authority"] == "individual_contributor"

    def test_unknown_authority(self):
        result = generate_contact_intelligence({"title": ""})
        assert result["decision_authority"] == "unknown"

    def test_high_relevance_sales(self):
        result = generate_contact_intelligence({"title": "Sales Director"})
        assert result["relevance_score"] == "high"

    def test_medium_relevance_ops(self):
        result = generate_contact_intelligence({"title": "Operations Manager"})
        assert result["relevance_score"] == "medium"

    def test_low_relevance_hr(self):
        result = generate_contact_intelligence({"title": "HR Specialist"})
        assert result["relevance_score"] == "low"

    def test_summary_format(self):
        result = generate_contact_intelligence({"title": "CEO"})
        assert "ceo" in result["summary"] or "C Level" in result["summary"]

    def test_with_enrichment(self):
        result = generate_contact_intelligence(
            {"title": "Engineer"},
            {"role": "sales"},
        )
        assert result["relevance_score"] == "high"


# ═══════════════════════════════════════════════════════════════════════
# 6. Activity Intelligence
# ═══════════════════════════════════════════════════════════════════════

class TestActivityIntelligence:
    def test_suggest_meeting_first(self):
        result = suggest_next_activity_type([])
        assert result == "meeting"

    def test_suggest_call_after_meetings(self):
        history = [{"type": "meeting"}, {"type": "meeting"}, {"type": "meeting"}]
        result = suggest_next_activity_type(history)
        assert result == "call"

    def test_suggest_email_in_negotiation(self):
        result = suggest_next_activity_type([], opportunity_stage="negotiation")
        assert result == "email"

    def test_infer_high_priority(self):
        result = infer_activity_priority("Demo proposal", "Scheduling a demo")
        assert result == "high"

    def test_infer_medium_priority(self):
        result = infer_activity_priority("Follow up call", "Checking in")
        assert result == "medium"

    def test_infer_low_priority(self):
        result = infer_activity_priority("Newsletter", "Monthly update")
        assert result == "low"

    def test_should_log_outbound(self):
        assert should_log_activity("outbound_email", "discovery", True)

    def test_should_not_log_no_crm(self):
        assert not should_log_activity("outbound_email", "discovery", False)

    def test_build_summary(self):
        result = build_activity_summary("email", "Follow-up", "completed")
        assert result["type"] == "email"
        assert result["subject"] == "Follow-up"
        assert result["outcome"] == "completed"
        assert result["priority"]  # should be inferred


# ═══════════════════════════════════════════════════════════════════════
# 7. Pipeline Outreach Strategy
# ═══════════════════════════════════════════════════════════════════════

class TestPipelineOutreachStrategy:
    def test_strategy_name(self):
        assert pipeline_outreach_strategy.name == "pipeline_outreach"

    def test_matches_pipeline_target(self):
        goal = PlanGoal(target_action="pipeline_outreach")
        assert pipeline_outreach_strategy.matches(goal) > 0.9

    def test_matches_crm_target(self):
        goal = PlanGoal(target_action="crm_campaign")
        assert pipeline_outreach_strategy.matches(goal) > 0.9

    def test_no_match(self):
        goal = PlanGoal(target_action="general_engagement")
        assert pipeline_outreach_strategy.matches(goal) == 0.0

    def test_generates_task_sequence(self):
        tasks = pipeline_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Pipeline outreach to Acme"),
            {
                "prospect_email": "jane@acme.com",
                "prospect_name": "Jane Doe",
                "company_name": "Acme Corp",
                "company_domain": "acme.com",
            },
        )
        assert len(tasks) >= 7
        types = [t.type for t in tasks]
        assert TaskType.FIND_COMPANY in types
        assert TaskType.FIND_CONTACT in types
        assert TaskType.CREATE_CONTACT in types
        assert TaskType.CREATE_OPPORTUNITY in types
        assert TaskType.SEND_EMAIL in types
        assert TaskType.CREATE_ACTIVITY in types
        assert TaskType.WAIT_FOR_REPLY in types

    def test_generates_dependencies(self):
        tasks = pipeline_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Pipeline outreach"),
            {
                "prospect_email": "j@acme.com",
                "prospect_name": "Jane",
                "company_name": "Acme",
            },
        )
        deps = pipeline_outreach_strategy.dependencies(tasks)
        assert len(deps) > 0
        for source, target in deps:
            assert any(t.id == source for t in tasks)
            assert any(t.id == target for t in tasks)

    def test_scheduling_hints(self):
        hints = pipeline_outreach_strategy.scheduling(PlanGoal())
        assert hints.business_hours_only

    def test_approval_rules_contain_email(self):
        tasks = pipeline_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Approval test"),
            {
                "prospect_email": "j@acme.com",
                "prospect_name": "Jane",
                "company_name": "Acme",
            },
        )
        rules = pipeline_outreach_strategy.approval_rules(tasks)
        rule_types = {r.task_type for r in rules}
        assert TaskType.SEND_EMAIL in rule_types


# ═══════════════════════════════════════════════════════════════════════
# 8. Opportunity Development Strategy
# ═══════════════════════════════════════════════════════════════════════

class TestOpportunityDevelopmentStrategy:
    def test_strategy_name(self):
        assert opportunity_development_strategy.name == "opportunity_development"

    def test_matches_target(self):
        goal = PlanGoal(target_action="advance_opportunity")
        assert opportunity_development_strategy.matches(goal) > 0.9

    def test_no_match(self):
        goal = PlanGoal(target_action="general")
        assert opportunity_development_strategy.matches(goal) == 0.0

    def test_generates_tasks_from_discovery(self):
        tasks = opportunity_development_strategy.generate_tasks(
            PlanGoal(outcome="Advance opportunity"),
            {
                "current_stage": "discovery",
                "contact_name": "Jane",
                "company_name": "Acme",
                "opportunity_id": "opp1",
                "contact_id": "c1",
                "company_id": "co1",
            },
        )
        assert len(tasks) >= 3
        types = [t.type for t in tasks]
        assert TaskType.UPDATE_CRM in types
        assert TaskType.UPDATE_OPPORTUNITY in types
        assert TaskType.CREATE_ACTIVITY in types

    def test_closed_stage_returns_empty(self):
        tasks = opportunity_development_strategy.generate_tasks(
            PlanGoal(outcome="Closed"),
            {"current_stage": "closed_won"},
        )
        assert tasks == []

    def test_closed_lost_produces_close_task(self):
        tasks = opportunity_development_strategy.generate_tasks(
            PlanGoal(outcome="Lost deal"),
            {
                "current_stage": "negotiation",
                "target_stage": "closed_lost",
                "loss_reason": "Budget",
                "opportunity_id": "opp1",
            },
        )
        has_close = any(
            t.type == TaskType.UPDATE_OPPORTUNITY for t in tasks
        )
        assert has_close

    def test_adds_note_when_requested(self):
        tasks = opportunity_development_strategy.generate_tasks(
            PlanGoal(outcome="With note"),
            {
                "current_stage": "discovery",
                "target_stage": "qualified",
                "opportunity_id": "opp1",
                "add_note": True,
                "note_text": "Good discovery call",
            },
        )
        has_note = any(t.type == TaskType.CREATE_NOTE for t in tasks)
        assert has_note

    def test_approval_rules(self):
        tasks = opportunity_development_strategy.generate_tasks(
            PlanGoal(outcome="Approval check"),
            {
                "current_stage": "qualified",
                "target_stage": "proposal",
                "opportunity_id": "opp1",
            },
        )
        rules = opportunity_development_strategy.approval_rules(tasks)
        rule_types = {r.task_type for r in rules}
        assert TaskType.UPDATE_OPPORTUNITY in rule_types


# ═══════════════════════════════════════════════════════════════════════
# 9. Next Best Action Strategy
# ═══════════════════════════════════════════════════════════════════════

class TestNextBestActionStrategy:
    def test_strategy_name(self):
        assert next_best_action_strategy.name == "next_best_action"

    def test_matches_target(self):
        goal = PlanGoal(target_action="next_best_action")
        assert next_best_action_strategy.matches(goal) > 0.9

    def test_no_match(self):
        goal = PlanGoal(target_action="general")
        assert next_best_action_strategy.matches(goal) == 0.0

    def test_generates_action_with_context(self):
        tasks = next_best_action_strategy.generate_tasks(
            PlanGoal(outcome="Recommend action"),
            {
                "contact_name": "Jane",
                "company_name": "Acme",
                "current_stage": "discovery",
                "opportunity_id": "opp1",
                "contact_id": "c1",
                "company_id": "co1",
            },
        )
        assert len(tasks) >= 2
        types = [t.type for t in tasks]
        assert TaskType.SEND_EMAIL in types or TaskType.SCHEDULE_MEETING in types
        assert TaskType.CREATE_ACTIVITY in types
        assert TaskType.CREATE_NOTE in types

    def test_generates_note_with_analysis(self):
        tasks = next_best_action_strategy.generate_tasks(
            PlanGoal(outcome="Analyze"),
            {
                "contact_name": "Jane",
                "company_name": "Acme",
                "current_stage": "discovery",
                "opportunity_id": "opp1",
            },
        )
        notes = [t for t in tasks if t.type == TaskType.CREATE_NOTE]
        assert notes
        assert "Next Best Action Analysis" in notes[0].payload.body

    def test_requires_approval_for_proposal(self):
        tasks = next_best_action_strategy.generate_tasks(
            PlanGoal(outcome="Send proposal"),
            {
                "contact_name": "Jane",
                "company_name": "Acme",
                "current_stage": "proposal",
                "opportunity_id": "opp1",
            },
        )
        rules = next_best_action_strategy.approval_rules(tasks)
        assert rules

    def test_empty_context_falls_back_to_sensible_default(self):
        tasks = next_best_action_strategy.generate_tasks(
            PlanGoal(outcome="Empty"),
            {},
        )
        assert len(tasks) >= 1
        assert tasks[0].type in (TaskType.SEND_EMAIL, TaskType.SCHEDULE_MEETING)

    def test_scheduling_hints(self):
        hints = next_best_action_strategy.scheduling(PlanGoal())
        assert hints.min_delay_between_tasks == 5


# ═══════════════════════════════════════════════════════════════════════
# 10. TaskType Enum
# ═══════════════════════════════════════════════════════════════════════

class TestCrmTaskTypes:
    def test_all_crm_types_exist(self):
        assert TaskType.FIND_CONTACT.value == "find_contact"
        assert TaskType.CREATE_CONTACT.value == "create_contact"
        assert TaskType.UPDATE_CONTACT.value == "update_contact"
        assert TaskType.FIND_COMPANY.value == "find_company"
        assert TaskType.CREATE_COMPANY.value == "create_company"
        assert TaskType.CREATE_OPPORTUNITY.value == "create_opportunity"
        assert TaskType.UPDATE_OPPORTUNITY.value == "update_opportunity"
        assert TaskType.CREATE_ACTIVITY.value == "create_activity"
        assert TaskType.CREATE_NOTE.value == "create_note"
        assert TaskType.ASSIGN_OWNER.value == "assign_owner"


# ═══════════════════════════════════════════════════════════════════════
# 11. CRM BridgeAdapter Integration
# ═══════════════════════════════════════════════════════════════════════

class TestCrmBridgeAdapterIntegration:
    @pytest.mark.asyncio
    async def test_bridge_wraps_crm_adapter(self):
        from services.adapters.crm import CrmAdapter
        from services.execution.bridge_adapter import BridgeAdapter
        from services.execution.execution_models import ExecutionTask
        from services.execution.execution_context import ExecutionContext
        from services.planner.planning_models import Task as PlanTask

        crm = CrmAdapter()
        bridge = BridgeAdapter(
            sdk_adapter=crm,
            action_mapping={
                TaskType.FIND_CONTACT: "find_contact",
                TaskType.CREATE_CONTACT: "create_contact",
                TaskType.CREATE_OPPORTUNITY: "create_opportunity",
            },
        )

        assert bridge.adapter_type == "crm"
        assert TaskType.FIND_CONTACT in bridge.supported_task_types

        plan_task = PlanTask(
            type=TaskType.CREATE_CONTACT,
            params={
                "email": "bridge@test.com",
                "first_name": "Bridge",
                "last_name": "Test",
            },
        )
        exec_task = ExecutionTask(id="et1", plan_task=plan_task)
        exec_ctx = ExecutionContext(session_id="s1")

        result = await bridge.execute(exec_task, exec_ctx)
        assert result.success
        output = result.output
        assert output["ok"]
        assert output["contact"]["email"] == "bridge@test.com"

    @pytest.mark.asyncio
    async def test_bridge_unknown_task_type(self):
        from services.adapters.crm import CrmAdapter
        from services.execution.bridge_adapter import BridgeAdapter
        from services.execution.execution_models import ExecutionTask
        from services.execution.execution_context import ExecutionContext
        from services.planner.planning_models import Task as PlanTask

        crm = CrmAdapter()
        bridge = BridgeAdapter(
            sdk_adapter=crm,
            action_mapping={TaskType.FIND_CONTACT: "find_contact"},
        )

        plan_task = PlanTask(type=TaskType.SEND_EMAIL)
        exec_task = ExecutionTask(id="et2", plan_task=plan_task)
        exec_ctx = ExecutionContext(session_id="s1")

        result = await bridge.execute(exec_task, exec_ctx)
        assert not result.success

    @pytest.mark.asyncio
    async def test_bridge_find_contact(self):
        from services.adapters.crm import CrmAdapter
        from services.execution.bridge_adapter import BridgeAdapter
        from services.execution.execution_models import ExecutionTask
        from services.execution.execution_context import ExecutionContext
        from services.planner.planning_models import Task as PlanTask

        crm = CrmAdapter()
        bridge = BridgeAdapter(
            sdk_adapter=crm,
            action_mapping={TaskType.FIND_CONTACT: "find_contact"},
        )

        plan_task = PlanTask(
            type=TaskType.FIND_CONTACT,
            params={"email": "existing@test.com"},
        )
        exec_task = ExecutionTask(id="et3", plan_task=plan_task)
        exec_ctx = ExecutionContext(session_id="s1")

        result = await bridge.execute(exec_task, exec_ctx)
        assert result.success
        assert result.output["total"] == 0
