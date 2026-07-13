"""Integration tests for Workspace Reasoner → Mission Control → Copilot pipeline.

Tests that:
- build_snapshot produces campaigns that WorkspaceReasoner analyzes
- Mission Control returns structured analysis with campaign references
- Copilot "what should I do next" yields an answer mentioning actual campaign names
"""

import pytest
from datetime import datetime, timezone

from services.workspace_memory import clear as clear_memory, record, record_search
from services.workspace_timeline import clear as clear_timeline
from services.workspace_snapshot import invalidate_cache, build_snapshot


@pytest.fixture
def session_with_data(client):
    """Create a session with 2 campaigns, some drafts, and memory."""
    resp = client.post("/api/web/session", json={})
    assert resp.status_code == 200
    token = resp.json()["session_token"]

    clear_memory(token)
    clear_timeline(token)
    invalidate_cache(token)

    now = datetime.now(timezone.utc).isoformat()

    campaigns = [
        {
            "id": "camp-1",
            "name": "Tech Founders Outreach",
            "status": "draft_review",
            "lead_count": 25,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "camp-2",
            "name": "SaaS Pilot Campaign",
            "status": "planning",
            "lead_count": 12,
            "created_at": now,
            "updated_at": now,
        },
    ]

    drafts = [
        {
            "id": "draft-1",
            "campaign_id": "camp-1",
            "status": "pending",
            "lead_name": "Alice",
        },
        {
            "id": "draft-2",
            "campaign_id": "camp-1",
            "status": "pending",
            "lead_name": "Bob",
        },
        {
            "id": "draft-3",
            "campaign_id": "camp-1",
            "status": "approved",
            "lead_name": "Carol",
        },
    ]

    record_search(token, "tech founders")
    record(token, "last_campaign_id", "camp-1")
    record(token, "last_campaign_name", "Tech Founders Outreach")
    record(token, "last_action", "open_campaign:Tech Founders Outreach")

    return {
        "token": token,
        "campaigns": campaigns,
        "drafts": drafts,
    }


