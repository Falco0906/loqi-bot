import os
import re
import threading
from datetime import datetime, timezone

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


def test_supabase_connection() -> bool:
    _log("test_supabase_connection called")
    client = get_supabase_client()
    if client is None:
        _log("test_supabase_connection aborted: no client")
        return False

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
        return True
    except Exception as error:
        _log(f"test_supabase_connection error: {error}")
        return False


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


def get_or_create_oauth_user(
    provider: str,
    provider_subject: str,
    *,
    email: str = "",
    username: str = "",
) -> tuple[dict | None, bool]:
    """Persist a provider identity using the legacy users table.

    The identity-platform tables are not present in every existing Loqi
    workspace yet. Until that migration is applied, the legacy users table's
    stable telegram_id column provides a durable bridge for OAuth identities.
    The boolean indicates whether this provider identity was created now.
    """
    client = get_supabase_client()
    if client is None or not provider_subject:
        return None, False

    try:
        # Prefer an identity already associated with this email when the
        # identity table exists, allowing accounts created by the newer schema
        # to be recognized during the transition.
        if email:
            identity_result = (
                client.table("email_identities")
                .select("user_id")
                .eq("email", email)
                .limit(1)
                .execute()
            )
            identity_rows = getattr(identity_result, "data", None) or []
            if identity_rows:
                user = get_user(str(identity_rows[0].get("user_id", "")))
                if user:
                    return user, False
    except Exception:
        # Older deployments may not have email_identities yet. The stable
        # provider subject fallback below remains safe and deterministic.
        pass

    synthetic_id = f"oauth:{provider}:{provider_subject}"
    existing = (
        client.table("users")
        .select("*")
        .eq("telegram_id", synthetic_id)
        .limit(1)
        .execute()
    )
    existing_user = _first_row(existing)
    if existing_user:
        return existing_user, False

    user = get_or_create_user(
        synthetic_id,
        username=username or (email.split("@", 1)[0] if email else provider),
    )
    return user, user is not None


def update_user_telegram_chat_id(user_id: str, telegram_chat_id: int) -> dict | None:
    _log(
        "update_user_telegram_chat_id called: "
        f"user_id={user_id}, telegram_chat_id={telegram_chat_id}"
    )
    client = get_supabase_client()
    if client is None:
        _log("update_user_telegram_chat_id aborted: no client")
        return None

    try:
        result = (
            client.table("users")
            .update({"telegram_chat_id": str(telegram_chat_id)})
            .eq("id", user_id)
            .execute()
        )
        user = _first_row(result)
        _log(f"update_user_telegram_chat_id success: {user}")
        return user
    except Exception as error:
        _log(f"update_user_telegram_chat_id error: {error}")
        return None


def get_user(user_id: str) -> dict | None:
    _log(f"get_user called: user_id={user_id}")
    client = get_supabase_client()
    if client is None:
        _log("get_user aborted: no client")
        return None

    try:
        result = client.table("users").select("*").eq("id", user_id).limit(1).execute()
        user = _first_row(result)
        _log(f"get_user success: {user}")
        return user
    except Exception as error:
        _log(f"get_user error: {error}")
        return None


