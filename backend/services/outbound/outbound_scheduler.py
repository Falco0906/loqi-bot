"""Outbound Scheduler — sends scheduled drafts when their time arrives.

Checks every 15 seconds for due scheduled messages, dispatches them
through the executor, and updates status.
"""
import asyncio
import logging
from datetime import datetime, timezone

from services.outbound.draft_store import draft_store
from services.outbound.outbound_models import DraftStatus
from services.outbound.outbound_executor import executor as outbound_executor
from services.outbound.outbound_events import emit_event, OutboundEventType
from services.outbound.outbound_registry import (
    schedule as registry_schedule,
    cancel_schedule as registry_cancel_schedule,
    list_providers as registry_list_providers,
    get_provider as registry_get_provider,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 15


class OutboundScheduler:
    def __init__(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        loop = asyncio.get_running_loop()
        logger.info("[OutboundScheduler] started (poll every %ds)", POLL_INTERVAL)
        while self._running:
            try:
                await loop.run_in_executor(None, self._tick)
            except Exception as e:
                logger.error("[OutboundScheduler] tick error: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        all_drafts = draft_store.list_all()
        for draft in all_drafts.drafts:
            if draft.status != DraftStatus.SCHEDULED:
                continue
            if draft.metadata and "send_at" in draft.metadata:
                send_at = draft.metadata["send_at"]
                if send_at <= now:
                    self._execute_scheduled(draft.id, draft.provider_id)

    def _execute_scheduled(self, draft_id: str, provider_id: str) -> None:
        logger.info("[OutboundScheduler] executing scheduled draft %s", draft_id)
        draft = draft_store.get(draft_id)
        if not draft:
            return
        real_provider_id = provider_id
        if not registry_get_provider(real_provider_id):
            for pid, inst in registry_list_providers().items():
                if hasattr(inst, 'provider_type') and inst.provider_type == "gmail":
                    real_provider_id = pid
                    draft.provider_id = pid
                    draft_store.update(draft)
                    break
            if not registry_get_provider(real_provider_id):
                logger.error("[OutboundScheduler] No Gmail outbound provider available for scheduled draft %s", draft_id)
                draft_store.mark_failed(draft_id, "No Gmail outbound provider registered")
                return
        draft_store.mark_sending(draft_id)
        result = outbound_executor.execute("send_reply", {
            "provider_id": real_provider_id,
            "draft_id": draft_id,
            "conversation_id": draft.conversation_id,
            "thread_id": draft.thread_id,
            "workflow_id": draft.workflow_id,
            "subject": draft.subject,
            "body": draft.body,
            "recipient": {"email": draft.recipient.email, "name": draft.recipient.name},
            "sender": {"email": draft.sender.email, "name": draft.sender.name},
            "cc": [{"email": c.email, "name": c.name} for c in draft.cc],
            "bcc": [{"email": b.email, "name": b.name} for b in draft.bcc],
        })
        if not result.get("ok"):
            draft_store.mark_failed(draft_id, result.get("error", "Scheduled send failed"))
            emit_event(OutboundEventType.MESSAGE_FAILED, provider_id,
                       f"Scheduled draft {draft_id} failed",
                       {"draft_id": draft_id, "error": result.get("error", "")})
        else:
            logger.info("[OutboundScheduler] scheduled draft %s sent successfully", draft_id)

    def schedule(self, draft_id: str, provider_id: str, send_at: str) -> dict:
        draft = draft_store.get(draft_id)
        if not draft:
            return {"ok": False, "error": "Draft not found"}
        if not draft.metadata:
            draft.metadata = {}
        draft.metadata["send_at"] = send_at
        draft.status = DraftStatus.SCHEDULED
        draft_store.update(draft)
        result = registry_schedule(provider_id, draft, send_at)
        emit_event(OutboundEventType.MESSAGE_SCHEDULED, provider_id,
                   f"Draft {draft_id} scheduled for {send_at}",
                   {"draft_id": draft_id, "send_at": send_at})
        return {"ok": True, "schedule_id": draft.id}

    def cancel_schedule(self, draft_id: str, provider_id: str) -> dict:
        draft = draft_store.get(draft_id)
        if not draft:
            return {"ok": False, "error": "Draft not found"}
        if draft.status != DraftStatus.SCHEDULED:
            return {"ok": False, "error": "Draft is not scheduled"}
        draft.status = DraftStatus.DRAFT
        if draft.metadata:
            draft.metadata.pop("send_at", None)
        draft_store.update(draft)
        registry_cancel_schedule(provider_id, draft_id)
        emit_event(OutboundEventType.MESSAGE_CANCELLED, provider_id,
                   f"Scheduled draft {draft_id} cancelled",
                   {"draft_id": draft_id})
        return {"ok": True}


outbound_scheduler = OutboundScheduler()
