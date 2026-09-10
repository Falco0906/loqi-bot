"""SaaS-2.6 — Durable outbound message + provider event persistence.

Outbound send history is canonical workspace state: its write is synchronous
at the outbound execution boundary so successful sends are immediately visible
to authorized history reads. Provider-event persistence remains best-effort.

Ownership is always derived server-side (provider -> user -> canonical
workspace); the client never supplies tenant authority.
"""

from __future__ import annotations

import asyncio
import threading


def _run_threaded(write) -> None:
    """Run one best-effort persistence write off the live path."""
    def _run() -> None:
        try:
            outcome = write()
            if inspect.isawaitable(outcome):
                asyncio.run(outcome)
        except Exception:  # noqa: BLE001 — best-effort persistence
            return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _run()
        return

    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def _workspace_for_provider(provider_id: str) -> str:
    """Server-derived canonical workspace for a connected provider's owner."""
    if not provider_id:
        return ""
    try:
        from services.communication.communication_store import store as comm_store
        provider = comm_store.get_provider(provider_id)
        user_id = getattr(provider, "user_id", "") or ""
        if not user_id:
            return ""
        from services.workspace.state import _async_workspace
        return asyncio.run(_async_workspace(user_id)) or ""
    except Exception:  # noqa: BLE001
        return ""


def persist_outbound_message(item) -> bool:
    """Persist one outbound send-history item before reporting send success.

    This is called from the outbound executor, which production async callers
    already run off the event loop. Failure is deliberately surfaced to that
    boundary instead of being hidden behind a daemon thread.
    """
    provider_id = getattr(item, "provider_id", "") or ""
    workspace_id = _workspace_for_provider(provider_id)
    if not workspace_id:
        raise RuntimeError("Outbound message has no resolvable workspace")
    from services.persistence.launch.models import OutboundMessage
    from services.persistence.launch.repositories import OutboundMessageRepository

    recipient = getattr(item, "recipient", None)
    entity = OutboundMessage(
        workspace_id=workspace_id,
        provider_id=provider_id,
        draft_id=getattr(item, "draft_id", "") or "",
        conversation_id=getattr(item, "conversation_id", "") or "",
        thread_id=getattr(item, "thread_id", "") or "",
        subject=getattr(item, "subject", "") or "",
        recipient_email=getattr(recipient, "email", "") or "",
        recipient_name=getattr(recipient, "name", "") or "",
        status=str(getattr(item, "status", "sent") or "sent"),
        error=getattr(item, "error", "") or "",
        external_message_id=getattr(item, "external_message_id", "") or "",
    )
    raw_id = getattr(item, "id", "") or ""
    if raw_id:
        entity.id = raw_id
    result = OutboundMessageRepository().save(entity)
    if result is None:
        raise RuntimeError("Outbound message persistence failed")
    return True


def persist_provider_event(provider_id: str, event_type: str, message: str = "",
                           metadata: dict | None = None) -> None:
    """Best-effort durable write of one provider lifecycle/communication event."""

    def _write():
        from services.persistence.launch.models import ProviderEvent
        from services.persistence.launch.repositories import ProviderEventRepository
        workspace_id = _workspace_for_provider(provider_id)
        if not workspace_id:
            return None
        entity = ProviderEvent(
            workspace_id=workspace_id,
            provider_id=provider_id or "",
            event_type=event_type or "",
            message=message or "",
            metadata=dict(metadata or {}),
        )
        return ProviderEventRepository().save(entity)

    _run_threaded(_write)


def list_outbound_history(workspace_id: str, provider_id: str = "", limit: int = 100) -> list:
    """Tenant-scoped durable outbound history for a workspace (async-safe)."""
    if not workspace_id:
        return []
    try:
        from services.persistence.launch.repositories import OutboundMessageRepository
        from services.supabase import _run_blocking
        return _run_blocking(
            OutboundMessageRepository().list_for_workspace(workspace_id, provider_id, limit=limit)
        )
    except Exception:  # noqa: BLE001
        return []


def list_provider_events(workspace_id: str, provider_id: str = "", limit: int = 100) -> list:
    """Tenant-scoped durable provider events for a workspace (async-safe)."""
    if not workspace_id:
        return []
    try:
        from services.persistence.launch.repositories import ProviderEventRepository
        from services.supabase import _run_blocking
        return _run_blocking(
            ProviderEventRepository().list_for_workspace(workspace_id, provider_id, limit=limit)
        )
    except Exception:  # noqa: BLE001
        return []
