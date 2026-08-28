"""Regression test suite for the Copilot API.

Exercises the real HTTP endpoints via TestClient.
Mocks only the OpenAI call so tests are deterministic and cost-free.
Fixtures are in conftest.py.
"""

import pytest
import main as main_module
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def _selected_copilot_workspace(monkeypatch):
    """Keep endpoint tests inside an explicitly resolved test workspace."""
    async def resolve(_request, _owner_id):
        return SimpleNamespace(workspace_id="workspace-1")

    monkeypatch.setattr(main_module.workspace_access, "resolve_selected_workspace_context", resolve)

    # Route tests exercise the authenticated tool boundary, not the live
    # Supabase schema. The dedicated Phase 6 ledger tests cover durable
    # idempotency/concurrency; this pass-through keeps this legacy suite from
    # depending on an externally migrated test database.
    class PassthroughExecutionService:
        async def execute(self, *, operation, **_kwargs):
            return await operation()

    monkeypatch.setattr(
        "services.copilot_execution_ledger.CopilotExecutionService",
        PassthroughExecutionService,
    )


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_contains_expected_keys(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body
        # The operations router owns /health and intentionally exposes only
        # liveness. Build metadata is available from /version.


class TestCopilotOperationBoundary:
    @pytest.mark.asyncio
    async def test_endpoint_uses_workspace_scoped_persistent_memory_as_bounded_history(self, monkeypatch):
        captured = {}

        class FakeMemory:
            async def retrieve(self, **kwargs):
                captured["retrieve"] = kwargs
                return {"conversation_turns": [{"role": "user", "text": "Remember the restaurant ICP."}]}

            async def record_turn(self, **kwargs):
                captured["record_turn"] = kwargs

            async def record_outcome(self, **_kwargs):
                return None

        async def fake_resolve_session(_request):
            return "owner-1", "session-1"

        def fake_decide(_text, **kwargs):
            captured["history"] = kwargs["message_history"]
            return {"intent": "conversation", "action": "", "search_context": {}}

        monkeypatch.setattr(main_module.identity_dependencies, "resolve_web_session", fake_resolve_session)
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.copilot_memory.CopilotMemoryService", lambda: FakeMemory())
        monkeypatch.setattr("services.supabase.get_user_preferences", lambda _user_id: {"tone": "concise"})
        monkeypatch.setattr("services.conversational_response_generator.classify_copilot_read_question", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("services.conversational_response_generator.decide_copilot_intent", fake_decide)
        monkeypatch.setattr("services.conversational_response_generator.generate_copilot_response", lambda **_kwargs: "Grounded response.")

        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="What should I do next?",
            copilot=main_module.CopilotContextModel(
                current_page="Mission Control",
                conversation_id="chat-a",
                message_history=[{"role": "assistant", "text": "I can help."}],
            ),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)

        assert result["ok"] is True
        assert captured["retrieve"] == {
            "user_id": "owner-1", "workspace_id": "workspace-1", "conversation_key": "chat-a",
        }
        assert captured["history"] == [
            {"role": "user", "text": "Remember the restaurant ICP."},
            {"role": "assistant", "text": "I can help."},
        ]
        assert captured["record_turn"]["workspace_id"] == "workspace-1"

    @pytest.mark.asyncio
    async def test_endpoint_executes_a_bounded_multi_step_plan_through_existing_tool_boundary(self, monkeypatch):
        """The HTTP boundary preserves workspace identity across planned steps."""
        calls = []

        async def fake_resolve_session(_request):
            return "owner-1", "session-1"

        async def fake_execute(tool_name, *, user_id, workspace_id, session_token, decision, **_kwargs):
            calls.append((tool_name, user_id, workspace_id, session_token, decision))
            assert user_id == "owner-1"
            assert workspace_id == "workspace-1"
            if tool_name == "campaign.read":
                return {"ok": True, "status": "completed", "tool": tool_name,
                        "result": {"campaign": {"id": "campaign-canonical", "name": "Outbound"}}}
            assert tool_name == "outreach.drafts.read"
            assert decision["campaign_id"] == "campaign-canonical"
            return {"ok": True, "status": "completed", "tool": tool_name,
                    "result": {"campaign_id": "campaign-canonical", "drafts": []}}

        monkeypatch.setattr(main_module.identity_dependencies, "resolve_web_session", fake_resolve_session)
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.conversational_response_generator.classify_copilot_read_question", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "read",
                "action": "campaign.read",
                "plan": [
                    {"action": "campaign.read", "campaign_id": "campaign-requested"},
                    {"action": "outreach.drafts.read"},
                ],
                "search_context": {},
            },
        )
        monkeypatch.setattr("services.copilot_tools.execute_copilot_tool", fake_execute)

        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="Show this campaign and its drafts",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)

        assert result["ok"] is True
        assert result["messages"][0]["data"]["tool"] == "copilot.orchestration"
        assert [call[0] for call in calls] == ["campaign.read", "outreach.drafts.read"]

    def test_workspace_context_uses_explicit_workspace_not_owner_default(self, monkeypatch):
        calls = []

        def load_state(owner_id, include_details=False, workspace_id="", canonical_only=False):
            calls.append((owner_id, include_details, workspace_id, canonical_only))
            assert workspace_id == "workspace-a"
            return {
                "campaigns": [{"id": "campaign-a", "name": "Workspace A campaign", "lead_count": 3}],
                "drafts": [],
            }

        monkeypatch.setattr("services.workspace_state.load_workspace_state", load_state)
        monkeypatch.setattr(
            main_module,
            "build_snapshot",
            lambda *_args, **_kwargs: {
                "campaigns": [{"id": "campaign-a", "name": "Workspace A campaign"}],
                "campaign_count": 1,
                "campaigns_ready": 0,
                "campaigns_draft_review": 0,
                "drafts": {},
                "total_leads": 3,
                "jobs": {},
                "memory": {},
                "timeline": [],
                "analysis": {},
            },
        )
        monkeypatch.setattr(main_module, "get_active_runtimes", lambda *_args: [])
        monkeypatch.setattr(main_module, "communication_store", SimpleNamespace(list_providers=lambda: []))

        context = main_module._build_copilot_workspace_context(
            "session-a",
            user_id="owner-1",
            workspace_id="workspace-a",
        )

        assert calls == [("owner-1", False, "workspace-a", True)]
        assert context["snapshot"]["campaigns"][0]["id"] == "campaign-a"

    @pytest.mark.asyncio
    async def test_inbox_read_rejects_owned_conversation_from_another_workspace(self, monkeypatch):
        from services.conversations.conversation_models import Conversation
        from services.conversations.conversation_store import conversation_store

        foreign = Conversation(
            conversation_id="conversation-b",
            owner_id="owner-1",
            metadata={"workspace_id": "workspace-b"},
        )
        monkeypatch.setattr(conversation_store, "get_conversation", lambda _cid: foreign)
        result = await main_module._run_copilot_inbox(
            "inbox.conversation.read",
            "owner-1",
            "workspace-a",
            "session-1",
            {"conversation_id": "conversation-b", "page_context": {}},
        )
        assert result["ok"] is False
        assert result["status"] == "unavailable"

    def test_analytics_actions_select_read_tools(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "analytics.workspace.summary"}) == "analytics.workspace.summary"
        assert select_copilot_tool({"intent": "read", "action": "analytics.campaign.summary"}) == "analytics.campaign.summary"
        assert select_copilot_tool({"intent": "read", "action": "analytics.leads.summary"}) == "analytics.leads.summary"

    @pytest.mark.asyncio
    async def test_analytics_workspace_returns_authoritative_snapshot_metrics(self, monkeypatch):
        monkeypatch.setattr(
            "services.workspace_state.load_workspace_state",
            lambda *_args, **_kwargs: {"campaigns": [{"id": "c-1", "name": "Outbound", "lead_count": 12, "status": "planning"}], "drafts": []},
        )
        monkeypatch.setattr(
            "services.workspace_snapshot.build_snapshot",
            lambda *_args, **_kwargs: {"total_leads": 12, "campaign_count": 1, "drafts": {"total": 0, "pending": 0, "approved": 0}, "campaigns_ready": 0, "campaigns_draft_review": 0, "campaigns": [{"id": "c-1", "name": "Outbound", "lead_count": 12}], "analysis": {}},
        )
        result = await main_module._run_copilot_analytics(
            "analytics.workspace.summary", "owner-1", "workspace-1", "session-1", {"page_context": {}},
        )
        assert result["ok"] is True
        assert result["result"]["metrics"]["total_leads"] == 12
        assert result["result"]["metrics"]["campaign_count"] == 1

    @pytest.mark.asyncio
    async def test_analytics_campaign_requires_real_selected_campaign(self, monkeypatch):
        monkeypatch.setattr(
            "services.workspace_state.load_workspace_state",
            lambda *_args, **_kwargs: {"campaigns": [], "drafts": []},
        )
        result = await main_module._run_copilot_analytics(
            "analytics.campaign.summary", "owner-1", "workspace-1", "session-1", {"page_context": {}},
        )
        assert result["ok"] is False
        assert result["status"] == "unavailable"
        assert "No campaign" in result["reason"]

    def test_knowledge_actions_select_read_tools(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "knowledge.search"}) == "knowledge.search"
        assert select_copilot_tool({"intent": "read", "action": "knowledge.read"}) == "knowledge.read"

    @pytest.mark.asyncio
    async def test_knowledge_search_returns_canonical_retrieval(self, monkeypatch):
        from services.knowledge.context_adapter import KnowledgePromptContext
        calls = []

        async def fake_retrieve(*_args, **_kwargs):
            calls.append(_kwargs)
            return KnowledgePromptContext(
                query="ICP",
                categories=("icp",),
                items=[{"id": "k-1", "title": "ICP", "category": "icp", "summary": "Mid-market operators"}],
                sources=[],
            )

        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", fake_retrieve)
        result = await main_module._run_copilot_knowledge(
            "knowledge.search", "owner-1", "workspace-1", "session-1",
            {"user_message": "what is our ICP?", "knowledge_categories": ["icp"], "page_context": {}},
        )
        assert result["ok"] is True
        assert result["result"]["items"][0]["id"] == "k-1"
        assert calls == [{"query": "what is our ICP?", "categories": ["icp"], "limit": 8, "workspace_id": "workspace-1"}]

    @pytest.mark.asyncio
    async def test_knowledge_empty_result_is_explicit_not_fabricated(self, monkeypatch):
        from services.knowledge.context_adapter import KnowledgePromptContext

        async def fake_retrieve(*_args, **_kwargs):
            return KnowledgePromptContext(query="unknown", items=[], sources=[])

        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", fake_retrieve)
        result = await main_module._run_copilot_knowledge(
            "knowledge.search", "owner-1", "workspace-1", "session-1",
            {"user_message": "what do we know about unknown?", "page_context": {}},
        )
        assert result["ok"] is True
        assert result["status"] == "empty"
        assert result["result"]["items"] == []
        assert "No matching Knowledge" in result["reason"]

    def test_inbox_actions_select_existing_contract(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "inbox.conversation.read"}) == "inbox.conversation.read"
        assert select_copilot_tool({"intent": "read", "action": "inbox.conversation.summary"}) == "inbox.conversation.summary"
        assert select_copilot_tool({"intent": "read", "action": "inbox.reply.generate"}) == "inbox.reply.generate"
        assert select_copilot_tool({"intent": "action", "action": "inbox.reply.send"}) == "inbox.reply.send"

    @pytest.mark.asyncio
    async def test_inbox_read_returns_authoritative_conversation_data(self, monkeypatch):
        from services.conversations.conversation_models import Conversation
        from services.conversations.conversation_store import conversation_store

        convo = Conversation(
            conversation_id="conversation-1",
            owner_id="owner-1",
            subject="Question about pricing",
            metadata={"workspace_id": "workspace-1"},
        )
        monkeypatch.setattr(conversation_store, "get_conversation", lambda _cid: convo)
        monkeypatch.setattr(conversation_store, "get_messages_for_conversation", lambda _cid: [])
        result = await main_module._run_copilot_inbox(
            "inbox.conversation.read", "owner-1", "workspace-1", "session-1",
            {"conversation_id": "conversation-1", "page_context": {}},
        )
        assert result["ok"] is True
        assert result["result"]["conversation"]["conversation_id"] == "conversation-1"
        assert result["result"]["conversation"]["subject"] == "Question about pricing"

    @pytest.mark.asyncio
    async def test_inbox_send_requires_confirmation_before_existing_send_route(self, monkeypatch):
        from services.conversations.conversation_models import Conversation
        from services.conversations.conversation_store import conversation_store

        convo = Conversation(
            conversation_id="conversation-1",
            owner_id="owner-1",
            metadata={"workspace_id": "workspace-1"},
        )
        monkeypatch.setattr(conversation_store, "get_conversation", lambda _cid: convo)
        called = False

        async def must_not_send(*_args, **_kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(main_module, "send_conversation_reply_route", must_not_send)
        result = await main_module._run_copilot_inbox(
            "inbox.reply.send", "owner-1", "workspace-1", "session-1",
            {"conversation_id": "conversation-1", "reply_body": "Thanks"},
        )
        assert result["ok"] is False
        assert result["status"] == "confirmation_required"
        assert called is False

    def test_outreach_actions_select_existing_contract(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "outreach.drafts.read"}) == "outreach.drafts.read"
        assert select_copilot_tool({"intent": "action", "action": "outreach.draft.refine"}) == "outreach.draft.refine"
        assert select_copilot_tool({"intent": "action", "action": "outreach.draft.send"}) == "outreach.draft.send"

    @pytest.mark.asyncio
    async def test_outreach_read_uses_owned_workspace_drafts(self, monkeypatch):
        monkeypatch.setattr(
            "services.workspace_state.load_drafts_only",
            lambda _user, _workspace: [{"id": "draft-1", "campaign_id": "campaign-1", "subject": "Hello", "text": "Hi there", "status": "pending"}],
        )
        result = await main_module._run_copilot_outreach(
            "outreach.drafts.read", "owner-1", "workspace-1", "session-1",
            {"page_context": {"campaign_id": "campaign-1"}},
        )
        assert result["ok"] is True
        assert result["result"]["drafts"][0]["id"] == "draft-1"

    @pytest.mark.asyncio
    async def test_outreach_send_and_schedule_require_explicit_confirmation(self, monkeypatch):
        monkeypatch.setattr(
            "services.workspace_state.load_drafts_only",
            lambda _user, _workspace: [{"id": "draft-1", "subject": "Hello", "text": "Hi", "status": "pending"}],
        )
        for tool in ("outreach.draft.send", "outreach.draft.schedule"):
            result = await main_module._run_copilot_outreach(
                tool, "owner-1", "workspace-1", "session-1", {"draft_id": "draft-1"},
            )
            assert result["ok"] is False
            assert result["status"] == "confirmation_required"

    @pytest.mark.asyncio
    async def test_outreach_endpoint_returns_authoritative_draft_result(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "read", "action": "outreach.drafts.read", "search_context": {}, "reason": "read drafts"},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr(
            "services.knowledge.context_adapter.retrieve_knowledge_context",
            lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}),
        )
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")

        async def fake_outreach_runner(*_args, **_kwargs):
            return {"ok": True, "status": "completed", "tool": "outreach.drafts.read", "result": {"drafts": [{"id": "draft-1", "subject": "Hello"}]}}

        monkeypatch.setattr(main_module, "_run_copilot_outreach", fake_outreach_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="show my drafts",
            copilot=main_module.CopilotContextModel(current_page="Outreach", page_context={"campaign_id": "campaign-1"}, message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["messages"][0]["data"]["tool"] == "outreach.drafts.read"
        assert result["messages"][0]["data"]["result"]["drafts"][0]["id"] == "draft-1"

    @pytest.mark.asyncio
    async def test_read_tool_uses_its_canonical_result_without_broad_knowledge_prefetch(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "read", "action": "analytics.workspace.summary", "search_context": {}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}})

        async def must_not_prefetch(*_args, **_kwargs):
            raise AssertionError("read tools must not receive broad semantic prefetches")

        async def analytics_runner(*_args, **_kwargs):
            return {"ok": True, "status": "completed", "tool": "analytics.workspace.summary", "result": {"metrics": {"campaign_count": 0}}}

        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", must_not_prefetch)
        monkeypatch.setattr(main_module, "_run_copilot_analytics", analytics_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="How is my workspace performing?",
            copilot=main_module.CopilotContextModel(current_page="Campaign Intelligence", message_history=[]),
        )

        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["messages"][0]["data"]["tool"] == "analytics.workspace.summary"

    def test_discovery_title_is_natural_and_separate_from_provider_query(self):
        title = main_module._discovery_title_from_search_context
        assert title({"industry": ["cafe"]}) == "Cafe leads"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"]}) == "Cafe owners"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"], "location": ["Hyderabad"]}) == "Cafe owners in Hyderabad"
        assert title({"industry": ["cafe"], "decision_makers": ["cafe_owner"], "location": ["Hyderabad"], "quantity": 100}) == "100 cafe owners in Hyderabad"

    def test_intent_contract_supports_conversation_read_and_unsupported_action(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent

        decisions = iter([
            '{"intent":"conversation","mode":"new","search_context":{},"reason":"greeting"}',
            '{"intent":"read","mode":"new","search_context":{},"reason":"existing results"}',
            '{"intent":"action","mode":"new","search_context":{},"action":"campaign.create","reason":"create campaign"}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        assert decide_copilot_intent("hi")["intent"] == "conversation"
        assert decide_copilot_intent("what did you find?", active_search={"discovery_id": "d-1"})["intent"] == "read"
        action = decide_copilot_intent("create a campaign for these")
        assert action["intent"] == "action"
        assert action["action"] == "campaign.create"

    def test_conversation_response_ignores_active_workspace_operations(self):
        from services.conversational_response_generator import generate_copilot_response

        response = generate_copilot_response(
            "hi",
            copilot_context={
                "intent": "conversation",
                "workspace_context": {
                    "snapshot": {"total_leads": 30},
                    "analysis": {"recommended_next_action": {"title": "Create a campaign"}},
                },
                "active_search": {"discovery_id": "d-1"},
                "available_actions": ["launch_campaign", "generate_drafts"],
            },
        )
        assert response == "I’m here to help with your Loqi workspace. What would you like to work on?"
        assert "campaign" not in response.lower()

    def test_read_response_is_grounded_in_authoritative_result(self, monkeypatch):
        from services.conversational_response_generator import generate_copilot_response

        captured = {}

        def fake_openai(system, user, **_kwargs):
            captured["system"] = system
            return "Fact: Campaign Alpha has 12 leads and 3 drafts pending review. Recommendation: review the oldest draft first."

        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            fake_openai,
        )
        response = generate_copilot_response(
            "How is Campaign Alpha doing?",
            copilot_context={
                "intent": "read",
                "mvp_read_only": True,
                "authoritative_tool": "analytics.campaign.summary",
                "authoritative_result": {"metrics": {"lead_count": 12, "pending_drafts": 3}},
                "page_context": {"campaign_name": "Stale client value"},
                "workspace_context": {
                    "snapshot": {"campaign_count": 99, "campaigns": [{"name": "Other workspace campaign"}]},
                    "analysis": {"recommended_next_action": {"title": "Create a campaign"}},
                },
            },
        )
        assert "Campaign Alpha" in response
        assert "lead_count" in captured["system"]
        assert "MVP READ-ONLY MODE" in captured["system"]
        assert "Other workspace campaign" not in captured["system"]
        assert "Stale client value" not in captured["system"]

    @pytest.mark.parametrize(
        ("question", "action"),
        [
            ("How is my campaign performing?", "analytics.workspace.summary"),
            ("Which replies need attention?", "inbox.conversation.recommend"),
            ("What should I change in my outreach?", "outreach.drafts.read"),
            ("Rewrite this draft", "outreach.drafts.read"),
        ],
    )
    def test_strategic_questions_select_read_capabilities(self, monkeypatch, question, action):
        from services.conversational_response_generator import decide_copilot_intent

        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: (
                '{"intent":"read","action":"%s","search_context":{}}' % action
            ),
        )
        decision = decide_copilot_intent(question, message_history=[])
        assert decision["intent"] == "read"
        assert decision["action"] == action

    def test_clear_strategic_questions_use_bounded_local_classification(self):
        from services.conversational_response_generator import classify_copilot_read_question

        ctx = {"campaign_id": "campaign-1", "draft_id": "draft-1", "conversation_id": "conversation-1"}
        active = {"discovery_id": "discovery-1"}
        assert classify_copilot_read_question("How is my campaign performing?", page_context=ctx)["action"] == "analytics.campaign.summary"
        assert classify_copilot_read_question("Which replies need attention?")["action"] == "inbox.conversation.recommend"
        assert classify_copilot_read_question("Which leads should I prioritize?", active_search=active)["action"] == "lead.rank"
        assert classify_copilot_read_question("Rewrite this draft.", page_context=ctx) is None
        assert classify_copilot_read_question("What happened with this prospect?", page_context=ctx)["action"] == "inbox.conversation.analyze"
        assert classify_copilot_read_question(
            "Why?", page_context=ctx,
            message_history=[{"role": "user", "text": "How is my campaign performing?"}],
        )["action"] == "analytics.campaign.summary"
        assert classify_copilot_read_question(
            "What should I change in my outreach?", page_context=ctx,
        )["action"] == "analytics.campaign.summary"
        assert classify_copilot_read_question(
            "What should I do next?", page_context=ctx,
        )["action"] == "analytics.campaign.summary"

    @pytest.mark.asyncio
    async def test_reply_attention_retrieval_uses_persisted_summaries_without_n_plus_one_reads(self, monkeypatch):
        class Candidate:
            conversation_id = "conversation-1"
            subject = "Pricing question"
            status = SimpleNamespace(value="replied")
            metadata = {"workspace_id": "workspace-1"}
            summary = SimpleNamespace(to_dict=lambda: {
                "company": "Acme", "contact_name": "Alex", "interest_level": "high",
                "last_summary": "Asked about pricing", "next_action": "Reply with options",
                "key_points": ["Pricing"],
            })

        class Store:
            def list_conversations(self, limit=50):
                assert limit == 50
                return [Candidate()]

            def get_messages_for_conversation(self, *_args, **_kwargs):
                raise AssertionError("reply attention must not read every conversation's messages")

        import services.conversations.conversation_store as conversation_module
        monkeypatch.setattr(conversation_module, "conversation_store", Store())
        monkeypatch.setattr(main_module, "_conversation_owned_by", lambda *_args: True)
        result = await main_module._run_copilot_inbox(
            "inbox.conversation.recommend", "owner-1", "workspace-1", "session-1", {},
        )
        assert result["ok"] is True
        assert result["result"]["count"] == 1
        assert result["result"]["conversations"][0]["next_action"] == "Reply with options"

    @pytest.mark.asyncio
    async def test_unverified_mutating_tool_remains_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "action", "action": "campaign.create", "search_context": {},
            },
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr(
            "services.knowledge.context_adapter.retrieve_knowledge_context",
            lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}),
        )
        monkeypatch.setattr(main_module, "_run_copilot_campaign", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mutation must not execute")))
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="create a campaign for these leads",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is False
        assert result["messages"][0]["data"]["status"] == "unavailable"

    def test_phase2_confirmation_uses_user_text_not_model_flag(self):
        from services.copilot_tools import mutation_confirmation_state

        assert mutation_confirmation_state("lead.save", "Please save these leads") == "required"
        assert mutation_confirmation_state("lead.save", "I confirm: save these leads") == "confirmed"
        assert mutation_confirmation_state("inbox.reply.send", "yes") == "required"
        assert mutation_confirmation_state("inbox.reply.send", "Do not send this reply") == "declined"

    @pytest.mark.asyncio
    async def test_enabled_mutation_requires_explicit_confirmation_before_runner(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "action", "action": "campaign.refine", "campaign_id": "campaign-1", "campaign_updates": {"objective": "New objective"}, "search_context": {}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr(
            main_module,
            "_run_copilot_campaign",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner must not execute before confirmation")),
        )
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="Could you change this campaign objective?",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", page_context={"campaign_id": "campaign-1"}, message_history=[]),
        )

        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is False
        assert result["operation"]["status"] == "confirmation_required"

    @pytest.mark.asyncio
    async def test_confirmed_mutation_returns_verified_authoritative_result(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "action", "action": "campaign.refine", "campaign_id": "campaign-1", "campaign_updates": {"objective": "New objective"}, "search_context": {}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}})
        calls = []

        async def campaign_runner(tool_name, user_id, workspace_id, session_token, decision):
            calls.append((tool_name, user_id, workspace_id, decision.get("confirmed")))
            return {
                "ok": True,
                "status": "completed",
                "tool": tool_name,
                "result": {"campaign": {"id": "campaign-1", "name": "Campaign A", "objective": "New objective"}},
            }

        monkeypatch.setattr(main_module, "_run_copilot_campaign", campaign_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="I confirm: update this campaign objective to New objective",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", page_context={"campaign_id": "campaign-1"}, message_history=[]),
        )

        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is True
        assert result["messages"][0]["data"]["result"]["campaign"]["objective"] == "New objective"
        assert calls == [("campaign.refine", "test-owner", "workspace-1", True)]

    @pytest.mark.asyncio
    async def test_mutation_failure_or_verification_failure_is_never_success(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "action", "action": "campaign.refine", "campaign_id": "campaign-1", "campaign_updates": {"name": "Changed"}, "search_context": {}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}})

        async def failed_runner(*_args, **_kwargs):
            return {"ok": False, "status": "verification_failed", "tool": "campaign.refine", "reason": "Campaign changes could not be verified in this workspace."}

        monkeypatch.setattr(main_module, "_run_copilot_campaign", failed_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="I confirm: rename this campaign to Changed",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", page_context={"campaign_id": "campaign-1"}, message_history=[]),
        )

        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is False
        assert result["operation"]["status"] == "verification_failed"

    @pytest.mark.asyncio
    async def test_unavailable_workspace_prevents_mutation_execution(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "action", "action": "campaign.refine", "campaign_id": "campaign-1", "campaign_updates": {"name": "Changed"}, "search_context": {}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})

        async def unavailable(*_args, **_kwargs):
            raise HTTPException(status_code=404, detail="Workspace not found")

        monkeypatch.setattr(main_module.workspace_access, "resolve_selected_workspace_context", unavailable)
        monkeypatch.setattr(main_module, "_run_copilot_campaign", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner must not execute outside workspace")))
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="Rename this campaign to Changed",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", page_context={"campaign_id": "campaign-1"}, message_history=[]),
        )

        with pytest.raises(HTTPException, match="Workspace not found"):
            await main_module.post_web_session_message("session-1", payload, request)

    @pytest.mark.asyncio
    async def test_tool_boundary_does_not_execute_for_conversation_or_read(self, monkeypatch):
        from services.copilot_tools import execute_copilot_tool, select_copilot_tool

        assert select_copilot_tool({"intent": "conversation"}) is None
        monkeypatch.setattr(
            "services.discovery.get_discovery",
            lambda _discovery_id, _workspace_id: {
                "id": "d-1", "status": "completed", "title": "Restaurant leads",
                "discovery_leads": [{"rank": 1, "workspace_lead": {"lead": {"name": "A"}}}],
                "discovery_companies": [], "summary": {"lead_count": 1},
            },
        )

        async def must_not_run(*_args, **_kwargs):
            raise AssertionError("Discovery runner must not run for a read")

        result = await execute_copilot_tool(
            "discovery.read",
            user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={"intent": "read", "active_search": {"discovery_id": "d-1"}},
            discovery_runner=must_not_run,
        )
        assert result["ok"] is True
        assert result["result"]["lead_count"] == 1

    @pytest.mark.asyncio
    async def test_discovery_and_refinement_use_executor_runner(self):
        from services.copilot_tools import execute_copilot_tool
        calls = []

        async def runner(user_id, context, session, *, workspace_id):
            calls.append((user_id, context, session, workspace_id))
            return {"discovery_id": "d-1", "job_id": "j-1", "status": "queued"}

        result = await execute_copilot_tool(
            "discovery.refine",
            user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={"intent": "discovery_refinement", "search_context": {"industry": ["restaurants"]}},
            discovery_runner=runner,
        )
        assert result["ok"] is True
        assert calls == [("u-1", {"industry": ["restaurants"]}, "s-1", "w-1")]

    def test_lead_actions_select_only_from_structured_contract(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "lead.read"}) == "lead.read"
        assert select_copilot_tool({"intent": "read", "action": "lead.filter"}) == "lead.filter"
        assert select_copilot_tool({"intent": "read", "action": "lead.rank"}) == "lead.rank"
        assert select_copilot_tool({"intent": "action", "action": "lead.attach"}) == "lead.attach"
        assert select_copilot_tool({"intent": "action", "action": "campaign.launch"}) is None

    def test_active_discovery_followups_route_to_lead_capabilities(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent
        from services.copilot_tools import select_copilot_tool

        decisions = iter([
            '{"intent":"read","action":"lead.rank","sort":"best","limit":5,"search_context":{},"reason":"rank existing leads"}',
            '{"intent":"read","action":"lead.rank","sort":"best","search_context":{},"reason":"rank existing leads"}',
            '{"intent":"read","action":"lead.filter","filters":{"title":"restaurant owner"},"search_context":{},"reason":"filter existing leads"}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        active = {"discovery_id": "d-1", "search_context": {"industry": ["restaurants"]}}

        best_five = decide_copilot_intent("find the best 5", active_search=active)
        strongest = decide_copilot_intent("show the strongest leads", active_search=active)
        owners = decide_copilot_intent("only restaurant owners", active_search=active)

        assert select_copilot_tool(best_five) == "lead.rank"
        assert best_five["limit"] == 5
        assert select_copilot_tool(strongest) == "lead.rank"
        assert select_copilot_tool(owners) == "lead.filter"
        assert owners["filters"] == {"title": "restaurant owner"}

    def test_campaign_intents_select_existing_campaign_tools(self):
        from services.copilot_tools import select_copilot_tool

        assert select_copilot_tool({"intent": "read", "action": "campaign.list"}) == "campaign.list"
        assert select_copilot_tool({"intent": "read", "action": "campaign.drafts"}) == "campaign.drafts"
        assert select_copilot_tool({"intent": "action", "action": "campaign.create"}) == "campaign.create"
        assert select_copilot_tool({"intent": "action", "action": "campaign.plan"}) == "campaign.plan"
        assert select_copilot_tool({"intent": "action", "action": "campaign.generate_drafts"}) == "campaign.generate_drafts"

    @pytest.mark.asyncio
    async def test_campaign_operation_returns_authoritative_result(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "read", "action": "campaign.list", "search_context": {}, "reason": "list campaigns"},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr(
            "services.knowledge.context_adapter.retrieve_knowledge_context",
            lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}),
        )
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")

        async def fake_campaign_runner(*_args, **_kwargs):
            return {
                "ok": True,
                "status": "completed",
                "tool": "campaign.list",
                "result": {"campaigns": [{"id": "c-1", "name": "Restaurant outreach", "status": "planning", "lead_count": 5}]},
            }

        monkeypatch.setattr(main_module, "_run_copilot_campaign", fake_campaign_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="show my campaigns",
            copilot=main_module.CopilotContextModel(current_page="Campaigns", message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["intent"] == "read"
        assert result["messages"][0]["data"]["tool"] == "campaign.list"
        assert result["messages"][0]["data"]["result"]["campaigns"][0]["id"] == "c-1"

    @pytest.mark.asyncio
    async def test_lead_read_filter_and_rank_use_owned_discovery(self, monkeypatch):
        from services.copilot_tools import execute_copilot_tool

        monkeypatch.setattr(
            "services.discovery.get_discovery",
            lambda discovery_id, workspace_id: {
                "id": discovery_id,
                "workspace_id": workspace_id,
                "status": "completed",
                "discovery_leads": [
                    {"lead_id": "l-1", "rank": 2, "match_score": 0.4, "workspace_lead": {"id": "wl-1", "title": "Owner", "lead": {"name": "A", "company": "Cafe A"}}},
                    {"lead_id": "l-2", "rank": 1, "match_score": 0.9, "workspace_lead": {"id": "wl-2", "title": "Founder", "lead": {"name": "B", "company": "Cafe B"}}},
                ],
                "discovery_companies": [],
            },
        )

        common = {
            "intent": "read",
            "active_search": {"discovery_id": "d-1"},
        }
        filtered = await execute_copilot_tool(
            "lead.filter", user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={**common, "filters": {"title": "owner"}}, discovery_runner=None,
        )
        assert filtered["ok"] is True
        assert [lead["id"] for lead in filtered["result"]["leads"]] == ["wl-1"]

        ranked = await execute_copilot_tool(
            "lead.rank", user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={**common, "sort": "best"}, discovery_runner=None,
        )
        assert [lead["id"] for lead in ranked["result"]["leads"]] == ["wl-2", "wl-1"]

        selected = await execute_copilot_tool(
            "lead.read", user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={**common, "page_context": {"selected_lead_ids": ["wl-2"]}}, discovery_runner=None,
        )
        assert [lead["id"] for lead in selected["result"]["leads"]] == ["wl-2"]

    @pytest.mark.asyncio
    async def test_lead_mutations_require_confirmation_and_use_existing_services(self, monkeypatch):
        from services.copilot_tools import execute_copilot_tool

        monkeypatch.setattr(
            "services.discovery.get_discovery",
            lambda *_args: {
                "id": "d-1", "status": "completed", "discovery_companies": [],
                "discovery_leads": [{"lead_id": "l-1", "rank": 1, "workspace_lead": {"id": "wl-1", "email": "a@example.com", "lead": {"name": "A"}}}],
            },
        )
        decision = {"intent": "action", "active_search": {"discovery_id": "d-1"}, "lead_ids": ["wl-1"]}
        pending = await execute_copilot_tool(
            "lead.approve", user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision=decision, discovery_runner=None,
        )
        assert pending["ok"] is False
        assert pending["status"] == "confirmation_required"

        calls = []
        async def persist(user_id, lead, approved, *, workspace_id):
            calls.append((user_id, lead["id"], approved, workspace_id))
            return lead["id"]

        monkeypatch.setattr("services.workspace_state.persist_lead_decision_awaited", persist)
        completed = await execute_copilot_tool(
            "lead.approve", user_id="u-1", workspace_id="w-1", session_token="s-1",
            decision={**decision, "confirmed": True}, discovery_runner=None,
        )
        assert completed["ok"] is True
        assert calls == [("u-1", "wl-1", True, "w-1")]

    @pytest.mark.asyncio
    async def test_endpoint_lead_rank_returns_authoritative_visible_result(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "read", "action": "lead.rank", "sort": "best", "limit": 1,
                "search_context": {}, "reason": "rank active Discovery",
            },
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr(
            "services.knowledge.context_adapter.retrieve_knowledge_context",
            lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}),
        )
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")
        monkeypatch.setattr(
            "services.discovery.get_discovery",
            lambda *_args: {
                "id": "d-1", "status": "completed", "discovery_companies": [],
                "discovery_leads": [
                    {"lead_id": "wl-1", "rank": 1, "match_score": 0.95,
                     "workspace_lead": {"id": "wl-1", "title": "Owner", "lead": {"name": "Best Lead"}}},
                    {"lead_id": "wl-2", "rank": 2, "match_score": 0.4,
                     "workspace_lead": {"id": "wl-2", "title": "Founder", "lead": {"name": "Other Lead"}}},
                ],
            },
        )
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="find the best 5",
            copilot=main_module.CopilotContextModel(
                current_page="Discovery",
                active_search={"discovery_id": "d-1"},
                message_history=[],
            ),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)
        message = result["messages"][0]
        assert result["intent"] == "read"
        assert message["data"]["tool"] == "lead.rank"
        assert message["data"]["result"]["discovery_id"] == "d-1"
        assert [lead["id"] for lead in message["data"]["result"]["leads"]] == ["wl-1"]

    @pytest.mark.asyncio
    async def test_endpoint_conversation_and_read_never_create_discovery(self, monkeypatch):
        decisions = iter([
            {"intent": "conversation", "mode": "new", "search_context": {}, "reason": "greeting"},
            {"intent": "read", "mode": "new", "search_context": {}, "reason": "read results"},
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: next(decisions),
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}))
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")
        monkeypatch.setattr(main_module, "_create_search_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("read/conversation must not create Discovery")))
        monkeypatch.setattr("services.discovery.get_discovery", lambda *_args: {"id": "d-1", "status": "completed", "title": "Restaurant leads", "discovery_leads": [], "discovery_companies": [], "summary": {}})
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(text="hi", copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]))
        conversation = await main_module.post_web_session_message("session-1", payload, request)
        assert conversation["intent"] == "conversation"
        assert "operation" not in conversation
        conversation_text = conversation["messages"][0]["text"]
        assert "campaign" not in conversation_text.lower()
        assert "<<action:" not in conversation_text
        payload.text = "what did you find?"
        payload.copilot.active_search = {"discovery_id": "d-1"}
        read = await main_module.post_web_session_message("session-1", payload, request)
        assert read["intent"] == "read"
        assert read["read_result"]["discovery_id"] == "d-1"

    @pytest.mark.asyncio
    async def test_discovery_tool_failure_is_structured(self, monkeypatch):
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "discovery", "mode": "new", "search_context": {"industry": ["restaurants"]}},
        )
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {"items": [], "sources": []}))
        monkeypatch.setattr("services.workspace_state.ensure_workspace", lambda _user_id: "workspace-1")
        async def fail_runner(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")
        monkeypatch.setattr(main_module, "_run_copilot_discovery", fail_runner)
        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(text="I need restaurant leads", copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]))
        result = await main_module.post_web_session_message("session-1", payload, request)
        assert result["ok"] is False
        assert result["operation"]["status"] == "failed"

    def test_agent_intent_router_distinguishes_action_and_refinements(self, monkeypatch):
        from services.conversational_response_generator import decide_copilot_intent

        decisions = iter([
            '{"intent":"lead_discovery","mode":"new","search_context":{"industry":["restaurants"],"location":[],"decision_makers":[],"quantity":null}}',
            '{"intent":"lead_discovery","mode":"refine","search_context":{"industry":["restaurants"],"location":["Hyderabad"],"decision_makers":[],"quantity":null}}',
            '{"intent":"lead_discovery","mode":"refine","search_context":{"industry":["restaurants"],"location":["Hyderabad"],"decision_makers":[],"quantity":100}}',
        ])
        monkeypatch.setattr(
            "services.conversational_response_generator._send_openai_request",
            lambda *_args, **_kwargs: next(decisions),
        )
        history = [{"role": "user", "text": "I need restaurant leads"}]
        first = decide_copilot_intent("I need restaurant leads", message_history=[])
        second = decide_copilot_intent("Make it Hyderabad", message_history=history)
        third = decide_copilot_intent("Actually give me 100", message_history=history + [{"role": "user", "text": "Make it Hyderabad"}])
        assert [first["intent"], second["intent"], third["intent"]] == ["discovery"] * 3
        assert second["search_context"]["location"] == ["Hyderabad"]
        assert third["search_context"]["quantity"] == 100

    @pytest.mark.asyncio
    async def test_endpoint_returns_real_discovery_operation_for_explicit_request(self, monkeypatch):
        async def fake_knowledge(*_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"items": [], "sources": []})

        async def fake_create_search_run(user_id, query, session, *, display_title=None, workspace_id=""):
            assert user_id == "test-owner"
            assert query == "Find leads matching industries: restaurants"
            assert session == "session-1"
            assert display_title == "Restaurant leads"
            assert workspace_id == "workspace-1"
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "discovery",
                "mode": "new",
                "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None},
                "reason": "explicit operation",
            },
        )

        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: {"user_id": "owner-1"})
        monkeypatch.setattr(
            main_module.engine,
            "handle_message",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy engine must not receive Copilot requests")),
        )
        monkeypatch.setattr(main_module, "_build_copilot_workspace_context", lambda *args, **kwargs: {"snapshot": {}, "analysis": {}})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", fake_knowledge)
        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)

        request = SimpleNamespace(headers=SimpleNamespace(get=lambda key, default="": "Bearer session-1" if key == "authorization" else default))
        payload = main_module.SendWebMessageRequest(
            text="I need new restaurant leads",
            copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]),
        )
        result = await main_module.post_web_session_message("session-1", payload, request)

        assert result["operation"]["kind"] == "search_discovery"
        assert result["operation"]["discovery_id"] == "discovery-1"
        assert result["operation"]["job_id"] == "job-1"

    @pytest.mark.asyncio
    async def test_copilot_bootstrap_does_not_fall_into_legacy_engine(self, monkeypatch):
        summaries = iter([None, {"user_id": "owner-1", "display_name": "user"}])
        monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: next(summaries))
        monkeypatch.setattr(main_module.engine, "create_web_session", lambda **_kwargs: {"session_token": "created-session"})
        monkeypatch.setattr(
            main_module,
            "_build_copilot_workspace_context",
            lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}},
        )
        monkeypatch.setattr(
            main_module.engine,
            "handle_message",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy engine must not receive Copilot bootstrap")),
        )
        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {"intent": "discovery", "mode": "new", "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None}, "reason": "explicit operation"},
        )
        async def empty_knowledge(*_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"items": [], "sources": []})
        monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", empty_knowledge)
        async def fake_create_search_run(_user_id, _query, _session, **_kwargs):
            return {"discovery_id": "discovery-2", "job_id": "job-2", "status": "queued"}
        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)

        request = SimpleNamespace(
            headers=SimpleNamespace(
                get=lambda key, default="": "Bearer session-1" if key == "authorization" else default,
            ),
        )
        payload = main_module.SendWebMessageRequest(
            text="I need restaurant leads",
            copilot=main_module.CopilotContextModel(current_page="Mission Control", message_history=[]),
        )
        result = await main_module.post_web_session_message("missing-session", payload, request)
        assert result["operation"]["job_id"] == "job-2"


