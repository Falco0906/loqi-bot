"""Read and diagnostic operations for connected communication providers.

The durable ``connected_accounts`` record is authoritative for provider
identity.  The communication registry/store only enriches active runtime
state such as health, cursors, and diagnostic thread mappings.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from services.communication.communication_store import store as communication_store
from services.communication.provider_events import get_events, latest_sequence
from services.communication.provider_models import CommunicationProvider, ProviderStatus, ProviderType
from services.communication.provider_registry import (
    get_provider,
    list_registered_types,
)
from services.outbound import service as outbound_service
from services.conversation_intelligence.buying_signal_detector import detect_signals
from services.conversation_intelligence.legacy_models import ConversationMessage, ConversationStage
from services.conversation_intelligence.stage_classifier import classify_stage
from services.conversations.compatibility import read_legacy_timeline_events
from services.conversations.conversation_store import conversation_owned_by, conversation_store
from services.followup_reasoner import recommend_followup
from services.conversation_intelligence.intent_extractor import detect_intents
from services.conversation_intelligence.legacy_reply_projection import project_legacy_reply_intelligence
from services.conversations.intelligence_memory import build_legacy_memory
from services.communication.reply_summary import generate_summary
from services.world_model.events import EventType as WMEventType
from services.world_model.publisher import publish


log = logging.getLogger("loqi")


class DurableProviderLookupError(Exception):
    """The authoritative connected-account query could not be completed."""


class LegacyProviderConnectionError(Exception):
    """A legacy raw-token provider connection cannot be completed."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LegacyGoogleOAuthStateError(Exception):
    """The legacy web Gmail callback received invalid OAuth state."""


# Serializes Gmail replace/connect sequences for OAuth and the legacy raw-token
# compatibility route. Same-user connections serialize; unrelated users do not.
_GMAIL_CONNECT_LOCKS_MAX = 4096
_gmail_connect_locks: dict[str, asyncio.Lock] = {}


def gmail_connect_lock(user_id: str) -> asyncio.Lock:
    """Return the bounded, user-scoped Gmail connection lock."""
    if not user_id:
        user_id = "_anonymous_"
    lock = _gmail_connect_locks.get(user_id)
    if lock is None:
        if len(_gmail_connect_locks) >= _GMAIL_CONNECT_LOCKS_MAX:
            for key in [key for key, value in _gmail_connect_locks.items() if not value.locked()]:
                _gmail_connect_locks.pop(key, None)
        lock = _gmail_connect_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _gmail_connect_locks[user_id] = lock
    return lock


def remove_existing_gmail_provider(user_id: str) -> None:
    """Replace all runtime Gmail projections for one user's reconnect."""
    from services.communication.provider_registry import list_providers, remove_instance
    from services.outbound.outbound_registry import remove_instance as remove_outbound_instance

    removed = 0
    for provider_id, instance in list(list_providers().items()):
        if getattr(instance, "provider_type", None) is not ProviderType.GMAIL:
            continue
        if getattr(instance, "_user_id", "") != user_id:
            continue
        try:
            instance.disconnect()
        except Exception:
            pass
        remove_instance(provider_id)
        try:
            remove_outbound_instance(provider_id)
        except Exception:
            pass
        try:
            communication_store.remove_provider(provider_id)
        except Exception:
            pass
        removed += 1
    if removed:
        log.info("[oauth] Replaced %d existing Gmail provider(s) for user %s", removed, user_id[:8])


def _provider_is_owned_by(provider_id: str, owner_id: str) -> bool:
    """Use the established provider-record ownership rule during this cutover."""
    return outbound_service.provider_record_owned_by(provider_id, owner_id)


def analyze_communication_message(
    *, text: str, sender: str, subject: str, conversation_id: str,
) -> dict[str, Any]:
    """Analyze one message and preserve the legacy intelligence envelope."""
    message = ConversationMessage(text=text, sender=sender, subject=subject)
    intelligence, memory = project_legacy_reply_intelligence(
        message=message,
        conversation_id=conversation_id,
    )
    return {"ok": True, "intelligence": intelligence.model_dump(), "memory": memory.model_dump()}


