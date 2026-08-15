"""PR8.1 — test-only recipient override tests."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.outbound.draft_store import draft_store as outbound_draft_store
from services.outbound.outbound_models import DraftMessage, Recipient

import main as main_module  # noqa: E402
from tests.conftest import _AuthTestClient  # noqa: E402


def _draft() -> DraftMessage:
    draft = DraftMessage(
        id=f"draft-{uuid.uuid4().hex[:8]}",
        provider_id="prov-1",
        subject="Outreach",
        body="Hello",
        recipient=Recipient(email="lead@acme.com", name="Acme Lead"),
        sender=Recipient(email="owner@loqi.com", name="Owner"),
        workflow_id="campaign-1",
    )
    outbound_draft_store.create(draft)
    return draft


async def async_fake_owner(request, session_token: str) -> str:
    return "owner-1"


@pytest.fixture(autouse=True)
def _clean_store():
    outbound_draft_store._drafts.clear()
    yield
    outbound_draft_store._drafts.clear()


class TestTestRecipientOverride:
    def test_override_is_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", raising=False)
        assert main_module._test_recipient_override_enabled() is False

    def test_enabled_flag_turns_override_on(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        assert main_module._test_recipient_override_enabled() is True

    def test_override_rejected_when_disabled(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "false")
        draft = _draft()
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.send_draft(
                "session", draft.id, MagicMock(),
                main_module.SendDraftRequest(test_recipient="test@example.com"),
            ))
        assert getattr(exc.value, "status_code", None) == 403

    def test_override_changes_only_recipient_and_preserves_identity(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        draft = _draft()
        captured = {}

        def fake_execute(action_type, params):
            captured["params"] = params
            return {
                "ok": True,
                "send_result": {
                    "id": "ext-1",
                    "external_message_id": "ext-1",
                    "thread_id": "thread-1",
                    "status": "sent",
                },
            }

        monkeypatch.setattr(main_module, "outbound_executor", MagicMock(execute=fake_execute))
        monkeypatch.setattr(main_module, "_get_outbound_provider_for_draft", lambda draft, owner_id="": "prov-1")
        monkeypatch.setattr(main_module, "_workspace_owner", async_fake_owner)
        monkeypatch.setattr("services.conversations.integration.create_conversation_from_send", lambda **kwargs: MagicMock())
        monkeypatch.setattr(main_module, "simulate_reply", lambda **kwargs: None)
        monkeypatch.setattr(main_module, "publish", lambda *args, **kwargs: None)
        monkeypatch.setattr(main_module, "_get_feedback", lambda: MagicMock())
        monkeypatch.setattr(main_module, "record_campaign_created", lambda *args, **kwargs: None)

        result = asyncio.run(main_module.send_draft(
            "session", draft.id, MagicMock(),
            main_module.SendDraftRequest(test_recipient="test@example.com", test_recipient_name="Test Recipient"),
        ))

        assert result["ok"] is True
        params = captured["params"]
        assert params["recipient"]["email"] == "test@example.com"
        assert params["recipient"]["name"] == "Test Recipient"
        assert params["thread_id"] == draft.thread_id
        assert params["conversation_id"] == draft.conversation_id
        assert params["workflow_id"] == "campaign-1"
        # Lead identity remains unchanged.
        stored = outbound_draft_store.get(draft.id)
        assert stored.recipient.email == "lead@acme.com"
        assert stored.workflow_id == "campaign-1"

    def test_normal_recipient_unchanged_without_override(self, monkeypatch):
        draft = _draft()
        captured = {}

        def fake_execute(action_type, params):
            captured["params"] = params
            return {
                "ok": True,
                "send_result": {
                    "id": "ext-1",
                    "external_message_id": "ext-1",
                    "thread_id": "thread-1",
                    "status": "sent",
                },
            }

        monkeypatch.setattr(main_module, "outbound_executor", MagicMock(execute=fake_execute))
        monkeypatch.setattr(main_module, "_get_outbound_provider_for_draft", lambda draft, owner_id="": "prov-1")
        monkeypatch.setattr(main_module, "_workspace_owner", async_fake_owner)
        monkeypatch.setattr("services.conversations.integration.create_conversation_from_send", lambda **kwargs: MagicMock())
        monkeypatch.setattr(main_module, "simulate_reply", lambda **kwargs: None)
        monkeypatch.setattr(main_module, "publish", lambda *args, **kwargs: None)
        monkeypatch.setattr(main_module, "_get_feedback", lambda: MagicMock())
        monkeypatch.setattr(main_module, "record_campaign_created", lambda *args, **kwargs: None)

        result = asyncio.run(main_module.send_draft("session", draft.id, MagicMock()))
        assert result["ok"] is True
        assert captured["params"]["recipient"]["email"] == "lead@acme.com"


class TestExecutorEnvelope:
    def test_overridden_recipient_reaches_provider_raw_path(self, monkeypatch):
        """The executor must rebuild the request from live params when the
        envelope recipient differs from the stored draft, so Gmail receives
        tofu9262@gmail.com instead of sending the persisted Gmail draft."""
        from services.outbound.outbound_executor import OutboundExecutor

        draft = _draft()
        draft.external_draft_id = "gmail-draft-1"
        captured = {}

        def fake_registry_send(provider_id, request):
            captured["request"] = request
            from services.outbound.outbound_models import SendResult
            return SendResult(
                provider_id=provider_id,
                external_message_id="ext-1",
                thread_id="thread-1",
                draft_id=request.draft_id,
            )

        monkeypatch.setattr(
            "services.outbound.outbound_executor.registry_send",
            fake_registry_send,
        )
        executor = OutboundExecutor()
        result = executor.execute("send_reply", {
            "provider_id": "prov-1",
            "draft_id": draft.id,
            "conversation_id": draft.conversation_id,
            "thread_id": draft.thread_id,
            "workflow_id": draft.workflow_id,
            "subject": draft.subject,
            "body": draft.body,
            "recipient": {"email": "tofu9262@gmail.com", "name": "Test Recipient"},
            "sender": {"email": draft.sender.email, "name": draft.sender.name},
        })

        assert result["ok"] is True
        request = captured["request"]
        assert request.recipient.email == "tofu9262@gmail.com"
        # Empty draft_id forces the Gmail raw-message path with the new envelope.
        assert request.draft_id == ""
        assert request.thread_id == draft.thread_id

    def test_normal_envelope_still_sends_persisted_gmail_draft(self, monkeypatch):
        from services.outbound.outbound_executor import OutboundExecutor

        draft = _draft()
        draft.external_draft_id = "gmail-draft-1"
        captured = {}

        def fake_registry_send(provider_id, request):
            captured["request"] = request
            from services.outbound.outbound_models import SendResult
            return SendResult(provider_id=provider_id, external_message_id="ext-1")

        monkeypatch.setattr(
            "services.outbound.outbound_executor.registry_send",
            fake_registry_send,
        )
        executor = OutboundExecutor()
        executor.execute("send_reply", {
            "provider_id": "prov-1",
            "draft_id": draft.id,
            "conversation_id": draft.conversation_id,
            "thread_id": draft.thread_id,
            "workflow_id": draft.workflow_id,
            "subject": draft.subject,
            "body": draft.body,
            "recipient": {"email": draft.recipient.email, "name": draft.recipient.name},
            "sender": {"email": draft.sender.email, "name": draft.sender.name},
        })

        request = captured["request"]
        assert request.recipient.email == "lead@acme.com"
        assert request.draft_id == "gmail-draft-1"


class TestSendDraftRoute:
    """Route-level tests against the real POST /drafts/{id}/send endpoint,
    using the exact request shape the Draft Review frontend sends."""

    def _register_fake_provider(self, captured):
        from services.outbound import outbound_registry
        from services.outbound.outbound_models import SendResult

        class FakeGmailOutbound:
            provider_type = "gmail"

            def send(self, request):
                captured["request"] = request
                return SendResult(
                    provider_id=request.provider_id,
                    external_message_id="ext-route",
                    thread_id="thread-route",
                    draft_id=request.draft_id,
                )

        fake = FakeGmailOutbound()
        outbound_registry.register_instance("prov-1", fake)
        return fake

    def _patch_route_deps(self, monkeypatch):
        monkeypatch.setattr(main_module, "_workspace_owner", async_fake_owner)
        monkeypatch.setattr(main_module, "_get_outbound_provider_for_draft", lambda draft, owner_id="": "prov-1")
        monkeypatch.setattr("services.conversations.integration.create_conversation_from_send", lambda **kwargs: MagicMock())
        monkeypatch.setattr(main_module, "simulate_reply", lambda **kwargs: None)
        monkeypatch.setattr(main_module, "publish", lambda *args, **kwargs: None)
        monkeypatch.setattr(main_module, "_get_feedback", lambda: MagicMock())
        monkeypatch.setattr(main_module, "record_campaign_created", lambda *args, **kwargs: None)

    def test_route_test_recipient_reaches_final_envelope(self, monkeypatch):
        from services.outbound import outbound_registry

        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        draft = _draft()
        draft.external_draft_id = "gmail-draft-1"
        captured = {}
        self._register_fake_provider(captured)
        self._patch_route_deps(monkeypatch)
        client = _AuthTestClient(main_module.app)

        response = client.post(
            f"/api/web/session/session-1/drafts/{draft.id}/send",
            json={
                "test_recipient": "tofu9262@gmail.com",
                "test_recipient_name": "Test Recipient",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        request = captured["request"]
        assert request.recipient.email == "tofu9262@gmail.com"
        assert request.draft_id == ""
        assert request.thread_id == draft.thread_id
        # Persisted draft recipient/identity unchanged.
        stored = outbound_draft_store.get(draft.id)
        assert stored.recipient.email == "lead@acme.com"
        assert stored.external_draft_id == "gmail-draft-1"
        outbound_registry._instances.pop("prov-1", None)

    def test_route_no_override_keeps_persisted_gmail_draft(self, monkeypatch):
        from services.outbound import outbound_registry

        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "false")
        draft = _draft()
        draft.external_draft_id = "gmail-draft-1"
        captured = {}
        self._register_fake_provider(captured)
        self._patch_route_deps(monkeypatch)
        client = _AuthTestClient(main_module.app)

        response = client.post(
            f"/api/web/session/session-1/drafts/{draft.id}/send",
            json={},
        )

        assert response.status_code == 200
        request = captured["request"]
        assert request.recipient.email == "lead@acme.com"
        assert request.draft_id == "gmail-draft-1"
        outbound_registry._instances.pop("prov-1", None)

    def test_route_test_recipient_rejected_when_disabled(self, monkeypatch):

        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "false")
        draft = _draft()
        self._patch_route_deps(monkeypatch)
        client = _AuthTestClient(main_module.app)

        response = client.post(
            f"/api/web/session/session-1/drafts/{draft.id}/send",
            json={"test_recipient": "tofu9262@gmail.com", "test_recipient_name": "Test Recipient"},
        )

        assert response.status_code == 403
