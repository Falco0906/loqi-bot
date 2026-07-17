"""Integration between outbound system and conversation management.

Hooks into the outbound send flow to create and update conversations.
Reuses existing outbound events and does not duplicate outbound history.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from services.conversations.conversation_models import (
    Conversation,
    ConversationStatus,
    ConversationThread,
    ConversationMessage,
    ConversationParticipant,
)
from services.conversations.conversation_store import conversation_store
from services.conversations.timeline import TimelineEventType, build_timeline_event
from services.conversations.state_machine import transition as state_transition
from services.conversations.classification import classifier_service, ReplyCategory
from services.outbound.outbound_events import OutboundEventType

logger = logging.getLogger(__name__)


def create_conversation_from_send(
    provider_id: str,
    provider_type: str,
    external_thread_id: str,
    external_message_id: str,
    subject: str,
    from_email: str,
    from_name: str,
    to_email: str,
    to_name: str,
    body: str,
    campaign_id: str = "",
    workflow_id: str = "",
    lead_id: str = "",
) -> Conversation:
    """Create a conversation after an outbound email is sent."""
    existing = conversation_store.find_by_external_thread(external_thread_id)
    if existing:
        logger.info("[conversations] Conversation already exists for thread %s: %s",
                     external_thread_id[:12], existing.conversation_id[:12])
        return existing

    convo = Conversation(
        provider_id=provider_id,
        provider_type=provider_type,
        external_thread_id=external_thread_id,
        subject=subject,
        status=ConversationStatus.SENT,
        participants=[
            ConversationParticipant(email=from_email, name=from_name, role="sender", provider_id=provider_id),
            ConversationParticipant(email=to_email, name=to_name, role="contact"),
        ],
        campaign_id=campaign_id,
        workflow_id=workflow_id,
        lead_id=lead_id,
        summary=None,
    )

    conversation_store.create_conversation(convo)

    thread = ConversationThread(
        conversation_id=convo.conversation_id,
        external_thread_id=external_thread_id,
        provider_id=provider_id,
        subject=subject,
    )
    conversation_store.add_thread(thread)

    msg = ConversationMessage(
        conversation_id=convo.conversation_id,
        thread_id=thread.thread_id,
        provider_id=provider_id,
        external_message_id=external_message_id,
        direction="outbound",
        from_email=from_email,
        from_name=from_name,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
    )
    conversation_store.add_message(msg)

    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=convo.conversation_id,
        event_type=TimelineEventType.EMAIL_SENT,
        title="Email sent",
        description=f"To: {to_name or to_email} | Subject: {subject[:80]}",
        metadata={
            "provider_id": provider_id,
            "external_message_id": external_message_id,
            "external_thread_id": external_thread_id,
        },
    ))

    logger.info("[conversations] Created conversation %s from sent email (thread=%s)",
                convo.conversation_id[:12], external_thread_id[:12])
    return convo


def handle_reply(
    conversation_id: str,
    external_message_id: str,
    from_email: str,
    from_name: str,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
) -> ConversationMessage:
    """Process an incoming reply to a conversation."""
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        logger.warning("[conversations] No conversation found for reply: %s", conversation_id[:12])
        thread = ConversationThread(conversation_id=conversation_id, subject=subject)
        conversation_store.add_thread(thread)
    else:
        threads = conversation_store.get_threads_for_conversation(conversation_id)
        thread = threads[0] if threads else ConversationThread(
            conversation_id=conversation_id, subject=subject
        )
        if thread.thread_id not in [t.thread_id for t in [thread]]:
            conversation_store.add_thread(thread)

    msg = ConversationMessage(
        conversation_id=conversation_id,
        thread_id=thread.thread_id,
        external_message_id=external_message_id,
        direction="inbound",
        from_email=from_email,
        from_name=from_name,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
    )
    conversation_store.add_message(msg)

    classification = classifier_service.classify(body, subject)
    msg.classification = {
        "category": classification.category.value,
        "confidence": classification.confidence,
        "source": classification.source,
    }

    if convo:
        convo.metadata["last_reply_category"] = classification.category.value
        if classification.category in (ReplyCategory.INTERESTED, ReplyCategory.MEETING_REQUEST):
            state_transition(convo.status, ConversationStatus.INTERESTED)
            convo.status = ConversationStatus.INTERESTED
        elif classification.category == ReplyCategory.BOUNCE:
            state_transition(convo.status, ConversationStatus.BOUNCED)
            convo.status = ConversationStatus.BOUNCED
        elif classification.category == ReplyCategory.NOT_INTERESTED:
            state_transition(convo.status, ConversationStatus.CLOSED_LOST)
            convo.status = ConversationStatus.CLOSED_LOST
        else:
            state_transition(convo.status, ConversationStatus.REPLIED)
            convo.status = ConversationStatus.REPLIED
        conversation_store.update_conversation(convo)

    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=TimelineEventType.REPLY_RECEIVED,
        title="Reply received",
        description=f"From: {from_name or from_email} | Category: {classification.category.value}",
        metadata={
            "classification": classification.category.value,
            "confidence": classification.confidence,
        },
    ))

    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=TimelineEventType.REPLY_CLASSIFIED,
        title=f"Classified as: {classification.category.value}",
        description=classification.explanation if classification.source == "ai" else "Rule-based classification",
        metadata={
            "category": classification.category.value,
            "confidence": classification.confidence,
            "source": classification.source,
        },
    ))

    logger.info("[conversations] Reply classified for %s: %s (%.2f)",
                conversation_id[:12], classification.category.value, classification.confidence)
    return msg


def handle_outbound_event(event_type: OutboundEventType, event_data: dict) -> None:
    """Handle outbound events to update conversation state.
    Called by the outbound event system when events are emitted.
    """
    conversation_id = event_data.get("conversation_id", "")
    if not conversation_id:
        return
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        return

    mapping = {
        OutboundEventType.MESSAGE_SENT: (ConversationStatus.SENT, TimelineEventType.EMAIL_SENT),
        OutboundEventType.MESSAGE_FAILED: (ConversationStatus.BOUNCED, TimelineEventType.EMAIL_BOUNCED),
        OutboundEventType.MESSAGE_SCHEDULED: (ConversationStatus.SENT, TimelineEventType.EMAIL_SENT),
    }
    if event_type in mapping:
        new_status, timeline_type = mapping[event_type]
        try:
            convo.status = state_transition(convo.status, new_status)
        except ValueError:
            pass
        conversation_store.add_timeline_event(build_timeline_event(
            conversation_id=conversation_id,
            event_type=timeline_type,
            title=f"Event: {event_type.value}",
            description=event_data.get("message", ""),
            metadata=event_data.get("metadata", {}),
        ))
        conversation_store.update_conversation(convo)
