"""PR5.1 — Knowledge context integration tests.

These tests stop at the model/prompt boundaries. No real LLM or Gmail call is
made. The canonical Knowledge retrieval function is patched only at the
adapter boundary so owner/category/query/limit wiring remains observable.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send
from services.knowledge.context_adapter import (
    KnowledgePromptContext,
    format_knowledge_context,
    retrieve_knowledge_context,
)
from services.reasoning.reasoning_models import (
    DecisionPriority,
    DecisionType,
    GoalSelection,
    GoalType,
    PriorityAssessment,
    ReasoningDecision,
    ReasoningResult,
    RiskAssessment,
    RiskLevel,
)

import main as main_module  # noqa: E402
def _auth_request(token="session"):
    request = SimpleNamespace()
    request.headers = SimpleNamespace(get=lambda k, d="": f"Bearer {token}" if k == "authorization" else d)
    return request


import services.ai as ai_module  # noqa: E402
import workflows as workflows_module  # noqa: E402


def _knowledge_item(item_id="ki-1", category="messaging"):
    return {
        "id": item_id,
        "category": category,
        "title": "Core value proposition",
        "summary": "Loqi helps teams run evidence-led outbound.",
        "content": {"claims": ["AI-native outbound operations"]},
        "tags": ["positioning"],
        "source_type": "user_input",
        "source_id": "source-1",
        "created_by": "owner-a",
        "updated_at": "2026-08-12T00:00:00+00:00",
    }


def _knowledge_context():
    return KnowledgePromptContext(
        query="reply pricing",
        categories=("company", "messaging", "sales_offer"),
        items=[_knowledge_item()],
        sources=[{
            "id": "source-1",
            "title": "Founder notes",
            "source_type": "user_input",
            "content": "Approved positioning notes.",
            "reference": "",
        }],
    )


def _reasoning() -> ReasoningResult:
    return ReasoningResult(
        conversation_id="c-1",
        decision=ReasoningDecision(type=DecisionType.REPLY),
        goal=GoalSelection(primary=GoalType.PROVIDE_PRICING),
        priority=PriorityAssessment(level=DecisionPriority.HIGH),
        risk=RiskAssessment(level=RiskLevel.LOW),
    )


def _intelligence() -> ConversationIntelligence:
    return ConversationIntelligence(conversation_id="c-1")


class TestKnowledgeAdapter:
    async def test_empty_retrieval_has_no_prompt_block(self, monkeypatch):
        calls = []

        async def fake_get(owner_id, **kwargs):
            calls.append((owner_id, kwargs))
            return {"items": [], "sources": []}

        monkeypatch.setattr(
            "services.knowledge.context_adapter.get_knowledge_context", fake_get)
        context = await retrieve_knowledge_context(
            "owner-a", query="company positioning", categories=["company"], limit=8)

        assert context.items == []
        assert format_knowledge_context(context) == ""
        assert calls == [("owner-a", {
            "query": "company positioning", "categories": ["company"], "limit": 8,
        })]

    async def test_relevant_retrieval_preserves_attribution(self, monkeypatch):
        async def fake_get(owner_id, **kwargs):
            assert owner_id == "owner-a"
            assert kwargs["categories"] == ["messaging"]
            assert kwargs["limit"] == 2
            return {"items": [_knowledge_item()], "sources": [{"id": "source-1"}]}

        monkeypatch.setattr(
            "services.knowledge.context_adapter.get_knowledge_context", fake_get)
        context = await retrieve_knowledge_context(
            "owner-a", query="value proposition", categories=["messaging"], limit=2)
        block = format_knowledge_context(context)

        assert context.item_ids == ["ki-1"]
        assert context.source_ids == ["source-1"]
        assert "id=ki-1" in block
        assert "category=messaging" in block
        assert "source_type=user_input" in block
        assert "not prospect-specific evidence" in block
        assert "Structured content" in block

    async def test_owner_scope_is_never_replaced_by_client_identifier(self, monkeypatch):
        seen = []

        async def fake_get(owner_id, **kwargs):
            seen.append(owner_id)
            return {"items": [_knowledge_item(item_id=f"{owner_id}-item")], "sources": []}

        monkeypatch.setattr(
            "services.knowledge.context_adapter.get_knowledge_context", fake_get)
        a = await retrieve_knowledge_context("owner-a", query="company")
        b = await retrieve_knowledge_context("owner-b", query="company")

        assert seen == ["owner-a", "owner-b"]
        assert a.item_ids == ["owner-a-item"]
        assert b.item_ids == ["owner-b-item"]


class TestReplyGenerationContext:
    def test_pipeline_includes_knowledge_and_metadata(self):
        from services.reply_generation.generation_pipeline import GenerationPipeline

        captured = []

        class Provider:
            provider_name = "test"
            default_model = "test-model"

            def generate(self, system_prompt, user_prompt, temperature):
                captured.append((system_prompt, user_prompt))
                return SimpleNamespace(text="A grounded response", model="test-model", token_usage={})

        pipeline = GenerationPipeline()
        import services.reply_generation.generation_pipeline as pipeline_module
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(pipeline_module, "get_default_provider", lambda: Provider())
        try:
            result = pipeline.generate(
                intelligence=_intelligence(), reasoning=_reasoning(),
                knowledge_context=_knowledge_context().to_dict(),
            )
        finally:
            monkeypatch.undo()

        assert captured
        assert "KNOWLEDGE CONTEXT" in captured[0][0] or "KNOWLEDGE CONTEXT" in captured[0][1]
        assert result.metadata.knowledge_item_ids == ["ki-1"]
        assert result.metadata.knowledge_source_ids == ["source-1"]
        assert result.metadata.knowledge_query == "reply pricing"

    def test_pipeline_without_knowledge_has_no_empty_section(self):
        from services.reply_generation.generation_pipeline import GenerationPipeline

        captured = []

        class Provider:
            provider_name = "test"
            default_model = "test-model"

            def generate(self, system_prompt, user_prompt, temperature):
                captured.append(user_prompt)
                return SimpleNamespace(text="A response", model="test-model", token_usage={})

        pipeline = GenerationPipeline()
        import services.reply_generation.generation_pipeline as pipeline_module
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(pipeline_module, "get_default_provider", lambda: Provider())
        try:
            pipeline.generate(intelligence=_intelligence(), reasoning=_reasoning())
        finally:
            monkeypatch.undo()

        assert captured and "KNOWLEDGE CONTEXT" not in captured[0]

    async def test_route_passes_owner_scoped_knowledge_to_reply_and_followup(self, monkeypatch):
        external_thread_id = f"thread_{uuid.uuid4().hex[:12]}"
        convo = create_conversation_from_send(
            provider_id="provider", provider_type="gmail",
            external_thread_id=external_thread_id,
            external_message_id=f"outbound_{uuid.uuid4().hex[:12]}",
            subject="Pricing question", from_email="owner@example.com",
            from_name="Owner", to_email="lead@example.com", to_name="Lead",
            body="Would pricing be useful?", campaign_id="campaign", workflow_id="workflow",
            lead_id="lead", owner_id="owner-a",
        )
        captured = []

        class FakePipeline:
            def __init__(self):
                pass

            def generate(self, **kwargs):
                captured.append(kwargs)
                return SimpleNamespace(to_dict=lambda: {"ok": True})

        async def fake_retrieve(owner_id, **kwargs):
            assert owner_id == "owner-a"
            return _knowledge_context()

        async def fake_owner(request, session_token):
            return "owner-a"

        monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)
        async def _resolve(request):
            return "owner-a", "session"
        monkeypatch.setattr(main_module, "_resolve_session_context", _resolve)
        monkeypatch.setattr("services.reply_generation.generation_pipeline.GenerationPipeline", FakePipeline)
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", fake_retrieve)

        reply = await main_module.generate_reply_route("_", convo.conversation_id, {}, _auth_request())
        follow_up = await main_module.generate_reply_route(
            "_", convo.conversation_id, {"follow_up": True}, _auth_request(),
        )

        assert reply["ok"] and follow_up["ok"]
        assert captured[0]["follow_up"] is False
        assert captured[1]["follow_up"] is True
        assert captured[0]["knowledge_context"]["item_ids"] == ["ki-1"]
        assert captured[1]["knowledge_context"]["source_ids"] == ["source-1"]


class TestLegacyDraftBoundary:
    def test_campaign_strategy_prompt_receives_knowledge(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            ai_module,
            "_send_openai_request",
            lambda system, user: captured.append((system, user)) or '{"campaign_objective":"Sell Loqi"}',
        )

        ai_module.generate_campaign_strategy(
            "Sell Loqi",
            {"knowledge_context": _knowledge_context().to_dict()},
        )

        assert captured
        assert "Core value proposition" in captured[0][1]
        assert "not prospect-specific evidence" in captured[0][1]

    def test_draft_workflow_passes_knowledge_to_outreach_generator(self, monkeypatch):
        captured = []
        knowledge = _knowledge_context().to_dict()

        class Enricher:
            def health_check(self):
                return {"ok": False}

        monkeypatch.setattr(workflows_module, "get_enricher", lambda: Enricher())
        monkeypatch.setattr(workflows_module, "generate_lead_intelligence", lambda lead, enrichment: {})

        def fake_generate(*args, **kwargs):
            captured.append(kwargs.get("knowledge_context"))
            return {"subject": "Subject", "body": "Body"}

        monkeypatch.setattr(workflows_module, "generate_outreach_email", fake_generate)
        result = workflows_module.draft_message({
            "lead": {"name": "Jordan", "company": "Acme", "title": "CTO"},
            "knowledge_context": knowledge,
            "_knowledge_context_trusted": True,
        })

        assert result["ok"] is True
        assert captured == [knowledge]

    def test_outreach_prompt_keeps_prospect_and_knowledge_distinct(self, monkeypatch):
        captured = []
        monkeypatch.setattr(ai_module, "_send_openai_request", lambda system, user: captured.append((system, user)) or '{"subject":"S","body":"B"}')

        ai_module.generate_outreach_email(
            {"name": "Jordan", "company": "Prospect Co", "title": "CTO"},
            lead_intelligence={"summary": "Prospect-specific research fact"},
            knowledge_context=_knowledge_context().to_dict(),
        )

        assert captured
        system, user = captured[0]
        assert "Knowledge is business guidance only" in system
        assert "Prospect-specific research fact" in user
        assert "Core value proposition" in user
        assert "not prospect-specific evidence" in user
