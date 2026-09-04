"""Outbound projections and durable send history are canonical state."""

import pytest

from services.outbound.outbound_models import DeliveryStatus, DraftMessage, Recipient, SendResult
from services.outbound.outbound_persistence import OutboundPersistence
from services.outbound.outbound_persistence import hydrate_draft_projection, projection_from_draft


def test_projection_round_trip_preserves_provider_envelope_and_versions():
    draft = DraftMessage(
        id="draft-1",
        provider_id="provider-1",
        external_draft_id="gmail-draft-1",
        gmail_thread_id="thread-1",
        conversation_id="conversation-1",
        workflow_id="campaign-1",
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="sender@example.com"),
        version=3,
    )
    canonical = {
        "id": draft.id,
        "campaign_id": "campaign-1",
        "subject": draft.subject,
        "body": draft.body,
        "status": "approved",
        "metadata": {"outbound_projection": projection_from_draft(draft)},
    }

    restored = hydrate_draft_projection(canonical)

    assert restored.external_draft_id == "gmail-draft-1"
    assert restored.gmail_thread_id == "thread-1"
    assert restored.recipient.email == "lead@example.com"
    assert restored.sender.email == "sender@example.com"
    assert restored.version == 3


def test_send_history_is_persisted_before_runtime_history(monkeypatch):
    persisted = []
    persistence = OutboundPersistence()
    monkeypatch.setattr(
        "services.outbound.outbound_persistence.persist_outbound_message",
        lambda item: persisted.append(item.id) or True,
    )

    item = persistence.record_send(
        SendResult(provider_id="provider-1", status=DeliveryStatus.SENT), subject="Sent",
    )

    assert persisted == [item.id]
    assert persistence.get_history() == [item]


def test_send_history_failure_is_not_exposed_as_runtime_success(monkeypatch):
    persistence = OutboundPersistence()
    monkeypatch.setattr(
        "services.outbound.outbound_persistence.persist_outbound_message",
        lambda _item: (_ for _ in ()).throw(RuntimeError("durable write failed")),
    )

    with pytest.raises(RuntimeError, match="durable write failed"):
        persistence.record_send(SendResult(provider_id="provider-1", status=DeliveryStatus.SENT))

    assert persistence.get_history() == []
