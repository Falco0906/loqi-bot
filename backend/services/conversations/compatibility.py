"""Legacy web-session and timeline compatibility facade.

This module preserves web-session, workflow-message, workflow-event, and
legacy timeline contracts. Durable Inbox conversations themselves belong to
``conversation_store.py`` in this package.
"""
import secrets
from datetime import datetime, timezone

from services.platform.supabase import get_or_create_user, get_supabase_client, get_user
from services.conversation_models import (
    ConversationTimelineEvent as LegacyTimelineEvent,
    TimelineEventType as LegacyTimelineEventType,
)
from services.conversations.timeline import TimelineEventType, build_timeline_event


_LEGACY_TIMELINE_METADATA_KEY = "legacy_timeline"

_LEGACY_TO_DURABLE_TIMELINE_TYPES = {
    LegacyTimelineEventType.LEAD_REPLIED: TimelineEventType.REPLY_RECEIVED,
    LegacyTimelineEventType.PRICING_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.MEETING_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.DEMO_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.COMPETITOR_MENTIONED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.POSITIVE_BUYING_SIGNAL: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.STRONG_OBJECTION: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.BUDGET_DISCUSSED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.TIMELINE_DISCUSSED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.DECISION_MAKER_MENTIONED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.FOLLOWUP_RECOMMENDED: TimelineEventType.FOLLOW_UP_SUGGESTED,
    LegacyTimelineEventType.STAGE_CHANGED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.OBJECTION_ANSWERED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.MEETING_SCHEDULED: TimelineEventType.MEETING_BOOKED,
    LegacyTimelineEventType.PROPOSAL_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.CASE_STUDY_REQUESTED: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.COMPETITIVE_SITUATION: TimelineEventType.REPLY_CLASSIFIED,
    LegacyTimelineEventType.LOST_OPPORTUNITY: TimelineEventType.CLOSED_LOST,
    LegacyTimelineEventType.WON_DEAL: TimelineEventType.CLOSED_WON,
    LegacyTimelineEventType.DORMANT_PERIOD: TimelineEventType.REPLY_CLASSIFIED,
}


def durable_timeline_type_for_legacy_event(
    event_type: LegacyTimelineEventType,
) -> TimelineEventType:
    """Return the canonical timeline type for one legacy analytical event."""
    return _LEGACY_TO_DURABLE_TIMELINE_TYPES[event_type]


def legacy_timeline_metadata(
    event_type: LegacyTimelineEventType,
    message: str,
    metadata: dict | None = None,
) -> dict:
    """Embed the legacy envelope so compatibility reads can round-trip it."""
    return {
        _LEGACY_TIMELINE_METADATA_KEY: {
            "event_type": event_type.value,
            "message": message,
            "metadata": dict(metadata or {}),
        }
    }


def record_legacy_analysis_event(
    conversation_id: str,
    event_type: LegacyTimelineEventType,
    message: str,
    metadata: dict | None = None,
) -> bool:
    """Persist one legacy analytical event for a canonical conversation.

    ``REPLY_RECEIVED`` remains owned by ``conversations.integration.handle_reply``.
    The old process-local store accepted arbitrary ids; non-canonical ids are now
    deliberately skipped because they have no durable conversation to own them.
    """
    if event_type is LegacyTimelineEventType.LEAD_REPLIED:
        return False

    from services.conversations.conversation_store import conversation_store

    if conversation_store.get_conversation(conversation_id) is None:
        return False

    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=durable_timeline_type_for_legacy_event(event_type),
        title=message,
        actor="system",
        metadata=legacy_timeline_metadata(event_type, message, metadata),
    ))
    return True


def read_legacy_timeline_events(conversation_id: str) -> list[LegacyTimelineEvent]:
    """Return the old timeline envelope projected from canonical timeline events."""
    from services.conversations.conversation_store import conversation_store

    legacy_events: list[LegacyTimelineEvent] = []
    for event in conversation_store.get_timeline(conversation_id):
        payload = (event.metadata or {}).get(_LEGACY_TIMELINE_METADATA_KEY)
        if not isinstance(payload, dict):
            continue
        try:
            event_type = LegacyTimelineEventType(str(payload.get("event_type") or ""))
        except ValueError:
            continue
        legacy_events.append(LegacyTimelineEvent(
            event_type=event_type,
            message=str(payload.get("message") or ""),
            timestamp=event.timestamp.isoformat(),
            metadata=dict(payload.get("metadata") or {}),
        ))
    return legacy_events


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_row(result) -> dict | None:
    data = getattr(result, "data", None) or []
    return data[0] if data else None


def _safe_insert(table_name: str, payload: dict) -> None:
    client = get_supabase_client()
    if client is None:
        return

    try:
        client.table(table_name).insert(payload).execute()
    except Exception as error:
        print(f"[conversation_store] optional insert failed for {table_name}: {error}")


def _safe_query(table_name: str, query_builder):
    client = get_supabase_client()
    if client is None:
        return None

    try:
        return query_builder(client.table(table_name)).execute()
    except Exception as error:
        print(f"[conversation_store] optional query failed for {table_name}: {error}")
        return None


