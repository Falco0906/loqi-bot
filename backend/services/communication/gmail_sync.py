"""Gmail Synchronizer — incremental sync engine for Gmail.

Manages cursor-based incremental sync.
After sync, automatically feeds into Conversation Intelligence pipeline.
"""

import logging
from typing import Optional

from services.communication.provider_models import (
    SyncResult,
    ProviderMessage,
    ProviderEventType,
)
from services.communication.communication_store import store
from services.communication.provider_events import emit_event
from services.communication.provider_normalizer import normalize_to_conversation_message
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.communication.gmail_provider import GmailProvider
from services.reply_intelligence import analyze_message
from services.conversation_memory import memory_store as conversation_memory

logger = logging.getLogger(__name__)


def sync_all(provider: GmailProvider) -> SyncResult:
    cursor = _load_cursor(provider)
    logger.info("[Sync] sync_all | provider=%s loaded_cursor=%s",
                provider._provider_id, cursor[:30] if cursor else "none")
    result = provider.sync(cursor=cursor)
    if result.cursor:
        logger.info("[Sync] sync_all | storing cursor=%s", result.cursor[:30] if result.cursor else "none")
        _store_cursor(provider, result.cursor)
    else:
        logger.warning("[Sync] sync_all | result.cursor is empty, NOT storing")
    return result


def sync_thread(provider: GmailProvider, thread_id: str) -> list[str]:
    messages = provider.fetch_thread(thread_id)
    if not messages:
        return []

    conversation_ids = []
    for msg in messages:
        cid = _process_provider_message(provider, msg)
        if cid:
            conversation_ids.append(cid)

    if conversation_ids:
        emit_event(
            ProviderEventType.THREAD_UPDATED,
            provider._provider_id,
            f"Thread {thread_id} updated: {len(conversation_ids)} conversations",
            {"thread_id": thread_id, "conversations": conversation_ids},
        )

    return list(set(conversation_ids))


def sync_since_cursor(provider: GmailProvider, cursor: str) -> SyncResult:
    result = provider.sync(cursor=cursor)
    if result.cursor and result.messages_synced > 0:
        _store_cursor(provider, result.cursor)
    return result


def _process_provider_message(
    provider: GmailProvider,
    provider_msg: ProviderMessage,
) -> Optional[str]:
    """Process a single provider message through the full intelligence pipeline.

    LOGGING: Every return path is logged explicitly.
    """

    external_id = provider_msg.external_id
    thread_id = provider_msg.thread_id
    subject = provider_msg.raw_headers.get("subject", "(no subject)")[:80]
    sender = provider_msg.raw_headers.get("from", "unknown")[:60]

    logger.info(
        "[Sync] _process_provider_message ENTER | ext_id=%s thread=%s subj=%s from=%s",
        external_id, thread_id, subject, sender,
    )

    # ── DEDUP CHECK ──
    already_seen = store.is_message_seen(external_id)
    logger.info(
        "[Sync]   DEDUP | is_message_seen(%s) = %s | seen_set_size=%d",
        external_id, already_seen, len(store.seen_messages()),
    )

    if already_seen:
        logger.info(
            "[Sync]   => RETURN None (duplicate) | ext_id=%s thread=%s subj=%s",
            external_id, thread_id, subject,
        )
        return None

    store.mark_message_seen(external_id)
    logger.info(
        "[Sync]   DEDUP | marked seen | ext_id=%s seen_set_size=%d",
        external_id, len(store.seen_messages()),
    )

    # ── THREAD MAPPING ──
    thread_mapping = store.get_thread_mapping(thread_id)
    logger.info(
        "[Sync]   THREAD | get_thread_mapping(%s) = %s",
        thread_id,
        thread_mapping.conversation_id if thread_mapping else None,
    )

    if thread_mapping:
        conversation_id = thread_mapping.conversation_id
        logger.info(
            "[Sync]   THREAD | using existing mapping | thread=%s -> conversation=%s",
            thread_id, conversation_id,
        )
    else:
        conversation_id = thread_id
        logger.info(
            "[Sync]   THREAD | no existing mapping | creating new with thread_id=%s as conversation_id",
            thread_id,
        )
        store.map_thread(
            external_thread_id=thread_id,
            conversation_id=conversation_id,
            provider_id=provider.provider_id,
            subject=subject,
        )
        logger.info(
            "[Sync]   THREAD | mapped | thread=%s -> conversation=%s",
            thread_id, conversation_id,
        )

    # ── NORMALIZE ──
    logger.info("[Sync]   NORMALIZE | calling normalize_to_conversation_message()")
    try:
        conversation_msg = normalize_to_conversation_message(provider_msg, conversation_id)
        logger.info(
            "[Sync]   NORMALIZE | OK | msg_id=%s sender=%s text_len=%d subj=%s",
            conversation_msg.id,
            conversation_msg.sender,
            len(conversation_msg.text),
            conversation_msg.subject[:60] if conversation_msg.subject else "(none)",
        )
    except Exception as e:
        logger.error("[Sync]   NORMALIZE | EXCEPTION: %s", e, exc_info=True)
        return None

    # ── ANALYZE MESSAGE (Conversation Intelligence) ──
    existing_memory = conversation_memory.get(conversation_id)
    logger.info(
        "[Sync]   ANALYZE | existing_memory=%s conversation_id=%s",
        "found" if existing_memory else "none",
        conversation_id,
    )

    try:
        intelligence, memory = analyze_message(
            message=conversation_msg,
            conversation_id=conversation_id,
            existing_memory=existing_memory,
        )
        logger.info(
            "[Sync]   ANALYZE | OK | intents=%d signals=%d stage=%s urgency=%s confidence=%d",
            len(intelligence.intents),
            len(intelligence.buying_signals),
            intelligence.conversation_stage.value,
            intelligence.urgency,
            intelligence.decision_confidence,
        )
    except Exception as e:
        logger.error("[Sync]   ANALYZE | EXCEPTION: %s", e, exc_info=True)
        return None

    # ── EMIT EVENT ──
    emit_event(
        ProviderEventType.MESSAGE_RECEIVED,
        provider._provider_id,
        f"Message analyzed: {conversation_msg.subject or '(no subject)'}",
        {
            "external_id": external_id,
            "thread_id": thread_id,
            "conversation_id": conversation_id,
            "intents": [i.intent.value for i in intelligence.intents],
            "stage": intelligence.conversation_stage.value,
        },
    )

    logger.info(
        "[Sync]   => RETURN conversation_id=%s | ext_id=%s thread=%s",
        conversation_id, external_id, thread_id,
    )
    return conversation_id


def _load_cursor(provider: GmailProvider) -> str:
    cursor = store.get_cursor(provider._provider_id)
    result = cursor.cursor if cursor else ""
    logger.info("[Sync] _load_cursor | provider=%s => %s",
                provider._provider_id, result[:30] if result else "(empty)")
    return result


def _store_cursor(provider: GmailProvider, cursor: str) -> None:
    logger.info("[Sync] _store_cursor | provider=%s cursor=%s",
                provider._provider_id, cursor[:30] if cursor else "(empty)")
    store.save_cursor(provider._provider_id, cursor)
