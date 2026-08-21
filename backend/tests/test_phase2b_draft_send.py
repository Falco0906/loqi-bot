"""PR-2B — Draft Send Now end-to-end regression tests.

Production symptom: Review UI shows an approved draft; clicking Send Now
returned 404 {"detail":"Draft not found"} → UI showed "Send request failed".

Root cause: _sync_draft_to_outbound stamped hydrated drafts with the FIRST
Gmail provider in the GLOBAL registry (_find_outbound_gmail_provider_id).
With multiple connected users — or after an identity divergence — a draft
was stamped with ANOTHER user's provider, which the send route's cross-user
ownership check then rejected with exactly that 404.

These tests pin the fixed contract:
  A. Approved durable draft → POST /send succeeds (hydration is owner-scoped)
  B. Unknown/nonexistent draft → explicit 404
  C. Foreign-provider draft → 404 without existence leak (security, kept)
  D. Restart simulation (outbound store empty) → still sendable
  E. Freshly approved draft → sendable
  F. Stale frontend draft id → clean 404 (no ambiguity)
  G. Executor failure does not corrupt draft state
  H. THE production bug: second user's presence must not poison first
     user's hydration (owner-scoped stamping)
"""
import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import main as main_module
from services.outbound import outbound_registry
from services.outbound.outbound_models import (
    DraftMessage,
    DraftStatus,
    ApprovalState,
    Recipient,
)
from services.outbound.draft_store import draft_store as outbound_draft_store
from services.communication import provider_registry as comm_registry

OWNER = "2b-owner-0001"
OTHER = "2b-other-0002"
SESSION = "2b-session"


class FakeComm:
    def __init__(self, user_id, email="", connected=True):
        self._user_id = user_id
        self._mailbox_email = email
        self._connected = connected
        self.provider_type = None

    def disconnect(self):
        self._connected = False


class FakeOutbound:
    provider_type = "gmail"

    def __init__(self, provider_id):
        self.id = provider_id


def register_gmail(provider_id: str, user_id: str, email: str = ""):
    comm_registry.register_instance(pid := provider_id, FakeComm(user_id=user_id, email=email))
    outbound_registry.register_instance(pid, FakeOutbound(pid))
    return pid


def make_outbound_draft(draft_id: str, provider_id: str) -> DraftMessage:
    d = DraftMessage(
        id=draft_id,
        provider_id=provider_id,
        subject="S",
        body="B",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="", name=""),
        status=DraftStatus.APPROVED,
        approval_state=ApprovalState.APPROVED,
    )
    outbound_draft_store.create(d)
    return d


def durable_draft(draft_id: str, status: str = "approved") -> dict:
    return {
        "id": draft_id,
        "status": status,
        "campaign_id": "cmp-1",
        "subject": "Subject",
        "text": "Body",
        "created_at": "2026-01-01T00:00:00+00:00",
        "lead": {"email": "lead@example.com", "name": "Lead"},
    }


@pytest.fixture()
def harness(monkeypatch):
    # Reset stores/registries
    outbound_draft_store._drafts.clear() if hasattr(outbound_draft_store, "_drafts") else None
    for attr in ("_drafts", "_store"):
        if hasattr(outbound_draft_store, attr):
            getattr(outbound_draft_store, attr).clear()
    comm_registry._instances.clear()
    outbound_registry._instances.clear()
    main_module._gmail_connect_locks.clear()

    state = {
        "durable": [],            # durable drafts returned by _workspace_drafts
        "workspace_ids_seen": [],
        "executed": [],           # outbound_executor.execute captures
        "executor_result": {"ok": True},
        "legacy": {},             # legacy session-scoped drafts
    }

    monkeypatch.setattr(main_module, "_session_token_from_request", lambda request: SESSION)

    async def fake_owner(request=None, session_token=None):
        return OWNER
    monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)

    async def fake_ws(request=None, owner_id=None):
        return ""
    monkeypatch.setattr(main_module, "_resolved_workspace_id_or_default", fake_ws)

    def fake_workspace_drafts(user_id, session_token="", workspace_id=""):
        state["workspace_ids_seen"].append(workspace_id)
        return list(state["durable"])
    monkeypatch.setattr(main_module, "_workspace_drafts", fake_workspace_drafts)

    monkeypatch.setattr(main_module, "_test_recipient_override_enabled", lambda: False)

    class StubExecutor:
        def execute(self, action, params):
            state["executed"].append({"action": action, **params})
            result = dict(state["executor_result"])
            if state["executor_result"].get("ok"):
                result.setdefault("send_result", {"thread_id": "t", "external_message_id": "m"})
            return result
    monkeypatch.setattr(main_module, "outbound_executor", StubExecutor())

    app = FastAPI()

    @app.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
    async def send(session_token: str, draft_id: str, request: Request, payload: dict = None):
        return await main_module.send_draft(session_token, draft_id, request, payload)

    client = TestClient(app, raise_server_exceptions=False)
    yield client, state


