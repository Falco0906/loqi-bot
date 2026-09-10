"""Characterization for the workspace-context read-model envelope."""

from __future__ import annotations

from types import SimpleNamespace


def _reasoner(monkeypatch, module):
    class _Analysis:
        def to_dict(self):
            return {
                "current_focus": "Review approved drafts",
                "recommended_next_action": "Send the approved draft",
                "campaign_priorities": [{"campaign_id": "campaign-a"}],
                "workspace_health": {"overall_health": "healthy"},
                "cross_campaign_insights": ["Keep momentum"],
                "workflow_continuation": {"step": "send"},
                "attention_items": [{"title": "Draft ready"}],
            }

    class _Reasoner:
        def __init__(self, snapshot):
            assert "campaign_count" in snapshot

        def analyze(self):
            return _Analysis()

    monkeypatch.setattr(module, "WorkspaceReasoner", _Reasoner)


def _provider(provider_id, user_id, email, status="healthy", last_sync="2026-01-02T00:00:00+00:00"):
    return SimpleNamespace(
        id=provider_id,
        user_id=user_id,
        provider_type=SimpleNamespace(value="gmail"),
        status=SimpleNamespace(value=status),
        metadata={"email": email},
        last_sync=last_sync,
    )


def test_workspace_context_preserves_complete_read_envelope(monkeypatch):
    from services.workspace import context as context_owner

    monkeypatch.setattr(context_owner, "load_workspace_state", lambda *_args, **_kwargs: {
        "campaigns": [{"id": "campaign-a", "name": "Alpha", "status": "active", "lead_count": 2}],
        "drafts": [
            {"id": "draft-pending", "campaign_id": "campaign-a", "status": "pending"},
            {"id": "draft-approved", "campaign_id": "campaign-a", "status": "approved"},
        ],
    })
    monkeypatch.setattr(context_owner, "enrich_campaigns", lambda *_args: [{
        "id": "campaign-a", "name": "Alpha", "status": "active", "current_step": "sending",
        "lead_count": 2, "pending_drafts": 1, "approved_drafts": 1,
        "created_at": "", "updated_at": "",
    }])
    _reasoner(monkeypatch, context_owner)
    provider = _provider("provider-a", "user-a", "a@loqi.example")
    monkeypatch.setattr(context_owner, "communication_store", SimpleNamespace(list_providers=lambda: [provider]))
    monkeypatch.setattr(
        context_owner,
        "get_provider",
        lambda _provider_id: SimpleNamespace(health=lambda: SimpleNamespace(value="healthy")),
    )

    context = context_owner.build_workspace_context(
        "legacy-path-token",
        user_id="user-a",
        workspace_id="workspace-a",
    )

    assert context == {
        "snapshot": {
            "campaigns": [{
                "id": "campaign-a", "name": "Alpha", "status": "active", "current_step": "sending",
                "lead_count": 2, "pending_drafts": 1, "approved_drafts": 1,
                "created_at": "", "updated_at": "",
            }],
            "campaign_count": 1,
            "campaigns_ready": 1,
            "campaigns_draft_review": 0,
            "drafts": {"total": 2, "pending": 1, "approved": 1},
            "total_leads": 2,
            "jobs": {"running": [], "recently_completed": []},
            "memory": {},
            "timeline": [],
            "active_workflows": [],
        },
        "analysis": {
            "current_focus": "Review approved drafts",
            "recommended_next_action": "Send the approved draft",
            "campaign_priorities": [{"campaign_id": "campaign-a"}],
            "workspace_health": {"overall_health": "healthy"},
            "cross_campaign_insights": ["Keep momentum"],
            "workflow_continuation": {"step": "send"},
            "attention_items": [{"title": "Draft ready"}],
        },
        "providers": [{
            "id": "provider-a", "provider_type": "gmail", "status": "healthy",
            "email": "a@loqi.example", "last_sync": "2026-01-02T00:00:00+00:00",
        }],
        "provider_summary": {
            "total": 1, "healthy": 1, "offline": 0, "last_sync": "2026-01-02T00:00:00+00:00",
        },
    }


def test_workspace_context_filters_foreign_provider_and_conversation(monkeypatch):
    from services.workspace import context as context_owner
    import services.conversations.conversation_store as conversations

    monkeypatch.setattr(context_owner, "load_workspace_state", lambda *_args, **_kwargs: {
        "campaigns": [], "drafts": [],
    })
    monkeypatch.setattr(context_owner, "enrich_campaigns", lambda *_args: [])
    _reasoner(monkeypatch, context_owner)
    monkeypatch.setattr(
        context_owner,
        "communication_store",
        SimpleNamespace(list_providers=lambda: [
            _provider("provider-a", "user-a", "a@loqi.example"),
            _provider("provider-b", "user-b", "b@loqi.example"),
        ]),
    )
    monkeypatch.setattr(context_owner, "get_provider", lambda _provider_id: None)
    foreign_store = SimpleNamespace(
        get_conversation=lambda _conversation_id: SimpleNamespace(
            owner_id="user-b", metadata={"workspace_id": "workspace-b"},
        ),
    )
    monkeypatch.setattr(conversations, "conversation_store", foreign_store)
    monkeypatch.setattr(context_owner, "conversation_store", foreign_store)
    monkeypatch.setattr(context_owner, "conversation_owned_by", lambda *_args: False)

    context = context_owner.build_workspace_context(
        "legacy-path-token",
        conversation_id="foreign-conversation",
        user_id="user-a",
        workspace_id="workspace-a",
    )

    assert [provider["id"] for provider in context["providers"]] == ["provider-a"]
    assert "conversation_intelligence" not in context


def test_workspace_context_route_uses_authorized_workspace_context(client, monkeypatch):
    from services.identity import dependencies as identity_dependencies
    from services.workspace import access, context as context_owner

    monkeypatch.setattr(identity_dependencies, "web_session_token", lambda _request: "bearer-a")

    async def authenticated_user(_request, _token=""):
        return "user-a"

    async def selected_workspace(_request, user_id):
        assert user_id == "user-a"
        return SimpleNamespace(workspace_id="workspace-a")

    seen = []
    def build(session_token, **kwargs):
        seen.append((session_token, kwargs))
        return {"snapshot": {"campaign_count": 0}, "analysis": {}}

    monkeypatch.setattr(identity_dependencies, "authenticated_user_id", authenticated_user)
    monkeypatch.setattr(access, "resolve_selected_workspace_context", selected_workspace)
    monkeypatch.setattr(context_owner, "build_workspace_context", build)

    response = client.get(
        "/api/web/session/path-token/workspace-context?conversation_id=conversation-a",
    )

    assert response.status_code == 200
    assert response.json() == {"snapshot": {"campaign_count": 0}, "analysis": {}}
    assert seen == [("bearer-a", {
        "current_page": "Mission Control",
        "conversation_id": "conversation-a",
        "user_id": "user-a",
        "workspace_id": "workspace-a",
    })]
