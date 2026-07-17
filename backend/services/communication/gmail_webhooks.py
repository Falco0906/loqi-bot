"""Gmail Webhooks — handles Pub/Sub push notifications from Gmail.

Gmail sends push notifications when new messages arrive.
These webhooks trigger incremental syncs.
"""

import json
from typing import Any, Callable, Optional

from services.communication.provider_models import ProviderEventType
from services.communication.provider_events import emit_event


_handlers: dict[str, list[Callable]] = {}


def handle_notification(payload: dict, provider_id: str) -> dict[str, Any]:
    """Process a Gmail push notification.

    Expected payload format (from Gmail Pub/Sub):
    {
        "emailAddress": "user@example.com",
        "historyId": "12345"
    }
    """
    email = payload.get("emailAddress", "unknown")
    history_id = payload.get("historyId", "")

    if not history_id:
        return {"status": "ignored", "reason": "no history_id"}

    emit_event(
        ProviderEventType.SYNC_STARTED,
        provider_id,
        f"Webhook triggered sync for {email}",
        {"email": email, "history_id": history_id},
    )

    _run_handlers("on_notification", provider_id, payload)

    return {
        "status": "ok",
        "email": email,
        "history_id": history_id,
    }


def register_handler(event: str, handler: Callable) -> None:
    """Register a handler for webhook events."""
    if event not in _handlers:
        _handlers[event] = []
    _handlers[event].append(handler)


def _run_handlers(event: str, provider_id: str, payload: dict) -> None:
    """Run all registered handlers for an event."""
    for handler in _handlers.get(event, []):
        try:
            handler(provider_id, payload)
        except Exception as e:
            emit_event(
                ProviderEventType.SYNC_FAILED,
                provider_id,
                f"Webhook handler failed: {e}",
                {"error": str(e)},
            )


def clear_handlers() -> None:
    """Clear all registered handlers (for testing)."""
    _handlers.clear()
