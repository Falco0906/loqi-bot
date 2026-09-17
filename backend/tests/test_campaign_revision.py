"""Offline contracts for the live campaign update revision boundary."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.campaigns import service as campaign_service
from services.persistence.launch import Campaign, CampaignRepository, CampaignRevisionResult


class _Result:
    def __init__(self, data):
        self.data = data


class _RevisionDatabase:
    """Deterministic stand-in for the migration-042 locked RPC."""

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
                assert name == "update_workspace_campaign_with_revision_v2"
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
                    status_changed = row["status"] != status_value
                    previous_status = row["status"]
                    if changed:
                        row.update({
                            "name": name_value,
                            "objective": objective_value,
                            "status": status_value,
                            "version": row["version"] + 1,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })
                    return _Result([{
                        **row,
                        "was_updated": changed,
                        "was_status_changed": status_changed,
                        "previous_status": previous_status,
                    }])

        return _Rpc()


def _repository():
    database = _RevisionDatabase()
    repository = CampaignRepository()
    repository._client = lambda: database
    return repository, database


def _persistence_result(
    campaign: Campaign,
    *,
    was_updated: bool = True,
    was_status_changed: bool = False,
    previous_status: str = "planning",
    strategy_error: Exception | None = None,
):
    return SimpleNamespace(
        revision=SimpleNamespace(
            campaign=campaign,
            was_updated=was_updated,
            was_status_changed=was_status_changed,
            previous_status=previous_status,
        ),
        strategy_error=strategy_error,
    )


def test_campaign_revision_migration_is_workspace_scoped_and_locked():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/042_campaign_status_revision.sql").read_text()
    for fragment in (
        "create or replace function update_workspace_campaign_with_revision_v2",
        "p_campaign_id uuid",
        "p_workspace_id uuid",
        "and c.workspace_id = p_workspace_id",
        "for update",
        "version = v_current.version + 1",
        "was_updated boolean",
        "was_status_changed boolean",
        "previous_status text",
        "if not v_changed then",
    ):
        assert fragment in sql


@pytest.mark.asyncio
async def test_revisioned_status_and_non_status_updates_increment_once():
    repository, database = _repository()

    status = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"status": "active"},
    )
    renamed = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"name": "Renamed"},
    )

    assert status.was_updated is True
    assert (status.campaign.status, status.campaign.version, status.previous_status) == ("active", 2, "planning")
    assert status.was_status_changed is True
    assert renamed.was_updated is True
    assert (renamed.campaign.name, renamed.campaign.version) == ("Renamed", 3)
    assert renamed.was_status_changed is False
    assert all(call[1]["p_workspace_id"] == "workspace-a" for call in database.calls)


@pytest.mark.asyncio
async def test_true_noop_returns_canonical_row_without_allocating_revision():
    repository, _database = _repository()

    result = await repository.update_for_workspace_with_revision(
        "campaign-1", "workspace-a", {"name": "Original"},
    )

    assert result.was_updated is False
    assert result.was_status_changed is False
    assert result.campaign.version == 1
    assert result.campaign.name == "Original"


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
        repository.update_for_workspace_with_revision("campaign-1", "workspace-a", {"status": "active"}),
        repository.update_for_workspace_with_revision("campaign-1", "workspace-a", {"name": "Renamed"}),
    )

    assert first.was_updated is True and second.was_updated is True
    assert sorted((first.campaign.version, second.campaign.version)) == [2, 3]


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
        return _persistence_result(canonical)

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
async def test_status_activity_is_appended_after_canonical_persistence_with_locked_facts(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    canonical = Campaign(
        id="campaign-1", workspace_id="workspace-a", name="Original",
        objective="Book demos", status="active", version=4,
        updated_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    order = []
    legacy_payloads = []
    activity_calls = []
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(
        campaign_service,
        "publish",
        lambda _session, _event, payload, **_kwargs: (order.append("legacy_publish"), legacy_payloads.append(payload)),
    )
    import services.workspace.state as workspace_state

    async def persist(*_args, **_kwargs):
        order.append("canonical_persist")
        return _persistence_result(canonical, was_status_changed=True, previous_status="draft")

    class _ActivityRepository:
        def append_campaign_status_changed(self, **kwargs):
            order.append("durable_activity")
            activity_calls.append(kwargs)

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())

    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"status": "active"},
    )

    assert response["ok"] is True
    assert order == ["canonical_persist", "legacy_publish", "durable_activity"]
    assert legacy_payloads == [{
        "campaign_id": "campaign-1", "status": "active", "previous_status": "draft", "revision": 4,
    }]
    assert activity_calls == [{
        "workspace_id": "workspace-a", "actor_user_id": "user-a",
        "source_key": "campaign:campaign-1:revision:4:status_changed",
        "payload": {"campaign_id": "campaign-1", "status": "active", "previous_status": "draft"},
        "occurred_at": "2026-09-17T00:00:00+00:00",
    }]


@pytest.mark.asyncio
async def test_non_status_or_noop_revision_results_never_append_status_activity(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    canonical = Campaign(id="campaign-1", workspace_id="workspace-a", name="Requested", objective="Book demos")
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: None)
    import services.workspace.state as workspace_state

    async def persist(*_args, **_kwargs):
        return _persistence_result(canonical)

    class _ActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            raise AssertionError("name-only update must not append status activity")

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())
    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"name": "Requested"},
    )
    assert response["ok"] is True


@pytest.mark.asyncio
async def test_completed_validation_failure_never_appends_durable_status_activity(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    published = []
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: published.append("legacy_publish"))
    import services.workspace.state as workspace_state

    monkeypatch.setattr(workspace_state, "load_drafts_only", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        workspace_state,
        "persist_campaign_update_with_revision_awaited",
        lambda *_args, **_kwargs: pytest.fail("failed launch must not persist status"),
    )

    class _ActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            raise AssertionError("failed launch must not append durable activity")

    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())
    with pytest.raises(HTTPException) as error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1", {"status": "completed"},
        )

    assert error.value.status_code == 400
    assert published == []


@pytest.mark.asyncio
async def test_dispatch_or_canonical_failure_emits_no_status_projection(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [dict(target)])
    projections = []
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: projections.append("legacy"))
    import services.workspace.state as workspace_state
    import services.outbound.service as outbound_service

    monkeypatch.setattr(workspace_state, "load_drafts_only", lambda *_args, **_kwargs: [
        {"campaign_id": "campaign-1", "status": "approved"},
    ])

    async def failed_dispatch(*_args, **_kwargs):
        return {"ok": False, "error": "provider unavailable"}

    monkeypatch.setattr(outbound_service, "dispatch_campaign_sends", failed_dispatch)
    with pytest.raises(HTTPException) as dispatch_error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1", {"status": "completed"},
        )
    assert dispatch_error.value.status_code == 400
    assert projections == []

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", lambda *_args, **_kwargs: _async_none())
    with pytest.raises(HTTPException) as persistence_error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1", {"status": "active"},
        )
    assert persistence_error.value.status_code == 503
    assert projections == []


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_status_noop_emits_no_legacy_or_durable_projection(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    canonical = Campaign(id="campaign-1", workspace_id="workspace-a", status="planning", version=1)
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    calls = []
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: calls.append("legacy"))
    import services.workspace.state as workspace_state

    async def persist(*_args, **_kwargs):
        return _persistence_result(canonical, was_updated=False, was_status_changed=False)

    class _ActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            calls.append("durable")

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())
    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"status": "planning"},
    )
    assert response["ok"] is True
    assert calls == []


@pytest.mark.asyncio
async def test_activity_append_failure_does_not_fail_canonical_status_update(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    canonical = Campaign(id="campaign-1", workspace_id="workspace-a", status="active", version=2)
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: None)
    import services.workspace.state as workspace_state

    async def persist(*_args, **_kwargs):
        return _persistence_result(canonical, was_status_changed=True)

    class _FailingActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            raise RuntimeError("unavailable")

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _FailingActivityRepository())
    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"status": "active"},
    )
    assert response["ok"] is True


@pytest.mark.asyncio
async def test_combined_status_strategy_failure_keeps_committed_status_projections(monkeypatch):
    target = {"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}
    canonical = Campaign(id="campaign-1", workspace_id="workspace-a", status="active", version=2)
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [target])
    calls = []
    monkeypatch.setattr(campaign_service, "publish", lambda *_args, **_kwargs: calls.append("legacy"))
    import services.workspace.state as workspace_state

    async def persist(*_args, **_kwargs):
        calls.append("persist")
        return _persistence_result(
            canonical, was_status_changed=True,
            strategy_error=RuntimeError("strategy unavailable"),
        )

    class _ActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            calls.append("durable")

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())
    with pytest.raises(HTTPException) as error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1",
            {"status": "active", "strategy": {"objective": "new"}},
        )
    assert error.value.status_code == 503
    assert calls == ["persist", "legacy", "durable"]


@pytest.mark.asyncio
async def test_state_handoff_preserves_committed_revision_when_strategy_write_fails(monkeypatch):
    import services.workspace.state as workspace_state

    canonical = Campaign(id="campaign-1", workspace_id="workspace-a", status="active", version=2)
    revision = CampaignRevisionResult(
        campaign=canonical, was_updated=True, was_status_changed=True, previous_status="planning",
    )
    calls = []

    async def resolve_workspace(*_args, **_kwargs):
        return "workspace-a"

    async def update_revision(*_args, **_kwargs):
        calls.append("campaign_rpc")
        return revision

    async def fail_strategy(*_args, **_kwargs):
        calls.append("strategy")
        raise RuntimeError("strategy unavailable")

    monkeypatch.setattr(workspace_state, "_async_workspace", resolve_workspace)
    monkeypatch.setattr(CampaignRepository, "update_for_workspace_with_revision", update_revision)
    monkeypatch.setattr(workspace_state, "_write_strategy", fail_strategy)
    monkeypatch.setattr(workspace_state, "append_event", lambda *_args, **_kwargs: pytest.fail("strategy failure keeps existing event behavior"))

    result = await workspace_state.persist_campaign_update_with_revision_awaited(
        "user-a", "campaign-1", {"status": "active", "strategy": {"objective": "new"}},
        workspace_id="workspace-a",
    )

    assert result is not None
    assert result.revision is revision
    assert isinstance(result.strategy_error, RuntimeError)
    assert calls == ["campaign_rpc", "strategy"]


@pytest.mark.asyncio
async def test_concurrent_status_projections_follow_committed_revision_order(monkeypatch):
    revisions = 1
    legacy_revisions = []
    durable_revisions = []

    def campaigns(*_args, **_kwargs):
        return [{"id": "campaign-1", "name": "Original", "objective": "Book demos", "status": "planning"}]

    monkeypatch.setattr(campaign_service, "load_campaigns", campaigns)
    monkeypatch.setattr(
        campaign_service,
        "publish",
        lambda _session, _event, payload, **_kwargs: legacy_revisions.append(payload["revision"]),
    )
    import services.workspace.state as workspace_state

    async def persist(*_args, **kwargs):
        nonlocal revisions
        revisions += 1
        status = kwargs.get("updates", {}).get("status")
        # The helper passes updates positionally; preserve the test's explicit
        # sequence under the production scoped projection gate.
        if not status:
            status = _args[2]["status"]
        campaign = Campaign(
            id="campaign-1", workspace_id="workspace-a", status=status,
            version=revisions,
        )
        return _persistence_result(campaign, was_status_changed=True, previous_status="planning")

    class _ActivityRepository:
        def append_campaign_status_changed(self, *, source_key, **_kwargs):
            durable_revisions.append(int(source_key.split(":")[3]))

    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)
    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())

    first, second = await asyncio.gather(
        campaign_service.update_campaign("session-a", "user-a", "workspace-a", "campaign-1", {"status": "active"}),
        campaign_service.update_campaign("session-b", "user-a", "workspace-a", "campaign-1", {"status": "paused"}),
    )
    assert first["ok"] is True and second["ok"] is True
    assert legacy_revisions == [2, 3]
    assert durable_revisions == [2, 3]
    assert campaign_service._status_projection_locks == {}


@pytest.mark.asyncio
async def test_completed_path_publishes_only_after_dispatch_and_canonical_persistence(monkeypatch):
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
        return _persistence_result(canonical, was_status_changed=True)

    monkeypatch.setattr(outbound_service, "dispatch_campaign_sends", dispatch)
    monkeypatch.setattr(workspace_state, "persist_campaign_update_with_revision_awaited", persist)

    class _ActivityRepository:
        def append_campaign_status_changed(self, **_kwargs):
            calls.append("durable_activity")

    monkeypatch.setattr(campaign_service, "get_activity_repository", lambda: _ActivityRepository())

    response = await campaign_service.update_campaign(
        "session-a", "user-a", "workspace-a", "campaign-1", {"status": "completed"},
    )

    assert response["ok"] is True
    assert calls.index("dispatch") < calls.index("persist") < calls.index("publish") < calls.index("durable_activity")


@pytest.mark.asyncio
async def test_invalid_status_retains_http_error_mapping(monkeypatch):
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [{"id": "campaign-1"}])

    with pytest.raises(HTTPException) as error:
        await campaign_service.update_campaign(
            "session-a", "user-a", "workspace-a", "campaign-1", {"status": "not-a-status"},
        )

    assert error.value.status_code == 400
