"""Regression test for the attach_discovery compensation bug.

Before the fix, `attach_discovery` tracked every attached lead's canonical ID
(both newly-created links AND links that already existed before the call)
in a single `attached_ids` list, and rolled back that *entire* list if any
later lead in the batch failed to attach. That meant one failed lead could
silently delete campaign-lead links that were already correctly in place
before this request ever ran.

The fix tracks newly-created links separately and only ever compensates
those.
"""
from __future__ import annotations

import pytest

import services.campaigns.service as campaign_service
import services.workspace.state as workspace_state


def _discovery_with_leads(lead_ids: list[str]) -> dict:
    return {
        "id": "discovery-1",
        "discovery_leads": [
            {"workspace_lead": {"id": lead_id, "email": f"{lead_id}@example.com"}}
            for lead_id in lead_ids
        ],
    }


@pytest.mark.asyncio
async def test_partial_attach_failure_does_not_delete_pre_existing_links(monkeypatch):
    campaign_id = "campaign-1"
    workspace_id = "workspace-1"
    owner_id = "user-1"

    # lead-a already has a link before this call starts; lead-b is new;
    # lead-c will fail to persist, forcing a rollback.
    pre_existing = {"lead-a"}
    created_during_call: list[str] = []
    removed: list[str] = []

    monkeypatch.setattr(
        campaign_service, "load_campaigns",
        lambda owner_id, workspace_id=None: [{"id": campaign_id, "discovery_id": ""}],
    )

    def fake_get_discovery(discovery_id, workspace_id):
        return _discovery_with_leads(["lead-a", "lead-b", "lead-c"])

    monkeypatch.setattr(
        "services.discovery.service.get_discovery", fake_get_discovery,
    )

    async def fake_persist_with_status(owner_id, campaign_id, lead, workspace_id=""):
        lead_id = lead["id"]
        if lead_id in pre_existing:
            return lead_id, False  # already existed — must never be deleted
        if lead_id == "lead-c":
            return None  # simulate failure partway through the batch
        created_during_call.append(lead_id)
        return lead_id, True

    monkeypatch.setattr(
        workspace_state, "persist_campaign_lead_id_awaited_with_status",
        fake_persist_with_status,
    )

    async def fake_remove_links(owner_id, campaign_id, lead_ids, workspace_id=""):
        removed.extend(lead_ids)
        return True

    monkeypatch.setattr(
        workspace_state, "remove_campaign_lead_links_awaited", fake_remove_links,
    )

    with pytest.raises(Exception) as exc_info:
        await campaign_service.attach_discovery(
            "session-token", owner_id, workspace_id, campaign_id, "discovery-1",
        )
    assert "rolled back" in str(getattr(exc_info.value, "detail", exc_info.value))

    # The pre-existing link for lead-a must never be passed to the delete call.
    assert "lead-a" not in removed
    # Only the link newly created during this call (lead-b) should be removed.
    assert removed == ["lead-b"]
    assert created_during_call == ["lead-b"]
