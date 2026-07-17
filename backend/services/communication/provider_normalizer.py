"""Provider Normalizer — converts provider-specific messages into ConversationMessage.

Provider modules NEVER call Copilot.
They ONLY produce normalized messages via this normalizer.

Conversation Intelligence never knows where a message came from.
"""

from typing import Optional
from services.communication.provider_models import (
    ProviderMessage,
    NormalizedMessage,
    MessageDirection,
)
from services.conversation_models import ConversationMessage


def normalize_to_conversation_message(
    provider_msg: ProviderMessage,
    conversation_id: str,
) -> ConversationMessage:
    """Convert a normalized provider message into a ConversationMessage.

    This is the boundary between the provider layer and Conversation Intelligence.
    After this, the message source is irrelevant.
    """
    body = _clean_body(provider_msg.raw_body)
    sender = _determine_sender(provider_msg)

    return ConversationMessage(
        id=provider_msg.id,
        text=body,
        sender=sender,
        timestamp=provider_msg.received_at,
        subject=provider_msg.raw_headers.get("subject", ""),
    )


def normalize_message(provider_msg: ProviderMessage, conversation_id: str) -> NormalizedMessage:
    """Create a NormalizedMessage from a raw provider message."""
    body = _clean_body(provider_msg.raw_body)
    sender = provider_msg.raw_headers.get("from", "")
    recipient = provider_msg.raw_headers.get("to", "")
    subject = provider_msg.raw_headers.get("subject", "")

    return NormalizedMessage(
        conversation_id=conversation_id,
        message_id=provider_msg.id,
        direction=provider_msg.direction,
        sender=sender,
        recipient=recipient,
        subject=subject,
        body=body,
        timestamp=provider_msg.received_at,
        provider=provider_msg.provider_id,
        provider_metadata=provider_msg.provider_metadata,
    )


def _clean_body(raw_body: str) -> str:
    """Strip HTML and trim whitespace."""
    if not raw_body:
        return ""
    if raw_body.startswith("<") or "&lt;" in raw_body or "&gt;" in raw_body:
        import re
        cleaned = re.sub(r"<[^>]+>", "", raw_body)
        cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&")
        cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">")
        cleaned = cleaned.replace("&quot;", '"').replace("&#39;", "'")
        return " ".join(cleaned.split()).strip()
    return raw_body.strip()


def _determine_sender(provider_msg: ProviderMessage) -> str:
    """Determine the sender type based on direction."""
    if provider_msg.direction == MessageDirection.INCOMING:
        return "lead"
    return "agent"