def update_communication_memory(
    *, session_token: str, text: str, conversation_id: str, sender: str, subject: str,
) -> dict[str, Any]:
    """Persist communication intelligence and publish the legacy preference event."""
    message = ConversationMessage(text=text, sender=sender, subject=subject)
    resolved_conversation_id = conversation_id or message.id
    intents = detect_intents(message.text)
    signals = detect_signals(message.text)
    stage, reasoning = classify_stage([], message.text)
    recommendation = recommend_followup(intents, signals, stage)
    # This legacy HTTP payload has neither a trusted canonical conversation
    # scope nor a stable provider message ID. It remains analysis-only; Gmail
    # sync owns durable memory writes once it has both values.
    memory = build_legacy_memory(
        conversation_id=resolved_conversation_id,
        message=message,
        intents=intents,
        buying_signals=signals,
        stage=stage,
        stage_reasoning=reasoning,
        followup_action=recommendation.action.value,
    )
    publish(session_token, WMEventType.PREFERENCE_LEARNED, {
        "conversation_id": resolved_conversation_id,
        "intents": [intent.value for intent in intents] if intents else [],
        "signals": [signal.signal.value for signal in signals] if signals else [],
        "stage": stage.value if stage else "",
        "followup_action": recommendation.action.value,
    }, actor="system")
    return {"ok": True, "memory": memory.model_dump()}


def recommend_communication_follow_up(*, text: str) -> dict[str, Any]:
    """Return the existing deterministic follow-up recommendation."""
    recommendation = recommend_followup(
        detect_intents(text),
        detect_signals(text),
        ConversationStage.ENGAGED,
    )
    return {"ok": True, "recommendation": recommendation.model_dump()}


def summarize_communication_message(*, text: str) -> dict[str, Any]:
    """Return the existing communication-summary envelope."""
    intents = detect_intents(text)
    signals = detect_signals(text)
    recommendation = recommend_followup(intents, signals, ConversationStage.ENGAGED)
    return {"ok": True, "summary": generate_summary(intents, signals, recommendation)}


class ConversationNotFoundForOwner(Exception):
    """A conversation is absent or belongs to another user."""


def communication_timeline_for_owner(*, owner_id: str, conversation_id: str) -> dict[str, Any]:
    """Return timeline events without exposing foreign conversation existence."""
    conversation = conversation_store.get_conversation(conversation_id)
    if conversation is None or not conversation_owned_by(conversation, owner_id):
        raise ConversationNotFoundForOwner
    events = read_legacy_timeline_events(conversation_id)
    return {"ok": True, "events": [event.model_dump() for event in events], "total": len(events)}


async def list_provider_summaries(owner_id: str) -> list[dict[str, Any]]:
    """Return durable connected accounts enriched with live runtime state."""
    from services.platform.supabase import get_durable_providers_for_user

    try:
        durable_rows = await asyncio.to_thread(
            get_durable_providers_for_user,
            owner_id,
            "google",
        )
    except Exception as error:
        log.error(
            "[providers] durable provider lookup failed user=%s error_type=%s",
            owner_id[:8],
            type(error).__name__,
        )
        raise DurableProviderLookupError from error

    log.info(
        "[providers] durable provider lookup returned %d record(s) user=%s",
        len(durable_rows),
        owner_id[:8],
    )
    providers: list[dict[str, Any]] = []
    seen_runtime_ids: set[str] = set()
    durable_gmail_emails: set[str] = set()

    for row in durable_rows:
        communication_provider_id = row.get("communication_provider_id") or ""
        email = (row.get("email") or "").strip().lower()
        durable_status = row.get("status") or "active"
        if email:
            durable_gmail_emails.add(email)
        runtime_instance = get_provider(communication_provider_id) if communication_provider_id else None
        record = communication_store.get_provider(communication_provider_id) if communication_provider_id else None
        if communication_provider_id:
            seen_runtime_ids.add(communication_provider_id)
        if record is not None:
            seen_runtime_ids.add(record.id)

        if durable_status == "auth_failed":
            status = ProviderStatus.AUTH_FAILED.value
        elif runtime_instance is not None:
            try:
                status = (await asyncio.to_thread(runtime_instance.health)).value
            except Exception as error:
                log.warning(
                    "[providers] runtime health probe failed provider=%s error_type=%s",
                    communication_provider_id[:8],
                    type(error).__name__,
                )
                if type(error).__name__ == "GmailReauthRequired":
                    status = ProviderStatus.AUTH_FAILED.value
                else:
                    status = (
                        durable_status
                        if durable_status in {"active", "healthy"}
                        else ProviderStatus.AUTH_FAILED.value
                    )
        else:
            status = (
                durable_status
                if durable_status in {"active", "healthy"}
                else ProviderStatus.AUTH_FAILED.value
            )

        providers.append({
            "id": communication_provider_id or f"durable-{row.get('row_id', '')}",
            "provider_type": ProviderType.GMAIL.value,
            "status": status,
            "email": row.get("email", ""),
            "last_sync": (record.last_sync if record else None) or row.get("last_synced_at"),
            "sync_cursor": record.sync_cursor if record else "",
            "created_at": row.get("created_at"),
        })

    # Legacy development connections are runtime-only.  They remain visible
    # until the legacy raw-token connect route is removed in a later phase.
    for record in communication_store.get_user_providers(owner_id):
        if record.id in seen_runtime_ids:
            continue
        record_email = (record.metadata.get("email", "") or "").strip().lower()
        if record.provider_type is ProviderType.GMAIL and record_email in durable_gmail_emails:
            continue
        instance = get_provider(record.id)
        providers.append({
            "id": record.id,
            "provider_type": record.provider_type.value,
            "status": (
                await asyncio.to_thread(instance.health)
            ).value if instance else record.status.value,
            "email": record.metadata.get("email", ""),
            "last_sync": record.last_sync,
            "sync_cursor": record.sync_cursor,
            "created_at": record.created_at,
        })

    return providers


