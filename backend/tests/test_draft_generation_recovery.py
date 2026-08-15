"""Tests for production-stability fixes in the campaign draft pipeline.

Covers batch task retention, durable generation progress, and recovery of
interrupted draft batches after a restart. Persistence is faked at the
workspace_state boundary so no Supabase or authentication code runs.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import services.workspace_state as workspace_state
import main as main_module
from main import (
    _create_batch_job,
    _draft_batch_tasks,
    _launch_batch_task,
    _reconcile_campaign_generation,
    _reconcile_stale_generating_campaigns,
    batch_jobs,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _campaign(**overrides) -> dict:
    campaign = {
        "id": str(uuid.uuid4()),
        "name": "Test Campaign",
        "status": "generating",
        "lead_count": 1,
        "leads": [{"id": "lead-1", "company": "Acme"}],
        "generation": {
            "batch_id": "batch-1",
            "total": 1,
            "completed": 0,
            "status": "processing",
            "started_at": _now(),
        },
    }
    campaign.update(overrides)
    return campaign


def _draft(campaign_id: str, batch_id: str | None = None, **overrides) -> dict:
    draft = {
        "id": str(uuid.uuid4()),
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "lead": {"id": "lead-1", "company": "Acme"},
        "subject": "Subject",
        "text": "Body",
        "status": "pending",
        "created_at": _now(),
    }
    draft.update(overrides)
    return draft


@pytest.fixture(autouse=True)
def _clean_stores():
    batch_jobs.clear()
    _draft_batch_tasks.clear()
    yield
    batch_jobs.clear()
    _draft_batch_tasks.clear()


@pytest.fixture
def fake_persist(monkeypatch):
    """Persist campaign updates in-memory; assertable from the test."""
    updates: list[tuple[str, str, dict]] = []

    def fake(user_id: str, campaign_id: str, payload: dict) -> bool:
        updates.append((user_id, campaign_id, payload))
        return True

    async def fake_awaited(user_id: str, campaign_id: str, payload: dict) -> bool:
        updates.append((user_id, campaign_id, payload))
        return True

    monkeypatch.setattr(workspace_state, "persist_campaign_update", fake)
    monkeypatch.setattr(
        workspace_state, "persist_campaign_update_awaited", fake_awaited)
    return updates


# ─────────────────────────────────────────────────────────────────────────
# Batch task retention
# ─────────────────────────────────────────────────────────────────────────


class TestBatchTaskRetention:
    async def test_task_is_retained_until_done(self, monkeypatch):
        started = asyncio.Event()

        async def stub_process(session_token, batch_id, leads, owner_id):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(main_module, "_process_batch_drafts", stub_process)
        _launch_batch_task("token", "batch-x", [], "owner-1")

        assert "batch-x" in _draft_batch_tasks
        assert not _draft_batch_tasks["batch-x"].done()
        await started.wait()
        assert not _draft_batch_tasks["batch-x"].done()

        _draft_batch_tasks["batch-x"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await _draft_batch_tasks["batch-x"]
        assert "batch-x" not in _draft_batch_tasks

    async def test_completed_task_removes_itself(self, monkeypatch):
        async def stub_process(session_token, batch_id, leads, owner_id):
            return None

        monkeypatch.setattr(main_module, "_process_batch_drafts", stub_process)
        _launch_batch_task("token", "batch-y", [], "owner-1")
        task = _draft_batch_tasks["batch-y"]
        await asyncio.wait_for(task, timeout=5)
        assert "batch-y" not in _draft_batch_tasks

    def test_create_batch_job_sets_durable_fields(self):
        job = _create_batch_job("b1", "c1", 3)
        assert job["status"] == "processing"
        assert job["campaign_id"] == "c1"
        assert job["batch_id"] == "b1"
        assert job["started_at"]
        assert batch_jobs["b1"] is job


# ─────────────────────────────────────────────────────────────────────────
# Reconciliation of interrupted batches
# ─────────────────────────────────────────────────────────────────────────


class TestReconcileCampaignGeneration:
    def test_no_drafts_marks_generation_failed(self, monkeypatch, fake_persist):
        campaign = _campaign()
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])

        result = _reconcile_campaign_generation("owner-1", campaign)

        assert result["generation"]["status"] == "failed"
        assert fake_persist[0][1] == campaign["id"]
        updates = fake_persist[0][2]
        assert updates["generation"]["status"] == "failed"
        assert updates["generation"]["batch_id"] == "batch-1"

    def test_with_drafts_marks_generation_completed(self, monkeypatch, fake_persist):
        campaign = _campaign()
        drafts = [_draft(campaign["id"], batch_id="batch-1")]
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": drafts)

        result = _reconcile_campaign_generation("owner-1", campaign)

        assert result["generation"]["status"] == "completed"
        updates = fake_persist[0][2]
        assert updates["generation"]["status"] == "completed"
        assert updates["generation"]["completed"] == 1

    def test_drafts_from_other_batches_do_not_count(self, monkeypatch, fake_persist):
        campaign = _campaign()
        drafts = [_draft(campaign["id"], batch_id="other-batch")]
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": drafts)

        result = _reconcile_campaign_generation("owner-1", campaign)

        assert result["generation"]["status"] == "failed"

    def test_legacy_campaign_without_generation_metadata_is_left_alone(self, monkeypatch, fake_persist):
        campaign = _campaign(generation=None)
        drafts = [_draft(campaign["id"], batch_id=None)]
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": drafts)

        result = _reconcile_campaign_generation("owner-1", campaign)

        assert result.get("generation") is None
        assert fake_persist == []

    def test_non_generating_campaign_is_left_alone(self, fake_persist):
        campaign = _campaign(status="active", generation=None)
        result = _reconcile_campaign_generation("owner-1", campaign)
        assert result["status"] == "active"
        assert fake_persist == []


# ─────────────────────────────────────────────────────────────────────────
# generation-status endpoint behavior
# ─────────────────────────────────────────────────────────────────────────


class TestGenerationStatus:
    async def test_active_job_reports_live_progress(self):
        job = _create_batch_job("b1", "c1", 5)
        job["completed"] = 2
        job["current_index"] = 1

        result = await main_module.campaign_generation_status("token", "c1", MagicMock())

        assert result["ok"] is True
        assert result["active"] is True
        assert result["status"] == "processing"
        assert result["total"] == 5
        assert result["completed"] == 2
        assert result["batch_id"] == "b1"

    async def test_no_active_job_uses_durable_state(self, monkeypatch, fake_persist):
        campaign = _campaign()
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [campaign])
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])

        result = await main_module.campaign_generation_status("token", campaign["id"], MagicMock())

        assert result["ok"] is True
        assert result["active"] is False
        assert result["status"] == "failed"
        assert fake_persist[0][2]["generation"]["status"] == "failed"

    async def test_completed_campaign_reports_durable_counts(self, monkeypatch):
        campaign = _campaign(
            status="active",
            generation={
                "batch_id": "b1",
                "total": 3,
                "completed": 3,
                "status": "completed",
                "started_at": _now(),
            },
        )
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [campaign])
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])

        result = await main_module.campaign_generation_status("token", campaign["id"], MagicMock())

        assert result["active"] is False
        assert result["status"] == "completed"
        assert result["total"] == 3
        assert result["completed"] == 3
        assert result["batch_id"] == "b1"

    async def test_missing_campaign_returns_inactive(self, monkeypatch):
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [])

        result = await main_module.campaign_generation_status("token", "nope", MagicMock())

        assert result["ok"] is True
        assert result["active"] is False


def _fake_owner(owner_id: str):
    async def fake_owner(request, session_token: str) -> str:
        return owner_id

    return fake_owner


# ─────────────────────────────────────────────────────────────────────────
# generate-drafts endpoint guard
# ─────────────────────────────────────────────────────────────────────────


class TestGenerateDraftsGuard:
    async def test_returns_existing_batch_when_already_processing(self, monkeypatch):
        campaign = _campaign()
        _create_batch_job("b1", campaign["id"], 4)
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [campaign])
        launched: list = []
        monkeypatch.setattr(main_module, "_launch_batch_task",
                            lambda *args, **kwargs: launched.append(args))

        result = await main_module.generate_campaign_drafts(
            "token", campaign["id"], MagicMock())

        assert result["ok"] is True
        assert result["batch_id"] == "b1"
        assert launched == []

    async def test_stale_generating_campaign_is_reconciled_then_restarted(
        self, monkeypatch, fake_persist,
    ):
        campaign = _campaign()
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [campaign])
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])
        launched: list = []
        monkeypatch.setattr(main_module, "_launch_batch_task",
                            lambda *args, **kwargs: launched.append(args))

        result = await main_module.generate_campaign_drafts(
            "token", campaign["id"], MagicMock())

        assert result["ok"] is True
        assert len(launched) == 1
        assert launched[0][1] == result["batch_id"]
        assert batch_jobs[result["batch_id"]]["status"] == "processing"
        processing = [
            u for _, _, u in fake_persist
            if (u.get("generation") or {}).get("status") == "processing"
        ]
        assert processing, "expected a persisted processing generation transition"

    async def test_missing_leads_rejected(self, monkeypatch):
        campaign = _campaign(status="active", leads=[], generation=None)
        monkeypatch.setattr(
            main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_campaigns", lambda uid, tok="": [campaign])
        monkeypatch.setattr(main_module, "_launch_batch_task",
                            lambda *args, **kwargs: None)

        with pytest.raises(Exception) as exc:
            await main_module.generate_campaign_drafts(
                "token", campaign["id"], MagicMock())
        assert "No leads found" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────
# Startup recovery sweep
# ─────────────────────────────────────────────────────────────────────────


class TestStartupRecovery:
    async def test_sweep_reconciles_generating_campaigns(self, monkeypatch, fake_persist):
        campaign = _campaign()
        client = MagicMock()
        client.table("campaigns").select(
            "id, workspace_id, settings"
        ).filter(
            "settings->generation->>status", "eq", "processing"
        ).execute.return_value = MagicMock(data=[{
            "id": campaign["id"],
            "workspace_id": "ws-1",
            "settings": {"generation": {"status": "processing", "batch_id": "batch-1"}},
        }])
        client.table("campaigns").select("settings").eq(
            "id", campaign["id"]
        ).limit(1).execute.return_value = MagicMock(data=[{
            "settings": {"generation": {"status": "processing", "batch_id": "batch-1"}},
        }])
        client.table("workflow_sessions").select("id, user_id").in_(
            "id", ["ws-1"]
        ).execute.return_value = MagicMock(data=[{"id": "ws-1", "user_id": "owner-1"}])
        monkeypatch.setattr(
            "services.supabase.get_supabase_client", lambda: client)
        monkeypatch.setattr(main_module, "_workspace_drafts", lambda uid, tok="": [])

        recovered = await asyncio.to_thread(_reconcile_stale_generating_campaigns)

        assert recovered == 1
        assert fake_persist[0][2]["generation"]["status"] == "failed"

    async def test_sweep_is_noop_without_sessions(self, monkeypatch):
        client = MagicMock()
        client.table("workflow_sessions").select("user_id").eq(
            "channel", "workspace"
        ).execute.return_value = MagicMock(data=[])
        monkeypatch.setattr(
            "services.supabase.get_supabase_client", lambda: client)

        recovered = await asyncio.to_thread(_reconcile_stale_generating_campaigns)
        assert recovered == 0
