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


def _run_blocking(coro_or_fn, timeout: float = 30.0):
    """Run a coroutine to completion from sync code; blocks.

    Safe both outside and inside a running event loop (a dedicated thread
    runs the coroutine and the caller joins it). A failure in the runner
    thread is re-raised on the caller thread so errors are never silently
    swallowed (PR10.8.2.1).
    """
    import asyncio
    import inspect

    coro = coro_or_fn if inspect.iscoroutine(coro_or_fn) else coro_or_fn()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    holder: dict[str, object] = {}

    def runner():
        try:
            holder["value"] = asyncio.run(coro)
        except BaseException as error:  # noqa: BLE001
            holder["error"] = error

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if "error" in holder:
        raise holder["error"]
    return holder.get("value")


def _dt_iso(value) -> str | None:
    """Normalize a datetime (or iso string) to an ISO-8601 string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    except Exception:
        return None


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


def _parse_dt(value):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _encrypt_credential_field(value: str) -> str:
    """Encrypt a persisted credential value; plaintext only when no key is
    configured (development). Production validation requires the key."""
    if not value:
        return value
    from services.credential_crypto import encrypt_token, encryption_key_configured
    if not encryption_key_configured():
        return value
    return encrypt_token(value)


def _decrypt_credential_field(value: str) -> str:
    """Decrypt a stored credential value. Legacy plaintext passes through."""
    if not value:
        return value
    from services.credential_crypto import decrypt_token, is_encrypted
    if not is_encrypted(value):
        return value
    try:
        return decrypt_token(value)
    except Exception:
        _log("credential decryption failed for a connected account (token skipped)")
        return ""


def _migrate_legacy_credentials(user_id: str, provider: str, access_token: str, refresh_token: str) -> None:
    """Encrypt-on-write for legacy plaintext credentials once a key is set."""
    from services.credential_crypto import encryption_key_configured, is_encrypted
    if not encryption_key_configured():
        return
    if (is_encrypted(access_token) or not access_token) and (is_encrypted(refresh_token) or not refresh_token):
        return
    try:
        _run_blocking(_upsert_connected_account(
            user_id=user_id,
            provider=provider,
            access_token=_encrypt_credential_field(access_token),
            refresh_token=_encrypt_credential_field(refresh_token),
        ))
        _log(f"legacy provider credentials migrated to encrypted form (user={user_id}, provider={provider})")
    except Exception as error:
        _log(f"legacy credential migration failed: {error}")


async def _upsert_connected_account(
    *,
    user_id: str,
    provider: str,
    account_id: str = "",
    email: str = "",
    access_token: str = "",
    refresh_token: str = "",
    token_expiry: str | None = None,
) -> bool:
    """Upsert a connected_account row; canonical store for OAuth credentials.

    Idempotent by ``(user_id, provider)``, so transient network failures are
    retried with bounded backoff (PR10.8); the caller still receives the
    failure if the budget is exhausted.
    """
    from services.persistence.launch import ConnectedAccount, ConnectedAccountRepository
    from services.persistence.retry import retry_async

    async def _perform() -> bool:
        repo = ConnectedAccountRepository()
        resolved_account_id = account_id or email
        enc_access = _encrypt_credential_field(access_token)
        enc_refresh = _encrypt_credential_field(refresh_token)
        existing = await repo.find_for_user(user_id, provider)
        if existing:
            if email:
                existing.email = email
            if resolved_account_id:
                existing.account_id = resolved_account_id
            if enc_access:
                existing.access_token = enc_access
            if enc_refresh:
                existing.refresh_token = enc_refresh
            if token_expiry:
                existing.token_expires_at = _parse_dt(token_expiry)
            existing.status = "active"
            existing.deleted_at = None
            await repo.save(existing)
        else:
            await repo.save(ConnectedAccount(
                user_id=user_id,
                provider=provider,
                account_id=resolved_account_id,
                display_name=email,
                email=email,
                access_token=enc_access,
                refresh_token=enc_refresh,
                token_expires_at=_parse_dt(token_expiry),
                status="active",
            ))
        return True

    return await retry_async(_perform, category="connected_accounts")


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

    connected_accounts is the exclusive source of truth for provider
    credentials; the legacy ``users`` google_* columns are no longer read or
    written by the application.

    Idempotent by ``(user_id, provider)``: reconnecting the same Google
    account updates the existing row in place (new credentials, ``account_id``
    identity, status back to ``active``) instead of creating a duplicate.
    """
    try:
        return bool(_run_blocking(_upsert_connected_account(
            user_id=user_id,
            provider=provider,
            account_id=account_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
        )))
    except Exception as error:
        _log(f"sync_connected_account error: {error}")
        return False


