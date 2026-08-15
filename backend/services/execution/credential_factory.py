"""Per-user credential resolution for globally registered BridgeAdapters.

The ``credentials_factory`` callable is the standard mechanism supported
by ``BridgeAdapter`` for resolving credentials at dispatch time instead
of baking them into the adapter at registration time.

This module provides a factory that reads the target user ID from the
execution task's plan params and resolves Google OAuth2 credentials
from the database, including automatic token refresh.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import ExecutionTask

logger = logging.getLogger(__name__)

# Param key used to carry the target user ID from plan construction
# through to credential resolution.
_CREDENTIAL_USER_ID_PARAM = "credential_user_id"

# Per-user locks to prevent concurrent OAuth token refreshes for the
# same user.  Unrelated users refresh independently.
_USER_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_USER_REFRESH_LOCKS_LOCK = threading.Lock()


def _get_user_lock(user_id: str) -> threading.Lock:
    """Return (or create) a per-user lock for serialising refreshes."""
    with _USER_REFRESH_LOCKS_LOCK:
        if user_id not in _USER_REFRESH_LOCKS:
            _USER_REFRESH_LOCKS[user_id] = threading.Lock()
        return _USER_REFRESH_LOCKS[user_id]


def resolve_google_credentials(
    task: ExecutionTask,
    context: ExecutionContext,
) -> dict[str, str]:
    """Resolve Google OAuth2 credentials for the user identified in a task.

    Reads ``credential_user_id`` from ``task.plan_task.params``, looks up
    the user, checks token expiry, refreshes if necessary, and returns a
    credentials dict suitable for ``GoogleApiAdapter``.

    Concurrent calls for the **same** user serialise on a per-user lock
    so that at most one OAuth refresh request is in flight at a time.
    Unrelated users proceed in parallel.

    Args:
        task: The execution task whose plan params carry the user ID.
        context: Execution context (unused, but part of the factory
                 signature defined by BridgeAdapter).

    Returns:
        A dict with ``access_token`` and ``token_type`` keys, or an
        empty dict if the user cannot be found or credentials cannot
        be resolved.
    """
    user_id = task.plan_task.params.get(_CREDENTIAL_USER_ID_PARAM)
    if not user_id:
        logger.warning(
            "No '%s' param on task '%s' — returning empty credentials",
            _CREDENTIAL_USER_ID_PARAM, task.id,
        )
        return {}

    from services.supabase import get_google_credentials, is_token_expired
    from services.google_auth import refresh_access_token
    from services.supabase import update_google_access_token

    creds = get_google_credentials(user_id)
    if not creds:
        logger.warning(
            "User '%s' has no google connected account — returning empty credentials",
            user_id,
        )
        return {}

    # Fast path: token is still fresh — no lock needed.
    if not is_token_expired(creds.get("token_expiry")):
        access_token = creds.get("access_token") or ""
        return {"access_token": access_token, "token_type": "Bearer"}

    # Token is (or appears) expired.  Serialise refreshes per user so
    # that concurrent tasks don't fire duplicate refresh requests.
    with _get_user_lock(user_id):
        # Re-read credentials — another thread may have already refreshed.
        creds = get_google_credentials(user_id)
        if not creds:
            return {}
        if not is_token_expired(creds.get("token_expiry")):
            access_token = creds.get("access_token") or ""
            return {"access_token": access_token, "token_type": "Bearer"}

        try:
            refresh_token = creds.get("refresh_token", "")
            if not refresh_token:
                logger.warning(
                    "User '%s' has no refresh_token — cannot refresh", user_id,
                )
                return {}

            # Reauth-required: Google already rejected this credential. Do NOT
            # keep attempting the doomed refresh — surface the failure once
            # and return empty so callers fail cleanly (PR10.8.1).
            from services.supabase import is_connected_account_reauth_required
            if is_connected_account_reauth_required(user_id, "google"):
                logger.warning(
                    "gmail_auth_reauth_required user_id=%s action=reauth_required skip_refresh=yes",
                    user_id,
                )
                return {}

            refreshed = refresh_access_token(refresh_token)
            access_token = refreshed.get("access_token", "")
            updated = update_google_access_token(
                user_id,
                access_token=access_token,
                token_expiry=refreshed.get("token_expiry"),
            )
            if updated:
                logger.info("Refreshed access token for user '%s'", user_id)
        except Exception as e:
            logger.error("Token refresh failed for user '%s': %s", user_id, e)
            return {}

    return {"access_token": access_token, "token_type": "Bearer"}
