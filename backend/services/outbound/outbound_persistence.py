"""Outbound Persistence — stores send history and delivery state.

Separate from draft_store which handles draft lifecycle.
Stores send history, delivery ids, provider ids, timestamps.
"""
from datetime import datetime, timezone
from typing import Optional

from services.outbound.outbound_models import (
    SendResult,
    SendHistoryItem,
    DeliveryStatus,
    Recipient,
)
from services.outbound.outbound_events import emit_event, OutboundEventType


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