def test_a_approved_durable_draft_sends(harness):
    client, state = harness
    own = register_gmail("prov-own", OWNER, email="me@gmail.com")
    state["durable"] = [durable_draft("draft-a")]
    r = client.post(f"/api/web/session/X/drafts/draft-a/send")
    body = r.json()
    assert r.status_code == 200 and body.get("ok") is True, body
    assert state["executed"] and state["executed"][0]["provider_id"] == own
    synced = outbound_draft_store.get("draft-a")
    assert synced.provider_id == own


def test_b_unknown_draft_is_404(harness):
    client, state = harness
    register_gmail("prov-own", OWNER)
    r = client.post("/api/web/session/X/drafts/does-not-exist/send")
    assert r.status_code == 404
    assert r.json()["detail"] == "Draft not found in any store"


def test_c_foreign_provider_draft_stays_404(harness):
    """Security control preserved: a draft bound to another user's LIVE
    provider must not be sendable nor distinguishable from missing."""
    from services.communication.communication_store import store as cs
    from services.communication.provider_models import (
        CommunicationProvider, ProviderType, ProviderStatus,
    )
    client, state = harness
    foreign = register_gmail("prov-foreign", OTHER, email="other@gmail.com")
    cs.save_provider(CommunicationProvider(
        id=foreign, provider_type=ProviderType.GMAIL,
        user_id=OTHER, status=ProviderStatus.HEALTHY,
    ))
    make_outbound_draft("draft-c", foreign)
    r = client.post("/api/web/session/X/drafts/draft-c/send")
    assert r.status_code == 404
    assert r.json()["detail"] == "Draft not found"


def test_d_restart_simulation_still_sendable(harness):
    """Hard refresh / backend restart: outbound store empty, durable copy
    remains the source of truth."""
    client, state = harness
    own = register_gmail("prov-own", OWNER)
    state["durable"] = [durable_draft("draft-d")]
    # (outbound store starts empty in this fixture = post-restart state)
    r = client.post("/api/web/session/X/drafts/draft-d/send")
    body = r.json()
    assert r.status_code == 200 and body.get("ok") is True
    assert state["executed"][0]["provider_id"] == own


def test_e_freshly_approved_durable_draft_sendable(harness):
    client, state = harness
    own = register_gmail("prov-own", OWNER)
    state["durable"] = [durable_draft("draft-e", status="approved")]
    r = client.post("/api/web/session/X/drafts/draft-e/send")
    assert r.status_code == 200 and r.json().get("ok") is True
    assert outbound_draft_store.get("draft-e").status == DraftStatus.SENT


def test_f_stale_frontend_draft_fails_cleanly(harness):
    client, state = harness
    register_gmail("prov-own", OWNER)
    state["durable"] = [durable_draft("live-draft")]
    r = client.post("/api/web/session/X/drafts/stale-id-from-old-session/send")
    assert r.status_code == 404  # explicit, not a 500/ambiguous error


def test_g_send_failure_does_not_corrupt_state(harness):
    client, state = harness
    own = register_gmail("prov-own", OWNER)
    state["durable"] = [durable_draft("draft-g")]
    state["executor_result"] = {"ok": False, "error": "gmail 500"}

    r = client.post("/api/web/session/X/drafts/draft-g/send")
    body = r.json()
    assert r.status_code == 200 and body.get("ok") is False

    d = outbound_draft_store.get("draft-g")
    assert d is not None and d.status != DraftStatus.SENT, "failed send must not mark sent"
    # Durable copy untouched (still approved, not sent).
    assert state["durable"][0]["status"] == "approved"


def test_h_production_bug_second_user_does_not_poison_first(harness):
    """THE regression: another user's Gmail provider exists in the global
    registry while OUR user has none yet — hydration must stamp EMPTY (and
    fail cleanly at resolution), never the foreign provider (old code → 404
    'Draft not found')."""
    client, state = harness
    register_gmail("prov-foreign-live", OTHER, email="other@gmail.com")
    state["durable"] = [durable_draft("draft-h")]

    r = client.post("/api/web/session/X/drafts/draft-h/send")
    body = r.json()
    assert r.status_code == 200  # reached the resolver, not the ownership 404
    assert body.get("ok") is False
    assert body.get("error") == "No Gmail outbound provider registered"

    synced = outbound_draft_store.get("draft-h")
    assert synced.provider_id != "prov-foreign-live"
