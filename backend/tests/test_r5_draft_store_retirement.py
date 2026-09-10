"""R5-B regression coverage for retiring main.py's session-local draft map."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main as main_module
import services.workspace.state as workspace_state
from services.workflows.models import PlanningInput


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": "Bearer test-token"})


async def _owner(_request, _session_token="") -> str:
    return "owner-1"


async def _workspace(_request, _owner_id) -> SimpleNamespace:
    return SimpleNamespace(workspace_id="workspace-1")


@pytest.mark.asyncio
async def test_export_csv_reads_authorized_workspace_drafts(monkeypatch):
    seen: list[tuple[str, str]] = []

    def load_drafts(owner_id: str, workspace_id: str = "") -> list[dict]:
        seen.append((owner_id, workspace_id))
        return [{"lead": {"name": "Ada", "email": "ada@example.com"}}]

    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "test-token")
    monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", _owner)
    monkeypatch.setattr(main_module.workspace_access, "resolve_selected_workspace_context", _workspace)
    monkeypatch.setattr(workspace_state, "load_drafts_only", load_drafts)

    response = await main_module.export_csv("ignored-url-token", _request())

    assert seen == [("owner-1", "workspace-1")]
    assert b"Ada" in response.body
    assert b"ada@example.com" in response.body


@pytest.mark.asyncio
async def test_workflow_plan_reads_authorized_workspace_state(monkeypatch):
    seen: dict[str, object] = {}

    def load_campaigns(owner_id: str, *, workspace_id: str = "", include_details: bool = True) -> list[dict]:
        seen["campaigns"] = (owner_id, workspace_id, include_details)
        return [{"id": "campaign-1", "name": "Canonical campaign", "lead_count": 3}]

    def load_drafts(owner_id: str, workspace_id: str = "") -> list[dict]:
        seen["drafts"] = (owner_id, workspace_id)
        return [{"id": "draft-1", "campaign_id": "campaign-1", "status": "pending"}]

    def build_snapshot(session_token: str, campaigns: list[dict], drafts: list[dict], total_leads: int, **kwargs) -> dict:
        seen["snapshot"] = (session_token, campaigns, drafts, total_leads, kwargs)
        return {"campaigns": campaigns, "drafts": {"pending": len(drafts)}}

    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "test-token")
    monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", _owner)
    monkeypatch.setattr(main_module.workspace_access, "resolve_selected_workspace_context", _workspace)
    monkeypatch.setattr(main_module, "load_campaigns", load_campaigns)
    monkeypatch.setattr(workspace_state, "load_drafts_only", load_drafts)
    monkeypatch.setattr(main_module, "build_snapshot", build_snapshot)

    result = await main_module.plan_workflow_endpoint(
        "ignored-url-token",
        PlanningInput(objective="Review my drafts", current_page="Draft Review"),
        _request(),
    )

    assert seen["campaigns"] == ("owner-1", "workspace-1", True)
    assert seen["drafts"] == ("owner-1", "workspace-1")
    assert seen["snapshot"] == (
        "test-token",
        [{"id": "campaign-1", "name": "Canonical campaign", "lead_count": 3}],
        [{"id": "draft-1", "campaign_id": "campaign-1", "status": "pending"}],
        3,
        {"user_id": "owner-1"},
    )
    assert result["ok"] is True


def test_copilot_context_fails_closed_without_authorized_context():
    with pytest.raises(HTTPException) as error:
        main_module._build_copilot_workspace_context("session-token")

    assert error.value.status_code == 401
    assert error.value.detail == "Authentication required"