def get_google_credentials(user_id: str) -> dict | None:
    """Return OAuth credentials for the user's google connected account.

    Canonical source: ``connected_accounts``. Returns
    ``{access_token, refresh_token, token_expiry}`` or None when the user has
    no google account connected.
    """
    from services.persistence.launch import ConnectedAccountRepository

    def _read():
        async def fetch():
            repo = ConnectedAccountRepository()
            account = await repo.find_for_user(user_id, "google")
            if account is None:
                return None
            raw_access = account.access_token or ""
            raw_refresh = account.refresh_token or ""
            _migrate_legacy_credentials(user_id, "google", raw_access, raw_refresh)
            return {
                "access_token": _decrypt_credential_field(raw_access),
                "refresh_token": _decrypt_credential_field(raw_refresh),
                "token_expiry": _dt_iso(account.token_expires_at),
            }
        return _run_blocking(fetch())

    try:
        return _read()
    except Exception as error:
        _log(f"get_google_credentials error: {error}")
        return None


def has_connected_account(user_id: str, provider: str = "google") -> bool:
    """Return True when the user has a live connected account for ``provider``."""
    from services.persistence.launch import ConnectedAccountRepository

    def _check():
        async def fetch():
            repo = ConnectedAccountRepository()
            account = await repo.find_for_user(user_id, provider)
            return account is not None and bool(
                account.refresh_token or account.access_token
            )
        return _run_blocking(fetch())

    try:
        return bool(_check())
    except Exception as error:
        _log(f"has_connected_account error: {error}")
        return False


def is_connected_account_reauth_required(user_id: str, provider: str = "google") -> bool:
    """Return True when the stored account is in the reauth-required state.

    Re-auth-required means Google rejected the refresh credential
    (``invalid_grant``); the account stays persisted but is skipped by sync
    until the user reconnects. Safe metadata only — never logs tokens.
    """
    from services.persistence.launch import ConnectedAccountRepository

    def _check():
        async def fetch():
            repo = ConnectedAccountRepository()
            account = await repo.find_for_user(user_id, provider)
            if account is None:
                return False
            return str(getattr(account, "status", "") or "") == "auth_failed"
        return _run_blocking(fetch())

    try:
        return bool(_check())
    except Exception as error:
        _log(f"is_connected_account_reauth_required error: {error}")
        return False


def mark_connected_account_auth_failed(user_id: str, provider: str = "google") -> bool:
    """Persist the reauth-required condition on the connected_accounts row.

    Uses the existing repository write path (no new persistence model). The
    status field is cleared back to ``active`` automatically when the user
    reconnects via ``sync_connected_account``. Never touches tokens.
    """
    from services.persistence.launch import ConnectedAccountRepository

    def _run():
        async def fetch():
            repo = ConnectedAccountRepository()
            account = await repo.find_for_user(user_id, provider)
            if account is None:
                return False
            account.status = "auth_failed"
            await repo.save(account)
            return True
        return _run_blocking(fetch())

    try:
        ok = bool(_run())
        if ok:
            _log(f"connected account marked auth_failed (user={user_id}, provider={provider})")
        return ok
    except Exception as error:
        _log(f"mark_connected_account_auth_failed error: {error}")
        return False


