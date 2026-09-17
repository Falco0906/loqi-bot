"""Native Discovery-selection -> manual Campaign creation regression."""

import asyncio
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_manual_campaign_returns_after_four_selected_leads_are_durable(monkeypatch):
    from services.campaigns import api as campaign_api

    attached: list[str] = []
    persisted: dict = {}
    active_links = 0
    max_active_links = 0
    strategy_started = asyncio.Event()
    release_strategy = asyncio.Event()
    ordering: list[str] = []
    durable_activity: list[dict] = []

    async def persist_campaign(_owner, campaign, workspace_id=""):
        ordering.append("campaign_persisted")
        persisted.update(campaign)
        return True

    async def persist_lead(_owner, _campaign_id, lead, workspace_id=""):
        nonlocal active_links, max_active_links
        active_links += 1
        max_active_links = max(max_active_links, active_links)
        await asyncio.sleep(0.05)
        attached.append(str(lead["id"]))
        active_links -= 1
        return True

    async def blocked_strategy(*_args, **_kwargs):
        strategy_started.set()
        await release_strategy.wait()

    monkeypatch.setattr(campaign_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(campaign_api.identity_dependencies, "authenticated_user_id", lambda *_args, **_kwargs: _async_value("owner-1"))
    monkeypatch.setattr(campaign_api.workspace_access, "resolve_legacy_workspace_id", lambda *_args, **_kwargs: _async_value("workspace-1"))
    monkeypatch.setattr("services.discovery.service.get_discovery", lambda discovery_id, workspace_id="": {
        "id": discovery_id, "workspace_id": workspace_id,
    })
    monkeypatch.setattr("services.workspace.state.persist_campaign_row", persist_campaign)
    monkeypatch.setattr("services.workspace.state.persist_campaign_lead_awaited", persist_lead)
    def load_verified_campaign(_owner, campaign_id, workspace_id=""):
        ordering.append("campaign_verified")
        return {
            **persisted, "id": campaign_id, "lead_count": len(attached), "leads": leads,
        }

    monkeypatch.setattr("services.workspace.state.load_campaign_state", load_verified_campaign)
    monkeypatch.setattr("services.workspace.state.append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("services.workspace.timeline.record_campaign_created", lambda *_args, **_kwargs: None)
    class ActivityRepository:
        def append_campaign_created(self, **kwargs):
            ordering.append("durable_activity")
            durable_activity.append(kwargs)

    monkeypatch.setattr("services.campaigns.service.get_activity_repository", lambda: ActivityRepository())
    monkeypatch.setattr("services.campaigns.service.publish", lambda *_args, **_kwargs: ordering.append("legacy_projection"))
    monkeypatch.setattr("services.campaigns.service.maybe_auto_strategy", blocked_strategy)
    monkeypatch.setattr("services.campaigns.service._feedback", lambda: SimpleNamespace(on_campaign_created=lambda *_args: None))

    leads = [{"id": f"workspace-lead-{index}", "company": f"Cafe {index}"} for index in range(1, 5)]
    payload = campaign_api.SaveCampaignRequest(
        name="Hyderabad cafe owners",
        objective="Start outreach",
        discovery_id="discovery-1",
        leads=leads,
        lead_count=len(leads),
    )
    request = SimpleNamespace()

    response = await campaign_api.save_campaign("_", payload, request)

    assert response["ok"] is True
    assert response["campaign"]["lead_count"] == 4
    assert [lead["id"] for lead in response["campaign"]["leads"]] == [f"workspace-lead-{index}" for index in range(1, 5)]
    assert attached == [f"workspace-lead-{index}" for index in range(1, 5)]
    assert persisted["id"] == response["campaign"]["id"]
    assert max_active_links == 4
    assert ordering.index("campaign_persisted") < ordering.index("campaign_verified") < ordering.index("durable_activity") < ordering.index("legacy_projection")
    assert durable_activity == [{
        "workspace_id": "workspace-1", "actor_user_id": "owner-1",
        "source_key": f"campaign:{response['campaign']['id']}:created",
        "payload": {
            "campaign_id": response["campaign"]["id"], "status": "planning", "lead_count": 4,
        },
        "occurred_at": response["campaign"]["created_at"],
    }]

    # The response is not held hostage by strategy setup.
    await asyncio.wait_for(strategy_started.wait(), timeout=0.2)
    release_strategy.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_manual_campaign_without_leads_returns_when_compatibility_event_is_slow(monkeypatch):
    from services.campaigns import api as campaign_api

    event_started = threading.Event()
    release_event = threading.Event()
    persisted = {}

    async def persist_campaign(_owner, campaign, workspace_id=""):
        persisted.update(campaign)
        return True

    def blocked_event(*_args, **_kwargs):
        event_started.set()
        release_event.wait(timeout=2)
        return True

    monkeypatch.setattr(campaign_api.identity_dependencies, "web_session_token", lambda _request: "session-1")
    monkeypatch.setattr(campaign_api.identity_dependencies, "authenticated_user_id", lambda *_args, **_kwargs: _async_value("owner-1"))
    monkeypatch.setattr(campaign_api.workspace_access, "resolve_legacy_workspace_id", lambda *_args, **_kwargs: _async_value("workspace-1"))
    monkeypatch.setattr("services.workspace.state.persist_campaign_row", persist_campaign)
    monkeypatch.setattr("services.workspace.state.load_campaign_state", lambda _owner, campaign_id, workspace_id="": {
        **persisted, "id": campaign_id, "lead_count": 0, "leads": [],
    })
    monkeypatch.setattr("services.workspace.state.append_event", blocked_event)
    monkeypatch.setattr("services.workspace.timeline.record_campaign_created", lambda *_args, **_kwargs: None)
    legacy_events = []

    class FailingActivityRepository:
        def append_campaign_created(self, **_kwargs):
            raise RuntimeError("activity unavailable")

    monkeypatch.setattr("services.campaigns.service.get_activity_repository", lambda: FailingActivityRepository())
    monkeypatch.setattr("services.campaigns.service.publish", lambda *_args, **_kwargs: legacy_events.append(_args[1]))
    monkeypatch.setattr("services.campaigns.service._feedback", lambda: SimpleNamespace(on_campaign_created=lambda *_args: None))

    response = await campaign_api.save_campaign(
        "_",
        campaign_api.SaveCampaignRequest(name="Empty campaign", objective="No leads yet"),
        SimpleNamespace(),
    )

    assert response["ok"] is True
    assert response["campaign"]["lead_count"] == 0
    assert response["campaign"]["leads"] == []
    assert persisted["id"] == response["campaign"]["id"]
    assert [event.value for event in legacy_events] == ["campaign_created"]
    await asyncio.to_thread(event_started.wait, 0.2)
    release_event.set()
    await asyncio.sleep(0)


async def _async_value(value):
    return value
