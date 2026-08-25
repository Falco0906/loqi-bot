"""Regression coverage for the campaign-delete latency path."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main as main_module
from services.persistence.launch import CampaignRepository
import services.workspace_state as workspace_state


@pytest.mark.asyncio
async def test_delete_campaign_uses_scoped_lookup_not_workspace_graph(monkeypatch):
    """Deleting one campaign must not load the full campaign/lead graph."""

    async def owner(_request, _token):
        return "owner-1"

    async def workspace(_request, _owner):
        return "workspace-1"

    async def get_for_workspace(_self, campaign_id, workspace_id):
        assert campaign_id == "campaign-1"
        assert workspace_id == "workspace-1"
        return SimpleNamespace(
            id=campaign_id,
            name="Fast delete",
            objective="Test campaign",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    async def persist(owner_id, campaign_id, updates, workspace_id=""):
        assert owner_id == "owner-1"
        assert campaign_id == "campaign-1"
        assert workspace_id == "workspace-1"
        assert updates == {"status": "deleted"}
        return True

    def unexpected_workspace_load(*_args, **_kwargs):
        raise AssertionError("delete must not load the complete workspace graph")

    monkeypatch.setattr(main_module, "_workspace_owner", owner)
    monkeypatch.setattr(main_module, "_resolved_workspace_id_or_default", workspace)
    monkeypatch.setattr(main_module, "_workspace_campaigns", unexpected_workspace_load)
    monkeypatch.setattr(CampaignRepository, "get_for_workspace", get_for_workspace)
    monkeypatch.setattr(workspace_state, "persist_campaign_update_awaited", persist)
    monkeypatch.setattr(main_module, "publish", lambda *_args, **_kwargs: None)

    request = MagicMock(headers={"authorization": "Bearer test-session"})
    result = await main_module.delete_campaign("_", "campaign-1", request)

    assert result["ok"] is True
    assert result["campaign"]["id"] == "campaign-1"
    assert result["campaign"]["status"] == "deleted"

