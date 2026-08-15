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
    owner_id: str = "",
) -> Conversation:
    """Create a conversation after an outbound email is sent.

    ``owner_id`` is the trusted, server-derived workspace owner that the
    conversation belongs to (PR10.8.3.1 fail-closed tenant isolation). It is
    used for ownership checks; it is never supplied by the request body.
    """
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
        owner_id=owner_id,
        summary=None,
    )

    conversation_store.create_conversation(convo)

    # Map the external thread in the communication store too, so a real
    # Gmail reply (sync/webhook) resolves this conversation instead of
    # falling back to a thread-id-keyed orphan.
    try:
        from services.communication.communication_store import store as communication_store
        communication_store.map_thread(
            external_thread_id=external_thread_id,
            conversation_id=convo.conversation_id,
            provider_id=provider_id,
            subject=subject,
        )
    except Exception as e:
        logger.warning("[conversations] Thread mapping failed for %s: %s", external_thread_id[:12], e)

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
    timestamp: Optional[datetime] = None,
) -> Optional[ConversationMessage]:
    """Process an incoming reply to a conversation.

    ``timestamp`` preserves the original message time (e.g. synthetic
    replies replayed with their recorded arrival time); defaults to now.

    Idempotent by ``external_message_id``: re-processing the same provider
    message (e.g. sync and simulator firing on the same thread) never adds
    a second message or duplicate timeline events.

    Returns None when the conversation does not exist — the reply is
    dropped rather than creating orphan thread/message state.
    """
    convo = conversation_store.get_conversation(conversation_id)
    if external_message_id:
        already = next(
            (m for m in conversation_store.get_messages_for_conversation(conversation_id)
             if m.external_message_id == external_message_id),
            None,
        )
        if already is not None:
            logger.info(
                "[conversations] Reply %s already processed for %s — skipping",
                external_message_id[:12], conversation_id[:12],
            )
            return already
    if not convo:
        logger.warning(
            "[conversations] Reply dropped: conversation %s not found "
            "(no orphan thread/message state created)",
            conversation_id[:12],
        )
        return None

    threads = conversation_store.get_threads_for_conversation(conversation_id)
    thread = threads[0] if threads else ConversationThread(
        conversation_id=conversation_id, subject=subject
    )

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
        sent_at=timestamp or datetime.now(timezone.utc),
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
        try:
            if classification.category in (ReplyCategory.INTERESTED, ReplyCategory.MEETING_REQUEST):
                convo.status = state_transition(convo.status, ConversationStatus.INTERESTED)
            elif classification.category == ReplyCategory.BOUNCE:
                convo.status = state_transition(convo.status, ConversationStatus.BOUNCED)
            elif classification.category == ReplyCategory.NOT_INTERESTED:
                convo.status = state_transition(convo.status, ConversationStatus.CLOSED_LOST)
            elif classification.category == ReplyCategory.OUT_OF_OFFICE:
                # Auto-archive: OOO auto-replies need no judgment. Terminal
                # state stands in for archiving until an ARCHIVED status exists.
                convo.status = state_transition(convo.status, ConversationStatus.CLOSED_LOST)
            else:
                convo.status = state_transition(convo.status, ConversationStatus.REPLIED)
        except ValueError:
            pass
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