class TestSessionCreation:
    def test_session_token_exists(self, client):
        resp = client.post("/api/web/session", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_token" in data

    def test_session_token_non_empty(self, client):
        resp = client.post("/api/web/session", json={})
        data = resp.json()
        assert len(data["session_token"]) > 0


class TestCopilotMessage:
    def test_copilot_message_returns_200(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        assert resp.status_code == 200

    def test_copilot_message_ok_true(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert data["ok"] is True

    def test_copilot_messages_is_array(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert isinstance(data["messages"], list)

    def test_copilot_messages_non_empty(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert len(data["messages"]) > 0

    def test_copilot_last_message_role_assistant(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        last = data["messages"][-1]
        assert last["role"] == "assistant"

    def test_copilot_last_message_text_non_empty(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        last = data["messages"][-1]
        assert len(last["text"]) > 0


class TestStructuredContext:
    def test_structured_context_returns_200(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Discovery",
                    "page_context": {"selected_count": 3},
                    "available_actions": ["select_all"],
                },
            },
        )
        assert resp.status_code == 200

    def test_structured_context_valid_response(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Discovery",
                    "page_context": {"selected_count": 3},
                    "available_actions": ["select_all"],
                },
            },
        )
        data = resp.json()
        assert data["ok"] is True
        assert len(data["messages"]) > 0
        assert data["messages"][-1]["role"] == "assistant"

    def test_explicit_lead_request_starts_canonical_discovery_job(self, client, session_token, monkeypatch):
        calls = []

        async def fake_create_search_run(user_id, query, session, **_kwargs):
            calls.append((user_id, query, session))
            return {"discovery_id": "discovery-1", "job_id": "job-1", "status": "queued"}

        monkeypatch.setattr(
            "services.conversational_response_generator.decide_copilot_intent",
            lambda *_args, **_kwargs: {
                "intent": "discovery",
                "mode": "new",
                "search_context": {"industry": ["restaurants"], "location": [], "decision_makers": [], "quantity": None},
                "reason": "explicit operation",
            },
        )

        monkeypatch.setattr(main_module, "_create_search_run", fake_create_search_run)
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "text": "I need new restaurant leads",
                "copilot": {
                    "current_page": "Mission Control",
                    "message_history": [],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["operation"]["kind"] == "search_discovery"
        assert body["operation"]["discovery_id"] == "discovery-1"
        assert body["operation"]["job_id"] == "job-1"
        assert body["operation"]["status"] == "queued"
        assert calls and calls[0][1] == "Find leads matching industries: restaurants"

class TestUnknownSession:
    def test_unknown_session_returns_valid_response(self, client):
        token = "nonexistent-session-token-12345"
        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is True

    def test_unknown_session_produces_messages(self, client):
        token = "nonexistent-session-token-12345"
        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "Hello",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) > 0


class TestInvalidPayload:
    def test_missing_text_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            json={},
        )
        assert resp.status_code == 422

    def test_invalid_json_returns_422(self, client, session_token):
        resp = client.post(
            f"/api/web/session/{session_token}/messages",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


COPILOT_PAYLOADS = [
    {
        "text": "Hello",
        "copilot": {
            "current_page": "Mission Control",
            "page_context": {},
            "available_actions": [],
        },
    },
    {
        "text": "Show leads",
        "copilot": {
            "current_page": "Discovery",
            "page_context": {"count": 5},
            "available_actions": ["select_all", "export"],
        },
    },
    {
        "text": "Help me",
        "copilot": {
            "current_page": "Compose",
            "page_context": {"draft_id": "abc"},
            "available_actions": [],
        },
    },
]


@pytest.fixture
def _schema_responses(client, session_token, monkeypatch):
    # This fixture validates the response envelope, not intent routing or
    # Discovery persistence. Keep its otherwise generic payloads on the safe
    # conversational path so a schema regression cannot create a real job.
    monkeypatch.setattr(
        "services.conversational_response_generator.decide_copilot_intent",
        lambda *_args, **_kwargs: {
            "intent": "conversation",
            "mode": "new",
            "search_context": {},
        },
    )
    monkeypatch.setattr(
        main_module,
        "_build_copilot_workspace_context",
        lambda *_args, **_kwargs: {"snapshot": {}, "analysis": {}},
    )
    return [
        client.post(
            f"/api/web/session/{session_token}/messages",
            json=p,
        )
        for p in COPILOT_PAYLOADS
    ]


class TestResponseSchema:
    """Assert every successful copilot response has the required schema."""

    def test_ok_field_present(self, _schema_responses):
        for resp in _schema_responses:
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    def test_messages_field_present(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            assert "messages" in data
            assert isinstance(data["messages"], list)

    def test_events_field_present(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            assert "events" in data
            assert isinstance(data["events"], list)

    def test_each_message_has_required_fields(self, _schema_responses):
        for resp in _schema_responses:
            data = resp.json()
            for msg in data["messages"]:
                assert "role" in msg
                assert "type" in msg
                assert "text" in msg
                assert msg["role"] == "assistant"
                assert len(msg["text"]) > 0
