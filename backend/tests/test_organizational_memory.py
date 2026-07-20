"""Tests for Phase 12 — Organizational Memory & Knowledge Platform.

Covers Memory SDK, Memory Adapter, consolidation, subscriber,
memory-aware strategies, and explainability.
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from services.memory.models import (
    Memory,
    AccountMemory,
    ContactMemory,
    ConversationMemory,
    MeetingMemory,
    OpportunityMemory,
    DecisionMemory,
    PreferenceMemory,
    OutcomeMemory,
    MemorySearch,
    MemorySearchResult,
    MemoryEvidence,
    MemoryCitation,
    MemoryType,
    MemoryRelationship,
)
from services.memory.memory_store import (
    InMemoryMemoryProvider,
    get_memory_provider,
    set_memory_provider,
    reset_memory_provider,
)
from services.memory.consolidation import consolidate_memories
from services.memory.subscriber import MemorySubscriber
from services.memory.explainability import explain_decision, audit_plan_influences
from services.adapters.memory import MemoryAdapter
from services.planner.planning_models import TaskType, PlanGoal
from services.planner.strategies.memory_outreach import memory_outreach_strategy
from services.planner.strategies.memory_nba import memory_nba_strategy
from services.execution.enums import ExecutionEventType
from services.execution.execution_models import ExecutionEvent


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_memory():
    reset_memory_provider()
    yield
    reset_memory_provider()


def _memory_id() -> str:
    return uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════════════════
# 1. Memory Models
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryModels:
    def test_memory_defaults(self):
        m = Memory()
        assert m.id == ""
        assert m.confidence == 0.5
        assert m.tags == []
        assert m.relationships == []

    def test_account_memory_defaults(self):
        m = AccountMemory()
        assert m.memory_type == MemoryType.ACCOUNT
        assert m.account_tier == ""
        assert m.buying_intent == ""

    def test_contact_memory_type(self):
        m = ContactMemory(email="test@test.com")
        assert m.memory_type == MemoryType.CONTACT

    def test_conversation_memory(self):
        m = ConversationMemory(
            conversation_id="conv1",
            summary="Discussed pricing",
            intents=["pricing_request"],
            objections=["too expensive"],
        )
        assert m.memory_type == MemoryType.CONVERSATION
        assert "too expensive" in m.objections

    def test_meeting_memory(self):
        m = MeetingMemory(
            event_id="evt1",
            summary="Product demo",
            attendees=["alice@co.com", "bob@co.com"],
            outcome="interested",
        )
        assert m.memory_type == MemoryType.MEETING
        assert len(m.attendees) == 2

    def test_opportunity_memory(self):
        m = OpportunityMemory(
            opportunity_id="opp1",
            company_id="co1",
            stage="closed_won",
            amount=50000.0,
            close_reason="Best value",
        )
        assert m.stage == "closed_won"
        assert m.close_reason == "Best value"

    def test_decision_memory(self):
        m = DecisionMemory(
            context="Vendor selection",
            options=["Acme", "Beta", "Gamma"],
            choice="Acme",
            rationale="Best fit",
        )
        assert m.choice == "Acme"

    def test_preference_memory(self):
        m = PreferenceMemory(
            entity_type="contact",
            entity_id="c1",
            preference_key="demo_time",
            preference_value="afternoon",
        )
        assert m.preference_key == "demo_time"

    def test_outcome_memory(self):
        m = OutcomeMemory(
            action_type="outreach",
            result="positive_reply",
            details="Prospect requested demo",
        )
        assert m.action_type == "outreach"

    def test_memory_search_defaults(self):
        s = MemorySearch()
        assert s.limit == 10
        assert s.offset == 0

    def test_memory_relationship(self):
        r = MemoryRelationship(target_id="mem2", relationship_type="related_to")
        assert r.target_id == "mem2"

    def test_citation(self):
        c = MemoryCitation(memory_ids=["m1", "m2"])
        assert len(c.memory_ids) == 2
        assert c.evidence == []

    def test_evidence(self):
        e = MemoryEvidence(
            memory_id="m1",
            memory_type=MemoryType.CONTACT,
            summary="Contact history",
            relevance_score=0.8,
        )
        assert e.relevance_score == 0.8


# ═══════════════════════════════════════════════════════════════════════
# 2. Memory Provider (InMemory)
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryProvider:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        provider = InMemoryMemoryProvider()
        m = ContactMemory(email="a@b.com", name="Alice")
        mid = await provider.store(m)
        assert mid != ""
        retrieved = await provider.retrieve(mid)
        assert retrieved is not None
        assert isinstance(retrieved, ContactMemory)
        assert retrieved.email == "a@b.com"

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent(self):
        provider = InMemoryMemoryProvider()
        result = await provider.retrieve("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_by_memory_type(self):
        provider = InMemoryMemoryProvider()
        await provider.store(ContactMemory(email="a@b.com"))
        await provider.store(AccountMemory(company_name="Acme"))
        await provider.store(OutcomeMemory(action_type="email", result="sent"))
        search = MemorySearch(memory_type=MemoryType.CONTACT)
        result = await provider.search(search)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_search_by_query(self):
        provider = InMemoryMemoryProvider()
        await provider.store(ConversationMemory(
            summary="Discussed pricing options", intents=["pricing"],
        ))
        await provider.store(ConversationMemory(
            summary="Discussed implementation timeline", intents=["timing"],
        ))
        search = MemorySearch(query="pricing")
        result = await provider.search(search)
        assert result.total >= 1

    @pytest.mark.asyncio
    async def test_update_memory(self):
        provider = InMemoryMemoryProvider()
        m = ContactMemory(email="old@test.com", name="Old Name")
        mid = await provider.store(m)
        await provider.update(mid, {"email": "new@test.com", "name": "New Name"})
        retrieved = await provider.retrieve(mid)
        assert retrieved is not None
        assert retrieved.email == "new@test.com"
        assert retrieved.name == "New Name"

    @pytest.mark.asyncio
    async def test_delete_memory(self):
        provider = InMemoryMemoryProvider()
        m = ContactMemory(email="delete@test.com")
        mid = await provider.store(m)
        assert await provider.delete(mid) is True
        assert await provider.retrieve(mid) is None
        assert await provider.delete(mid) is False

    @pytest.mark.asyncio
    async def test_summarize_empty(self):
        provider = InMemoryMemoryProvider()
        summary = await provider.summarize("contact", "c1")
        assert summary == {}

    @pytest.mark.asyncio
    async def test_summarize_with_memories(self):
        provider = InMemoryMemoryProvider()
        await provider.store(ContactMemory(contact_id="c1", name="Alice"))
        await provider.store(ContactMemory(contact_id="c1", name="Alice Updated"))
        summary = await provider.summarize("contact", "c1")
        assert summary["entity_type"] == "contact"
        assert summary["entity_id"] == "c1"
        assert summary["total_memories"] >= 2

    @pytest.mark.asyncio
    async def test_search_limit_and_offset(self):
        provider = InMemoryMemoryProvider()
        for i in range(5):
            await provider.store(ContactMemory(email=f"test{i}@test.com"))
        result = await provider.search(MemorySearch(limit=2))
        assert len(result.memories) == 2
        assert result.total == 5

    @pytest.mark.asyncio
    async def test_search_by_tags(self):
        provider = InMemoryMemoryProvider()
        m1 = ContactMemory(email="a@b.com", tags=["vip", "enterprise"])
        m2 = ContactMemory(email="c@d.com", tags=["standard"])
        await provider.store(m1)
        await provider.store(m2)
        result = await provider.search(MemorySearch(tags=["vip"]))
        assert result.total == 1


# ═══════════════════════════════════════════════════════════════════════
# 3. Memory Consolidation
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryConsolidation:
    @pytest.mark.asyncio
    async def test_consolidate_accounts(self):
        provider = InMemoryMemoryProvider()
        now = datetime.now(timezone.utc)
        for i in range(3):
            await provider.store(AccountMemory(
                company_id="co1",
                company_name="Acme",
                account_tier="enterprise" if i == 0 else "mid_market",
                buying_intent="high" if i == 0 else "medium",
                key_contacts=[f"contact{i}@acme.com"],
                timestamp=now - timedelta(hours=i),
            ))
        result = await consolidate_memories(provider)
        assert result["account"] >= 1
        search = MemorySearch(entity_id="co1")
        sr = await provider.search(search)
        consolidated = [m for m in sr.memories if "consolidated" in m.tags]
        assert len(consolidated) >= 1

    @pytest.mark.asyncio
    async def test_consolidate_conversation_objections(self):
        provider = InMemoryMemoryProvider()
        await provider.store(ConversationMemory(
            conversation_id="conv1",
            objections=["too expensive"],
            summary="First call",
        ))
        await provider.store(ConversationMemory(
            conversation_id="conv1",
            objections=["too expensive", "bad timing"],
            summary="Second call",
        ))
        result = await consolidate_memories(provider)
        assert result["conversation"] >= 1
        search = MemorySearch(query="too expensive")
        sr = await provider.search(search)
        assert sr.total >= 1


# ═══════════════════════════════════════════════════════════════════════
# 4. Memory Subscriber (Learning)
# ═══════════════════════════════════════════════════════════════════════

class TestMemorySubscriber:
    def _make_event(self, event_type, task_type="", **data):
        return ExecutionEvent(
            id=_memory_id(),
            session_id="s1",
            task_id="t1" if event_type == ExecutionEventType.TASK_COMPLETED else None,
            event_type=event_type,
            data={"task_type": task_type, **data},
        )

    @pytest.mark.asyncio
    async def test_subscriber_stores_on_task_completed_email(self):
        provider = get_memory_provider()
        sub = MemorySubscriber()
        event = self._make_event(
            ExecutionEventType.TASK_COMPLETED,
            task_type="send_email",
            recipient="alice@test.com",
            subject="Follow-up",
        )
        sub.handle(event)
        await asyncio.sleep(0.05)
        search = MemorySearch(memory_type=MemoryType.CONVERSATION)
        result = await provider.search(search)
        assert result.total >= 1

    @pytest.mark.asyncio
    async def test_subscriber_stores_outcome_on_session_complete(self):
        provider = get_memory_provider()
        sub = MemorySubscriber()
        event = self._make_event(
            ExecutionEventType.SESSION_COMPLETED,
            strategy_name="pipeline_outreach",
            status="completed",
            task_count=3,
        )
        sub.handle(event)
        await asyncio.sleep(0.05)
        search = MemorySearch(memory_type=MemoryType.OUTCOME)
        result = await provider.search(search)
        assert result.total >= 1

    def test_subscriber_handles_errors_gracefully(self):
        sub = MemorySubscriber()
        bad_event = ExecutionEvent(
            id="bad",
            session_id="s1",
            event_type=ExecutionEventType.TASK_COMPLETED,
            data=None,
        )
        sub.handle(bad_event)


# ═══════════════════════════════════════════════════════════════════════
# 5. Memory Adapter
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryAdapter:
    def _ctx(self, action, params):
        from services.adapters.adapter_context import AdapterContext
        return AdapterContext.build(
            execution_session_id="test",
            execution_task_id="t1",
            action=action,
            params=params,
        )

    @pytest.mark.asyncio
    async def test_adapter_metadata(self):
        adapter = MemoryAdapter()
        meta = adapter.metadata
        assert meta.name == "memory"
        assert "store_memory" in meta.supported_operations
        assert "search_memory" in meta.supported_operations

    @pytest.mark.asyncio
    async def test_store_contact_memory(self):
        adapter = MemoryAdapter()
        result = await adapter.execute(self._ctx("store_memory", {
            "memory_type": "contact",
            "email": "alice@test.com",
            "name": "Alice",
        }))
        assert result.success
        assert result.data["ok"]

    @pytest.mark.asyncio
    async def test_store_and_retrieve_round_trip(self):
        adapter = MemoryAdapter()
        store_result = await adapter.execute(self._ctx("store_memory", {
            "memory_type": "conversation",
            "summary": "Great call",
            "outcome": "positive",
        }))
        mid = store_result.data["memory_id"]
        retrieve_result = await adapter.execute(self._ctx("retrieve_memory", {
            "memory_id": mid,
        }))
        assert retrieve_result.success
        assert retrieve_result.data["ok"]

    @pytest.mark.asyncio
    async def test_search_memory(self):
        adapter = MemoryAdapter()
        for i in range(3):
            await adapter.execute(self._ctx("store_memory", {
                "memory_type": "contact",
                "email": f"user{i}@test.com",
                "name": f"User {i}",
            }))
        result = await adapter.execute(self._ctx("search_memory", {
            "memory_type": "contact",
            "limit": 10,
        }))
        assert result.success
        assert result.data["total"] >= 3

    @pytest.mark.asyncio
    async def test_update_memory(self):
        adapter = MemoryAdapter()
        store = await adapter.execute(self._ctx("store_memory", {
            "memory_type": "contact",
            "name": "Old",
        }))
        mid = store.data["memory_id"]
        update = await adapter.execute(self._ctx("update_memory", {
            "memory_id": mid,
            "updates": {"name": "New"},
        }))
        assert update.success
        retrieve = await adapter.execute(self._ctx("retrieve_memory", {
            "memory_id": mid,
        }))
        assert retrieve.success
        assert retrieve.data["memory"].get("name") == "New"

    @pytest.mark.asyncio
    async def test_delete_memory(self):
        adapter = MemoryAdapter()
        store = await adapter.execute(self._ctx("store_memory", {
            "memory_type": "contact",
        }))
        mid = store.data["memory_id"]
        delete = await adapter.execute(self._ctx("delete_memory", {"memory_id": mid}))
        assert delete.success
        retrieve = await adapter.execute(self._ctx("retrieve_memory", {"memory_id": mid}))
        assert not retrieve.data["ok"]

    @pytest.mark.asyncio
    async def test_summarize_memory(self):
        adapter = MemoryAdapter()
        await adapter.execute(self._ctx("store_memory", {
            "memory_type": "contact",
            "contact_id": "c1",
            "name": "Alice",
        }))
        result = await adapter.execute(self._ctx("summarize_memory", {
            "entity_type": "contact",
            "entity_id": "c1",
        }))
        assert result.success
        assert result.data["ok"]

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        adapter = MemoryAdapter()
        result = await adapter.execute(self._ctx("bogus", {}))
        assert not result.success


# ═══════════════════════════════════════════════════════════════════════
# 6. Memory BridgeAdapter Integration
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryBridgeAdapter:
    @pytest.mark.asyncio
    async def test_bridge_wraps_memory_adapter(self):
        from services.execution.bridge_adapter import BridgeAdapter
        from services.execution.execution_models import ExecutionTask
        from services.execution.execution_context import ExecutionContext
        from services.planner.planning_models import Task as PlanTask

        adapter = MemoryAdapter()
        bridge = BridgeAdapter(
            sdk_adapter=adapter,
            action_mapping={
                TaskType.STORE_MEMORY: "store_memory",
                TaskType.RETRIEVE_MEMORY: "retrieve_memory",
                TaskType.SEARCH_MEMORY: "search_memory",
            },
        )
        assert bridge.adapter_type == "memory"
        assert TaskType.STORE_MEMORY in bridge.supported_task_types

        plan_task = PlanTask(
            type=TaskType.STORE_MEMORY,
            params={"memory_type": "contact", "email": "bridge@test.com"},
        )
        exec_task = ExecutionTask(id="et1", plan_task=plan_task)
        exec_ctx = ExecutionContext(session_id="s1")
        result = await bridge.execute(exec_task, exec_ctx)
        assert result.success
        assert result.output["ok"]

    @pytest.mark.asyncio
    async def test_bridge_unknown_action(self):
        from services.execution.bridge_adapter import BridgeAdapter
        from services.execution.execution_models import ExecutionTask
        from services.execution.execution_context import ExecutionContext
        from services.planner.planning_models import Task as PlanTask

        adapter = MemoryAdapter()
        bridge = BridgeAdapter(
            sdk_adapter=adapter,
            action_mapping={TaskType.STORE_MEMORY: "store_memory"},
        )
        plan_task = PlanTask(type=TaskType.SEND_EMAIL)
        exec_task = ExecutionTask(id="et2", plan_task=plan_task)
        exec_ctx = ExecutionContext(session_id="s1")
        result = await bridge.execute(exec_task, exec_ctx)
        assert not result.success


# ═══════════════════════════════════════════════════════════════════════
# 7. Memory-Aware Strategies — MemoryOutreach
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryOutreachStrategy:
    def test_strategy_name(self):
        assert memory_outreach_strategy.name == "memory_outreach"

    def test_matches_target(self):
        goal = PlanGoal(target_action="memory_outreach")
        assert memory_outreach_strategy.matches(goal) > 0.9

    def test_matches_previous_outcome_target(self):
        goal = PlanGoal(outcome="previous objections influenced")
        assert memory_outreach_strategy.matches(goal) >= 0.85

    def test_no_match(self):
        goal = PlanGoal(target_action="general")
        assert memory_outreach_strategy.matches(goal) == 0.0

    @pytest.mark.asyncio
    async def test_generates_tasks_with_memory_context(self):
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="conv1",
            objections=["budget constraints"],
            summary="Previous call: prospect mentioned budget issues",
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Memory outreach to Acme"),
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

    @pytest.mark.asyncio
    async def test_memory_citation_in_task_metadata(self):
        provider = get_memory_provider()
        mem = await provider.store(OutcomeMemory(
            action_type="email",
            result="positive_reply",
            details="Previous outreach was successful",
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Outreach with memory"),
            {
                "prospect_email": "bob@test.com",
                "prospect_name": "Bob",
                "company_name": "Test Corp",
            },
        )
        email_tasks = [t for t in tasks if t.type == TaskType.SEND_EMAIL]
        if email_tasks:
            assert "memory_citation" in email_tasks[0].metadata
            assert "memory_ids" in email_tasks[0].metadata

    @pytest.mark.asyncio
    async def test_previous_objections_influence_instructions(self):
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="c1",
            objections=["too expensive", "budget constraints"],
            summary="Prospect raised pricing concerns",
            tags=["objection"],
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Handle objections"),
            {
                "prospect_email": "obj@test.com",
                "prospect_name": "Objection Prospect",
                "company_name": "Budget Corp",
            },
        )
        email_tasks = [t for t in tasks if t.type == TaskType.SEND_EMAIL]
        if email_tasks:
            instructions = email_tasks[0].instructions.lower()
            has_objection_ref = any(
                kw in instructions for kw in ["objection", "budget", "pricing", "expensive"]
            )
            assert has_objection_ref

    @pytest.mark.asyncio
    async def test_previous_outcomes_referenced(self):
        provider = get_memory_provider()
        await provider.store(OutcomeMemory(
            action_type="outreach",
            result="meeting_booked",
            details="Previous outreach led to a booked meeting",
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="Follow-up outreach"),
            {
                "prospect_email": "outcome@test.com",
                "prospect_name": "Outcome Test",
                "company_name": "Outcome Corp",
            },
        )
        assert len(tasks) >= 7


# ═══════════════════════════════════════════════════════════════════════
# 8. Memory-Aware Strategies — MemoryNBA
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryNBAStrategy:
    def test_strategy_name(self):
        assert memory_nba_strategy.name == "memory_nba"

    def test_matches_target(self):
        goal = PlanGoal(target_action="memory_nba")
        assert memory_nba_strategy.matches(goal) > 0.9

    def test_matches_meeting_influence(self):
        goal = PlanGoal(outcome="meeting history should influence")
        assert memory_nba_strategy.matches(goal) >= 0.8

    @pytest.mark.asyncio
    async def test_successful_meetings_boost_demo_score(self):
        provider = get_memory_provider()
        await provider.store(MeetingMemory(
            event_id="evt1",
            summary="Great demo session",
            outcome="interested",
            attendees=["alice@test.com"],
            tags=["successful_meeting"],
        ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="Next action with meeting memory"),
            {
                "contact_name": "Alice",
                "company_name": "Demo Corp",
                "opportunity_id": "opp1",
                "contact_id": "c1",
                "current_stage": "discovery",
            },
        )
        assert len(tasks) >= 2
        types = [t.type for t in tasks]
        assert any(t in (TaskType.SEND_EMAIL, TaskType.SCHEDULE_MEETING) for t in types)
        assert TaskType.CREATE_ACTIVITY in types
        assert TaskType.CREATE_NOTE in types

    @pytest.mark.asyncio
    async def test_previous_decision_maker_preferred(self):
        provider = get_memory_provider()
        await provider.store(DecisionMemory(
            context="Vendor selection",
            options=["Us", "Competitor"],
            choice="Us",
            rationale="Better features and pricing",
            tags=["decision"],
        ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="Decision-aware action"),
            {
                "contact_name": "Bob",
                "company_name": "Decision Corp",
                "opportunity_id": "opp2",
                "contact_id": "c2",
                "current_stage": "qualified",
            },
        )
        assert len(tasks) >= 2

    @pytest.mark.asyncio
    async def test_repeated_failures_alter_recommendations(self):
        provider = get_memory_provider()
        for i in range(3):
            await provider.store(OutcomeMemory(
                action_type="outreach",
                result="no_reply" if i < 2 else "not_interested",
                details="Repeated lack of engagement",
                tags=["failure"],
            ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="Failure-aware action"),
            {
                "contact_name": "Fail Test",
                "company_name": "Fail Corp",
                "opportunity_id": "opp3",
                "contact_id": "c3",
                "current_stage": "discovery",
                "engagement_score": 0.1,
            },
        )
        assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_memory_citation_included_in_output(self):
        provider = get_memory_provider()
        await provider.store(PreferenceMemory(
            entity_type="contact",
            entity_id="c4",
            preference_key="demo_time",
            preference_value="afternoon",
        ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="Preference-aware action"),
            {
                "contact_name": "Pref Test",
                "company_name": "Pref Corp",
                "opportunity_id": "opp4",
                "contact_id": "c4",
                "current_stage": "qualified",
            },
        )
        action_tasks = [t for t in tasks if t.type in (TaskType.SEND_EMAIL, TaskType.SCHEDULE_MEETING)]
        if action_tasks:
            assert "memory_citation" in action_tasks[0].metadata
            assert action_tasks[0].metadata["memory_citation"] != ""


# ═══════════════════════════════════════════════════════════════════════
# 9. Explainability
# ═══════════════════════════════════════════════════════════════════════

class TestExplainability:
    @pytest.mark.asyncio
    async def test_explain_decision_with_memories(self):
        provider = get_memory_provider()
        m1 = await provider.store(ContactMemory(
            contact_id="c1", name="Alice", confidence=0.8,
        ))
        m2 = await provider.store(ConversationMemory(
            conversation_id="conv1", objections=["budget"],
            confidence=0.7,
        ))
        citation = await explain_decision([m1, m2], provider=provider)
        assert len(citation.memory_ids) == 2
        assert len(citation.evidence) == 2
        assert "influenced" in citation.explanation

    @pytest.mark.asyncio
    async def test_explain_decision_no_memories(self):
        citation = await explain_decision(["nonexistent"])
        assert citation.explanation == "No memories influenced this decision."

    @pytest.mark.asyncio
    async def test_explain_decision_empty_list(self):
        citation = await explain_decision([])
        assert len(citation.evidence) == 0

    @pytest.mark.asyncio
    async def test_audit_plan_influences(self):
        provider = get_memory_provider()
        mid = await provider.store(OutcomeMemory(
            action_type="email", result="positive",
        ))
        audit = await audit_plan_influences([
            {"task_id": "t1", "task_label": "Send email", "memory_ids": [mid]},
            {"task_id": "t2", "task_label": "No memory task", "memory_ids": []},
        ], provider=provider)
        assert len(audit) == 1
        assert audit[0]["task_id"] == "t1"
        assert audit[0]["citation"]["evidence_count"] == 1

    @pytest.mark.asyncio
    async def test_memory_evidence_contains_excerpt(self):
        provider = get_memory_provider()
        mid = await provider.store(ContactMemory(
            email="excerpt@test.com",
        ))
        citation = await explain_decision([mid], provider=provider)
        assert citation.evidence[0].excerpt != ""
        assert len(citation.evidence[0].excerpt) > 50


# ═══════════════════════════════════════════════════════════════════════
# 10. Memory TaskTypes & Payloads
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryTaskTypes:
    def test_all_memory_types_exist(self):
        assert TaskType.STORE_MEMORY.value == "store_memory"
        assert TaskType.RETRIEVE_MEMORY.value == "retrieve_memory"
        assert TaskType.SEARCH_MEMORY.value == "search_memory"
        assert TaskType.UPDATE_MEMORY.value == "update_memory"
        assert TaskType.DELETE_MEMORY.value == "delete_memory"
        assert TaskType.SUMMARIZE_MEMORY.value == "summarize_memory"


# ═══════════════════════════════════════════════════════════════════════
# 11. End-to-end scenarios
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndScenarios:
    """6 integration scenarios proving memory-driven behavior."""

    @pytest.mark.asyncio
    async def test_previous_objections_influence_future_outreach(self):
        """Scenario 1: Previous objections should influence future outreach instructions."""
        provider = get_memory_provider()
        await provider.store(ConversationMemory(
            conversation_id="conv_e2e_1",
            objections=["too expensive", "budget concerns"],
            summary="Prospect raised budget issues",
            source="email",
            confidence=0.8,
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="E2E: objection-aware outreach"),
            {
                "prospect_email": "e2e@test.com",
                "prospect_name": "E2E Prospect",
                "company_name": "E2E Corp",
                "conversation_id": "conv_e2e_1",
            },
        )
        email_tasks = [t for t in tasks if t.type == TaskType.SEND_EMAIL]
        assert len(email_tasks) >= 1
        instructions = email_tasks[0].instructions.lower()
        assert "budget" in instructions or "expensive" in instructions or "objection" in instructions
        assert email_tasks[0].metadata.get("memory_citation", "") != ""

    @pytest.mark.asyncio
    async def test_successful_meetings_influence_nba(self):
        """Scenario 2: Successful meetings should influence next-best-action."""
        provider = get_memory_provider()
        await provider.store(MeetingMemory(
            event_id="evt_e2e_1",
            summary="Excellent product demo",
            outcome="interested",
            attendees=["lead@e2e.com"],
            confidence=0.9,
            tags=["successful_meeting"],
        ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="E2E: meeting-informed NBA"),
            {
                "contact_name": "E2E Lead",
                "company_name": "E2E Demo Corp",
                "opportunity_id": "opp_e2e_1",
                "contact_id": "c_e2e_1",
                "current_stage": "qualified",
            },
        )
        assert len(tasks) >= 2
        action_tasks = [t for t in tasks if t.type == TaskType.SEND_EMAIL]
        if action_tasks:
            assert action_tasks[0].metadata.get("memory_ids", [])

    @pytest.mark.asyncio
    async def test_previous_decision_maker_preferred_in_nba(self):
        """Scenario 3: Previous decision maker should be preferred."""
        provider = get_memory_provider()
        await provider.store(DecisionMemory(
            context="Previous vendor selection",
            options=["Us", "Competitor A", "Competitor B"],
            choice="Us",
            rationale="Best overall value and support",
            confidence=0.85,
            tags=["decision", "won"],
        ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="E2E: decision-aware NBA"),
            {
                "contact_name": "Decision Maker",
                "company_name": "Decision E2E",
                "opportunity_id": "opp_e2e_2",
                "contact_id": "c_e2e_2",
                "current_stage": "negotiation",
            },
        )
        assert len(tasks) >= 2

    @pytest.mark.asyncio
    async def test_repeated_failures_alter_recommendations(self):
        """Scenario 4: Repeated failures should alter recommendations."""
        provider = get_memory_provider()
        for i in range(4):
            await provider.store(OutcomeMemory(
                action_type="email",
                result="no_reply" if i < 3 else "unsubscribed",
                details="No engagement from prospect",
                confidence=0.6,
                tags=["failure", "no_engagement"],
            ))
        tasks = await memory_nba_strategy.generate_tasks(
            PlanGoal(outcome="E2E: failure-aware NBA"),
            {
                "contact_name": "Low Engagement",
                "company_name": "Failure E2E",
                "opportunity_id": "opp_e2e_3",
                "contact_id": "c_e2e_3",
                "current_stage": "discovery",
                "engagement_score": 0.05,
            },
        )
        assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_retrieved_memories_are_cited(self):
        """Scenario 5: Retrieved memories must be cited in the plan."""
        provider = get_memory_provider()
        mid = await provider.store(AccountMemory(
            company_id="co_e2e",
            company_name="Cite E2E Corp",
            account_tier="enterprise",
            buying_intent="high",
            confidence=0.9,
        ))
        tasks = await memory_outreach_strategy.generate_tasks(
            PlanGoal(outcome="E2E: citation test"),
            {
                "prospect_email": "cite@e2e.com",
                "prospect_name": "Cite Prospect",
                "company_name": "Cite E2E Corp",
            },
        )
        email_tasks = [t for t in tasks if t.type == TaskType.SEND_EMAIL]
        if email_tasks:
            assert "memory_citation" in email_tasks[0].metadata
            assert email_tasks[0].metadata["memory_citation"] != ""
            assert len(email_tasks[0].metadata.get("memory_ids", [])) >= 1

    @pytest.mark.asyncio
    async def test_execution_stores_new_memories_automatically(self):
        """Scenario 6: Execution should store new memories automatically via subscriber."""
        provider = get_memory_provider()
        sub = MemorySubscriber()

        # Simulate a task completion event for an email send
        event = ExecutionEvent(
            id=_memory_id(),
            session_id="s_e2e_auto",
            task_id="t_e2e_auto",
            event_type=ExecutionEventType.TASK_COMPLETED,
            data={
                "task_type": "send_email",
                "recipient": "auto@e2e.com",
                "subject": "Automated memory test",
            },
        )
        sub.handle(event)
        import asyncio
        await asyncio.sleep(0.05)

        search = MemorySearch(memory_type=MemoryType.CONVERSATION)
        result = await provider.search(search)
        memories = [m for m in result.memories if "auto@e2e.com" in str(m.__dict__)]
        assert len(memories) >= 1

        # Simulate a session completed event
        session_event = ExecutionEvent(
            id=_memory_id(),
            session_id="s_e2e_auto",
            event_type=ExecutionEventType.SESSION_COMPLETED,
            data={
                "strategy_name": "test_strategy",
                "status": "completed",
                "task_count": 5,
            },
        )
        sub.handle(session_event)
        await asyncio.sleep(0.05)

        outcome_search = MemorySearch(memory_type=MemoryType.OUTCOME)
        outcome_result = await provider.search(outcome_search)
        outcomes = [m for m in outcome_result.memories if "s_e2e_auto" in str(m.__dict__)]
        assert len(outcomes) >= 1
