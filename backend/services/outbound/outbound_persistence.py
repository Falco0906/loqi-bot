"""Outbound Persistence — stores send history and delivery state.

Separate from draft_store which handles draft lifecycle.
Stores send history, delivery ids, provider ids, timestamps.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from services.outbound.outbound_models import (
    SendResult,
    SendHistoryItem,
    DeliveryStatus,
    Recipient,
)
from services.outbound.outbound_events import emit_event, OutboundEventType
from services.persistence.launch.communication_persistence import persist_outbound_message


class OutboundPersistence:
    def __init__(self) -> None:
        self._history: list[SendHistoryItem] = []
        self._send_results: dict[str, SendResult] = {}

    def record_send(self, result: SendResult, subject: str = "",
                    recipient_email: str = "", recipient_name: str = "",
                    conversation_id: str = "", workflow_id: str = "",
                    thread_id: str = "") -> SendHistoryItem:
        item = SendHistoryItem(
            provider_id=result.provider_id,
            external_message_id=result.external_message_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            workflow_id=workflow_id,
            subject=subject,
            recipient=Recipient(email=recipient_email, name=recipient_name),
            status=result.status,
            draft_id=result.draft_id,
            error=result.error,
        )
        # The durable communication record is authoritative.  Do not expose
        # a process-local success entry when its canonical write failed.
        persist_outbound_message(item)
        self._history.append(item)
        self._send_results[result.id] = result
        if result.status == DeliveryStatus.FAILED:
            emit_event(OutboundEventType.MESSAGE_FAILED, result.provider_id,
                       f"Message failed: {subject[:60]}",
                       {"send_id": result.id, "error": result.error})
        else:
            emit_event(OutboundEventType.MESSAGE_SENT, result.provider_id,
                       f"Message sent: {subject[:60]}",
                       {"send_id": result.id, "external_id": result.external_message_id})
        return item

    def record_delivery_update(self, send_id: str, status: DeliveryStatus) -> bool:
        if send_id not in self._send_results:
            return False
        old = self._send_results[send_id]
        old.status = status
        for item in self._history:
            if item.id == send_id:
                item.status = status
                break
        return True

    def get_history(self, provider_id: str = "", limit: int = 50) -> list[SendHistoryItem]:
        result = self._history
        if provider_id:
            result = [h for h in result if h.provider_id == provider_id]
        result = sorted(result, key=lambda h: h.sent_at, reverse=True)
        return result[:limit]

    def get_send_result(self, send_id: str) -> Optional[SendResult]:
        return self._send_results.get(send_id)

    def clear(self) -> None:
        self._history.clear()
        self._send_results.clear()


outbound_persistence = OutboundPersistence()


def projection_from_draft(draft) -> dict[str, Any]:
    """Serialize the provider-facing fields missing from the canonical Draft columns."""
    return {
        "provider_id": draft.provider_id,
        "external_draft_id": draft.external_draft_id,
        "gmail_message_id": draft.gmail_message_id,
        "gmail_thread_id": draft.gmail_thread_id,
        "conversation_id": draft.conversation_id,
        "thread_id": draft.thread_id,
        "workflow_id": draft.workflow_id,
        "recipient": draft.recipient.model_dump(),
        "sender": draft.sender.model_dump(),
        "cc": [item.model_dump() for item in draft.cc],
        "bcc": [item.model_dump() for item in draft.bcc],
        "attachments": [item.model_dump() for item in draft.attachments],
        "reply_to_message_id": draft.reply_to_message_id,
        "in_reply_to": draft.in_reply_to,
        "references": draft.references,
        "approval_state": draft.approval_state.value,
        "status": draft.status.value,
        "last_editor": draft.last_editor,
        "version": draft.version,
        # Empty for immediate drafts. These fields make the delayed job and
        # its due time available when hydrating after a process restart.
        "scheduled_job_id": str((draft.metadata or {}).get("scheduled_job_id") or ""),
        "send_at": str((draft.metadata or {}).get("send_at") or ""),
    }


async def persist_draft_projection(
    owner_id: str, workspace_id: str, draft, *, change_summary: str = "",
) -> bool:
    """Persist one outbound projection in the canonical workspace Draft row.

    The projection is deliberately nested in ``Draft.metadata``: canonical
    draft content/status remains owned by the Draft model, while this records
    provider-only identifiers and envelope details needed after a restart.
    """
    if not owner_id or not workspace_id or not getattr(draft, "id", ""):
        return False
    from services.persistence.launch.repositories import DraftRepository

    entity = await DraftRepository().get_for_workspace(draft.id, workspace_id)
    if entity is None:
        return False
    metadata = dict(entity.metadata or {})
    versions = list(metadata.get("outbound_versions") or [])
    snapshot = {
        "version": draft.version,
        "subject": draft.subject,
        "body": draft.body,
        "editor": draft.last_editor,
        "change_summary": change_summary or f"v{draft.version}: {draft.subject[:60]}",
        "edited_at": draft.updated_at,
    }
    if not versions or versions[-1] != snapshot:
        versions.append(snapshot)
    metadata["outbound_projection"] = projection_from_draft(draft)
    metadata["outbound_versions"] = versions[-25:]
    entity.metadata = metadata
    await DraftRepository().save(entity)
    return True


def hydrate_draft_projection(canonical: dict[str, Any], *, provider_id: str = "", sender_email: str = ""):
    """Build a runtime DraftMessage from one canonical durable Draft record."""
    from services.outbound.outbound_models import ApprovalState, DraftMessage, DraftStatus, Recipient

    metadata = dict(canonical.get("metadata") or {})
    projection = dict(metadata.get("outbound_projection") or {})
    lead = canonical.get("lead") if isinstance(canonical.get("lead"), dict) else {}
    recipient = projection.get("recipient") or {
        "email": lead.get("email", ""),
        "name": lead.get("name") or " ".join(filter(None, [lead.get("first_name", ""), lead.get("last_name", "")])).strip(),
    }
    state = projection.get("status") or canonical.get("status") or "pending_approval"
    approval = projection.get("approval_state") or ("approved" if state == "approved" else "pending")
    try:
        draft_status = DraftStatus(state)
    except ValueError:
        draft_status = DraftStatus.PENDING_APPROVAL
    try:
        approval_state = ApprovalState(approval)
    except ValueError:
        approval_state = ApprovalState.PENDING
    return DraftMessage(
        id=str(canonical.get("id") or ""), provider_id=str(projection.get("provider_id") or canonical.get("provider") or provider_id),
        external_draft_id=str(projection.get("external_draft_id") or ""), gmail_message_id=str(projection.get("gmail_message_id") or ""),
        gmail_thread_id=str(projection.get("gmail_thread_id") or ""), conversation_id=str(projection.get("conversation_id") or ""),
        thread_id=str(projection.get("thread_id") or ""), workflow_id=str(projection.get("workflow_id") or canonical.get("campaign_id") or ""),
        subject=str(canonical.get("subject") or ""), body=str(canonical.get("body") or canonical.get("text") or ""),
        recipient=Recipient(**recipient), sender=Recipient(**(projection.get("sender") or {"email": sender_email, "name": ""})),
        cc=[Recipient(**item) for item in projection.get("cc", [])], bcc=[Recipient(**item) for item in projection.get("bcc", [])],
        reply_to_message_id=str(projection.get("reply_to_message_id") or ""), in_reply_to=str(projection.get("in_reply_to") or ""),
        references=str(projection.get("references") or ""), status=draft_status, approval_state=approval_state,
        created_at=str(canonical.get("created_at") or ""), updated_at=str(canonical.get("updated_at") or ""),
        version=int(projection.get("version") or 1), last_editor=str(projection.get("last_editor") or ""), metadata=metadata,
    )
