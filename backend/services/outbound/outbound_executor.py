"""Outbound Executor — universal outbound dispatcher.

Planner gives an action. Executor dispatches through the registry.
Never imports Gmail directly.
"""
import logging
from typing import Optional

from services.outbound.outbound_registry import (
    get_provider,
    create_draft as registry_create_draft,
    update_draft as registry_update_draft,
    delete_draft as registry_delete_draft,
    send as registry_send,
    schedule as registry_schedule,
    cancel_schedule as registry_cancel_schedule,
)
from services.outbound.draft_store import draft_store
from services.outbound.outbound_persistence import outbound_persistence
from services.outbound.outbound_models import (
    DraftMessage,
    SendRequest,
    SendResult,
    ScheduledMessage,
    DeliveryStatus,
    ApprovalState,
    DraftStatus,
    Recipient,
)

logger = logging.getLogger(__name__)


class OutboundActionType:
    CREATE_REPLY_DRAFT = "create_reply_draft"
    UPDATE_REPLY_DRAFT = "update_reply_draft"
    SEND_REPLY = "send_reply"
    SCHEDULE_REPLY = "schedule_reply"
    DELETE_DRAFT = "delete_draft"


class OutboundExecutor:
    def execute(self, action_type: str, params: dict) -> dict:
        handler = self._get_handler(action_type)
        if not handler:
            return {"ok": False, "error": f"Unknown action type: {action_type}"}
        try:
            return handler(params)
        except Exception as e:
            logger.error("[OutboundExecutor] %s failed: %s", action_type, e, exc_info=True)
            return {"ok": False, "error": str(e)}

    def _get_handler(self, action_type: str):
        handlers = {
            OutboundActionType.CREATE_REPLY_DRAFT: self._handle_create_draft,
            OutboundActionType.UPDATE_REPLY_DRAFT: self._handle_update_draft,
            OutboundActionType.SEND_REPLY: self._handle_send,
            OutboundActionType.SCHEDULE_REPLY: self._handle_schedule,
            OutboundActionType.DELETE_DRAFT: self._handle_delete_draft,
        }
        return handlers.get(action_type)

    def _handle_create_draft(self, params: dict) -> dict:
        provider_id = params["provider_id"]
        conversation_id = params.get("conversation_id", "")
        thread_id = params.get("thread_id", "")
        workflow_id = params.get("workflow_id", "")
        subject = params["subject"]
        body = params["body"]
        recipient = Recipient(**params["recipient"])
        sender = Recipient(**params["sender"])
        cc = [Recipient(**c) for c in params.get("cc", [])]
        bcc = [Recipient(**b) for b in params.get("bcc", [])]
        reply_to = params.get("reply_to_message_id", "")
        in_reply_to = params.get("in_reply_to", "")
        references = params.get("references", "")

        draft = DraftMessage(
            provider_id=provider_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            workflow_id=workflow_id,
            subject=subject,
            body=body,
            recipient=recipient,
            sender=sender,
            cc=cc,
            bcc=bcc,
            reply_to_message_id=reply_to,
            in_reply_to=in_reply_to,
            references=references,
        )

        draft_store.create(draft)
        result = registry_create_draft(provider_id, draft)

        if result:
            draft_store.update(result)

        return {
            "ok": True,
            "draft_id": draft.id,
            "external_draft_id": getattr(result, "external_draft_id", "") if result else "",
        }

    def _handle_update_draft(self, params: dict) -> dict:
        provider_id = params["provider_id"]
        draft_id = params["draft_id"]
        existing = draft_store.get(draft_id)
        if not existing:
            return {"ok": False, "error": f"Draft {draft_id} not found"}

        updated = existing.model_copy(update={
            "subject": params.get("subject", existing.subject),
            "body": params.get("body", existing.body),
            "recipient": Recipient(**params["recipient"]) if "recipient" in params else existing.recipient,
        })
        draft_store.update(updated)
        result = registry_update_draft(provider_id, updated)
        if result:
            draft_store.update(result)
        return {"ok": True, "draft_id": draft_id}

    def _handle_send(self, params: dict) -> dict:
        provider_id = params["provider_id"]
        draft_id = params.get("draft_id", "")

        if draft_id:
            draft = draft_store.get(draft_id)
            if not draft:
                return {"ok": False, "error": f"Draft {draft_id} not found"}
            request_recipient = Recipient(**params["recipient"]) if "recipient" in params else draft.recipient
            envelope_changed = (
                "recipient" in params
                and (request_recipient.email != draft.recipient.email
                     or request_recipient.name != draft.recipient.name)
            )
            if envelope_changed:
                # The live request wants a different envelope recipient (e.g.
                # the test-only recipient override). Rebuild the SendRequest
                # from the request params so the provider uses the requested
                # To envelope instead of the persisted Gmail draft's To.
                request = SendRequest(
                    provider_id=provider_id,
                    conversation_id=params.get("conversation_id", draft.conversation_id),
                    thread_id=params.get("thread_id", draft.thread_id),
                    workflow_id=params.get("workflow_id", draft.workflow_id),
                    subject=params.get("subject", draft.subject),
                    body=params.get("body", draft.body),
                    recipient=request_recipient,
                    sender=Recipient(**params["sender"]) if "sender" in params else draft.sender,
                    cc=draft.cc,
                    bcc=draft.bcc,
                    reply_to_message_id=params.get("reply_to_message_id", draft.reply_to_message_id),
                    in_reply_to=params.get("in_reply_to", draft.in_reply_to),
                    references=params.get("references", draft.references),
                    draft_id="",
                )
            else:
                request = SendRequest(
                    provider_id=provider_id,
                    conversation_id=draft.conversation_id,
                    thread_id=draft.thread_id,
                    workflow_id=draft.workflow_id,
                    subject=draft.subject,
                    body=draft.body,
                    recipient=draft.recipient,
                    sender=draft.sender,
                    cc=draft.cc,
                    bcc=draft.bcc,
                    reply_to_message_id=draft.reply_to_message_id,
                    in_reply_to=draft.in_reply_to,
                    references=draft.references,
                    draft_id=draft.external_draft_id,
                )
        else:
            request = SendRequest(
                provider_id=provider_id,
                conversation_id=params.get("conversation_id", ""),
                thread_id=params.get("thread_id", ""),
                workflow_id=params.get("workflow_id", ""),
                subject=params["subject"],
                body=params["body"],
                recipient=Recipient(**params["recipient"]),
                sender=Recipient(**params["sender"]),
            )

        logger.info(
            "[TEST RECIPIENT] original_recipient=%s effective_recipient=%s gmail_send_path=%s",
            (draft.recipient.email if draft_id and "draft" in locals() and draft else ""),
            request.recipient.email,
            "raw_message" if not request.draft_id else "persisted_draft",
        )

        send_result = registry_send(provider_id, request)
        if not send_result:
            return {"ok": False, "error": "Provider not found"}

        outbound_persistence.record_send(
            result=send_result,
            subject=request.subject,
            recipient_email=request.recipient.email,
            recipient_name=request.recipient.name,
            conversation_id=request.conversation_id,
            workflow_id=request.workflow_id,
            thread_id=request.thread_id,
        )

        if draft_id and send_result.status == DeliveryStatus.SENT:
            draft_store.mark_sent(draft_id)

        return {
            "ok": send_result.status != DeliveryStatus.FAILED,
            "send_result": {
                "id": send_result.id,
                "external_message_id": send_result.external_message_id,
                "thread_id": send_result.thread_id,
                "status": send_result.status.value,
                "error": send_result.error,
            },
        }

    def _handle_schedule(self, params: dict) -> dict:
        provider_id = params["provider_id"]
        draft_id = params["draft_id"]
        send_at = params["send_at"]
        draft = draft_store.get(draft_id)
        if not draft:
            return {"ok": False, "error": f"Draft {draft_id} not found"}
        scheduled = registry_schedule(provider_id, draft, send_at)
        if not scheduled:
            return {"ok": False, "error": "Provider not found"}
        draft.status = DraftStatus.SCHEDULED
        draft_store.update(draft)
        return {"ok": True, "schedule_id": scheduled.id}

    def _handle_delete_draft(self, params: dict) -> dict:
        provider_id = params["provider_id"]
        draft_id = params["draft_id"]
        draft = draft_store.get(draft_id)
        if not draft:
            return {"ok": False, "error": f"Draft {draft_id} not found"}
        if draft.external_draft_id:
            registry_delete_draft(provider_id, draft.external_draft_id)
        draft_store.delete(draft_id)
        return {"ok": True, "draft_id": draft_id}


executor = OutboundExecutor()