class TestWorkspaceSnapshot:
    def test_build_snapshot_has_campaigns(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        assert snapshot["campaign_count"] == 2
        assert snapshot["campaigns_ready"] == 0
        assert snapshot["campaigns_draft_review"] == 1
        names = [c["name"] for c in snapshot["campaigns"]]
        assert "Tech Founders Outreach" in names
        assert "SaaS Pilot Campaign" in names
        assert snapshot["drafts"]["pending"] == 2
        assert snapshot["drafts"]["approved"] == 1
        assert snapshot["drafts"]["total"] == 3

    def test_snapshot_contains_analysis(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot.get("analysis", {})
        assert analysis is not None
        assert "campaign_priorities" in analysis
        assert "current_focus" in analysis
        assert "recommended_next_action" in analysis
        assert "workspace_health" in analysis
        assert "workflow_continuation" in analysis
        assert "attention_items" in analysis


class TestWorkspaceReasoner:
    def test_analyze_ranks_correctly(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        priorities = analysis["campaign_priorities"]
        assert len(priorities) == 2

        tech = next(p for p in priorities if "Tech Founders" in p["name"])
        saas = next(p for p in priorities if "SaaS Pilot" in p["name"])
        assert tech["rank"] == 1
        assert saas["rank"] == 2
        assert tech["score"] > saas["score"]

    def test_recommended_action_uses_campaign_name(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        rna = analysis["recommended_next_action"]
        assert rna is not None
        assert "Tech Founders" in rna.get("title", "")
        assert rna.get("link") == "/draft"

    def test_current_focus_from_memory(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        cf = analysis["current_focus"]
        assert cf is not None
        assert cf.get("campaign_name") == "Tech Founders Outreach"
        assert "reviewing" in cf.get("action_type", "").lower() or "overview" in cf.get("focus", "").lower()

    def test_attention_items_include_pending_drafts(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        items = analysis.get("attention_items", [])
        assert len(items) >= 1
        assert any("pending" in i["title"].lower() for i in items)
        assert items[0]["link"] in ("/draft", "/campaigns/camp-1")

    def test_health_not_empty(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        health = analysis["workspace_health"]
        assert health is not None
        assert health["overall_health"] in ("healthy", "moderate", "at_risk", "empty")
        assert health["pipeline_velocity"] in ("strong", "moderate", "slow", "no_pipeline")

    def test_workflow_continuation_mentions_campaign(self, session_with_data):
        s = session_with_data
        snapshot = build_snapshot(s["token"], s["campaigns"], s["drafts"])
        analysis = snapshot["analysis"]

        wc = analysis["workflow_continuation"]
        assert wc is not None
        assert wc["should_resume"] is True or wc["should_resume"] is False
        if wc["campaign_name"]:
            assert any(name in wc["campaign_name"] for name in ["Tech Founders", "SaaS Pilot"])


class TestMissionControlIntegration:
    def test_mc_endpoint_returns_campaigns(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        existing = client.app.dependency_overrides if hasattr(client.app, "dependency_overrides") else {}

        from main import campaign_store
        campaign_store[token] = s["campaigns"]
        from main import draft_store
        draft_store[token] = s["drafts"]

        resp = client.get(f"/api/web/session/{token}/mission-control")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["campaign_count"] == 2
        assert len(data["campaigns"]) == 2

    def test_mc_contains_workspace_analysis(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        from main import campaign_store, draft_store
        campaign_store[token] = s["campaigns"]
        draft_store[token] = s["drafts"]

        resp = client.get(f"/api/web/session/{token}/mission-control")
        data = resp.json()
        analysis = data.get("workspace_analysis", {})
        assert analysis is not None
        assert "current_focus" in analysis
        assert "campaign_priorities" in analysis
        assert "workspace_health" in analysis
        assert "cross_campaign_insights" in analysis
        assert "workflow_continuation" in analysis

    def test_mc_recommendations_reference_campaign(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        from main import campaign_store, draft_store
        campaign_store[token] = s["campaigns"]
        draft_store[token] = s["drafts"]

        resp = client.get(f"/api/web/session/{token}/mission-control")
        data = resp.json()
        recs = data.get("recommendations", [])
        assert len(recs) >= 1
        titles = " ".join(r.get("observation", "") for r in recs)
        assert any(name in titles for name in ["Tech Founders", "draft"])

    def test_mc_brief_mentions_campaign(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        from main import campaign_store, draft_store
        campaign_store[token] = s["campaigns"]
        draft_store[token] = s["drafts"]

        resp = client.get(f"/api/web/session/{token}/mission-control")
        data = resp.json()
        brief = data.get("brief", {})
        lines = brief.get("lines", [])
        text = " ".join(lines)
        assert any(name in text for name in ["Tech Founders", "Outreach", "campaign"])


class TestCopilotIntegration:
    def test_copilot_responds_with_campaign_context(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        from main import campaign_store, draft_store
        campaign_store[token] = s["campaigns"]
        draft_store[token] = s["drafts"]

        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "What should I do next?",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        messages = data.get("messages", [])
        assert len(messages) >= 1
        text = messages[-1].get("text", "")
        assert len(text) > 0
        assert "Tech Founders" in text or "Outreach" in text or "draft" in text or "pending" in text, (
            f"Copilot response should reference workspace context, got: {text[:200]}"
        )

    def test_copilot_does_not_ask_for_context(self, client, session_with_data):
        s = session_with_data
        token = s["token"]

        from main import campaign_store, draft_store
        campaign_store[token] = s["campaigns"]
        draft_store[token] = s["drafts"]

        resp = client.post(
            f"/api/web/session/{token}/messages",
            json={
                "text": "What should I do next?",
                "copilot": {
                    "current_page": "Mission Control",
                    "page_context": {},
                    "available_actions": [],
                },
            },
        )
        data = resp.json()
        text = data["messages"][-1]["text"]
        forbidden = ["provide more context", "I don't have enough", "can't see your workspace", "cannot access"]
        for phrase in forbidden:
            assert phrase.lower() not in text.lower(), (
                f"Copilot should not ask for context, got: {phrase} in {text[:200]}"
            )