def _ensure_identity_user(user_id: str, display_name: str = "") -> bool:
    """Ensure a durable ``identity_users`` row exists for ``user_id``.

    ``connected_accounts.user_id`` has a foreign key onto
    ``identity_users``. The web flow resolves users-table ids, so the
    canonical write must be mirrored into ``identity_users`` first or the
    insert fails with 23503 (which sync_connected_account swallows).
    """
    _log(f"_ensure_identity_user called: user_id={user_id}")
    client = get_supabase_client()
    if client is None:
        _log("_ensure_identity_user aborted: no client")
        return False
    try:
        found = (
            client.table("identity_users")
            .select("id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if getattr(found, "data", None):
            return True
        client.table("identity_users").insert({
            "id": user_id,
            "display_name": display_name or "web-user",
            "locale": "en",
            "email": "",
            "metadata": {},
            "version": 1,
        }).execute()
        _log(f"_ensure_identity_user created row for {user_id}")
        return True
    except Exception as error:
        _log(f"_ensure_identity_user error: {error}")
        return False


def save_google_tokens(
    user_id: str,
    *,
    email: str,
    telegram_chat_id: int | None,
    access_token: str,
    refresh_token: str,
    token_expiry: str | None,
    account_id: str = "",
) -> dict | None:
    """Persist OAuth tokens in connected_accounts (the canonical store).

    Credentials live exclusively in connected_accounts; the users table only
    records the optional telegram_chat_id routing field. Returns a truthy
    dict so callers can treat None as failure.
    """
    _log(
        "save_google_tokens called: "
        f"user_id={user_id}, email={email}, telegram_chat_id={telegram_chat_id}, token_expiry={token_expiry}"
    )
    client = get_supabase_client()
    if client is None:
        _log("save_google_tokens aborted: no client")
        return None

    user_payload = {}
    if telegram_chat_id is not None:
        user_payload["telegram_chat_id"] = str(telegram_chat_id)

    user = None
    if user_payload:
        try:
            result = (
                client.table("users")
                .update(user_payload)
                .eq("id", user_id)
                .execute()
            )
            user = _first_row(result)
            _log(f"save_google_tokens success: {user}")
        except Exception as error:
            _log(f"save_google_tokens error: {error}")
    else:
        user = get_user(user_id)

    if not _ensure_identity_user(user_id, display_name=(user or {}).get("username", "")):
        _log(f"save_google_tokens: identity_users row missing or uncreatable for {user_id}")
        return None

    ok = sync_connected_account(
        user_id,
        provider="google",
        account_id=account_id,
        email=email,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
    )
    if not ok:
        _log("save_google_tokens: connected_account write failed")
        return None
    return user or {"user_id": user_id}


def update_google_access_token(
    user_id: str,
    *,
    access_token: str,
    token_expiry: str | None,
) -> dict | None:
    """Persist a refreshed Google access token in connected_accounts.

    This is the canonical write for refreshed tokens; credentials live
    exclusively in connected_accounts, never in the legacy users google_*
    columns. Returns a truthy dict with the persisted values so callers can
    treat None as failure.
    """
    _log(
        "update_google_access_token called: "
        f"user_id={user_id}, token_expiry={token_expiry}"
    )
    try:
        ok = sync_connected_account(
            user_id,
            provider="google",
            access_token=access_token,
            token_expiry=token_expiry,
        )
        if not ok:
            return None
        return {"access_token": access_token, "token_expiry": token_expiry}
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
    account_id: str = "",
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
        account_id=account_id,
    )
    return result is not None


def reconcile_connected_account_duplicates(user_id: str | None = None) -> int:
    """Soft-delete obsolete duplicate connected_account rows (safe, reversible).

    Canonical rule: one active row per ``(user_id, provider)``. For each
    duplicate group the newest row that still has a refresh token is the
    canonical row; obsolete duplicates are soft-deleted (``deleted_at``) —
    credentials are never decrypted/logged here.

    Returns the number of rows deactivated. Safe to run at any time; the
    DB-level unique index (020 migration) enforces the invariant going forward.
    """
    from services.persistence.launch import ConnectedAccountRepository
    from services.persistence.launch.models import ConnectedAccount

    def _run():
        async def fetch():
            repo = ConnectedAccountRepository()
            if user_id:
                accounts = await repo.list_for_user(user_id)
            else:
                accounts = await repo._list(
                    [("deleted_at", "is", "null")],
                    order="created_at", desc=True, limit=5000,
                )
            by_key: dict[tuple[str, str], list[ConnectedAccount]] = {}
            for account in accounts:
                by_key.setdefault((account.user_id, account.provider), []).append(account)

            deactivated = 0
            for group in by_key.values():
                if len(group) <= 1:
                    continue
                # Prefer a row with a real refresh token, then newest created.
                canonical = max(
                    group,
                    key=lambda a: (
                        bool(a.refresh_token and len(a.refresh_token) >= 20),
                        a.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    ),
                )
                for other in group:
                    if other.id == canonical.id:
                        continue
                    other.deleted_at = datetime.now(timezone.utc)
                    await repo.save(other)
                    deactivated += 1
            return deactivated
        return _run_blocking(fetch())

    try:
        count = _run()
        if count:
            _log(f"reconcile_connected_account_duplicates deactivated {count} obsolete row(s)")
        return count
    except Exception as error:
        _log(f"reconcile_connected_account_duplicates error: {error}")
        return 0


def load_all_provider_credentials() -> list[dict]:
    """Load all persisted provider credentials.

    Sole source of truth is the canonical connected_accounts table. Returns
    legacy-shaped rows (id, google_provider_id, access_token, refresh_token,
    token_expiry, email) for backward compatibility with existing callers.
    """
    _log("load_all_provider_credentials called")
    client = get_supabase_client()
    if client is None:
        _log("load_all_provider_credentials: no client")
        return []

    canonical_rows = []
    try:
        result = (
            client.table("connected_accounts")
            .select("user_id, provider, email, display_name, account_id, access_token, refresh_token, token_expires_at, status, created_at")
            .neq("refresh_token", "")
            .neq("refresh_token", None)
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        seen: dict[tuple[str, str], dict] = {}
        for r in rows:
            access_token = _decrypt_credential_field((r.get("access_token") or "").strip())
            refresh_token = _decrypt_credential_field((r.get("refresh_token") or "").strip())
            if refresh_token:
                _migrate_legacy_credentials(
                    str(r.get("user_id") or ""), str(r.get("provider") or "google"),
                    access_token, refresh_token,
                )
            if len(refresh_token) < 20:
                _log(
                    f"load_all_provider_credentials: skipping row without a real refresh token "
                    f"(email={r.get('email')}, len={len(refresh_token)})"
                )
                continue
            key = (str(r.get("user_id") or ""), str(r.get("provider") or "google"))
            # Canonical row per (user_id, provider): rows are ordered newest
            # first, so the first seen wins. Obsolete duplicates are skipped.
            if key in seen:
                _log(
                    f"load_all_provider_credentials: skipping duplicate row "
                    f"(user={key[0]}, provider={key[1]}) — canonical already selected"
                )
                continue
            seen[key] = r
            canonical_rows.append({
                "id": r.get("user_id", ""),
                "google_provider_id": r.get("provider", "google") + "-" + (r.get("email") or r.get("display_name") or ""),
                "google_refresh_token": refresh_token,
                "google_access_token": access_token,
                "email": r.get("email") or r.get("display_name") or "",
                "google_client_id": "",
                "google_client_secret": "",
                "token_expiry": r.get("token_expires_at") or "",
                "telegram_id": "",
                "account_id": r.get("account_id") or r.get("email") or r.get("display_name") or "",
                "status": r.get("status") or "active",
                "_canonical": True,
            })
    except Exception as canonical_error:
        _log(f"load_all_provider_credentials canonical read error: {canonical_error}")
        return []
    _log(f"load_all_provider_credentials: found {len(canonical_rows)} canonical credential records")
    return canonical_rows
