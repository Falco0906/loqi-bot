"""Offline contracts for the safe hybrid campaign timeline projection."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from services.campaigns.timeline import CampaignTimelineService
from services.world_model.activity_repository import WorkspaceActivityEvent
from services.world_model.events import EventType, WorkspaceEvent


@dataclass
class _History:
    id: str
    draft_id: str
    status: str
    sent_at: str
    recipient_email: str = "secret@example.test"
    error: str = "raw provider failure"
    provider_id: str = "provider-secret"


class _Store:
    def __init__(self, events: list[WorkspaceEvent]):
        self.events = events

    def get_events(self, _session_token: str, *, after_sequence: int, limit: int):
        return [event for event in self.events if event.sequence > after_sequence][:limit]


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


def _configure_sources(monkeypatch, *, campaigns, activities, drafts, history, legacy):
    import services.campaigns.timeline as timeline

    class _ActivityRepository:
        def read_events_after(self, workspace_id, after_sequence):
            assert workspace_id == "workspace-a"
            assert after_sequence == 0
            return activities

    monkeypatch.setattr(timeline, "load_campaigns", lambda owner_id, *, workspace_id: campaigns)
    monkeypatch.setattr(timeline, "load_drafts_only", lambda owner_id, *, workspace_id: drafts)
    monkeypatch.setattr(timeline, "list_outbound_history", lambda workspace_id, _provider, _limit: history)
    monkeypatch.setattr(timeline, "get_activity_repository", lambda: _ActivityRepository())
    monkeypatch.setattr(timeline, "get_wm_store", lambda: _Store(legacy))


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
async def test_projects_durable_and_canonical_sources_with_redacted_legacy_fallback(monkeypatch):
    legacy = [
        WorkspaceEvent(
            id="legacy-sent", type=EventType.DRAFT_SENT, session_id="session-a", sequence=9,
            timestamp="2026-01-01T00:00:09+00:00",
            data={"campaign_id": "campaign-a", "draft_id": "draft-a", "recipient_email": "leak@example.test"},
        ),
        WorkspaceEvent(
            id="legacy-failure", type=EventType.DRAFT_FAILED, session_id="session-a", sequence=10,
            timestamp="2026-01-01T00:00:10+00:00",
            data={"campaign_id": "campaign-a", "draft_id": "draft-unrecorded", "error": "unsafe failure"},
        ),
        WorkspaceEvent(
            id="legacy-update", type=EventType.DRAFT_UPDATED, session_id="session-a", sequence=11,
            timestamp="2026-01-01T00:00:11+00:00",
            data={"campaign_id": "campaign-a", "draft_id": "draft-a", "subject": "secret", "status": "pending"},
        ),
        WorkspaceEvent(
            id="legacy-foreign", type=EventType.DRAFT_SENT, session_id="session-a", sequence=12,
            timestamp="2026-01-01T00:00:12+00:00",
            data={"campaign_id": "campaign-b", "draft_id": "draft-b", "recipient_email": "foreign@example.test"},
        ),
    ]
    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[
            _activity("created", "campaign_created", {"campaign_id": "campaign-a", "status": "planning", "lead_count": 1}, 1, "2026-01-01T00:00:01+00:00"),
            _activity("generated", "draft_generated", {"campaign_id": "campaign-a", "draft_id": "draft-a", "batch_job_id": "job-a", "status": "pending"}, 2, "2026-01-01T00:00:02+00:00"),
            _activity("foreign", "campaign_created", {"campaign_id": "campaign-b", "status": "planning", "lead_count": 1}, 3, "2026-01-01T00:00:03+00:00"),
        ],
        drafts=[{"id": "draft-a", "campaign_id": "campaign-a"}, {"id": "draft-b", "campaign_id": "campaign-b"}],
        history=[
            _History("history-a", "draft-a", "sent", "2026-01-01T00:00:04+00:00"),
            _History("history-b", "draft-b", "failed", "2026-01-01T00:00:05+00:00"),
        ],
        legacy=legacy,
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["campaign_id"] == "campaign-a"
    assert [event["type"] for event in result["events"]] == [
        "campaign_created", "draft_generated", "draft_sent", "draft_failed", "draft_updated",
    ]
    assert result["events"][0]["data"] == {"status": "planning"}
    assert result["events"][-1]["data"] == {"status": "pending"}
    assert all(set(event) <= {"type", "timestamp", "data"} for event in result["events"])
    assert "leak@example.test" not in str(result)
    assert "unsafe failure" not in str(result)
    assert "secret" not in str(result)
    assert "provider-secret" not in str(result)
    assert "session-a" not in str(result)


@pytest.mark.asyncio
async def test_only_recorded_canonical_failures_are_synthesized(monkeypatch):
    _configure_sources(
        monkeypatch,
        campaigns=[{"id": "campaign-a"}],
        activities=[],
        drafts=[{"id": "draft-a", "campaign_id": "campaign-a"}],
        history=[_History("failed-a", "draft-a", "failed", "2026-01-01T00:00:04+00:00")],
        legacy=[],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["events"] == [{"type": "draft_failed", "timestamp": "2026-01-01T00:00:04+00:00", "data": {}}]


@pytest.mark.asyncio
async def test_legacy_status_event_is_not_duplicated_when_its_durable_revision_exists(monkeypatch):
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
        drafts=[], history=[],
        legacy=[
            WorkspaceEvent(
                type=EventType.CAMPAIGN_STATUS_CHANGED, session_id="session-a", sequence=10,
                timestamp="2026-01-01T00:00:08+00:00",
                data={"campaign_id": "campaign-a", "status": "completed", "revision": 7},
            ),
        ],
    )

    result = await CampaignTimelineService().read(
        owner_id="user-a", workspace_id="workspace-a", session_token="session-a", campaign_id="campaign-a",
    )

    assert result["events"] == [{
        "type": "campaign_status_changed",
        "timestamp": "2026-01-01T00:00:07+00:00",
        "data": {"status": "completed"},
    }]