def _run_coro(coro):
    """Run an async persistence call from sync code; safe inside a running loop."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro())
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(coro()), daemon=True).start()


def _parse_dt(value):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def sync_connected_account(
    user_id: str,
    *,
    provider: str,
    account_id: str = "",
    email: str = "",
    access_token: str = "",
    refresh_token: str = "",
    token_expiry: str | None = None,
) -> bool:
    """Mirror OAuth tokens into the canonical connected_accounts table.

    The legacy users google_* columns remain the compatibility bridge; this is
    the canonical dual-write so tokens never live in only one place.
    """
    from services.persistence.launch import ConnectedAccount, ConnectedAccountRepository
    try:
        repo = ConnectedAccountRepository()
        if not account_id:
            account_id = email

        async def _upsert():
            existing = await repo.find_for_user(user_id, provider)
            if existing:
                existing.email = email or existing.email
                existing.access_token = access_token or existing.access_token
                existing.refresh_token = refresh_token or existing.refresh_token
                if token_expiry:
                    existing.token_expires_at = _parse_dt(token_expiry)
                existing.status = "active"
                await repo.save(existing)
            else:
                await repo.save(ConnectedAccount(
                    user_id=user_id,
                    provider=provider,
                    account_id=account_id,
                    display_name=email,
                    email=email,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expires_at=_parse_dt(token_expiry),
                    status="active",
                ))

        _run_coro(_upsert)
        return True
    except Exception as error:
        _log(f"sync_connected_account error: {error}")
        return False


def save_google_tokens(
    user_id: str,
    *,
    email: str,
    telegram_chat_id: int | None,
    access_token: str,
    refresh_token: str,
    token_expiry: str | None,
) -> dict | None:
    _log(
        "save_google_tokens called: "
        f"user_id={user_id}, email={email}, telegram_chat_id={telegram_chat_id}, token_expiry={token_expiry}"
    )
    client = get_supabase_client()
    if client is None:
        _log("save_google_tokens aborted: no client")
        return None

    payload = {
        "google_access_token": access_token,
        "google_refresh_token": refresh_token,
        "token_expiry": token_expiry,
    }
    if telegram_chat_id is not None:
        payload["telegram_chat_id"] = str(telegram_chat_id)

    user = None
    try:
        result = (
            client.table("users")
            .update(payload)
            .eq("id", user_id)
            .execute()
        )
        user = _first_row(result)
        _log(f"save_google_tokens success: {user}")
    except Exception as error:
        _log(f"save_google_tokens error: {error}")
        # The current legacy schema has no users.email column. Tokens are
        # still durable in the Google-specific columns, so retry without the
        # optional email field instead of reporting a false connection error.
        if "email" in str(error):
            try:
                result = (
                    client.table("users")
                    .update({
                        "google_access_token": access_token,
                        "google_refresh_token": refresh_token,
                        "token_expiry": token_expiry,
                        **({"telegram_chat_id": str(telegram_chat_id)} if telegram_chat_id is not None else {}),
                    })
                    .eq("id", user_id)
                    .execute()
                )
                user = _first_row(result)
            except Exception as retry_error:
                _log(f"save_google_tokens compatibility retry error: {retry_error}")

    if user is not None:
        sync_connected_account(
            user_id,
            provider="google",
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
        )
    return user


def update_google_access_token(
    user_id: str,
    *,
    access_token: str,
    token_expiry: str | None,
) -> dict | None:
    _log(
        "update_google_access_token called: "
        f"user_id={user_id}, token_expiry={token_expiry}"
    )
    client = get_supabase_client()
    if client is None:
        _log("update_google_access_token aborted: no client")
        return None

    try:
        result = (
            client.table("users")
            .update(
                {
                    "google_access_token": access_token,
                    "token_expiry": token_expiry,
                }
            )
            .eq("id", user_id)
            .execute()
        )
        user = _first_row(result)
        _log(f"update_google_access_token success: {user}")
        if user is not None:
            sync_connected_account(
                user_id,
                provider="google",
                access_token=access_token,
                token_expiry=token_expiry,
            )
        return user
    except Exception as error:
        _log(f"update_google_access_token error: {error}")
        return None


def is_token_expired(token_expiry: str | None) -> bool:
    _log(f"is_token_expired called: token_expiry={token_expiry}")
    if not token_expiry:
        _log("is_token_expired result: True (missing token_expiry)")
        return True

    try:
        expiry = datetime.fromisoformat(token_expiry.replace("Z", "+00:00"))
        expired = expiry <= datetime.now(timezone.utc)
        _log(f"is_token_expired result: {expired}")
        return expired
    except Exception as error:
        _log(f"is_token_expired error: {error}")
        return True


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


def get_user_preferences(user_id: str) -> dict | None:
    _log(f"get_user_preferences called: user_id={user_id}")
    client = get_supabase_client()
    if client is None:
        _log("get_user_preferences aborted: no client")
        return None

    try:
        result = client.table("user_preferences").select("*").eq("user_id", user_id).limit(1).execute()
        prefs = _first_row(result)
        _log(f"get_user_preferences success: {prefs}")
        if prefs:
            return {
                "tone": prefs.get("tone"),
                "length": prefs.get("length"),
                "style": prefs.get("style"),
                "industry_focus": prefs.get("industry_focus"),
            }
        return None
    except Exception as error:
        _log(f"get_user_preferences error: {error}")
        return None


def save_user_preference(user_id: str, key: str, value: str) -> None:
    _log(f"save_user_preference called: user_id={user_id}, key={key}, value={value}")
    client = get_supabase_client()
    if client is None:
        _log("save_user_preference aborted: no client")
        return

    try:
        existing = client.table("user_preferences").select("*").eq("user_id", user_id).limit(1).execute()
        existing_row = _first_row(existing)

        if existing_row:
            result = (
                client.table("user_preferences")
                .update({key: value})
                .eq("user_id", user_id)
                .execute()
            )
        else:
            payload = {"user_id": user_id, key: value}
            result = client.table("user_preferences").insert(payload).execute()

        _log(f"save_user_preference success")
    except Exception as error:
        _log(f"save_user_preference error: {error}")


def save_provider_credentials(
    user_id: str,
    provider_id: str,
    *,
    access_token: str,
    refresh_token: str,
    token_expiry: str,
    email: str,
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    """Persist provider credentials on the authenticated user's row."""
    _log(f"save_provider_credentials: user_id={user_id}, provider_id={provider_id}, email={email}")
    # OAuth now passes the durable Loqi user ID. Only use the legacy
    # provider:* row for callers that have no authenticated account.
    user = get_user(user_id)
    if not user:
        synthetic_id = f"provider:{user_id}"
        user = get_or_create_user(synthetic_id, username=f"Provider:{provider_id[:8]}")
    if not user:
        _log("save_provider_credentials: failed to get or create user")
        return False
    result = save_google_tokens(
        user["id"],
        email=email,
        telegram_chat_id=None,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
    )
    if result:
        try:
            client = get_supabase_client()
            if client:
                client.table("users").update({
                    "google_client_id": client_id,
                    "google_client_secret": client_secret,
                    "google_provider_id": provider_id,
                }).eq("id", user["id"]).execute()
        except Exception as e:
            _log(f"save_provider_credentials: extra fields update error: {e}")
    return result is not None


