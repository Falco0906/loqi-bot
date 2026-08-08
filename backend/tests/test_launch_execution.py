"""PR3A — execution engine: durable launch dispatch.

Covers the fix where Launch must dispatch from durable approved drafts (the
UI approval path persists to workspace state, never the in-memory outbound
store), persist launch progress durably for polling, and refuse to launch a
campaign with no approved drafts. Persistence + outbound stores are faked at
the workspace_state / store boundary so no Supabase or Gmail runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import main as main_module
import services.workspace_state as workspace_state
from services.outbound.draft_store import DraftStore

import services.outbound.draft_store as outbound_draft_store_module


def _draft(draft_id: str, campaign_id: str = "c-1", status: str = "approved",
           email: str = "ada@acme.com", subject: str = "Hi", body: str = "Body") -> dict:
    return {
        "id": draft_id,
        "campaign_id": campaign_id,
        "lead_id": f"lead-{draft_id}",
        "lead": {"email": email, "name": "Ada Lovelace"},
        "subject": subject,
        "text": body,
        "body": body,
        "status": status,
    }


def _campaign(**overrides) -> dict:
    campaign = {
        "id": "c-1",
        "name": "Outbound",
        "objective": "Book demos",
        "status": "planning",
        "lead_count": 2,
    }
    campaign.update(overrides)
    return campaign


class _FakeFeedback:
    def on_campaign_launched(self, session_token: str, campaign_id: str) -> None:
        return None


@pytest.fixture
def env(monkeypatch):
    """Fresh outbound DraftStore + fake workspace_state for one launch."""
    outbound_draft_store_module.draft_store = DraftStore()
    state = {
        "drafts": [],
        "campaigns": [_campaign()],
        "campaign_updates": [],
        "draft_updates": [],
    }
    calls: list[dict] = []

    async def fake_owner(session_token: str, request=None) -> str:
        return "owner-1"

    def fake_campaigns(owner_id: str, session_token: str = "") -> list[dict]:
        return list(state["campaigns"])

    def fake_drafts(owner_id: str, session_token: str = "") -> list[dict]:
        return list(state["drafts"])

    async def fake_persist_campaign(owner_id: str, campaign_id: str, updates: dict) -> bool:
        state["campaign_updates"].append((campaign_id, dict(updates)))
        return True

    async def fake_persist_draft(owner_id: str, draft_id: str, updates: dict) -> bool:
        state["draft_updates"].append((draft_id, dict(updates)))
        for d in state["drafts"]:
            if d["id"] == draft_id:
                d.update(updates)
        return True

    def fake_execute(kind: str, payload: dict) -> dict:
        calls.append(payload)
        return {"ok": True, "send_result": {"thread_id": "th-1", "external_message_id": "em-1"}}

    monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)
    monkeypatch.setattr(main_module, "_workspace_campaigns", fake_campaigns)
    monkeypatch.setattr(main_module, "_workspace_drafts", fake_drafts)
    monkeypatch.setattr(workspace_state, "persist_campaign_update_awaited", fake_persist_campaign)
    monkeypatch.setattr(workspace_state, "persist_draft_update_awaited", fake_persist_draft)
    monkeypatch.setattr(main_module, "_find_outbound_gmail_provider_id", lambda: "prov-1")
    monkeypatch.setattr(main_module, "publish", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "record_campaign_launched", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "_get_feedback", lambda: _FakeFeedback())
    monkeypatch.setattr(main_module.outbound_executor, "execute", fake_execute)

    return {"state": state, "calls": calls}


def _launch_progress(state) -> dict:
    launches = [u for (_cid, u) in state["campaign_updates"] if u.get("launch") is not None]
    return launches[-1]["launch"]


async def test_launch_dispatch_reads_durable_approved_drafts(env):
    env["state"]["drafts"] = [_draft("d-1"), _draft("d-2")]
    result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")

    assert result["total"] == 2
    assert result["sent"] == 2
    assert result["failed"] == 0
    assert {c["draft_id"] for c in env["calls"]} == {"d-1", "d-2"}
    assert env["calls"][0]["recipient"]["email"] == "ada@acme.com"

    sent_marks = {draft_id for draft_id, u in env["state"]["draft_updates"] if u.get("status") == "sent"}
    assert sent_marks == {"d-1", "d-2"}, "durable drafts must be marked sent after delivery"

    progress = _launch_progress(env["state"])
    assert progress["total"] == 2
    assert progress["sent"] == 2
    assert progress["failed"] == 0


async def test_dispatch_only_sends_approved_drafts(env):
    env["state"]["drafts"] = [
        _draft("d-approved"),
        _draft("d-pending", status="pending"),
        _draft("d-sent", status="sent"),
    ]
    result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")
    assert [c["draft_id"] for c in env["calls"]] == ["d-approved"]
    assert result["total"] == 1
    assert result["sent"] == 1


async def test_dispatch_zero_approved_returns_error(env):
    env["state"]["drafts"] = [_draft("d-pending", status="pending")]
    result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")
    assert result["ok"] is False
    assert "approve" in result["error"].lower()
    assert env["calls"] == []


async def test_dispatch_partial_failure_tracks_progress(env, monkeypatch):
    env["state"]["drafts"] = [_draft("d-1"), _draft("d-2")]
    attempts = [0]

    def flaky(kind: str, payload: dict) -> dict:
        attempts[0] += 1
        if attempts[0] == 2:
            return {"ok": False, "error": "Gmail 403"}
        return {"ok": True, "send_result": {"thread_id": "th", "external_message_id": "em"}}

    monkeypatch.setattr(main_module.outbound_executor, "execute", flaky)
    result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")
    assert result["sent"] == 1
    assert result["failed"] == 1
    assert _launch_progress(env["state"])["status"] == "partial"


async def test_launch_requires_approved_drafts(env):
    env["state"]["drafts"] = [_draft("d-pending", status="pending")]
    payload = SimpleNamespace(name=None, objective=None, strategy=None, status="completed")
    with pytest.raises(Exception) as excinfo:
        await main_module.update_campaign("tok-1", "c-1", payload, request=None)
    assert excinfo.value.status_code == 400
    assert env["state"]["campaign_updates"] == []
    assert env["calls"] == []


async def test_launch_persists_status_and_progress(env):
    env["state"]["drafts"] = [_draft("d-1")]
    payload = SimpleNamespace(name=None, objective=None, strategy=None, status="completed")
    result = await main_module.update_campaign("s-1", "c-1", payload, request=None)
    assert result["ok"] is True
    assert len(env["calls"]) == 1
    assert ("c-1", {"status": "completed"}) in env["state"]["campaign_updates"]
    assert _launch_progress(env["state"])["sent"] == 1


async def test_launch_progress_endpoint_reads_durable_values(env):
    env["state"]["campaigns"] = [{
        **_campaign(),
        "launch_sent": 1,
        "launch_total": 2,
        "launch_failed": 1,
    }]
    result = await main_module.campaign_launch_progress("s-1", "c-1", request=None)
    assert result["launch_sent"] == 1
    assert result["launch_total"] == 2
    assert result["launch_complete"] is False


async def test_campaign_timeline_endpoint_filters_wm_events(env):
    """PR3B — timeline endpoint aggregates World Model events for one campaign."""
    from services.world_model import EventType as WMET
    from services.world_model import publish as wm_publish

    wm_publish("pr3b-tok-1", WMET.DRAFT_SENT, {
        "draft_id": "d1", "campaign_id": "c-1", "recipient_email": "ada@acme.com"})
    wm_publish("pr3b-tok-1", WMET.DRAFT_FAILED, {
        "draft_id": "d2", "campaign_id": "c-1", "error": "smtp refused"})
    wm_publish("pr3b-tok-1", WMET.DRAFT_SENT, {
        "draft_id": "d3", "campaign_id": "c-9", "recipient_email": "zed@acme.com"})

    result = await main_module.campaign_timeline("pr3b-tok-1", "c-1", request=None)
    assert result["ok"] is True
    assert [e["type"] for e in result["events"]] == ["draft_sent", "draft_failed"]
    assert all(e["data"]["campaign_id"] == "c-1" for e in result["events"])
    assert result["events"][1]["data"]["error"] == "smtp refused"