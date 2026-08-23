"""Focused Copilot lead-save and campaign handoff contracts."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_lead_save_normalizes_provider_status_and_returns_workspace_lead_id(monkeypatch):
    from services import workspace_state

    captured = []

    class FakeLeadRepo:
        async def find_by_email(self, _email):
            return SimpleNamespace(
                id="canonical-lead-1", email="owner", first_name="A",
                last_name="Owner", title="Owner", phone="", linkedin_url="",
            )

    class FakeWorkspaceLeadRepo:
        async def find_in_workspace(self, _workspace, _lead_id):
            return None

        async def save(self, entity):
            captured.append(entity)
            entity.id = "workspace-lead-1"
            return entity

    monkeypatch.setattr(workspace_state, "LeadRepository", FakeLeadRepo)
    monkeypatch.setattr(workspace_state, "WorkspaceLeadRepository", FakeWorkspaceLeadRepo)
    monkeypatch.setattr(workspace_state, "_async_workspace", lambda *_args, **_kwargs: _async_value("workspace-1"))

    result = await workspace_state._normalize_lead(
        "workspace-1",
        {"email": "owner", "status": "saved", "title": "Owner"},
    )

    assert result == "workspace-lead-1"
    assert captured[0].lead_status == "added"
    assert workspace_state._canonical_lead_status("selected") == "added"
    assert workspace_state._canonical_lead_status("provider-specific") == "new"


@pytest.mark.asyncio
async def test_campaign_create_returns_authoritative_campaign_and_attached_ids(monkeypatch):
    import main as main_module

    persisted = {}

    async def persist_row(_user, campaign, workspace_id=""):
        persisted.update(campaign)
        return True

    async def attach(_user, _campaign_id, lead, workspace_id=""):
        return {"a@example.test": "workspace-lead-a", "b@example.test": "workspace-lead-b"}.get(lead["email"])

    monkeypatch.setattr(main_module, "_maybe_auto_strategy", _noop_async)
    monkeypatch.setattr(
        "services.discovery.get_discovery",
        lambda *_args, **_kwargs: {
            "id": "discovery-1",
            "discovery_leads": [
                {"rank": 1, "workspace_lead": {"id": "source-a", "lead": {"email": "a@example.test"}}},
                {"rank": 2, "workspace_lead": {"id": "source-b", "lead": {"email": "b@example.test"}}},
            ],
        },
    )
    monkeypatch.setattr("services.workspace_state.persist_campaign_row", persist_row)
    monkeypatch.setattr("services.workspace_state.persist_campaign_lead_id_awaited", attach)
    monkeypatch.setattr("services.workspace_state.load_campaign_state", lambda _u, _c, workspace_id="": persisted)
    monkeypatch.setattr("services.workspace_state.append_event", lambda *_args, **_kwargs: None)

    result = await main_module._run_copilot_campaign(
        "campaign.create",
        "owner-1",
        "workspace-1",
        "session-1",
        {
            "campaign": {"name": "Cafe owners", "objective": "outreach"},
            "active_search": {"discovery_id": "discovery-1"},
            "page_context": {},
        },
    )

    assert result["ok"] is True
    assert result["result"]["campaign_id"] == persisted["id"]
    assert result["result"]["active_campaign_id"] == persisted["id"]
    assert result["result"]["attached_lead_ids"] == ["workspace-lead-a", "workspace-lead-b"]


@pytest.mark.asyncio
async def test_campaign_attach_returns_canonical_lead_ids_without_new_discovery(monkeypatch):
    from services import copilot_tools

    monkeypatch.setattr(
        copilot_tools,
        "_load_owned_discovery",
        lambda *_args: _async_value({
            "id": "discovery-1",
            "status": "completed",
            "discovery_leads": [
                {"rank": 1, "workspace_lead": {"id": "workspace-lead-a", "lead": {"name": "A"}}},
            ],
            "discovery_companies": [],
        }),
    )
    monkeypatch.setattr("services.workspace_state.load_campaign_state", lambda *_args, **_kwargs: {"id": "campaign-1"})
    monkeypatch.setattr(
        "services.workspace_state.persist_campaign_lead_id_awaited",
        lambda *_args, **_kwargs: _async_value("workspace-lead-a"),
    )

    async def must_not_start_discovery(*_args, **_kwargs):
        raise AssertionError("lead attachment must not create a Discovery")

    result = await copilot_tools.execute_copilot_tool(
        "lead.attach",
        user_id="owner-1",
        workspace_id="workspace-1",
        session_token="session-1",
        decision={
            "confirmed": True,
            "campaign_id": "campaign-1",
            "active_search": {"discovery_id": "discovery-1"},
        },
        discovery_runner=must_not_start_discovery,
    )

    assert result["ok"] is True
    assert result["result"]["campaign_id"] == "campaign-1"
    assert result["result"]["attached_lead_ids"] == ["workspace-lead-a"]


def test_campaign_result_exposes_active_campaign_context():
    result = {
        "campaign": {"id": "campaign-1", "name": "Cafe owners"},
        "campaign_id": "campaign-1",
        "active_campaign_id": "campaign-1",
        "attached_lead_ids": ["workspace-lead-a"],
    }
    assert result["active_campaign_id"] == result["campaign"]["id"]
    assert result["campaign_id"] == "campaign-1"


def test_database_failures_are_not_formatted_into_copilot_text():
    import main as main_module

    raw = "PostgREST 23514: new row violates workspace_leads_lead_status_check"
    safe = main_module._copilot_tool_failure_reason("campaign.create")
    assert raw not in safe
    assert safe == "campaign.create could not be completed. Please try again."


async def _async_value(value):
    return value


async def _noop_async(*_args, **_kwargs):
    return None