def get_or_create_channel_user(
    *,
    channel: str,
    external_user_id: str,
    username: str | None = None,
) -> dict | None:
    if channel == "telegram":
        return get_or_create_user(external_user_id, username=username)

    # Web sessions must never fabricate a second identity for an already
    # resolved session: resolve through the existing user row or the durable
    # workflow_sessions mapping first. Only fall back to creating a user row
    # for a genuinely new anonymous token.
    existing = get_web_session(external_user_id)
    if existing:
        return existing

    channel_key = f"{channel}:{external_user_id}"
    return get_or_create_user(channel_key, username=username)


def create_lightweight_web_session(
    display_name: str | None = None,
    *,
    user_id: str | None = None,
) -> dict | None:
    session_token = secrets.token_urlsafe(18)
    if user_id:
        user = get_user(user_id)
    else:
        user = None
    if user is None:
        user = get_or_create_channel_user(
            channel="web",
            external_user_id=session_token,
            username=display_name or "web-user",
        )
    if user is None:
        return None

    return {
        "session_token": session_token,
        "user": user,
        "channel": "web",
        "created_at": _utc_now(),
    }


def get_web_session(session_token: str) -> dict | None:
    client = get_supabase_client()
    if client is None:
        return None

    try:
        result = (
            client.table("users")
            .select("*")
            .eq("telegram_id", f"web:{session_token}")
            .limit(1)
            .execute()
        )
        row = _first_row(result)
        if row:
            return row
    except Exception as error:
        print(f"[conversation_store] get_web_session error: {error}")
        return None

    # Authenticated web sessions never create a second users row; they are
    # bound to the authenticated user through the durable workflow_sessions
    # mapping. Resolve the token through that mapping when present.
    linked = _safe_query(
        "workflow_sessions",
        lambda table: (
            table.select("user_id")
            .eq("channel", "web")
            .eq("session_key", session_token)
            .order("created_at", desc=True)
            .limit(1)
        ),
    )
    linked_row = _first_row(linked) if linked is not None else None
    if linked_row and linked_row.get("user_id"):
        return get_user(str(linked_row["user_id"]))
    return None


def get_channel_user(
    *,
    channel: str,
    external_user_id: str,
) -> dict | None:
    if channel == "telegram":
        client = get_supabase_client()
        if client is None:
            return None

        try:
            result = (
                client.table("users")
                .select("*")
                .eq("telegram_id", external_user_id)
                .limit(1)
                .execute()
            )
            return _first_row(result)
        except Exception as error:
            print(f"[conversation_store] get_channel_user error: {error}")
            return None

    return get_web_session(external_user_id)


def ensure_workflow_session(
    *,
    user_id: str,
    channel: str,
    session_key: str,
) -> str:
    fallback_session_id = f"{channel}:{session_key}"
    result = _safe_query(
        "workflow_sessions",
        lambda table: (
            table.select("*")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .eq("session_key", session_key)
            .order("created_at", desc=True)
            .limit(1)
        ),
    )
    existing = _first_row(result) if result is not None else None
    if existing:
        return existing.get("id", fallback_session_id)

    payload = {
        "user_id": user_id,
        "channel": channel,
        "session_key": session_key,
        "status": "active",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _safe_insert("workflow_sessions", payload)

    result = _safe_query(
        "workflow_sessions",
        lambda table: (
            table.select("*")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .eq("session_key", session_key)
            .order("created_at", desc=True)
            .limit(1)
        ),
    )
    created = _first_row(result) if result is not None else None
    return created.get("id", fallback_session_id) if created else fallback_session_id


def touch_workflow_session(session_id: str) -> None:
    client = get_supabase_client()
    if client is None or ":" in session_id:
        return

    try:
        (
            client.table("workflow_sessions")
            .update({"updated_at": _utc_now()})
            .eq("id", session_id)
            .execute()
        )
    except Exception as error:
        print(f"[conversation_store] touch_workflow_session error: {error}")


def record_workflow_message(
    *,
    session_id: str,
    role: str,
    message_type: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    payload = {
        "workflow_session_id": session_id,
        "role": role,
        "message_type": message_type,
        "content": content,
        "metadata": metadata or {},
        "created_at": _utc_now(),
    }
    _safe_insert("workflow_messages", payload)


def record_workflow_event(
    *,
    session_id: str,
    event_type: str,
    payload: dict | None = None,
) -> None:
    data = {
        "workflow_session_id": session_id,
        "event_type": event_type,
        "payload": payload or {},
        "created_at": _utc_now(),
    }
    _safe_insert("workflow_events", data)


def list_conversation_messages(user_id: str) -> list[dict]:
    client = get_supabase_client()
    if client is None:
        return []

    try:
        result = (
            client.table("conversations")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return getattr(result, "data", None) or []
    except Exception as error:
        print(f"[conversation_store] list_conversation_messages error: {error}")
        return []


def list_workflow_sessions(user_id: str, channel: str, session_key: str) -> list[dict]:
    result = _safe_query(
        "workflow_sessions",
        lambda table: (
            table.select("*")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .eq("session_key", session_key)
            .order("updated_at", desc=True)
        ),
    )
    rows = getattr(result, "data", None) if result is not None else None
    if rows:
        return rows

    user = get_user(user_id)
    return [
        {
            "id": f"{channel}:{session_key}",
            "user_id": user_id,
            "channel": channel,
            "session_key": session_key,
            "status": "active",
            "title": (user or {}).get("username") or "Current session",
            "updated_at": _utc_now(),
        }
    ]
