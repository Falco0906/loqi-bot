"""Contracts for Mission Control durable activity acknowledgement."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_summary_acknowledges_only_the_sequence_delivered_in_its_payload(monkeypatch):
    from services.mission_control.briefing import MissionControlService
    from services.world_model.state import WorkspaceDelta

    acknowledgements = []

    class ActivityRepository:
        def acknowledge(self, workspace_id, user_id, delivered):
            acknowledgements.append((workspace_id, user_id, delivered))
            return delivered

    async def shared_payload(*_args, **_kwargs):
        return {
            "campaigns": [], "snapshot": {"campaigns": [], "drafts": {"total": 0, "pending": 0, "approved": 0}, "total_leads": 0, "analysis": {}},
            "analysis": {"workspace_health": {}, "attention_items": []}, "recommendations": [],
            "brief": {"greeting": "", "lines": [], "suggestion": ""},
            "delta": WorkspaceDelta(event_count=1, event_range=(5, 5)), "drafts": [], "total_leads": 0,
        }

    monkeypatch.setattr("services.mission_control.payload.compute_shared_payload", shared_payload)
    monkeypatch.setattr("services.world_model.activity_repository.get_activity_repository", lambda: ActivityRepository())
    monkeypatch.setattr("services.job_engine.job_manager.list_active_jobs", lambda *_args: [])
    monkeypatch.setattr("services.workspace.timeline.get_grouped_events", lambda *_args: [])

    class Onboarding:
        async def get_wizard_data(self, _owner): return {}

    monkeypatch.setattr("services.onboarding.api.get_onboarding_service", lambda: Onboarding())
    response = await MissionControlService().get_summary(
        owner_id="user-a", workspace_id="workspace-a", actor_user_id="user-a", session_token="legacy-token",
    )
    assert response["delta"]["event_range"] == [5, 5]
    assert acknowledgements == [("workspace-a", "user-a", 5)]
