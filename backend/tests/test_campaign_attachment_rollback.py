"""Offline ownership/compensation regressions for Discovery attachment."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

import services.campaigns.service as campaigns
import services.discovery.service as discovery
import services.workspace.state as state
from services.persistence.launch import CampaignLead


@pytest.fixture
def attachment(monkeypatch):
    env = SimpleNamespace(links={}, lead_ids=[], deleted=[], save_error=None, race=False, own_retry=False)
    campaign = {"id": "campaign-1", "workspace_id": "workspace-1", "discovery_id": "discovery-1"}

    class CampaignRepo:
        async def get_for_workspace(self, campaign_id, workspace_id):
            return campaign if (campaign_id, workspace_id) == ("campaign-1", "workspace-1") else None

    class Query:
        def __init__(self): self.filters = {}; self.deleting = False
        def delete(self): self.deleting = True; return self
        def select(self, *_args): return self
        def eq(self, key, value): self.filters[key] = {value}; return self
        def in_(self, key, values): self.filters[key] = set(values); return self
        def execute(self):
            rows = [link for link in env.links.values()
                    if all(getattr(link, key) in values for key, values in self.filters.items())]
            if self.deleting:
                for link in rows:
                    env.deleted.append(link.id)
                    del env.links[link.id]
            return SimpleNamespace(data=[{"id": link.id} for link in rows])

    class LinkRepo:
        def _client(self): return SimpleNamespace(table=lambda _name: Query())
        async def find_link(self, campaign_id, lead_id):
            return next((link for link in env.links.values()
                         if (link.campaign_id, link.lead_id) == (campaign_id, lead_id)), None)
        async def save(self, link):
            if env.race:
                env.race = False
                persisted_id = link.id if env.own_retry else "competing-link"
                env.links[persisted_id] = CampaignLead(id=persisted_id, campaign_id=link.campaign_id, lead_id=link.lead_id)
                raise APIError({"code": "23505", "message": "unique constraint", "details": None, "hint": None})
            if env.save_error:
                raise env.save_error
            env.links[link.id] = link
            return link

    async def workspace(_owner, workspace_id=""): return workspace_id
    async def normalize(_workspace, lead):
        if lead["id"] == "invalid": return None
        if lead["id"] == "error": raise RuntimeError("local attachment failure")
        return lead["id"]

    monkeypatch.setattr(state, "_async_workspace", workspace)
    monkeypatch.setattr(state, "_normalize_lead", normalize)
    monkeypatch.setattr(state, "CampaignRepository", CampaignRepo)
    monkeypatch.setattr(state, "CampaignLeadRepository", LinkRepo)
    monkeypatch.setattr(state, "append_event", lambda *_args: True)
    monkeypatch.setattr(campaigns, "load_campaigns", lambda *_args, **_kwargs: [dict(campaign)])
    monkeypatch.setattr(state, "load_campaign_state", lambda *_args, **_kwargs: dict(campaign))
    monkeypatch.setattr(discovery, "get_discovery", lambda *_args: {
        "discovery_leads": [{"workspace_lead": {"id": value}} for value in env.lead_ids],
    })
    monkeypatch.setattr(campaigns, "maybe_auto_strategy", AsyncMock())
    monkeypatch.setattr(campaigns, "publish", lambda *_args, **_kwargs: None)
    return env


async def attach():
    return await campaigns.attach_discovery("session", "owner", "workspace-1", "campaign-1", "discovery-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("existing,selected", [
    ([], ["new"]), (["old"], ["old"]), (["old"], ["old", "new"]),
    (["old"], ["old", "new", "new"]),
])
@pytest.mark.parametrize("failure", ["invalid", "error"])
async def test_failed_batch_rolls_back_only_owned_rows(attachment, existing, selected, failure):
    for lead_id in existing:
        attachment.links[f"existing-{lead_id}"] = CampaignLead(id=f"existing-{lead_id}", campaign_id="campaign-1", lead_id=lead_id)
    attachment.lead_ids = selected + [failure]
    with pytest.raises(HTTPException if failure == "invalid" else RuntimeError):
        await attach()
    assert {link.lead_id for link in attachment.links.values()} == set(existing)
    assert not any(value.startswith("existing-") for value in attachment.deleted)
    assert len(attachment.deleted) == len(set(selected) - set(existing))


@pytest.mark.asyncio
async def test_success_and_retry_keep_same_canonical_links(attachment):
    attachment.lead_ids = ["one", "two"]
    first = await attach()
    original_ids = set(attachment.links)
    second = await attach()
    assert first["ok"] is second["ok"] is True
    assert first["added"] == second["added"] == 2
    assert set(attachment.links) == original_ids
    assert attachment.deleted == []


@pytest.mark.asyncio
async def test_competing_unique_insert_is_not_owned_or_rolled_back(attachment):
    attachment.race = True
    attachment.lead_ids = ["one", "invalid"]
    with pytest.raises(HTTPException): await attach()
    assert set(attachment.links) == {"competing-link"}
    assert attachment.deleted == []


@pytest.mark.asyncio
async def test_unique_retry_of_same_write_retains_rollback_ownership(attachment):
    attachment.race = attachment.own_retry = True
    attachment.lead_ids = ["one", "invalid"]
    with pytest.raises(HTTPException): await attach()
    assert attachment.links == {}
    assert len(attachment.deleted) == 1


@pytest.mark.asyncio
async def test_compensation_rejects_wrong_workspace(attachment):
    attachment.links["old-link"] = CampaignLead(id="old-link", campaign_id="campaign-1", lead_id="old")
    assert not await state.remove_campaign_lead_links_awaited("owner", "campaign-1", ["old-link"], workspace_id="workspace-other")
    assert set(attachment.links) == {"old-link"}


@pytest.mark.asyncio
@pytest.mark.parametrize("later_failure", ["projection", "reload"])
async def test_later_failure_preserves_existing_links(attachment, monkeypatch, later_failure):
    attachment.links["old-link"] = CampaignLead(id="old-link", campaign_id="campaign-1", lead_id="old")
    attachment.lead_ids = ["old", "new"]
    if later_failure == "projection":
        def fail_projection(*_args, **_kwargs): raise RuntimeError("local projection failure")
        monkeypatch.setattr(campaigns, "publish", fail_projection)
    else:
        monkeypatch.setattr(state, "load_campaign_state", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError if later_failure == "projection" else HTTPException): await attach()
    assert set(attachment.links) == {"old-link"}


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback_raises", [False, True])
async def test_rollback_failure_does_not_hide_original_error(attachment, monkeypatch, caplog, rollback_raises):
    attachment.lead_ids = ["new", "error"]
    monkeypatch.setattr(state, "remove_campaign_lead_links_awaited", AsyncMock(
        side_effect=RuntimeError("local rollback failure") if rollback_raises else None,
        return_value=False,
    ))
    with pytest.raises(RuntimeError, match="local attachment failure") as caught: await attach()
    assert "rollback could not be confirmed" in caught.value.__notes__[0]
    assert "campaign_attachment_rollback_unconfirmed" in caplog.text


@pytest.mark.asyncio
async def test_exact_row_rollback_preserves_replacement_and_other_campaign(attachment):
    attachment.links["replacement"] = CampaignLead(id="replacement", campaign_id="campaign-1", lead_id="one")
    attachment.links["other"] = CampaignLead(id="other", campaign_id="campaign-2", lead_id="one")
    assert await state.remove_campaign_lead_links_awaited("owner", "campaign-1", ["original", "other"], workspace_id="workspace-1")
    assert set(attachment.links) == {"replacement", "other"}


@pytest.mark.asyncio
async def test_unrelated_save_failure_is_not_treated_as_duplicate(attachment):
    attachment.save_error = TypeError("local schema/programming failure")
    with pytest.raises(TypeError, match="local schema/programming failure"):
        await state.persist_campaign_lead_link_awaited("owner", "campaign-1", {"id": "one"}, workspace_id="workspace-1")