async def provider_health(owner_id: str, provider_id: str) -> dict[str, Any] | None:
    """Return one owned provider's live health envelope data."""
    if not _provider_is_owned_by(provider_id, owner_id):
        return None
    instance = get_provider(provider_id)
    if instance is None:
        return None
    status = await asyncio.to_thread(instance.health)
    provider = communication_store.get_provider(provider_id)
    if provider is not None and provider.provider_type == ProviderType.GMAIL:
        try:
            from services.platform.supabase import is_connected_account_reauth_required

            if await asyncio.to_thread(
                is_connected_account_reauth_required,
                provider.user_id,
                "google",
            ):
                status = ProviderStatus.AUTH_FAILED
        except Exception:
            pass
    return {
        "ok": True,
        "provider_id": provider_id,
        "status": status.value,
        "last_sync": provider.last_sync if provider else "",
    }


async def provider_status(owner_id: str, provider_id: str) -> dict[str, Any] | None:
    """Return one owned provider's runtime connection and cursor state."""
    if not _provider_is_owned_by(provider_id, owner_id):
        return None
    provider = communication_store.get_provider(provider_id)
    if provider is None:
        return None
    instance = get_provider(provider_id)
    health = (await asyncio.to_thread(instance.health)).value if instance else provider.status.value
    cursor = communication_store.get_cursor(provider_id)
    return {
        "ok": True,
        "provider_id": provider_id,
        "provider_type": provider.provider_type.value,
        "status": health,
        "connected": instance is not None,
        "last_sync": provider.last_sync,
        "sync_cursor": cursor.cursor if cursor else "",
        "watching": getattr(instance, "_watching", False) if instance else False,
    }


def provider_threads(owner_id: str, provider_id: str) -> dict[str, Any] | None:
    """Return thread mappings owned by one connected provider."""
    if not _provider_is_owned_by(provider_id, owner_id):
        return None
    threads = [
        thread
        for thread in communication_store.get_all_threads()
        if thread.provider_id == provider_id
    ]
    return {
        "ok": True,
        "provider_id": provider_id,
        "threads": [thread.model_dump() for thread in threads],
        "total": len(threads),
    }


def provider_messages(owner_id: str, provider_id: str) -> dict[str, Any] | None:
    """Return the existing provider-diagnostics message envelope unchanged."""
    if not _provider_is_owned_by(provider_id, owner_id):
        return None
    return {
        "ok": True,
        "provider_id": provider_id,
        "total_messages_seen": communication_store.message_count(),
        "recent_messages": communication_store.get_recent_messages(limit=10),
        "mailbox_email": "",
    }


