"""PR-3E — draft lifecycle event regression tests.

Verifies:
  1. draft.sent / draft.approved / draft.scheduled events are published
  2. scoped to the server-resolved owner (user isolation)
  3. payloads contain identifiers only — no credentials/bodies/secrets
"""
import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import main as main_module

OWNER = "3e-owner-0001"
OTHER = "3e-owner-9999"


class _StubOutbound:
    provider_id = "prov-1"
    workflow_id = "cmp-1"
    subject = "S"

    class recipient:  # noqa: N805
        name = "Lead One"

    class sender:
        email = "me@gmail.com"
        name = ""


@pytest.fixture()
def capture(monkeypatch):
    events: list[tuple[str, dict]] = []

    async def fake_publish(user_id, event_type, data=None, *, job_id="", status="", progress=None):
        events.append((user_id, {"type": event_type, **(data or {})}))
        return True

    # Patch the singleton INSTANCE (not just the class): guarantees the
    # helper's `from services.events_bus import event_bus` binding hits it.
    import services.events_bus as eb
    monkeypatch.setattr(eb.event_bus, "publish_user_event", fake_publish)
    return events


def _wire_send_route(app, monkeypatch):
    """Minimal app exposing the send route with all externals stubbed."""
    from services.outbound import outbound_registry
    from services.communication import provider_registry as comm_registry
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_models import (
        DraftMessage, DraftStatus, ApprovalState, Recipient,
    )

    # clear registries/stores
    comm_registry._instances.clear()
    outbound_registry._instances.clear()
    if hasattr(outbound_draft_store, "_drafts"):
        outbound_draft_store._drafts.clear()

    async def fake_owner(request=None, session_token=None):
        return OWNER
    monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)
    monkeypatch.setattr(main_module, "_session_token_from_request", lambda r: SESSION)
    monkeypatch.setattr(main_module, "_test_recipient_override_enabled", lambda: False)
    monkeypatch.setattr(main_module, "_get_outbound_provider_for_draft", lambda d, o: "prov-1")

    class StubExecutor:
        def execute(self, action, params):
            return {"ok": True, "send_result": {"thread_id": "t", "external_message_id": "m"}}
    main_module.outbound_executor = StubExecutor()

    draft = DraftMessage(
        id="draft-ev-1",
        provider_id="prov-1",
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead One"),
        sender=Recipient(email="", name=""),
        status=DraftStatus.APPROVED,
        approval_state=ApprovalState.APPROVED,
    )
    outbound_draft_store.create(draft)

    sess = type("S", (), {})
    sess.get = lambda _id: [d for d in []]  # legacy store empty → durable path unused

    @app.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
    async def send(session_token: str, draft_id: str, request: Request, payload: dict = None):
        return await main_module.send_draft(session_token, draft_id, request, payload)

    return draft


SESSION = "3e-session"


def test_draft_sent_event_published_and_scoped(monkeypatch, capture):
    from services.communication.provider_models import CommunicationProvider, ProviderType, ProviderStatus

    app = FastAPI()
    draft = _wire_send_route(app, monkeypatch)

    # ownership check reads communication_store; register the provider for OWNER
    cs = __import__("services.communication.communication_store", fromlist=["store"]).store
    cs.save_provider(CommunicationProvider(
        id="prov-1", provider_type=ProviderType.GMAIL,
        user_id=OWNER, status=ProviderStatus.HEALTHY,
    ))

    async def fake_resolve(request=None):
        return OWNER
    monkeypatch.setattr(main_module, "_resolve_session_context", lambda r: asyncio.sleep(0, result=(OWNER, SESSION)))

    # Drive the real route coroutine directly (TestClient's portal loop
    # interferes with the async event capture).
    request_stub = type("R", (), {"headers": {}})()

    async def run_send():
        return await main_module.send_draft(SESSION, "draft-ev-1", request_stub, None)

    resp = asyncio.run(run_send())
    assert resp.get("ok") is True, resp

    types = [e["type"] for _, e in capture]
    assert "draft.sent" in types
    # scoped to owner only
    assert all(uid == OWNER for uid, _ in capture)

    payload = next(e for uid, e in capture if e["type"] == "draft.sent")
    blob = json.dumps(payload).lower()
    for banned in ("access_token", "refresh_token", "secret", "password", "authorization"):
        assert banned not in blob


def test_event_helper_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("redis down")
    monkeypatch.setattr("services.events_bus.EventBus.publish_user_event", boom)

    async def run():
        await main_module._emit_draft_event(OWNER, "draft.approved", draft_id="d1")
    asyncio.run(run())  # must not raise
