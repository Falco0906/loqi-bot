"""Offline contracts for the live campaign update revision boundary."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import pytest
from fastapi import HTTPException

from services.campaigns import service as campaign_service
from services.persistence.launch import Campaign, CampaignRepository


class _Result:
    def __init__(self, data):
        self.data = data


class _RevisionDatabase:
    """Deterministic stand-in for the migration-041 locked RPC."""

    def __init__(self):
        self.lock = Lock()
        self.calls: list[tuple[str, dict]] = []
        timestamp = "2026-09-17T00:00:00+00:00"
        self.row = {
            "id": "campaign-1", "workspace_id": "workspace-a", "organization_id": "",
            "name": "Original", "objective": "Book demos", "status": "planning",
            "search_query": "", "discovery_id": None, "settings": {}, "created_by": "user-a",
            "updated_by": "", "metadata": {}, "version": 1, "created_at": timestamp,
            "updated_at": timestamp, "archived_at": None, "deleted_at": None,
        }

    def rpc(self, name: str, arguments: dict):
        database = self

        class _Rpc:
            def execute(self):
                assert name == "update_workspace_campaign_with_revision"
                with database.lock:
                    database.calls.append((name, dict(arguments)))
                    if arguments["p_workspace_id"] != database.row["workspace_id"]:
                        raise RuntimeError("campaign not found in workspace")
                    row = database.row
                    name_value = arguments["p_name"] if arguments["p_name_provided"] else row["name"]
                    objective_value = arguments["p_objective"] if arguments["p_objective_provided"] else row["objective"]
                    status_value = arguments["p_status"] if arguments["p_status_provided"] else row["status"]
                    # Match the existing state-layer normalization and the RPC.
                    name_value = name_value or None
                    objective_value = objective_value or None
                    changed = bool(arguments["p_touch"]) or any((
                        row["name"] != name_value,
                        row["objective"] != objective_value,
                        row["status"] != status_value,
                    ))
                    if changed:
                        row.update({
                            "name": name_value,
                            "objective": objective_value,
                            "status": status_value,
                            "version": row["version"] + 1,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })
                    return _Result([{**row, "was_updated": changed}])

        return _Rpc()


def _repository():
    database = _RevisionDatabase()
    repository = CampaignRepository()
    repository._client = lambda: database
    return repository, database


def test_campaign_revision_migration_is_workspace_scoped_and_locked():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/041_campaign_update_revision.sql").read_text()
    for fragment in (
        "create or replace function update_workspace_campaign_with_revision",
        "p_campaign_id uuid",
        "p_workspace_id uuid",
        "and c.workspace_id = p_workspace_id",
        "for update",
        "version = v_current.version + 1",
        "was_updated boolean",
        "if not v_changed then",
    ):
        assert fragment in sql


@pytest.mark.asyncio
async def test_revisioned_status_and_non_status_updates_increment_once():
    repository, database = _repository()

    status, status_changed = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"status": "running"},
    )
    renamed, rename_changed = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"name": "Renamed"},
    )

    assert status_changed is True
    assert (status.status, status.version) == ("running", 2)
    assert rename_changed is True
    assert (renamed.name, renamed.version) == ("Renamed", 3)
    assert all(call[1]["p_workspace_id"] == "workspace-a" for call in database.calls)


@pytest.mark.asyncio
async def test_true_noop_returns_canonical_row_without_allocating_revision():
    repository, _database = _repository()

    campaign, changed = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"name": "Original"},
    )

    assert changed is False
    assert campaign.version == 1
    assert campaign.name == "Original"


@pytest.mark.asyncio
async def test_revisioned_update_rejects_campaign_outside_selected_workspace():
    repository, _database = _repository()

    with pytest.raises(RuntimeError, match="not found in workspace"):
        await repository.update_for_workspace_with_revision(
            "campaign-1", "workspace-b", {"status": "running"},
        )


@pytest.mark.asyncio
async def test_concurrent_real_updates_receive_distinct_monotonic_revisions():
    repository, _database = _repository()

    first, second = await asyncio.gather(
        repository.update_for_workspace_with_revision("campaign-1", "workspace-a", {"status": "running"}),
        repository.update_for_workspace_with_revision("campaign-1", "workspace-a", {"name": "Renamed"}),
    )

    assert first[1] is True and second[1] is True
    assert sorted((first[0].version, second[0].version)) == [2, 3]


@pytest.mark.asyncio
async def test_live_service_preserves_response_envelope_and_uses_rpc_return(monkeypatch):
    target = {
        "id": "campaign-1", "name": "Original", "objective": "Book demos",
        "status": "planning", "lead_count": 0,
    }
    canonical = Campaign(
        id="campaign-1", workspace_id="workspace-a", name="Canonical name",
        objective="Book demos", status="planning", version=2,
        updated_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    calls = []

    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(campaign_service, "publish", lambda *args, **kwargs: calls.append(("publish", args, kwargs)))
    monkeypatch.setattr(campaign_service, "_feedback", lambda: object())
    import services.workspace.state as workspace_state

    async def persist(owner_id, campaign_id, updates, *, workspace_id=""):
        calls.append(("persist", owner_id, campaign_id, dict(updates), workspace_id))
        return canonical, True

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)

    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"name": "Requested"},
    )

    assert response == {
        "ok": True,
        "campaign": {
            "id": "campaign-1", "name": "Canonical name", "objective": "Book demos",
            "status": "planning", "lead_count": 0,
            "updated_at": "2026-09-17T00:00:00+00:00",
        },
    }
    assert calls[0][0] == "publish"  # Existing in-memory order is unchanged.
    assert calls[1] == ("persist", "user-a", "campaign-1", {"name": "Requested"}, "workspace-a")
    assert "version" not in response["campaign"]


@pytest.mark.asyncio
async def test_completed_path_keeps_legacy_publish_dispatch_then_persist_order(monkeypatch):
    target = {
        "id": "campaign-1", "name": "Original", "objective": "Book demos",
        "status": "planning", "lead_count": 1,
    }
    canonical = Campaign(
        id="campaign-1", workspace_id="workspace-a", name="Original",
        objective="Book demos", status="completed", version=2,
    )
    calls = []
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(campaign_service, "publish", lambda *args, **kwargs: calls.append("publish"))

    class _Feedback:
        def on_campaign_launched(self, *_args):
            calls.append("feedback")

    monkeypatch.setattr(campaign_service, "_feedback", lambda: _Feedback())
    import services.workspace.state as workspace_state
    import services.outbound.service as outbound_service
    import services.workspace.timeline as timeline

    monkeypatch.setattr(workspace_state, "load_drafts_only", lambda *_args, **_kwargs: [
        {"campaign_id": "campaign-1", "status": "approved"},
    ])
    monkeypatch.setattr(timeline, "record_campaign_launched", lambda *_args: calls.append("timeline"))

    async def dispatch(*_args, **_kwargs):
        calls.append("dispatch")
        return {"ok": True, "total": 1, "sent": 1, "failed": 0}

    async def persist(*_args, **_kwargs):
        calls.append("persist")
        return canonical, True

    monkeypatch.setattr(outbound_service, "dispatch_campaign_sends", dispatch)
    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)

    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"status": "completed"},
    )

    assert response["ok"] is True
    assert calls.index("publish") < calls.index("dispatch") < calls.index("persist")


@pytest.mark.asyncio
async def test_invalid_status_retains_http_error_mapping(monkeypatch):
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [{"id": "campaign-1"}])

    with pytest.raises(HTTPException) as error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1", {"status": "not-a-status"},
        )

    assert error.value.status_code == 400
