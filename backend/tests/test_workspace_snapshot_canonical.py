"""Regression tests for canonical workspace snapshot authority."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.mission_control.payload import embed_delta_into_snapshot
from services.workspace import snapshot as workspace_snapshot
from services.world_model import EventType, get_store, publish


def _canonical_campaigns() -> list[dict]:
    return [{
        "id": "campaign-canonical",
        "name": "Canonical campaign",
        "status": "planning",
        "lead_count": 2,
        "strategy": {"objective": "Reach qualified leads"},
        "updated_at": "2026-01-01T00:00:00+00:00",
    }]


def _canonical_drafts() -> list[dict]:
    return [
        {
            "id": "draft-pending",
            "campaign_id": "campaign-canonical",
            "status": "pending",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": "draft-approved",
            "campaign_id": "campaign-canonical",
            "status": "approved",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    ]


def _disable_noncanonical_snapshot_inputs(monkeypatch) -> None:
    workspace_snapshot._cache.clear()
    monkeypatch.setattr(workspace_snapshot.job_manager, "list_recent_jobs", lambda _user_id: [])
    monkeypatch.setattr(workspace_snapshot, "get_memory", lambda _session_token: {})
    monkeypatch.setattr(workspace_snapshot, "get_events", lambda _session_token, limit=10: [])

    class NoopLearner:
        def run(self, _session_token):
            return []

    monkeypatch.setattr(workspace_snapshot, "Learner", NoopLearner)


def test_empty_world_model_keeps_complete_canonical_workspace_snapshot(monkeypatch):
    _disable_noncanonical_snapshot_inputs(monkeypatch)
    store = get_store()
    store.clear_session("empty-world-model")

    result = workspace_snapshot.build_snapshot(
        "empty-world-model",
        _canonical_campaigns(),
        _canonical_drafts(),
        total_leads=2,
        force_refresh=True,
        user_id="owner-1",
    )

    assert result["campaigns"] == [{
        "id": "campaign-canonical",
        "name": "Canonical campaign",
        "status": "planning",
        "current_step": "review",
        "lead_count": 2,
        "pending_drafts": 1,
        "approved_drafts": 1,
        "created_at": "",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }]
    assert result["drafts"] == {"total": 2, "pending": 1, "approved": 1}
    assert result["total_leads"] == 2


def test_stale_world_model_cannot_override_canonical_snapshot_facts(monkeypatch):
    _disable_noncanonical_snapshot_inputs(monkeypatch)
    token = "stale-world-model"
    store = get_store()
    store.clear_session(token)
    publish(token, EventType.CAMPAIGN_CREATED, {
        "id": "campaign-foreign",
        "name": "Stale foreign campaign",
        "status": "sending",
        "lead_count": 999,
    })
    publish(token, EventType.DRAFT_GENERATED, {
        "id": "draft-foreign",
        "campaign_id": "campaign-foreign",
        "subject": "Stale",
    })

    result = workspace_snapshot.build_snapshot(
        token,
        _canonical_campaigns(),
        _canonical_drafts(),
        total_leads=2,
        force_refresh=True,
        user_id="owner-1",
    )

    assert [campaign["id"] for campaign in result["campaigns"]] == ["campaign-canonical"]
    assert result["campaigns"][0]["name"] == "Canonical campaign"
    assert result["campaigns"][0]["lead_count"] == 2
    assert result["drafts"] == {"total": 2, "pending": 1, "approved": 1}


def test_world_model_delta_enriches_without_changing_canonical_snapshot_facts(monkeypatch):
    _disable_noncanonical_snapshot_inputs(monkeypatch)
    token = "world-model-delta"
    store = get_store()
    store.clear_session(token)
    publish(token, EventType.CAMPAIGN_CREATED, {"id": "activity-only", "name": "Activity"})

    result = workspace_snapshot.build_snapshot(
        token,
        _canonical_campaigns(),
        _canonical_drafts(),
        total_leads=2,
        force_refresh=True,
        user_id="owner-1",
    )
    embed_delta_into_snapshot(result, store.compute_delta(token))

    assert result["campaigns"][0]["id"] == "campaign-canonical"
    assert result["drafts"] == {"total": 2, "pending": 1, "approved": 1}
    assert result["_delta"]["new_campaigns"] == 1


def test_world_model_events_cannot_cross_workspace_into_canonical_snapshot(monkeypatch):
    _disable_noncanonical_snapshot_inputs(monkeypatch)
    token = "shared-legacy-token"
    store = get_store()
    store.clear_session(token)
    publish(token, EventType.LEAD_DISCOVERED, {
        "id": "foreign-lead",
        "campaign_id": "foreign-campaign",
        "name": "Foreign lead",
    })

    result = workspace_snapshot.build_snapshot(
        token,
        _canonical_campaigns(),
        _canonical_drafts(),
        total_leads=2,
        force_refresh=True,
        user_id="owner-1",
    )

    assert [campaign["id"] for campaign in result["campaigns"]] == ["campaign-canonical"]
    assert result["total_leads"] == 2


@pytest.mark.asyncio
async def test_workflow_planning_receives_canonical_snapshot_despite_world_model_conflict(monkeypatch):
    import services.workflows.service as workflow_service

    _disable_noncanonical_snapshot_inputs(monkeypatch)
    token = "workflow-canonical"
    store = get_store()
    store.clear_session(token)
    publish(token, EventType.CAMPAIGN_CREATED, {
        "id": "world-model-only", "name": "Wrong planning input", "lead_count": 999,
    })
    captured: dict[str, object] = {}
    monkeypatch.setattr(workflow_service, "load_campaigns", lambda *_args, **_kwargs: _canonical_campaigns())
    monkeypatch.setattr(workflow_service, "load_drafts_only", lambda *_args, **_kwargs: _canonical_drafts())

    # The planner result is intentionally simple; this test characterizes its input boundary.
    class Plans:
        primary_plan = SimpleNamespace(model_dump=lambda: {"id": "primary"})
        alternative_plan = SimpleNamespace(model_dump=lambda: {"id": "alternative"})
        recommendation = "Review"
        confidence = 1.0

    def plan_with_captured_snapshot(**kwargs):
        captured["snapshot"] = kwargs["snapshot"]
        return Plans()

    monkeypatch.setattr(workflow_service, "plan_workflow", plan_with_captured_snapshot)
    result = await workflow_service.plan_workspace_workflow(
        user_id="owner-1",
        workspace_id="workspace-1",
        session_token=token,
        objective="Review campaigns",
    )

    assert result["ok"] is True
    snapshot = captured["snapshot"]
    assert [campaign["id"] for campaign in snapshot["campaigns"]] == ["campaign-canonical"]


@pytest.mark.asyncio
async def test_copilot_analytics_receives_canonical_snapshot_despite_world_model_conflict(monkeypatch):
    from services.copilot import runners
    from services.workspace import state as workspace_state

    _disable_noncanonical_snapshot_inputs(monkeypatch)
    token = "copilot-canonical"
    store = get_store()
    store.clear_session(token)
    publish(token, EventType.CAMPAIGN_CREATED, {
        "id": "world-model-only", "name": "Wrong analytics input", "lead_count": 999,
    })
    monkeypatch.setattr(
        workspace_state,
        "load_workspace_state",
        lambda *_args, **_kwargs: {"campaigns": _canonical_campaigns(), "drafts": _canonical_drafts()},
    )

    result = await runners.run_analytics(
        "analytics.workspace.summary",
        "owner-1",
        "workspace-1",
        token,
        {},
    )

    assert result["ok"] is True
    assert [campaign["id"] for campaign in result["result"]["campaigns"]] == ["campaign-canonical"]
