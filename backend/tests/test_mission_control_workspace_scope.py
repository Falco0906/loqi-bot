"""Offline contracts for Mission Control's selected-workspace boundary."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _authenticate(monkeypatch, user_id: str = "user-a") -> None:
    from services.identity import dependencies as identity_dependencies

    monkeypatch.setattr(identity_dependencies, "web_session_token", lambda _request: "bearer-a")

    async def authenticated_user(_request, _token=""):
        return user_id

    monkeypatch.setattr(identity_dependencies, "authenticated_user_id", authenticated_user)


class _MissionControlDouble:
    def __init__(self) -> None:
        self.summary_calls: list[dict] = []
        self.briefing_calls: list[dict] = []

    async def get_summary(self, **kwargs):
        self.summary_calls.append(kwargs)
        return {"ok": True, "campaigns": [], "workspace_id": kwargs["workspace_id"]}

    async def get_workspace_briefing(self, **kwargs):
        self.briefing_calls.append(kwargs)
        return {"ok": True, "briefing": {"workspace_id": kwargs["workspace_id"]}}


def test_mission_control_route_uses_authorized_selected_workspace(client, monkeypatch):
    from services.mission_control import api
    from services.workspace import access

    _authenticate(monkeypatch)
    service = _MissionControlDouble()
    monkeypatch.setattr(api, "get_service", lambda: service)

    async def selected_workspace(request, user_id):
        assert user_id == "user-a"
        assert request.headers["x-workspace-id"] == "workspace-b"
        return SimpleNamespace(workspace_id="workspace-b", user_id="user-a")

    monkeypatch.setattr(access, "resolve_selected_workspace_context", selected_workspace)
    response = client.get(
        "/api/web/session/path-token/mission-control",
        headers={"X-Workspace-Id": "workspace-b"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "campaigns": [], "workspace_id": "workspace-b"}
    assert service.summary_calls == [{
        "owner_id": "user-a",
        "workspace_id": "workspace-b",
        "actor_user_id": "user-a",
        "session_token": "bearer-a",
    }]

    briefing = client.get(
        "/api/web/session/path-token/briefing",
        headers={"X-Workspace-Id": "workspace-b"},
    )
    assert briefing.status_code == 200
    assert briefing.json() == {"ok": True, "briefing": {"workspace_id": "workspace-b"}}
    assert service.briefing_calls == [{
        "owner_id": "user-a",
        "workspace_id": "workspace-b",
        "actor_user_id": "user-a",
        "session_token": "bearer-a",
        "user_timezone": None,
    }]


@pytest.mark.asyncio
async def test_shared_payload_scopes_canonical_reads_snapshots_and_cache(monkeypatch):
    from services.mission_control import payload

    payload._payload_cache.clear()
    payload._inflight.clear()
    state_calls: list[tuple] = []
    snapshot_calls: list[dict] = []

    def load_state(owner_id, *, include_details, workspace_id, canonical_only):
        state_calls.append((owner_id, include_details, workspace_id, canonical_only))
        return {
            "campaigns": [{"id": f"campaign-{workspace_id}", "name": workspace_id, "lead_count": 1}],
            "drafts": [{"id": f"draft-{workspace_id}", "campaign_id": f"campaign-{workspace_id}", "status": "pending"}],
        }

    def build_snapshot(session_token, campaigns, drafts, total_leads, *, user_id, workspace_id):
        snapshot_calls.append({
            "session_token": session_token,
            "campaigns": campaigns,
            "drafts": drafts,
            "total_leads": total_leads,
            "user_id": user_id,
            "workspace_id": workspace_id,
        })
        return {
            "campaigns": campaigns,
            "drafts": {"total": len(drafts), "pending": len(drafts), "approved": 0},
            "total_leads": total_leads,
            "analysis": {},
        }

    monkeypatch.setattr("services.workspace.state.load_workspace_state", load_state)
    monkeypatch.setattr("services.workspace.snapshot.build_snapshot", build_snapshot)
    monkeypatch.setattr("services.mission_control.recommendations.generate_recommendations", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.mission_control.narrative.generate_brief", lambda *_args, **_kwargs: {"greeting": "", "lines": [], "suggestion": ""})

    first = await payload.compute_shared_payload(
        "user-a", "workspace-a", "user-a", "bearer-a", include_narrative=False,
    )
    second = await payload.compute_shared_payload(
        "user-a", "workspace-b", "user-a", "bearer-a", include_narrative=False,
    )

    assert [call[2] for call in state_calls] == ["workspace-a", "workspace-b"]
    assert all(call[3] is True for call in state_calls)
    assert [call["workspace_id"] for call in snapshot_calls] == ["workspace-a", "workspace-b"]
    assert all(call["user_id"] == "user-a" for call in snapshot_calls)
    assert first["campaigns"][0]["id"] == "campaign-workspace-a"
    assert second["campaigns"][0]["id"] == "campaign-workspace-b"


@pytest.mark.asyncio
async def test_selected_workspace_payload_excludes_session_scoped_world_model_delta(monkeypatch):
    from services.mission_control import payload
    from services.world_model import EventType, get_store, publish

    payload._payload_cache.clear()
    payload._inflight.clear()
    store = get_store()
    store.clear_session("shared-bearer")
    publish("shared-bearer", EventType.CAMPAIGN_CREATED, {"id": "foreign-campaign", "lead_count": 999})

    monkeypatch.setattr(
        "services.workspace.state.load_workspace_state",
        lambda *_args, **_kwargs: {"campaigns": [{"id": "campaign-a", "lead_count": 1}], "drafts": []},
    )
    monkeypatch.setattr(
        "services.workspace.snapshot.build_snapshot",
        lambda *_args, **_kwargs: {"campaigns": [{"id": "campaign-a"}], "drafts": {"total": 0, "pending": 0, "approved": 0}, "total_leads": 1, "analysis": {}},
    )
    monkeypatch.setattr("services.mission_control.recommendations.generate_recommendations", lambda *_args, **_kwargs: [])

    result = await payload.compute_shared_payload(
        "user-a", "workspace-a", "user-a", "shared-bearer", include_narrative=False,
    )

    assert result["snapshot"]["campaigns"] == [{"id": "campaign-a"}]
    assert result["delta"].event_count == 0
    assert result["snapshot"]["_delta"]["event_count"] == 0


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (404, "No accessible workspace"),
        (404, "Workspace not found"),
        (409, "Multiple workspaces available; select one via the X-Workspace-Id header"),
    ],
)
def test_mission_control_route_preserves_workspace_resolver_errors(
    client, monkeypatch, status_code, detail,
):
    from services.mission_control import api
    from services.workspace import access

    _authenticate(monkeypatch)
    service = _MissionControlDouble()
    monkeypatch.setattr(api, "get_service", lambda: service)

    async def resolver_error(_request, _user_id):
        raise HTTPException(status_code=status_code, detail=detail)

    monkeypatch.setattr(access, "resolve_selected_workspace_context", resolver_error)
    response = client.get("/api/web/session/path-token/mission-control")

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert service.summary_calls == []
