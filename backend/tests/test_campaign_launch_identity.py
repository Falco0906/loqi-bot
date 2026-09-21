"""Durable identity boundary for accepted campaign send launches."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.campaigns.service as campaign_service


def _campaign() -> dict:
    return {"id": "campaign-1", "name": "Campaign", "status": "planning"}


@pytest.mark.asyncio
async def test_launch_identity_is_created_before_dispatch_and_is_forwarded(monkeypatch):
    order: list[object] = []
    target = _campaign()
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])

    import services.workspace.state as workspace_state
    import services.workspace.timeline as timeline
    import services.outbound.service as outbound_service

    monkeypatch.setattr(
        workspace_state, "load_drafts_only",
        lambda *_args, **_kwargs: [{"campaign_id": "campaign-1", "status": "approved"}],
    )

    async def create_launch(**kwargs):
        order.append(("launch", kwargs))
        return SimpleNamespace(id="database-launch-1")

    async def dispatch(*_args, launch_id, **_kwargs):
        order.append(("dispatch", launch_id))
        return {"ok": True, "total": 1, "sent": 1, "failed": 0}

    async def persist(*_args, **_kwargs):
        campaign = SimpleNamespace(
            id="campaign-1", workspace_id="workspace-1", name="Campaign",
            objective="", status="completed", version=2, updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        return SimpleNamespace(
            revision=SimpleNamespace(campaign=campaign, was_updated=True, was_status_changed=True, previous_status="planning"),
            strategy_error=None,
        )

    monkeypatch.setattr(campaign_service, "create_campaign_launch", create_launch)
    monkeypatch.setattr(outbound_service, "dispatch_campaign_sends", dispatch)
    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(timeline, "record_campaign_launched", lambda *_args: order.append("timeline"))
    monkeypatch.setattr(campaign_service, "_feedback", lambda: SimpleNamespace(on_campaign_launched=lambda *_args: order.append("feedback")))
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: SimpleNamespace(append_campaign_status_changed=lambda **_kwargs: None))

    result = await campaign_service.update_campaign(
        "session", "actor-1", "workspace-1", "campaign-1", {"status": "completed"},
    )

    assert result["ok"] is True
    assert order[0] == ("launch", {"workspace_id": "workspace-1", "campaign_id": "campaign-1", "actor_user_id": "actor-1"})
    assert ("dispatch", "database-launch-1") in order
    assert order.index(("launch", {"workspace_id": "workspace-1", "campaign_id": "campaign-1", "actor_user_id": "actor-1"})) < order.index(("dispatch", "database-launch-1"))


@pytest.mark.asyncio
async def test_launch_creation_failure_prevents_dispatch(monkeypatch):
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [_campaign()])
    import services.workspace.state as workspace_state
    import services.outbound.service as outbound_service

    monkeypatch.setattr(
        workspace_state, "load_drafts_only",
        lambda *_args, **_kwargs: [{"campaign_id": "campaign-1", "status": "approved"}],
    )

    async def unavailable(**_kwargs):
        raise RuntimeError("persistence unavailable")

    async def dispatch(*_args, **_kwargs):
        raise AssertionError("dispatch must not start without a durable launch ID")

    monkeypatch.setattr(campaign_service, "create_campaign_launch", unavailable)
    monkeypatch.setattr(outbound_service, "dispatch_campaign_sends", dispatch)

    with pytest.raises(HTTPException) as error:
        await campaign_service.update_campaign(
            "session", "actor-1", "workspace-1", "campaign-1", {"status": "completed"},
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_distinct_accepted_launches_receive_distinct_database_ids(monkeypatch):
    ids = iter(["database-launch-1", "database-launch-2"])

    class Repository:
        async def create_for_workspace(self, **kwargs):
            assert kwargs == {"workspace_id": "workspace-1", "campaign_id": "campaign-1", "actor_user_id": "actor-1"}
            return SimpleNamespace(id=next(ids))

    import services.persistence.launch as launch_persistence
    monkeypatch.setattr(launch_persistence, "CampaignLaunchRepository", Repository)

    first = await campaign_service.create_campaign_launch(
        workspace_id="workspace-1", campaign_id="campaign-1", actor_user_id="actor-1",
    )
    second = await campaign_service.create_campaign_launch(
        workspace_id="workspace-1", campaign_id="campaign-1", actor_user_id="actor-1",
    )
    assert (first.id, second.id) == ("database-launch-1", "database-launch-2")


@pytest.mark.asyncio
async def test_repository_omits_id_so_database_allocates_it(monkeypatch):
    from services.persistence.launch import CampaignLaunchRepository

    inserted: list[dict] = []

    class _Insert:
        def select(self, _fields):
            return self

        def execute(self):
            return SimpleNamespace(data=[{
                "id": "database-launch-1", "workspace_id": "workspace-1",
                "campaign_id": "campaign-1", "actor_user_id": "actor-1",
                "started_at": "2026-09-20T00:00:00+00:00",
            }])

    class _Table:
        def insert(self, row):
            inserted.append(dict(row))
            return _Insert()

    repository = CampaignLaunchRepository()
    monkeypatch.setattr(repository, "_client", lambda: SimpleNamespace(table=lambda _name: _Table()))
    launch = await repository.create_for_workspace(
        workspace_id="workspace-1", campaign_id="campaign-1", actor_user_id="actor-1",
    )

    assert launch.id == "database-launch-1"
    assert inserted == [{
        "workspace_id": "workspace-1", "campaign_id": "campaign-1", "actor_user_id": "actor-1",
    }]


@pytest.mark.asyncio
async def test_one_launch_id_reaches_every_progress_write(monkeypatch):
    import services.outbound.service as outbound_service

    drafts = [
        {
            "id": "draft-1", "campaign_id": "campaign-1", "status": "approved",
            "lead": {"email": "", "name": "No Email"}, "subject": "", "text": "",
        },
        {
            "id": "draft-2", "campaign_id": "campaign-1", "status": "approved",
            "lead": {"email": "lead@example.test", "name": "Lead"}, "subject": "", "text": "",
        },
    ]
    progress_launch_ids: list[str] = []
    monkeypatch.setattr(outbound_service.workspace_state, "load_drafts_only", lambda *_args, **_kwargs: drafts)
    monkeypatch.setattr(outbound_service, "find_outbound_gmail_provider_id", lambda: "provider-1")
    monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outbound_service,
        "update_campaign_launch_progress",
        lambda *_args, launch_id, **_kwargs: progress_launch_ids.append(launch_id) or __import__("asyncio").sleep(0, result=True),
    )
    failure_launch_ids: list[str] = []

    async def persist_failure(*, launch_id, **_kwargs):
        failure_launch_ids.append(launch_id)

    monkeypatch.setattr(outbound_service, "persist_campaign_launch_failure", persist_failure)
    monkeypatch.setattr(
        outbound_service.outbound_executor,
        "send_hydrated_draft",
        lambda *_args, **_kwargs: {"ok": False, "error": "provider unavailable"},
    )

    result = await outbound_service.dispatch_campaign_sends(
        "session", {"id": "campaign-1"}, "actor-1",
        workspace_id="workspace-1", launch_id="database-launch-1",
    )

    assert result["failed"] == 2
    assert progress_launch_ids == ["database-launch-1", "database-launch-1"]
    assert failure_launch_ids == ["database-launch-1", "database-launch-1"]


def test_campaign_launch_migration_stores_only_safe_scope_fields():
    from pathlib import Path

    sql = Path(__file__).parents[1] / "supabase" / "migrations" / "045_campaign_launches.sql"
    text = sql.read_text()
    assert "id uuid primary key default gen_random_uuid()" in text
    assert "workspace_id uuid not null" in text
    assert "campaign_id uuid not null" in text
    assert "actor_user_id uuid" in text
    for forbidden in ("session_token", "recipient", "subject", "body", "provider", "error"):
        assert forbidden not in text
