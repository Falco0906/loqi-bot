"""Outbound executor tests over durable, hydrated request boundaries."""
from __future__ import annotations

import pytest

from services.communication.gmail_auth_failure import GmailReauthRequired
from services.outbound import outbound_registry
from services.outbound.outbound_base import OutboundProviderBase
from services.outbound.outbound_executor import OutboundExecutor
from services.outbound.outbound_models import DraftMessage, DraftStatus, Recipient, SendRequest, SendResult, DeliveryStatus


class _Provider(OutboundProviderBase):
    provider_type = "outbound-test"

    def create_draft(self, draft):
        return draft

    def update_draft(self, draft):
        return draft

    def delete_draft(self, draft_id):
        return True

    def send(self, request):
        return SendResult(
            provider_id=request.provider_id,
            external_message_id="message-1",
            thread_id="thread-1",
            draft_id=request.draft_id,
            status=DeliveryStatus.SENT,
        )

    def schedule(self, draft, send_at):
        return None

    def cancel_schedule(self, schedule_id):
        return True

    def get_status(self, message_id):
        return "sent"

    def fetch_draft(self, draft_id):
        return None

    def list_drafts(self):
        return []


@pytest.fixture
def executor(monkeypatch):
    outbound_registry.register_instance("provider-1", _Provider())
    persisted = []
    monkeypatch.setattr(
        "services.outbound.outbound_executor.persist_outbound_message",
        lambda item: persisted.append(item) or True,
    )
    yield OutboundExecutor(), persisted
    outbound_registry.remove_instance("provider-1")


def _draft(*, external_draft_id="gmail-draft-1"):
    return DraftMessage(
        id="draft-1",
        provider_id="provider-1",
        external_draft_id=external_draft_id,
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="me@example.com", name="Me"),
        status=DraftStatus.APPROVED,
    )


def test_send_hydrated_draft_uses_provider_draft_and_persists_history(executor):
    service, persisted = executor

    result = service.send_hydrated_draft(_draft(), provider_id="provider-1")

    assert result["ok"] is True
    assert result["send_result"]["external_message_id"] == "message-1"
    assert persisted[0].draft_id == "gmail-draft-1"
    assert persisted[0].recipient.email == "lead@example.com"


def test_recipient_override_uses_raw_envelope_without_mutating_draft(executor):
    service, persisted = executor
    draft = _draft()

    result = service.send_hydrated_draft(
        draft,
        provider_id="provider-1",
        recipient_override=Recipient(email="test@example.com", name="Test"),
    )

    assert result["ok"] is True
    assert draft.recipient.email == "lead@example.com"
    assert persisted[0].draft_id == ""
    assert persisted[0].recipient.email == "test@example.com"


def test_raw_conversation_request_is_sent_without_draft_lookup(executor):
    service, persisted = executor
    request = SendRequest(
        provider_id="provider-1",
        subject="Re: Subject",
        body="Reply",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="me@example.com", name="Me"),
        conversation_id="conversation-1",
    )

    result = service.send_request(request)

    assert result["ok"] is True
    assert persisted[0].conversation_id == "conversation-1"


def test_history_persistence_failure_is_not_reported_as_send_success(executor, monkeypatch):
    service, _persisted = executor
    monkeypatch.setattr(
        "services.outbound.outbound_executor.persist_outbound_message",
        lambda _item: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    result = service.send_hydrated_draft(_draft(), provider_id="provider-1")

    assert result["ok"] is False
    assert result["error"] == "Email send history could not be persisted"
    # Gmail already accepted this message; callers must retain the durable
    # in-flight send claim rather than issue a duplicate retry.
    assert result["provider_accepted"] is True
    assert result["retry_safe"] is False


def test_reauth_required_is_actionable_and_safe_to_release_send_claim(executor, monkeypatch):
    service, persisted = executor
    monkeypatch.setattr(
        "services.outbound.outbound_executor.registry_send",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            GmailReauthRequired("Gmail account requires re-authentication")
        ),
    )

    result = service.send_hydrated_draft(_draft(), provider_id="provider-1")

    assert result == {
        "ok": False,
        "error": "Gmail authorization expired. Reconnect Gmail to send.",
        "retry_safe": True,
    }
    assert persisted == []
