import os
import re

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
TERMINAL_MESSAGES = {
    "Type /start when you are ready to reach out to more leads.",
    "Operation cancelled. Type /start to try again.",
}

_client: Client | None = None


def _log(message: str) -> None:
    print(f"[supabase] {message}")


def get_supabase_client() -> Client | None:
    _log("get_supabase_client called")
    global _client

    if _client is not None:
        _log("get_supabase_client returning cached client")
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        _log("get_supabase_client error: missing SUPABASE_URL or SUPABASE_KEY")
        return None

    try:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _log("get_supabase_client success: client created")
        return _client
    except Exception as error:
        _log(f"get_supabase_client error: {error}")
        return None


def _first_row(result) -> dict | None:
    data = getattr(result, "data", None) or []
    return data[0] if data else None


def test_supabase_connection() -> None:
    _log("test_supabase_connection called")
    client = get_supabase_client()
    if client is None:
        _log("test_supabase_connection aborted: no client")
        return

    try:
        telegram_id = "test_123"
        _log(f"test_supabase_connection input query: telegram_id={telegram_id}")
        existing_result = (
            client.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        existing_user = _first_row(existing_result)

        if existing_user:
            _log(f"test_supabase_connection existing user found: {existing_user}")
        else:
            payload = {"telegram_id": telegram_id}
            _log(f"test_supabase_connection input insert payload: {payload}")
            insert_result = client.table("users").insert(payload).execute()
            _log(f"test_supabase_connection insert success: {insert_result.data}")

        fetch_result = (
            client.table("users")
            .select("*")
            .eq("telegram_id", "test_123")
            .limit(1)
            .execute()
        )
        _log("test_supabase_connection input fetch: telegram_id=test_123")
        _log(f"test_supabase_connection fetch success: {fetch_result.data}")
    except Exception as error:
        _log(f"test_supabase_connection error: {error}")


def get_or_create_user(telegram_id: str, username: str | None = None) -> dict | None:
    _log(f"get_or_create_user called: telegram_id={telegram_id}, username={username}")
    client = get_supabase_client()
    if client is None:
        _log("get_or_create_user aborted: no client")
        return None

    try:
        _log(f"get_or_create_user input query: telegram_id={telegram_id}")
        existing_result = (
            client.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        existing_user = _first_row(existing_result)
        if existing_user:
            _log(f"get_or_create_user success: existing user found {existing_user}")
            if username and existing_user.get("username") != username:
                try:
                    _log(
                        "get_or_create_user input update: "
                        f"user_id={existing_user['id']}, username={username}"
                    )
                    update_result = (
                        client.table("users")
                        .update({"username": username})
                        .eq("id", existing_user["id"])
                        .execute()
                    )
                    updated_user = _first_row(update_result) or existing_user
                    _log(f"get_or_create_user update success: {updated_user}")
                    return updated_user
                except Exception as error:
                    _log(f"get_or_create_user update error: {error}")
            return existing_user

        insert_payload = {"telegram_id": telegram_id}
        if username:
            insert_payload["username"] = username

        _log(f"get_or_create_user input insert payload: {insert_payload}")
        insert_result = client.table("users").insert(insert_payload).execute()
        created_user = _first_row(insert_result)
        _log(f"get_or_create_user insert success: {created_user}")
        return created_user
    except Exception as error:
        _log(f"get_or_create_user error: {error}")
        return None


def log_conversation(user_id: str, role: str, message: str) -> None:
    _log(
        "log_conversation called: "
        f"user_id={user_id}, role={role}, message={message}"
    )
    client = get_supabase_client()
    if client is None:
        _log("log_conversation aborted: no client")
        return

    try:
        payload = {
            "user_id": user_id,
            "role": role,
            "message": message,
        }
        _log(f"log_conversation input payload: {payload}")
        result = client.table("conversations").insert(payload).execute()
        _log(f"log_conversation success: {result.data}")
    except Exception as error:
        _log(f"log_conversation error: {error}")


def get_session_context(user_id: str) -> dict:
    _log(f"get_session_context called: user_id={user_id}")
    client = get_supabase_client()
    if client is None:
        _log("get_session_context aborted: no client")
        return {
            "started_at": None,
            "user_messages": [],
            "service": None,
            "target": None,
        }

    try:
        _log(f"get_session_context input query: user_id={user_id}")
        result = (
            client.table("conversations")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
    except Exception as error:
        _log(f"get_session_context error: {error}")
        return {
            "started_at": None,
            "user_messages": [],
            "service": None,
            "target": None,
        }

    rows = getattr(result, "data", None) or []
    boundary_index = -1
    boundary_time = None

    for index, row in enumerate(rows):
        message = (row.get("message") or "").strip()
        role = row.get("role")
        if role == "user" and message.lower() == "/start":
            boundary_index = index
            boundary_time = row.get("created_at")
        elif role == "assistant" and message in TERMINAL_MESSAGES:
            boundary_index = index
            boundary_time = row.get("created_at")

    active_rows = rows[boundary_index + 1 :]
    user_messages = [
        (row.get("message") or "").strip()
        for row in active_rows
        if row.get("role") == "user" and (row.get("message") or "").strip().lower() != "/start"
    ]
    assistant_messages = [
        (row.get("message") or "").strip()
        for row in active_rows
        if row.get("role") == "assistant"
    ]

    context = {
        "started_at": boundary_time,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "last_assistant_message": assistant_messages[-1] if assistant_messages else None,
        "service": user_messages[0] if len(user_messages) >= 1 else None,
        "target": user_messages[1] if len(user_messages) >= 2 else None,
        "selected_lead_id": None,
    }

    selected_lead = get_selected_lead(user_id, since_timestamp=boundary_time)
    if selected_lead:
        context["selected_lead_id"] = selected_lead.get("id")

    _log(f"get_session_context success: {context}")
    return context


def store_leads(user_id: str, leads: list[dict]) -> list[dict]:
    _log(f"store_leads called: user_id={user_id}, leads_count={len(leads)}")
    client = get_supabase_client()
    if client is None or not leads:
        if client is None:
            _log("store_leads aborted: no client")
        else:
            _log("store_leads aborted: no leads provided")
        return []

    payload = []
    for lead in leads:
        payload.append(
            {
                "user_id": user_id,
                "name": lead.get("name") or "Unknown",
                "company": lead.get("company") or "Unknown Company",
                "email": lead.get("email") or "",
                "linkedin_url": lead.get("linkedin_url") or "",
                "status": "pending",
            }
        )

    try:
        _log(f"store_leads input payload: {payload}")
        result = client.table("leads").insert(payload).execute()
        stored_leads = getattr(result, "data", None) or []
        _log(f"store_leads success: {stored_leads}")
        return stored_leads
    except Exception as error:
        _log(f"store_leads error: {error}")
        return []


def get_pending_leads(
    user_id: str,
    since_timestamp: str | None = None,
    limit: int = 5,
) -> list[dict]:
    _log(
        "get_pending_leads called: "
        f"user_id={user_id}, since_timestamp={since_timestamp}, limit={limit}"
    )
    client = get_supabase_client()
    if client is None:
        _log("get_pending_leads aborted: no client")
        return []

    try:
        query = (
            client.table("leads")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "pending")
        )
        if since_timestamp:
            query = query.gt("created_at", since_timestamp)

        result = query.order("created_at").limit(limit).execute()
        pending_leads = getattr(result, "data", None) or []
        _log(f"get_pending_leads success: {pending_leads}")
        return pending_leads
    except Exception as error:
        _log(f"get_pending_leads error: {error}")
        return []


def select_lead(
    user_id: str,
    selection_text: str,
    since_timestamp: str | None = None,
) -> dict | None:
    _log(
        "select_lead called: "
        f"user_id={user_id}, selection_text={selection_text}, since_timestamp={since_timestamp}"
    )
    pending_leads = get_pending_leads(user_id, since_timestamp=since_timestamp, limit=5)
    if not pending_leads:
        _log("select_lead aborted: no pending leads found")
        return None

    selected_index = 0
    match = re.search(r"\b([1-5])\b", selection_text)
    if not match:
        _log("select_lead error: selection text did not include a valid lead number")
        return None

    selected_index = int(match.group(1)) - 1

    if selected_index >= len(pending_leads):
        _log(f"select_lead error: selection index {selected_index} out of range")
        return None

    selected_lead = pending_leads[selected_index]
    _log(f"select_lead selected lead: {selected_lead}")
    client = get_supabase_client()
    if client is None:
        _log("select_lead aborted: no client")
        return None

    try:
        result = (
            client.table("leads")
            .update({"status": "selected"})
            .eq("id", selected_lead["id"])
            .execute()
        )
        selected_lead_result = _first_row(result) or selected_lead
        _log(f"select_lead success: {selected_lead_result}")
        return selected_lead_result
    except Exception as error:
        _log(f"select_lead error: {error}")
        return None


def get_selected_lead(
    user_id: str,
    since_timestamp: str | None = None,
) -> dict | None:
    _log(
        "get_selected_lead called: "
        f"user_id={user_id}, since_timestamp={since_timestamp}"
    )
    client = get_supabase_client()
    if client is None:
        _log("get_selected_lead aborted: no client")
        return None

    try:
        query = (
            client.table("leads")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "selected")
        )
        if since_timestamp:
            query = query.gt("created_at", since_timestamp)

        result = query.order("created_at", desc=True).limit(1).execute()
        selected_lead = _first_row(result)
        _log(f"get_selected_lead success: {selected_lead}")
        return selected_lead
    except Exception as error:
        _log(f"get_selected_lead error: {error}")
        return None


def clear_session_context(
    user_id: str,
    since_timestamp: str | None = None,
) -> None:
    _log(
        "clear_session_context called: "
        f"user_id={user_id}, since_timestamp={since_timestamp}"
    )
    client = get_supabase_client()
    if client is None:
        _log("clear_session_context aborted: no client")
        return

    try:
        query = client.table("leads").update({"status": "cleared"}).eq("user_id", user_id)
        if since_timestamp:
            query = query.gt("created_at", since_timestamp)
        result = query.in_("status", ["pending", "selected"]).execute()
        _log(f"clear_session_context success: {getattr(result, 'data', None) or []}")
    except Exception as error:
        _log(f"clear_session_context error: {error}")


def get_lead_by_id(lead_id: str) -> dict | None:
    _log(f"get_lead_by_id called: lead_id={lead_id}")
    client = get_supabase_client()
    if client is None:
        _log("get_lead_by_id aborted: no client")
        return None

    try:
        result = client.table("leads").select("*").eq("id", lead_id).limit(1).execute()
        lead = _first_row(result)
        _log(f"get_lead_by_id success: {lead}")
        return lead
    except Exception as error:
        _log(f"get_lead_by_id error: {error}")
        return None
