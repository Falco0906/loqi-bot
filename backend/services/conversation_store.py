import secrets
from datetime import datetime, timezone

from services.supabase import get_or_create_user, get_supabase_client, get_user


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

    channel_key = f"{channel}:{external_user_id}"
    return get_or_create_user(channel_key, username=username)


def create_lightweight_web_session(display_name: str | None = None) -> dict | None:
    session_token = secrets.token_urlsafe(18)
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
        return _first_row(result)
    except Exception as error:
        print(f"[conversation_store] get_web_session error: {error}")
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
