"""Regression: strategy job reuse must be scoped to the requesting owner.

Before the fix, enqueue_strategy_job() reused any active job matching
campaign_id + workspace_id, regardless of who created it. strategy_job_status()
separately rejects a job whose user_id doesn't match the polling caller. So a
second owner (or a stale job row) could be handed a job_id they could never
successfully poll — surfacing as a generic "Strategy generation failed" even
though a job was legitimately running under a different owner.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.campaigns.service as campaign_service


def _active_job(job_id: str, owner_id: str, campaign_id: str, workspace_id: str):
    return SimpleNamespace(
        id=job_id, user_id=owner_id, campaign_id=campaign_id,
        workspace_id=workspace_id, status=SimpleNamespace(value="running"),
    )


@pytest.mark.asyncio
async def test_active_job_from_a_different_owner_is_not_reused(monkeypatch):
    existing = _active_job("job-owner-a", "owner-a", "campaign-1", "workspace-1")

    # enqueue_strategy_job does `from services.job_engine import Job, job_manager`
    # as a local import, so patch the module it actually imports from.
    import services.job_engine as job_engine_module
    monkeypatch.setattr(
        job_engine_module, "job_manager",
        SimpleNamespace(
            _storage=SimpleNamespace(list_active_jobs_by_type=lambda _type: [existing]),
            create_job=AsyncMockCompat(True),
        ),
    )
    monkeypatch.setattr(campaign_service, "persist_strategy_job_meta", AsyncMockCompat(True))
    monkeypatch.setattr(campaign_service, "register_strategy_workflow", lambda: None)

    job_id, status = await campaign_service.enqueue_strategy_job(
        "session", "owner-b", "campaign-1", "objective", {}, workspace_id="workspace-1",
    )

    # Must NOT get back owner-a's job — that would be unpollable for owner-b.
    assert job_id != "job-owner-a"
    assert status == "queued"


@pytest.mark.asyncio
async def test_active_job_from_the_same_owner_is_still_reused(monkeypatch):
    existing = _active_job("job-owner-a", "owner-a", "campaign-1", "workspace-1")

    import services.job_engine as job_engine_module
    monkeypatch.setattr(
        job_engine_module, "job_manager",
        SimpleNamespace(
            _storage=SimpleNamespace(list_active_jobs_by_type=lambda _type: [existing]),
            create_job=AsyncMockCompat(True),
        ),
    )
    monkeypatch.setattr(campaign_service, "persist_strategy_job_meta", AsyncMockCompat(True))
    monkeypatch.setattr(campaign_service, "register_strategy_workflow", lambda: None)

    job_id, status = await campaign_service.enqueue_strategy_job(
        "session", "owner-a", "campaign-1", "objective", {}, workspace_id="workspace-1",
    )

    assert job_id == "job-owner-a"
    assert status == "running"


class AsyncMockCompat:
    """Minimal awaitable-callable stand-in (avoids importing unittest.mock here)."""
    def __init__(self, return_value):
        self._return_value = return_value

    def __call__(self, *_args, **_kwargs):
        async def _inner():
            return self._return_value
        return _inner()
