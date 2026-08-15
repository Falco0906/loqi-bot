"""Deterministic Loqi communication boundary for inbound Gmail.

A message belongs to the Loqi Inbox only when it resolves to a trusted,
workspace-scoped relationship. Unrelated Gmail mail is ignored and never
persisted into conversation state.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_email(value: str) -> str:
    """Lower-case and strip an RFC-ish address to a deterministic identity."""
    header = (value or "").strip()
    match = re.match(r'^(?:"?([^"<>]*)"?\s*)?<([^>]+)>\s*$', header)
    email = match.group(2) if match else header
    return email.strip().lower()


def resolve_inbound_conversation(
    *,
    provider_id: str,
    provider_user_id: str,
    thread_id: str,
    sender_email: str,
) -> tuple[Optional[str], str]:
    """Resolve the Loqi conversation this inbound message belongs to.

    Returns ``(conversation_id, disposition)`` where disposition is one of:
      - "matched_thread": existing thread mapping -> existing conversation
      - "matched_conversation": no thread mapping, but a persisted conversation
        owns the external thread id
      - "matched_lead": sender is a workspace-owned lead with an existing
        Loqi conversation (never creates a new conversation here)
      - "ignored": no trusted Loqi relationship; message must not be persisted

    Workspace ownership always comes from the authenticated provider's
    ``provider_user_id`` — never from a payload or client.
    """
    from services.communication.communication_store import store as communication_store
    from services.conversations.conversation_store import conversation_store

    # 1. Strongest: existing provider thread mapping.
    mapping = communication_store.get_thread_mapping(thread_id)
    if mapping is not None:
        return mapping.conversation_id, "matched_thread"

    # 2. Persisted conversation owns this external thread id.
    existing = conversation_store.find_by_external_thread(thread_id)
    if existing is not None:
        return existing.conversation_id, "matched_conversation"

    # 3. Known workspace-owned lead with an existing Loqi conversation.
    lead_conversations = _conversations_for_known_lead(provider_user_id, sender_email)
    if len(lead_conversations) == 1:
        return lead_conversations[0], "matched_lead"
    if len(lead_conversations) > 1:
        # Ambiguous multi-lead match: never guess; drop the message.
        logger.info(
            "[inbound-filter] ambiguous lead match provider=%s email=%s matches=%d -> ignored",
            provider_id, sender_email, len(lead_conversations),
        )
        return None, "ignored"

    return None, "ignored"


def _conversations_for_known_lead(provider_user_id: str, sender_email: str) -> list[str]:
    """Conversations for workspace-owned leads with this exact email."""
    if not provider_user_id or not sender_email:
        return []
    try:
        import asyncio

        from services.conversations.conversation_store import conversation_store
        from services.persistence.launch.repositories import WorkspaceLeadRepository
        from services.workspace_state import _async_workspace

        workspace_id = asyncio.run(_async_workspace(provider_user_id))
        if not workspace_id:
            return []
        leads = asyncio.run(WorkspaceLeadRepository().list_by_email(workspace_id, sender_email))
        lead_ids = {str(lead.lead_id or "") for lead in leads if lead.lead_id}
        return [
            conversation.conversation_id
            for conversation in conversation_store.list_conversations(limit=10000)
            if conversation.lead_id and conversation.lead_id in lead_ids
        ]
    except Exception:
        logger.exception("[inbound-filter] lead resolution failed email=%s", sender_email)
        return []
