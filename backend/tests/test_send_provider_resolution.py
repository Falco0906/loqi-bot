"""Regression tests: owner-scoped Gmail provider resolution for Send Now.

Covers:
  A. Draft references valid current provider -> uses it.
  B. Draft references stale/nonexistent provider -> resolves current Gmail
     provider for the same owner and sends through it.
  C. Draft references another user's provider -> must NOT use it.
  D. No current Gmail provider -> clean failure.
  E. Existing valid provider behavior unchanged.
  F. Backend restart does not break the fallback.
  G. Reconnecting Gmail and then sending an old approved draft works through
     the newly connected provider.
  H. GmailOutbound 401 must surface ok=false from the send endpoint.
"""
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.outbound.outbound_models import (
    DraftMessage,
    DraftStatus,
    ApprovalState,
    Recipient,
)
from services.outbound import outbound_registry
from services.communication import provider_registry as comm_registry
from services.outbound.draft_store import draft_store as outbound_draft_store
from services.communication.provider_registry import disconnect_provider as registry_disconnect

OWNER = "owner-0000-0000-0000-000000000001"
OTHER = "owner-0000-0000-0000-000000000002"
SESSION = "session-under-test"


class FakeComm:
    def __init__(self, user_id, email="", connected=True):
        self._user_id = user_id
        self._mailbox_email = email
        self._connected = connected

    def disconnect(self):
        self._connected = False


class FakeOutbound:
    provider_type = "gmail"

    def __init__(self, provider_id):
        self._provider_id = provider_id


def register_provider(provider_id: str, user_id: str, email: str = "", connected: bool = True) -> str:
    pid = provider_id or str(uuid.uuid4())
    comm_registry.register_instance(pid, FakeComm(user_id=user_id, email=email, connected=connected))
    outbound_registry.register_instance(pid, FakeOutbound(pid))
    return pid


def clear_providers() -> None:
    comm_registry._instances.clear()
    outbound_registry._instances.clear()


def make_draft(draft_id: str, provider_id: str) -> DraftMessage:
    draft = DraftMessage(
        id=draft_id,
        provider_id=provider_id,
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="", name=""),
        status=DraftStatus.APPROVED,
        approval_state=ApprovalState.APPROVED,
    )
    outbound_draft_store.create(draft)
    return draft


@pytest.fixture(autouse=True)
def clean_registries():
    clear_providers()
    outbound_draft_store.clear()
    yield
    clear_providers()
    outbound_draft_store.clear()


import main as main_module  # noqa: E402


class TestProviderResolution:
    def test_A_valid_current_provider_is_used(self):
        stored = register_provider("prov-valid", OWNER, email="a@x.com")
        draft = make_draft("draft-a", stored)
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == stored
        assert draft.provider_id == stored

    def test_E_stored_provider_unchanged_when_valid(self):
        stored = register_provider("prov-valid", OWNER, email="a@x.com")
        draft = make_draft("draft-e", stored)
        main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert draft.provider_id == stored
        assert outbound_draft_store.get("draft-e").provider_id == stored

    def test_B_stale_provider_falls_back_to_owners_current(self):
        current = register_provider("prov-current", OWNER, email="a@x.com")
        draft = make_draft("draft-b", "prov-stale-gone")
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == current
        assert draft.provider_id == current
        assert outbound_draft_store.get("draft-b").provider_id == current

    def test_C_other_users_provider_is_not_used(self):
        other_prov = register_provider("prov-other", OTHER, email="other@x.com")
        own_prov = register_provider("prov-own", OWNER, email="a@x.com")
        draft = make_draft("draft-c", other_prov)
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == own_prov
        assert resolved != other_prov
        assert draft.provider_id == own_prov

    def test_C2_disconnected_stored_provider_not_used(self):
        stale = register_provider("prov-stale", OWNER, email="a@x.com")
        registry_disconnect(stale)  # removes comm instance; outbound instance survives
        current = register_provider("prov-current", OWNER, email="b@x.com")
        draft = make_draft("draft-c2", stale)
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == current
        assert draft.provider_id == current

    def test_D_no_current_provider_is_clean_failure(self):
        register_provider("prov-other", OTHER, email="other@x.com")
        draft = make_draft("draft-d", "prov-stale-gone")
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == ""

    def test_F_restart_hydration_fix(self):
        other_prov = register_provider("prov-other", OTHER, email="other@x.com")
        own_prov = register_provider("prov-own", OWNER, email="a@x.com")
        durable_like = {
            "id": "draft-f",
            "status": "approved",
            "campaign_id": "cmp-f",
            "lead": {"email": "lead@example.com", "name": "Lead"},
            "subject": "Subject",
            "text": "Body",
        }
        main_module._sync_draft_to_outbound(durable_like, SESSION)
        synced = outbound_draft_store.get("draft-f")
        assert synced.provider_id == other_prov  # sync pins first registered gmail provider
        resolved = main_module._get_outbound_provider_for_draft(synced, OWNER)
        assert resolved == own_prov
        assert resolved != other_prov
        assert synced.provider_id == own_prov

    def test_G_reconnect_resolves_new_provider(self):
        old = register_provider("prov-old", OWNER, email="a@x.com")
        draft = make_draft("draft-g", old)
        registry_disconnect(old)
        new = register_provider("prov-new", OWNER, email="b@x.com")
        resolved = main_module._get_outbound_provider_for_draft(draft, OWNER)
        assert resolved == new
        assert draft.provider_id == new
        assert outbound_draft_store.get("draft-g").provider_id == new


