"""Unified Discovery uses saved lead references through the existing campaign API."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from services.campaigns import api, service
from services.workspace import state

LEAD = "00000000-0000-4000-8000-000000000041"
OTHER = "00000000-0000-4000-8000-000000000042"


@pytest.fixture
def selected_campaign(monkeypatch):
    calls = []
    campaign = {"id": "campaign", "name": "Selected prospects", "leads": [], "lead_count": 0}

    class Leads:
        async def get_for_workspace(self, lead_id, workspace_id):
            calls.append((lead_id, workspace_id))
            return SimpleNamespace(id=LEAD) if (lead_id, workspace_id) == (LEAD, "selected") else None

    async def authorize(_request, **_kwargs): return "owner", "token", "selected"
    async def persist_campaign(_owner, value, workspace_id=""):
        assert workspace_id == "selected"
        campaign.update(value)
        campaign["leads"] = []
        return True
    async def persist_lead(_owner, campaign_id, lead, workspace_id=""):
        assert workspace_id == "selected"
        assert lead == {"id": LEAD, "workspace_lead_id": LEAD}
        if not any(row["id"] == LEAD for row in campaign["leads"]):
            campaign["leads"].append({"id": LEAD})
        campaign["lead_count"] = len(campaign["leads"])
        return True
    def load(_owner, campaign_id, workspace_id="", *, strict=False):
        assert workspace_id == "selected"
        return {**campaign, "leads": list(campaign["leads"])} if campaign_id == campaign["id"] else None

    monkeypatch.setattr("services.persistence.launch.repositories.WorkspaceLeadRepository", Leads)
    monkeypatch.setattr(api, "_authorized_workspace", authorize)
    monkeypatch.setattr(state, "persist_campaign_row", AsyncMock(side_effect=persist_campaign))
    monkeypatch.setattr(state, "persist_campaign_lead_awaited", AsyncMock(side_effect=persist_lead))
    async def persist_creation(workspace, actor, identity, _hash, value):
        assert workspace == "selected"
        await persist_campaign(actor, value, workspace_id=workspace)
        for lead in value["leads"]:
            await persist_lead(actor, identity, lead, workspace_id=workspace)
        return True
    monkeypatch.setattr("services.campaigns.creation.recover_creation", AsyncMock(return_value=None))
    monkeypatch.setattr("services.campaigns.creation.persist_creation", AsyncMock(side_effect=persist_creation))
    monkeypatch.setattr(state, "load_campaign_state", load)
    monkeypatch.setattr(service, "load_campaign_state", load)
    monkeypatch.setattr(state, "append_event", Mock(return_value=True))
    monkeypatch.setattr(service, "publish", Mock())
    monkeypatch.setattr(service, "maybe_auto_strategy", AsyncMock())
    monkeypatch.setattr(service, "get_activity_repository", lambda: SimpleNamespace(append_campaign_created=lambda **_kwargs: None))
    monkeypatch.setattr("services.workspace.timeline.record_campaign_created", Mock())
    monkeypatch.setattr(service, "_feedback", lambda: SimpleNamespace(on_campaign_created=Mock()))
    return SimpleNamespace(calls=calls, campaign=campaign)


@pytest.mark.asyncio
async def test_attach_saved_lead_uses_existing_authorized_route(selected_campaign):
    response = await api.add_campaign_lead("_", "campaign", api.AddCampaignLeadRequest(lead={"workspace_lead_id": LEAD}), SimpleNamespace())
    assert response["ok"] and response["added"]
    assert selected_campaign.campaign["leads"] == [{"id": LEAD}]
    assert selected_campaign.calls == [(LEAD, "selected")]
    service.maybe_auto_strategy.assert_not_awaited()  # Analysis is not an attachment prerequisite.


@pytest.mark.asyncio
async def test_retry_does_not_duplicate_attachment(selected_campaign):
    payload = api.AddCampaignLeadRequest(lead={"workspace_lead_id": LEAD})
    await api.add_campaign_lead("_", "campaign", payload, SimpleNamespace())
    response = await api.add_campaign_lead("_", "campaign", payload, SimpleNamespace())
    assert response["added"] is False
    state.persist_campaign_lead_awaited.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_with_selected_leads_uses_existing_route(selected_campaign):
    result = await api.save_campaign("_", api.SaveCampaignRequest(name="Selected", idempotency_key="selected-intent", leads=[{"workspace_lead_id": LEAD}]), SimpleNamespace())
    assert result["ok"]
    assert result["campaign"]["lead_count"] == 1
    assert result["campaign"]["leads"] == [{"id": LEAD}]


@pytest.mark.asyncio
@pytest.mark.parametrize("create", [True, False])
@pytest.mark.parametrize("lead_id,status", [(OTHER, 404), ("invalid", 422)])
async def test_foreign_missing_or_invalid_lead_is_rejected_before_mutation(selected_campaign, create, lead_id, status):
    with pytest.raises(HTTPException) as error:
        if create:
            await api.save_campaign("_", api.SaveCampaignRequest(name="Rejected", idempotency_key="rejected-intent", leads=[{"workspace_lead_id": lead_id}]), SimpleNamespace())
        else:
            await api.add_campaign_lead("_", "campaign", api.AddCampaignLeadRequest(lead={"workspace_lead_id": lead_id}), SimpleNamespace())
    assert error.value.status_code == status
    state.persist_campaign_row.assert_not_awaited()
    state.persist_campaign_lead_awaited.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_campaign_is_rejected_before_attachment(selected_campaign):
    with pytest.raises(HTTPException) as error:
        await api.add_campaign_lead("_", "other-campaign", api.AddCampaignLeadRequest(lead={"workspace_lead_id": LEAD}), SimpleNamespace())
    assert error.value.status_code == 404
    state.persist_campaign_lead_awaited.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_duplicate_selection_rejected_before_writes(selected_campaign):
    with pytest.raises(HTTPException) as error:
        await api.save_campaign("_", api.SaveCampaignRequest(name="Duplicate", idempotency_key="duplicate-intent", leads=[{"workspace_lead_id": LEAD}] * 2), SimpleNamespace())
    assert error.value.status_code == 422
    state.persist_campaign_row.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_authorization_not_bypassed(selected_campaign, monkeypatch):
    async def forbidden(_request): raise HTTPException(403, "Workspace access denied")
    monkeypatch.setattr(api, "_authorized_workspace", forbidden)
    with pytest.raises(HTTPException) as error:
        await api.add_campaign_lead("_", "campaign", api.AddCampaignLeadRequest(lead={"workspace_lead_id": LEAD}), SimpleNamespace())
    assert error.value.status_code == 403
    assert selected_campaign.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_saved_reference_bypasses_normalization_but_rechecks_workspace(monkeypatch, allowed):
    async def workspace(*_args, **_kwargs): return "selected"
    monkeypatch.setattr(state, "_async_workspace", workspace)
    monkeypatch.setattr(state, "CampaignRepository", lambda: SimpleNamespace(get_for_workspace=AsyncMock(return_value=SimpleNamespace(id="campaign"))))
    lookup = AsyncMock(return_value=SimpleNamespace(id=LEAD) if allowed else None)
    monkeypatch.setattr(state, "WorkspaceLeadRepository", lambda: SimpleNamespace(get_for_workspace=lookup))
    normalizer = AsyncMock(side_effect=AssertionError("Saved leads must not be re-normalized"))
    monkeypatch.setattr(state, "_normalize_lead", normalizer)
    monkeypatch.setattr(state, "CampaignLeadRepository", lambda: SimpleNamespace(find_link=AsyncMock(return_value=None), save=AsyncMock(side_effect=lambda row: row)))
    result = await state._persist_campaign_lead_link_row("owner", "campaign", {"workspace_lead_id": LEAD}, workspace_id="selected")
    assert bool(result) is allowed
    if allowed: assert result.lead_id == LEAD
    lookup.assert_awaited_once_with(LEAD, "selected")
    normalizer.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_inline_contract_is_unchanged():
    inline = {"id": "provider-id", "email": "prospect@example.test"}
    assert await service._authorize_selected_lead("selected", inline) is inline
