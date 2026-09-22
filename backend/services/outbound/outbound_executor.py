"""Outbound send executor over authorized, hydrated requests.

Draft authorization and hydration belong to the outbound service. This module
only performs the provider side effect and records the durable send history.
"""
from __future__ import annotations

import logging

from services.outbound.outbound_models import DraftMessage, DeliveryStatus, Recipient, SendHistoryItem, SendRequest
from services.outbound.outbound_registry import send as registry_send
from services.persistence.launch.communication_persistence import persist_outbound_message

logger = logging.getLogger(__name__)


class OutboundExecutor:
    """Execute a provider send for a caller-authorized outbound request."""

    def send_request(self, request: SendRequest, *, original_recipient_email: str = "") -> dict:
        """Send one request and durably record its result before reporting success."""
        logger.info(
            "[TEST RECIPIENT] original_recipient=%s effective_recipient=%s gmail_send_path=%s",
            original_recipient_email,
            request.recipient.email,
            "raw_message" if not request.draft_id else "persisted_draft",
        )
        try:
            send_result = registry_send(request.provider_id, request)
        except Exception as error:  # noqa: BLE001 - translate provider failures at this boundary
            logger.error("outbound_send_failed provider_id=%s error_type=%s", request.provider_id, type(error).__name__)
            # A transport exception can occur after the provider accepted the
            # request.  The caller must retain its durable send claim instead
            # of treating this as retry-safe and risking a duplicate email.
            return {"ok": False, "error": str(error), "retry_safe": False}
        if not send_result:
            return {"ok": False, "error": "Provider not found", "retry_safe": True}

        history_item = SendHistoryItem(
            provider_id=send_result.provider_id,
            external_message_id=send_result.external_message_id,
            conversation_id=request.conversation_id,
            thread_id=request.thread_id,
            workflow_id=request.workflow_id,
            subject=request.subject,
            recipient=request.recipient,
            status=send_result.status,
            draft_id=send_result.draft_id,
            error=send_result.error,
        )
        try:
            persist_outbound_message(history_item)
        except Exception as error:  # noqa: BLE001 - durable history is part of the send boundary
            logger.error(
                "outbound_history_persistence_failed provider_id=%s error_type=%s",
                request.provider_id,
                type(error).__name__,
            )
            return {
                "ok": False,
                "error": "Email send history could not be persisted",
                "provider_accepted": send_result.status != DeliveryStatus.FAILED,
                "retry_safe": send_result.status == DeliveryStatus.FAILED,
            }

        return {
            "ok": send_result.status != DeliveryStatus.FAILED,
            "retry_safe": send_result.status == DeliveryStatus.FAILED,
            "send_result": {
                "id": send_result.id,
                "external_message_id": send_result.external_message_id,
                "thread_id": send_result.thread_id,
                "status": send_result.status.value,
                "error": send_result.error,
            },
        }

    def send_hydrated_draft(
        self,
        draft: DraftMessage,
        *,
        provider_id: str,
        recipient_override: Recipient | None = None,
    ) -> dict:
        """Send one already-authorized hydrated draft without a runtime lookup."""
        recipient = recipient_override or draft.recipient
        envelope_changed = recipient != draft.recipient
        request = SendRequest(
            provider_id=provider_id,
            conversation_id=draft.conversation_id,
            thread_id=draft.thread_id,
            workflow_id=draft.workflow_id,
            subject=draft.subject,
            body=draft.body,
            recipient=recipient,
            sender=draft.sender,
            cc=draft.cc,
            bcc=draft.bcc,
            attachments=draft.attachments,
            reply_to_message_id=draft.reply_to_message_id,
            in_reply_to=draft.in_reply_to,
            references=draft.references,
            # A recipient override deliberately sends a raw message instead of
            # the provider-side draft whose envelope belongs to the real lead.
            draft_id="" if envelope_changed else draft.external_draft_id,
        )
        return self.send_request(request, original_recipient_email=draft.recipient.email)


executor = OutboundExecutor()
