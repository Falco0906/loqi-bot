"""Background Gmail inbox sync and follow-up readiness maintenance."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from services.communication import provider_registry
from services.communication.gmail_sync import sync_all
from services.communication.provider_models import ProviderType
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.followup_planner import followup_planner_service
from services.conversations.state_machine import transition
from services.conversations.timeline import TimelineEventType, build_timeline_event

logger = logging.getLogger(__name__)


class InboxSyncEngine:
    """One process-local loop over the existing provider sync implementation."""

    def __init__(self, interval_seconds: float | None = None) -> None:
        self.interval_seconds = interval_seconds or float(os.getenv("INBOX_SYNC_INTERVAL_SECONDS", "120"))
        self._task: asyncio.Task | None = None
        self._sync_lock = asyncio.Lock()
        self._webhook_registered = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._register_webhook()
        self._task = asyncio.create_task(self._run(), name="loqi-inbox-sync")
        logger.info("[inbox-sync] engine started interval_seconds=%s", self.interval_seconds)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("[inbox-sync] engine stopped")

    async def sync_once(self, provider_ids: list[str] | None = None) -> dict:
        async with self._sync_lock:
            started = datetime.now(timezone.utc)
            providers = provider_registry.list_providers()
            if provider_ids is not None:
                providers = {pid: providers[pid] for pid in provider_ids if pid in providers}
            gmail_providers = {
                pid: provider for pid, provider in providers.items()
                if getattr(provider, "provider_type", None) in {ProviderType.GMAIL, "gmail"}
                and bool(getattr(provider, "_connected", True))
            }
            logger.info("[inbox-sync] cycle start providers=%d", len(gmail_providers))
            results = []
            for provider_id, provider in gmail_providers.items():
                try:
                    result = await asyncio.to_thread(sync_all, provider)
                    results.append(result)
                    logger.info(
                        "[inbox-sync] provider=%s complete threads=%d messages=%d conversations=%d errors=%d duration_ms=%d",
                        provider_id, result.threads_synced, result.messages_synced,
                        result.new_conversations, len(result.errors), result.duration_ms,
                    )
                except Exception:
                    logger.exception("[inbox-sync] provider=%s failed; continuing", provider_id)
            ready = await asyncio.to_thread(maintain_follow_up_readiness)
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            logger.info("[inbox-sync] cycle end providers=%d follow_up_ready=%d duration_ms=%d", len(gmail_providers), ready, elapsed)
            return {"providers": len(gmail_providers), "results": results, "follow_up_ready": ready}

    async def trigger_provider_sync(self, provider_id: str) -> None:
        try:
            await self.sync_once([provider_id])
        except Exception:
            logger.exception("[inbox-sync] webhook-triggered sync failed provider=%s", provider_id)

    async def _run(self) -> None:
        try:
            while True:
                try:
                    await self.sync_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("[inbox-sync] cycle failed; loop continues")
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            raise

    def _register_webhook(self) -> None:
        if self._webhook_registered:
            return
        try:
            from services.communication.gmail_webhooks import register_handler

            def on_notification(provider_id: str, _payload: dict) -> None:
                try:
                    asyncio.get_running_loop().create_task(self.trigger_provider_sync(provider_id))
                except RuntimeError:
                    logger.warning("[inbox-sync] webhook ignored: no running event loop provider=%s", provider_id)

            register_handler("on_notification", on_notification)
            self._webhook_registered = True
        except Exception:
            logger.exception("[inbox-sync] webhook registration failed; polling remains active")


def maintain_follow_up_readiness() -> int:
    """Promote due conversations to FOLLOW_UP_READY without sending anything."""
    transitioned = 0
    for conversation in conversation_store.list_conversations(limit=10000):
        if conversation.status == ConversationStatus.FOLLOW_UP_SENT:
            continue
        try:
            if conversation.status == ConversationStatus.FOLLOW_UP_PENDING:
                _mark_ready(conversation)
                transitioned += 1
                continue
            if conversation.status not in {
                ConversationStatus.SENT,
                ConversationStatus.DELIVERED,
                ConversationStatus.OPENED,
            }:
                continue
            plan = followup_planner_service.plan(conversation)
            if not plan.should_follow_up:
                continue
            conversation.status = transition(conversation.status, ConversationStatus.FOLLOW_UP_PENDING)
            conversation_store.update_conversation(conversation)
            _mark_ready(conversation, plan.reason)
            transitioned += 1
        except Exception:
            logger.exception("[inbox-sync] follow-up readiness failed conversation=%s", conversation.conversation_id)
    return transitioned


def _mark_ready(conversation, reason: str = "") -> None:
    if conversation.status != ConversationStatus.FOLLOW_UP_READY:
        conversation.status = transition(conversation.status, ConversationStatus.FOLLOW_UP_READY)
        conversation_store.update_conversation(conversation)
    if not any(event.event_type == TimelineEventType.FOLLOW_UP_READY for event in conversation_store.get_timeline(conversation.conversation_id)):
        conversation_store.add_timeline_event(build_timeline_event(
            conversation_id=conversation.conversation_id,
            event_type=TimelineEventType.FOLLOW_UP_READY,
            title="Follow-up ready",
            description=reason or "Conversation is ready for human follow-up review.",
            metadata={"automated_send": False},
        ))


inbox_sync_engine = InboxSyncEngine()