def provider_events(
    provider_id: str,
    after_sequence: int,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Merge current-process provider events with durable workspace events."""
    runtime_events = get_events(provider_id=provider_id, after_sequence=after_sequence)
    durable_events: list[Any] = []
    if workspace_id:
        try:
            from services.persistence.launch.communication_persistence import list_provider_events

            durable_events = list_provider_events(workspace_id, provider_id, 100)
        except Exception:
            durable_events = []

    seen_ids = {event.id for event in runtime_events}
    durable = [
        {
            "id": getattr(event, "id", ""),
            "event_type": getattr(event, "event_type", ""),
            "provider_id": getattr(event, "provider_id", ""),
            "message": getattr(event, "message", ""),
            "timestamp": (
                getattr(event, "event_timestamp", None).isoformat()
                if getattr(event, "event_timestamp", None)
                else ""
            ),
            "sequence": 0,
            "metadata": getattr(event, "metadata", {}) or {},
        }
        for event in durable_events
        if getattr(event, "id", "") not in seen_ids
    ]
    runtime = [
        {
            "id": event.id,
            "event_type": event.event_type.value,
            "provider_id": event.provider_id,
            "message": event.message,
            "timestamp": event.timestamp,
            "sequence": event.sequence,
            "metadata": event.metadata,
        }
        for event in runtime_events
    ]
    return {
        "ok": True,
        "events": durable + runtime,
        "latest_sequence": latest_sequence(),
    }


def registered_provider_types() -> dict[str, Any]:
    """Return the existing runtime registry type envelope."""
    return {"ok": True, "types": [provider_type.value for provider_type in list_registered_types()]}


async def disconnect_provider(
    owner_id: str,
    session_token: str,
    provider_id: str,
) -> bool:
    """Disconnect one owned runtime provider and publish its lifecycle events."""
    from services.communication.provider_registry import disconnect_provider as registry_disconnect

    if not _provider_is_owned_by(provider_id, owner_id):
        return False
    if not registry_disconnect(provider_id):
        return False

    try:
        from services.identity.session_cache import session_cache

        await session_cache.invalidate_user(owner_id)
    except Exception:
        pass

    publish(
        session_token,
        WMEventType.PROVIDER_DISCONNECTED,
        {"provider_id": provider_id},
        actor="user",
    )
    try:
        from services.events_bus import event_bus

        await event_bus.publish_user_event(
            owner_id,
            "provider.disconnected",
            {"provider": "gmail"},
            status="disconnected",
        )
    except Exception:
        pass
    return True


async def sync_provider(
    owner_id: str,
    session_token: str,
    provider_id: str,
    cursor: str = "",
) -> Any | None:
    """Run one owned provider sync through the existing inbox-sync boundary."""
    if not _provider_is_owned_by(provider_id, owner_id):
        return None

    from services.communication.inbox_sync_engine import inbox_sync_engine

    result = await inbox_sync_engine.sync_provider_now(provider_id, cursor=cursor)
    if result is None:
        return None
    # Preserve the existing route's event payload contract exactly, including
    # its current SyncResult field-name mismatch characterized by R17-0.
    publish(
        session_token,
        WMEventType.SYNC_COMPLETED,
        {
            "provider_id": provider_id,
            "new_messages": result.new_messages,
            "updated_threads": result.updated_threads,
        },
        actor="system",
    )
    return result


async def connect_gmail_oauth_provider(
    *,
    user_id: str,
    access_token: str,
    refresh_token: str,
    email: str,
    account_id: str,
) -> CommunicationProvider:
    """Connect Gmail, prove durable persistence, and project it into runtime."""
    from services.communication.gmail_provider import GmailProvider
    from services.communication import provider_startup
    from services.communication.provider_registry import register_instance, remove_instance
    from services.communication.google_auth import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    from services.platform.supabase import get_durable_providers_for_user, sync_connected_account

    async with gmail_connect_lock(user_id):
        log.info(
            "[oauth] provider persistence started user=%s email=%s",
            user_id[:8],
            email or "(unknown)",
        )
        remove_existing_gmail_provider(user_id)
        provider = GmailProvider()
        provider_record = provider.connect(
            auth_token=access_token,
            user_id=user_id,
            email=email,
            account_id=account_id,
            scope=",".join([
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ]),
            refresh_token=refresh_token,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        register_instance(provider_record.id, provider)
        provider_startup.register_outbound_gmail_instance(provider_record.id)

        async def rollback_runtime() -> None:
            """Remove only runtime state created by this failed attempt."""
            try:
                provider.disconnect()
            except Exception:
                pass
            remove_instance(provider_record.id)
            try:
                from services.outbound.outbound_registry import remove_instance as remove_outbound_instance

                remove_outbound_instance(provider_record.id)
            except Exception:
                pass
            try:
                communication_store.remove_provider(provider_record.id)
            except Exception:
                pass

        token_expiry = ""
        token_expiry_epoch = getattr(provider, "_token_expiry", 0.0)
        if token_expiry_epoch:
            token_expiry = datetime.fromtimestamp(
                token_expiry_epoch,
                tz=timezone.utc,
            ).isoformat()

        saved = await asyncio.to_thread(
            sync_connected_account,
            user_id,
            provider="google",
            account_id=account_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            communication_provider_id=provider_record.id,
        )
        if not saved:
            await rollback_runtime()
            log.error("[oauth] provider persistence failed user=%s", user_id[:8])
            raise RuntimeError("Connected account could not be persisted")

        try:
            durable_rows = await asyncio.to_thread(
                get_durable_providers_for_user,
                user_id,
                "google",
            )
        except Exception as error:
            await rollback_runtime()
            log.error(
                "[oauth] provider persistence verification failed user=%s error_type=%s",
                user_id[:8],
                type(error).__name__,
            )
            raise RuntimeError("Connected account persistence could not be verified") from error
        if not any(row.get("communication_provider_id") == provider_record.id for row in durable_rows):
            await rollback_runtime()
            log.error("[oauth] persisted provider not visible in durable lookup user=%s", user_id[:8])
            raise RuntimeError("Connected account persistence could not be verified")

        provider_startup.register_google_oauth_credential_instance(
            access_token,
            refresh_token,
            email,
        )
        try:
            from services.identity.session_cache import session_cache

            await session_cache.invalidate_user(user_id)
        except Exception:
            pass
        log.info(
            "[oauth] provider persistence succeeded user=%s provider=%s",
            user_id[:8],
            provider_record.id[:8],
        )
        return provider_record


async def connect_legacy_raw_token_provider(
    *,
    user_id: str,
    provider_type: str,
    auth_token: str,
    email: str = "",
    scope: str = "",
) -> CommunicationProvider:
    """Connect a development-only raw-token provider compatibility route."""
    if (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower() == "production":
        raise LegacyProviderConnectionError(
            403,
            "Provider connect is disabled in production — use the Gmail OAuth flow",
        )
    try:
        provider_kind = ProviderType(provider_type)
    except ValueError as error:
        raise LegacyProviderConnectionError(400, f"Unknown provider type: {provider_type}") from error

    from services.communication import provider_startup
    from services.communication.provider_registry import instantiate_provider, register_instance

    instance = instantiate_provider(provider_kind)
    if instance is None:
        raise LegacyProviderConnectionError(400, f"Provider not registered: {provider_type}")

    if provider_kind == ProviderType.GMAIL:
        async with gmail_connect_lock(user_id):
            remove_existing_gmail_provider(user_id)
            provider = instance.connect(
                auth_token=auth_token,
                user_id=user_id,
                email=email,
                scope=scope,
            )
            register_instance(provider.id, instance)
            provider_startup.register_outbound_gmail_instance(provider.id)
    else:
        provider = instance.connect(
            auth_token=auth_token,
            user_id=user_id,
            email=email,
            scope=scope,
        )
        register_instance(provider.id, instance)

    publish(
        user_id,
        WMEventType.PROVIDER_CONNECTED,
        {
            "provider_id": provider.id,
            "provider_type": provider_type,
            "email": email,
        },
        actor="user",
    )
    return provider


def frontend_postmessage_origin() -> str:
    """Return the configured frontend origin for Gmail OAuth popup messages."""
    return os.getenv("FRONTEND_ORIGIN") or os.getenv("FRONTEND_URL") or ""


async def resolve_oauth_state_user(state: str) -> str:
    """Resolve a server-issued Gmail OAuth state token to its Loqi user."""
    from services.identity.oauth_state import consume_state

    user_id, _context = await consume_state(state)
    if not user_id or user_id == "gmail_user":
        return ""
    from services.platform.supabase import get_user

    if await asyncio.to_thread(get_user, user_id):
        return user_id
    return user_id


async def complete_legacy_google_callback(code: str, state: str) -> str:
    """Complete the legacy web Gmail callback and publish its historic event."""
    from services.communication.google_auth import exchange_code_for_tokens
    from services.identity.oauth_state import consume_state
    from services.platform.supabase import save_google_tokens
    from services.world_model import EventType as WMEventType, publish

    user_id, _context = await consume_state(state)
    if not user_id or user_id == "gmail_user":
        raise LegacyGoogleOAuthStateError("Invalid or expired OAuth state")

    tokens = await asyncio.to_thread(exchange_code_for_tokens, code)
    saved_user = await asyncio.to_thread(
        save_google_tokens,
        user_id,
        email=tokens.get("email", ""),
        telegram_chat_id=None,
        access_token=tokens.get("access_token", ""),
        refresh_token=tokens.get("refresh_token", ""),
        token_expiry=tokens.get("token_expiry"),
    )
    if saved_user is None:
        raise RuntimeError("Failed to save Google tokens")

    publish(
        f"web:{user_id}",
        WMEventType.PROVIDER_CONNECTED,
        {
            "provider_type": "gmail",
            "email": tokens.get("email", ""),
            "channel": "web",
        },
        actor="user",
    )
    return tokens.get("email", "")


def legacy_web_gmail_connect_url(session_token: str) -> str:
    """Return the historic web-session Gmail OAuth URL compatibility value."""
    from services.conversations.legacy_engine import ConversationEngine

    return ConversationEngine().get_gmail_connect_url(
        channel="web",
        external_user_id=session_token,
    )