def load_all_provider_credentials() -> list[dict]:
    """Load all persisted provider credentials.

    Prefers the canonical connected_accounts table; falls back to the legacy
    users google_* columns for compatibility. Returns legacy-shaped rows with:
    id, google_provider_id, access_token, refresh_token, token_expiry, email.
    """
    _log("load_all_provider_credentials called")
    client = get_supabase_client()
    if client is None:
        _log("load_all_provider_credentials: no client")
        return []

    # Canonical read: connected_accounts first.
    canonical_rows = []
    try:
        result = (
            client.table("connected_accounts")
            .select("user_id, provider, email, display_name, access_token, refresh_token, token_expires_at, status")
            .neq("refresh_token", "")
            .neq("refresh_token", None)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        for r in rows:
            if not r.get("refresh_token"):
                continue
            canonical_rows.append({
                "id": r.get("user_id", ""),
                "google_provider_id": r.get("provider", "google") + "-" + (r.get("email") or r.get("display_name") or ""),
                "google_refresh_token": r.get("refresh_token", ""),
                "google_access_token": r.get("access_token", ""),
                "email": r.get("email") or r.get("display_name") or "",
                "google_client_id": "",
                "google_client_secret": "",
                "token_expiry": r.get("token_expires_at") or "",
                "telegram_id": "",
                "_canonical": True,
            })
    except Exception as canonical_error:
        _log(f"load_all_provider_credentials canonical read error: {canonical_error}")
    if canonical_rows:
        _log(f"load_all_provider_credentials: found {len(canonical_rows)} canonical credential records")
        return canonical_rows

    # Legacy fallback: users table google_* columns.
    try:
        result = (
            client.table("users")
            .select("id, google_access_token, google_refresh_token, token_expiry, google_client_id, google_client_secret, google_provider_id, telegram_id")
            .neq("google_refresh_token", "")
            .neq("google_refresh_token", None)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        for r in rows:
            r["email"] = ""
        # Include authenticated users as well as legacy provider:* rows. The
        # old filter made stable-account credentials invisible on restart.
        rows = [r for r in rows if r.get("google_refresh_token")]
        _log(f"load_all_provider_credentials: found {len(rows)} legacy credential records")
        return rows
    except Exception as e:
        _log(f"load_all_provider_credentials legacy error: {e}")
        return []