class TestSendEndpointResolution:
    @pytest.fixture(scope="module")
    def env(self):
        from fastapi.testclient import TestClient
        from services.identity import api as identity_api
        with TestClient(main_module.app) as client:
            owner = "7de769b4-d450-4033-95ab-2718129f905a"

            def mint_token():
                import asyncio
                svc = identity_api._get_service()
                session, _ = asyncio.run(
                    svc._session_svc.create_session(user_id=owner, organization_id="")
                )
                return session.id

            yield client, owner, mint_token

    def _send(self, client, draft_id, token):
        return client.post(
            f"/api/web/session/ANY/drafts/{draft_id}/send",
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_G_endpoint_sends_via_new_provider_after_reconnect(self, env):
        client, owner, mint = env
        old = register_provider("prov-old", owner, email="a@x.com")
        draft = make_draft("draft-endpoint-g", old)
        registry_disconnect(old)
        new = register_provider("prov-new", owner, email="b@x.com")

        captured = {}

        class StubExecutor:
            def execute(self, action, params):
                captured.update(params)
                return {"ok": True, "send_result": {"thread_id": "t", "external_message_id": "m"}}

        main_module.outbound_executor = StubExecutor()
        r = self._send(client, draft.id, mint())
        body = r.json()
        assert r.status_code == 200 and body.get("ok") is True
        assert captured.get("provider_id") == new
        assert outbound_draft_store.get(draft.id).provider_id == new

    def test_D_endpoint_no_provider_clean_failure(self, env):
        client, _, mint = env
        draft = make_draft("draft-endpoint-d", "prov-stale-gone")

        class ExplodingExecutor:
            def execute(self, action, params):
                raise AssertionError("executor must not run without a provider")

        main_module.outbound_executor = ExplodingExecutor()
        r = self._send(client, draft.id, mint())
        body = r.json()
        assert r.status_code == 200
        assert body.get("ok") is False
        assert body.get("error") == "No Gmail outbound provider registered"

    def test_H_gmail_401_surfaces_ok_false(self, env):
        client, owner, mint = env
        register_provider("prov-valid", owner, email="a@x.com")
        draft = make_draft("draft-endpoint-h", "prov-valid")

        class FailingExecutor:
            def execute(self, action, params):
                return {
                    "ok": False,
                    "send_result": {
                        "ok": False,
                        "status": "failed",
                        "error": '{"error": {"code": 401, "message": "UNAUTHENTICATED"}}',
                    },
                }

        main_module.outbound_executor = FailingExecutor()
        r = self._send(client, draft.id, mint())
        body = r.json()
        assert r.status_code == 200
        assert body.get("ok") is False
        assert outbound_draft_store.get(draft.id).status == DraftStatus.APPROVED
