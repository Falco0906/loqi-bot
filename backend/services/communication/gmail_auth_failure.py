"""Gmail OAuth authentication failure classification (PR10.8.1).

Distinguishes PERMANENT re-auth-required conditions from TRANSIENT
failures so the backend can:

- stop hammering Google with a doomed refresh token once Google has
  rejected it with ``invalid_grant``
- keep retrying genuinely transient network/API failures
- log safe metadata only (status, error code) — never raw response
  bodies, tokens, or Authorization headers
"""

from __future__ import annotations


class GmailAuthError(Exception):
    """Base for Gmail auth errors. Message never contains credentials."""


class GmailReauthRequired(GmailAuthError):
    """Permanent: the stored refresh credential is invalid/revoked and the
    user must reconnect Gmail through the existing OAuth flow."""


class GmailTransientError(GmailAuthError):
    """Transient: retryable network/API failure. Provider stays enabled."""


# Google OAuth token-endpoint error codes that mean the stored refresh
# credential is no longer usable and only re-authorization can fix it.
REAUTH_REQUIRED_ERROR_CODES = {"invalid_grant", "unauthorized_client"}

# Codes that are permanent but are NOT a user re-auth problem (client
# misconfiguration, etc.). Kept transient for isolation purposes so a
# provider is never permanently disabled on a config surprise.
TRANSIENT_STATUS_CODES = {429}


def parse_token_response(response) -> tuple[str, str]:
    """Return ``(error_code, error_description)`` from an OAuth token response.

    Safe: never raises on malformed bodies, never returns raw body text.
    ``error_code`` is a short stable token (e.g. ``invalid_grant``) suitable
    for structured logging; ``error_description`` is omitted from logs.
    """
    try:
        data = response.json()
    except Exception:
        return "", ""
    if isinstance(data, dict):
        return str(data.get("error") or ""), str(data.get("error_description") or "")
    return "", ""


def classify_refresh_status(status_code: int, error_code: str) -> str:
    """Classify a token-refresh response.

    Returns one of ``"reauth_required"``, ``"transient"``, ``"success"``.
    Only the ``invalid_grant``/``unauthorized_client`` family is permanent;
    everything else (timeouts, 429, 5xx, unknown 4xx) is transient.
    """
    if 200 <= status_code < 300:
        return "success"
    if status_code == 400 and error_code in REAUTH_REQUIRED_ERROR_CODES:
        return "reauth_required"
    return "transient"


def raise_for_token_response(response, *, provider_id: str = "", user_id: str = "") -> None:
    """Raise a typed exception for a non-2xx token-endpoint response.

    ``GmailReauthRequired`` for permanent credential-invalid responses,
    ``GmailTransientError`` otherwise. The exception messages are sanitized
    (status code only) — callers must log classification, never the body.
    """
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 300:
        return
    error_code, _ = parse_token_response(response)
    if classify_refresh_status(status, error_code) == "reauth_required":
        raise GmailReauthRequired("Gmail account requires re-authentication")
    raise GmailTransientError(f"Gmail token refresh failed (status={status})")
