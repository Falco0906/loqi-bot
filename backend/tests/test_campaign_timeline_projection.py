"""Offline contracts for the durable/canonical campaign timeline projection."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from services.campaigns.timeline import CampaignTimelineService
from services.persistence.launch import CampaignLaunchFailure
from services.world_model.activity_repository import WorkspaceActivityEvent


@dataclass
class _History:
    id: str
    draft_id: str
    status: str
    sent_at: str
    recipient_email: str = "secret@example.test"
    error: str = "raw provider failure"
    provider_id: str = "provider-secret"


def _activity(
    event_id: str, event_type: str, payload: dict, sequence: int, occurred_at: str,
    source_key: str | None = None,
) -> WorkspaceActivityEvent:
    return WorkspaceActivityEvent(
        id=event_id,
        workspace_id="workspace-a",
        actor_user_id="user-a",
        event_type=event_type,
        payload=payload,
        source_key=source_key or f"source:{event_id}",
        sequence=sequence,
        occurred_at=occurred_at,
    )


def _configure_sources(monkeypatch, *, campaigns, activities, drafts, history, launch_failures):
    import services.campaigns.timeline as timeline

    class _ActivityRepository:
        def read_events_after(self, workspace_id, after_sequence):
            assert workspace_id == "workspace-a"
            assert after_sequence == 0
            return activities

    class _LaunchFailureRepository:
        async def list_for_campaign(self, *, workspace_id, campaign_id):
            assert workspace_id == "workspace-a"
            assert campaign_id == "campaign-a"
            return launch_failures

    monkeypatch.setattr(timeline, "load_campaigns", lambda owner_id, *, workspace_id: campaigns)
    monkeypatch.setattr(timeline, "load_drafts_only", lambda owner_id, *, workspace_id: drafts)
    monkeypatch.setattr(timeline, "list_outbound_history", lambda workspace_id, _provider, _limit: history)
    monkeypatch.setattr(timeline, "get_activity_repository", lambda: _ActivityRepository())
    monkeypatch.setattr(timeline, "CampaignLaunchFailureRepository", _LaunchFailureRepository)


@pytest.mark.asyncio
async def test_denies_foreign_campaign_before_any_timeline_source_read(monkeypatch):
    import services.campaigns.timeline as timeline

    reads: list[str] = []
    monkeypatch.setattr(timeline, "load_campaigns", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(timeline, "load_drafts_only", lambda *_args, **_kwargs: reads.append("drafts"))
    monkeypatch.setattr(timeline, "list_outbound_history", lambda *_args, **_kwargs: reads.append("history"))
    monkeypatch.setattr(timeline, "get_activity_repository", lambda: reads.append("activity"))

    with pytest.raises(HTTPException) as error:
        await CampaignTimelineService().read(
            owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="foreign",
        )

    assert error.value.status_code == 404
    assert reads == []


@pytest.mark.asyncio
async def test_projects_only_durable_and_canonical_execution_sources(monkeypatch):
    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[
            _activity("created", "campaign_created", {"campaign_id": "campaign-a", "status": "planning", "lead_count": 1}, 1, "2026-01-01T00:00:01+00:00"),
            _activity("generated", "draft_generated", {"campaign_id": "campaign-a", "draft_id": "draft-a", "batch_job_id": "job-a", "status": "pending"}, 2, "2026-01-01T00:00:02+00:00"),
            _activity("foreign", "campaign_created", {"campaign_id": "campaign-b", "status": "planning", "lead_count": 1}, 3, "2026-01-01T00:00:03+00:00"),
        ],
        drafts=[
            {"id": "draft-a", "campaign_id": "campaign-a"},
            {"id": "draft-failed", "campaign_id": "campaign-a"},
            {"id": "draft-b", "campaign_id": "campaign-b"},
        ],
        history=[
            _History("history-a", "draft-a", "sent", "2026-01-01T00:00:04+00:00"),
            _History("history-b", "draft-b", "failed", "2026-01-01T00:00:05+00:00"),
        ],
        launch_failures=[
            CampaignLaunchFailure(
                id="failure-a", campaign_launch_id="launch-a", workspace_id="workspace-a",
                campaign_id="campaign-a", draft_id="draft-failed",
                occurred_at="2026-01-01T00:00:10+00:00",
            ),
            CampaignLaunchFailure(
                id="failure-foreign", campaign_launch_id="launch-b", workspace_id="workspace-a",
                campaign_id="campaign-a", draft_id="draft-b",
                occurred_at="2026-01-01T00:00:12+00:00",
            ),
        ],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["campaign_id"] == "campaign-a"
    assert [event["type"] for event in result["events"]] == [
        "campaign_created", "draft_generated", "draft_sent", "draft_failed",
    ]
    assert result["events"][0]["data"] == {"status": "planning"}
    assert result["events"][-1]["data"] == {}
    assert all(set(event) <= {"type", "timestamp", "data"} for event in result["events"])
    assert "provider-secret" not in str(result)
    assert "session-a" not in str(result)


@pytest.mark.asyncio
async def test_only_recorded_canonical_failures_are_synthesized(monkeypatch):
    from services.outbound.outbound_models import DeliveryStatus

    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[],
        drafts=[{"id": "draft-a", "campaign_id": "campaign-a"}],
        history=[_History("failed-a", "draft-a", DeliveryStatus.FAILED, "2026-01-01T00:00:04+00:00")],
        launch_failures=[],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["events"] == [{"type": "draft_failed", "timestamp": "2026-01-01T00:00:04+00:00", "data": {}}]


@pytest.mark.asyncio
async def test_later_launch_can_show_a_separate_failure_for_the_same_draft(monkeypatch):
    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[],
        drafts=[{"id": "draft-a", "campaign_id": "campaign-a"}],
        history=[],
        launch_failures=[
            CampaignLaunchFailure(
                id="failure-1", campaign_launch_id="launch-1", workspace_id="workspace-a",
                campaign_id="campaign-a", draft_id="draft-a", occurred_at="2026-01-01T00:00:01+00:00",
            ),
            CampaignLaunchFailure(
                id="failure-2", campaign_launch_id="launch-2", workspace_id="workspace-a",
                campaign_id="campaign-a", draft_id="draft-a", occurred_at="2026-01-02T00:00:01+00:00",
            ),
        ],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["events"] == [
        {"type": "draft_failed", "timestamp": "2026-01-01T00:00:01+00:00", "data": {}},
        {"type": "draft_failed", "timestamp": "2026-01-02T00:00:01+00:00", "data": {}},
    ]


@pytest.mark.asyncio
async def test_legacy_sources_are_never_read_after_cutover(monkeypatch):
    import services.campaigns.timeline as timeline

    monkeypatch.setattr(
        timeline,
        "get_wm_store",
        lambda: (_ for _ in ()).throw(AssertionError("timeline must not read World Model")),
        raising=False,
    )
    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[
            _activity(
                "status", "campaign_status_changed",
                {"campaign_id": "campaign-a", "status": "completed", "previous_status": "planning"},
                7, "2026-01-01T00:00:07+00:00",
                source_key="campaign:campaign-a:revision:7:status_changed",
            ),
        ],
        drafts=[], history=[], launch_failures=[],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["events"] == [{
        "type": "campaign_status_changed",
        "timestamp": "2026-01-01T00:00:07+00:00",
        "data": {"status": "completed"},
    }]
