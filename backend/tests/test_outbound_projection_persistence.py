"""Outbound projections and durable send history are canonical state."""

from services.outbound.outbound_models import DraftMessage, Recipient
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
