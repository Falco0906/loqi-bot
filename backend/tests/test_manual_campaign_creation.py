"""Native Discovery-selection -> manual Campaign creation regression."""

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_manual_campaign_returns_after_four_selected_leads_are_durable(monkeypatch):
    import main as main_module

    attached: list[str] = []
    persisted: dict = {}
    strategy_started = asyncio.Event()
    release_strategy = asyncio.Event()

    async def persist_campaign(_owner, campaign, workspace_id=""):
        persisted.update(campaign)
        return True

    async def persist_lead(_owner, _campaign_id, lead, workspace_id=""):
        attached.append(str(lead["id"]))
        return True

    async def blocked_strategy(*_args, **_kwargs):
        strategy_started.set()
        await release_strategy.wait()

    monkeypatch.setattr(main_module, "_session_token_from_request", lambda _request: "session-1")
    monkeypatch.setattr(main_module, "_workspace_owner", lambda *_args, **_kwargs: _async_value("owner-1"))
    monkeypatch.setattr(main_module, "_resolved_workspace_id_or_default", lambda *_args, **_kwargs: _async_value("workspace-1"))
    monkeypatch.setattr("services.workspace_state.persist_campaign_row", persist_campaign)
    monkeypatch.setattr("services.workspace_state.persist_campaign_lead_awaited", persist_lead)
    monkeypatch.setattr("services.workspace_state.append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "record_campaign_created", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "_maybe_auto_strategy", blocked_strategy)
    monkeypatch.setattr(main_module, "_get_feedback", lambda: SimpleNamespace(on_campaign_created=lambda *_args: None))

    leads = [{"id": f"workspace-lead-{index}", "company": f"Cafe {index}"} for index in range(1, 5)]
    payload = main_module.SaveCampaignRequest(
        name="Hyderabad cafe owners",
        objective="Start outreach",
        discovery_id="discovery-1",
        leads=leads,
        lead_count=len(leads),
    )
    request = SimpleNamespace()

    response = await main_module.save_campaign("_", payload, request)

    assert response["ok"] is True
    assert response["campaign"]["lead_count"] == 4
    assert [lead["id"] for lead in response["campaign"]["leads"]] == [f"workspace-lead-{index}" for index in range(1, 5)]
    assert attached == [f"workspace-lead-{index}" for index in range(1, 5)]
    assert persisted["id"] == response["campaign"]["id"]

    # The response is not held hostage by strategy setup.
    await asyncio.wait_for(strategy_started.wait(), timeout=0.2)
    release_strategy.set()
    await asyncio.sleep(0)


async def _async_value(value):
    return value
