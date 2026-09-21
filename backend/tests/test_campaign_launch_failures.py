"""Offline contracts for launch-scoped, privacy-safe campaign failures."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.persistence.launch import CampaignLaunchFailureRepository


@pytest.mark.asyncio
async def test_failure_repository_uses_only_canonical_scope_and_maps_idempotent_result(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class _RPC:
        def execute(self):
            return SimpleNamespace(data=[{
                "failure_id": "failure-1",
                "occurred_at": "2026-09-21T12:00:00+00:00",
                "was_created": False,
            }])

    class _Client:
        def rpc(self, name, arguments):
            calls.append((name, dict(arguments)))
            return _RPC()

    repository = CampaignLaunchFailureRepository()
    monkeypatch.setattr(repository, "_client", lambda: _Client())

    failure, was_created = await repository.record_for_launch(
        campaign_launch_id="launch-1",
        workspace_id="workspace-1",
        campaign_id="campaign-1",
        draft_id="draft-1",
    )

    assert was_created is False
    assert failure.id == "failure-1"
    assert failure.campaign_launch_id == "launch-1"
    assert calls == [("record_campaign_launch_failure", {
        "p_campaign_launch_id": "launch-1",
        "p_workspace_id": "workspace-1",
        "p_campaign_id": "campaign-1",
        "p_draft_id": "draft-1",
        "p_occurred_at": None,
    })]
    assert "session" not in str(calls).lower()
    assert "email" not in str(calls).lower()


@pytest.mark.asyncio
async def test_failure_repository_rejects_missing_canonical_scope_without_rpc(monkeypatch):
    repository = CampaignLaunchFailureRepository()
    monkeypatch.setattr(repository, "_client", lambda: (_ for _ in ()).throw(AssertionError("RPC must not run")))

    with pytest.raises(ValueError):
        await repository.record_for_launch(
            campaign_launch_id="launch-1",
            workspace_id="",
            campaign_id="campaign-1",
            draft_id="draft-1",
        )


def test_launch_failure_migration_enforces_launch_scoped_idempotency_and_safe_columns():
    sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "046_campaign_launch_failures.sql").read_text()

    assert "unique (campaign_launch_id, draft_id)" in sql
    assert "references campaign_launches(id)" in sql
    assert "join drafts as d" in sql
    assert "d.workspace_id = cl.workspace_id" in sql
    assert "d.campaign_id = cl.campaign_id" in sql
    assert sql.index("perform 1") < sql.index("select clf.* into v_existing")
    assert "on conflict (campaign_launch_id, draft_id) do nothing" in sql
    for forbidden in (
        "recipient_email", "provider_id", "subject", "body", "session_token",
        "error_text", "raw_error", "lead_id", "metadata",
    ):
        assert forbidden not in sql
