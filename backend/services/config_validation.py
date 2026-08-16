"""Centralized environment/configuration validation (PR10.2).

Runs once at application startup (FastAPI lifespan) before any background
worker or provider starts. Fail-fast: invalid or unsafe configuration raises
with a clear, actionable error.

Security contract:
- Every message references the configuration KEY only. Values — especially
  secrets — are never included in errors, warnings, logs, or responses.
- Secrets are never copied or re-serialized here.
"""

from __future__ import annotations

import os
import re
from typing import Mapping
from urllib.parse import urlparse

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
ENV_NAMES = {"development", "production"}

# Production requires the core integrations the product cannot function
# without. Everything else is optional-with-warning, matching the existing
# architecture's degraded-mode support.
PRODUCTION_REQUIRED = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    # SaaS-1.7: the identity crypto service reads these (with DEVELOPMENT
    # fallbacks when unset). Production must never silently fall back to
    # development secrets — require explicit production values.
    "IDENTITY_PEPPER",
    "IDENTITY_SIGNING_KEY_DEFAULT",
)

# Production must never enable development/test behavior.
PRODUCTION_FORBIDDEN_TRUE = (
    "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE",
    "SIMULATE_REPLIES",
    "SIMULATE_ACCELERATED",
)

BOOLEAN_KEYS = (
    "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE",
    "SIMULATE_REPLIES",
    "SIMULATE_ACCELERATED",
    "RATE_LIMIT_ENABLED",
)

URL_KEYS = (
    "SUPABASE_URL",
    "FRONTEND_URL",
    "FRONTEND_ORIGIN",
    "GOOGLE_REDIRECT_URI",
    "GOOGLE_OAUTH_REDIRECT_URI",
)

POSITIVE_INT_KEYS = (
    "PORT",
    "INBOX_SYNC_INTERVAL_SECONDS",
    "RATE_LIMIT_DEFAULT_PER_MINUTE",
    "RATE_LIMIT_AI_PER_MINUTE",
    "RATE_LIMIT_OUTBOUND_PER_MINUTE",
    "RATE_LIMIT_AUTH_PER_MINUTE",
    "RATE_LIMIT_WEBHOOK_PER_MINUTE",
)
POSITIVE_FLOAT_KEYS = ("SIMULATE_REPLY_MULTIPLIER",)

EMAIL_PROVIDERS = {"console", "resend"}
LEAD_PROVIDERS = {"synthetic", "apollo"}
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
LOG_FORMATS = {"text", "json"}

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _raw(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    return "" if value is None else str(value).strip()


def is_production(env: Mapping[str, str] | None = None) -> bool:
    """True when the environment indicator says production.

    Reuses the existing indicators (``ENVIRONMENT`` then ``APP_ENV``), both of
    which default to ``development`` elsewhere in the codebase.
    """
    source = os.environ if env is None else env
    indicator = _raw(source, "ENVIRONMENT") or _raw(source, "APP_ENV") or "development"
    return indicator.lower() == "production"


def _is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_config(env: Mapping[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Validate configuration.

    Returns ``(errors, warnings)``. ``errors`` must cause startup to fail;
    ``warnings`` are advisory only. Key names only — never values.
    """
    source = os.environ if env is None else env
    production = is_production(source)
    errors: list[str] = []
    warnings: list[str] = []

    # ── Environment indicator ──
    indicator = _raw(source, "ENVIRONMENT") or _raw(source, "APP_ENV") or "development"
    if indicator.lower() not in ENV_NAMES:
        errors.append(
            "ENVIRONMENT/APP_ENV must be one of: development, production "
            f"(got an unsupported value)"
        )

    # ── Required in production ──
    if production:
        for key in PRODUCTION_REQUIRED:
            if not _raw(source, key):
                errors.append(f"{key} is required in production and is not set")

    # ── Production safety ──
    if production:
        for key in PRODUCTION_FORBIDDEN_TRUE:
            value = _raw(source, key).lower()
            if value in TRUE_VALUES:
                errors.append(f"{key} must not be enabled in production")
        if _raw(source, "BILLING_PROVIDER_MODE").lower() == "mock":
            errors.append("BILLING_PROVIDER_MODE=mock is not allowed in production")
        if _raw(source, "MOCK_TOKEN"):
            warnings.append("MOCK_TOKEN is set — mock authentication is active")
        if _raw(source, "LOG_LEVEL").upper() == "DEBUG":
            errors.append("LOG_LEVEL=DEBUG is not allowed in production")
        if _raw(source, "RATE_LIMIT_ENABLED").lower() in {"0", "false", "no", "off"}:
            errors.append("RATE_LIMIT_ENABLED must not be disabled in production")
        if not _raw(source, "LOQI_CREDENTIAL_ENCRYPTION_KEY"):
            errors.append("LOQI_CREDENTIAL_ENCRYPTION_KEY is required in production")
        # PR10.8.3: if the Telegram bot is active in production, the webhook
        # must be authenticated with a shared secret (Telegram secret_token).
        if _raw(source, "TELEGRAM_BOT_TOKEN"):
            if not _raw(source, "TELEGRAM_WEBHOOK_SECRET"):
                errors.append(
                    "TELEGRAM_WEBHOOK_SECRET is required in production when "
                    "TELEGRAM_BOT_TOKEN is set (the /webhook endpoint would "
                    "otherwise be unauthenticated)"
                )
        elif not _raw(source, "TELEGRAM_WEBHOOK_SECRET"):
            warnings.append(
                "TELEGRAM_WEBHOOK_SECRET is not set — /webhook is unauthenticated"
            )

    # ── Type / format validation (only when the variable is set) ──
    for key in URL_KEYS:
        value = _raw(source, key)
        if value and not _is_valid_url(value):
            errors.append(f"{key} must be a valid http(s) URL")

    for key in POSITIVE_INT_KEYS:
        value = _raw(source, key)
        if value:
            if not value.isdigit() or int(value) <= 0:
                errors.append(f"{key} must be a positive integer")
            elif key == "PORT" and not (1 <= int(value) <= 65535):
                errors.append(f"{key} must be a valid TCP port (1-65535)")

    for key in POSITIVE_FLOAT_KEYS:
        value = _raw(source, key)
        if value:
            try:
                number = float(value)
            except ValueError:
                errors.append(f"{key} must be a positive number")
                continue
            if number <= 0:
                errors.append(f"{key} must be a positive number")

    for key in BOOLEAN_KEYS:
        value = _raw(source, key)
        if value and value.lower() not in TRUE_VALUES | FALSE_VALUES:
            errors.append(
                f"{key} must be one of: {', '.join(sorted(TRUE_VALUES | FALSE_VALUES))}"
            )

    # ── Provider enums ──
    email_provider = _raw(source, "EMAIL_PROVIDER")
    if email_provider and email_provider.lower() not in EMAIL_PROVIDERS:
        errors.append(f"EMAIL_PROVIDER must be one of: {', '.join(sorted(EMAIL_PROVIDERS))}")
    lead_provider = _raw(source, "LEAD_PROVIDER")
    if lead_provider and lead_provider.lower() not in LEAD_PROVIDERS:
        errors.append(f"LEAD_PROVIDER must be one of: {', '.join(sorted(LEAD_PROVIDERS))}")

    # ── Logging configuration ──
    log_level = _raw(source, "LOG_LEVEL").upper()
    if log_level and log_level not in LOG_LEVELS:
        errors.append(f"LOG_LEVEL must be one of: {', '.join(sorted(LOG_LEVELS))}")
    log_format = _raw(source, "LOG_FORMAT").lower()
    if log_format and log_format not in LOG_FORMATS:
        errors.append(f"LOG_FORMAT must be one of: {', '.join(sorted(LOG_FORMATS))}")

    # ── Credential encryption key (PR10.7) ──
    from services.credential_crypto import is_placeholder_key, is_valid_key_format
    for key_name in ("LOQI_CREDENTIAL_ENCRYPTION_KEY", "LOQI_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS"):
        key_value = _raw(source, key_name)
        if key_value:
            if not is_valid_key_format(key_value):
                errors.append(f"{key_name} must be 64 hex characters (AES-256 key)")
            elif production and key_name == "LOQI_CREDENTIAL_ENCRYPTION_KEY" and is_placeholder_key(key_value):
                errors.append(f"{key_name} must not use a placeholder value in production")

    # ── Conditional requirements ──
    if email_provider.lower() == "resend":
        if production and not _raw(source, "RESEND_API_KEY"):
            errors.append("RESEND_API_KEY is required when EMAIL_PROVIDER=resend in production")
        elif not _raw(source, "RESEND_API_KEY"):
            warnings.append("EMAIL_PROVIDER=resend is set but RESEND_API_KEY is not set")
        if not _raw(source, "RESEND_FROM_EMAIL"):
            warnings.append("RESEND_FROM_EMAIL is not set")
    if lead_provider.lower() == "apollo" and not _raw(source, "APOLLO_API_KEY"):
        warnings.append("LEAD_PROVIDER=apollo is set but APOLLO_API_KEY is not set")

    # ── Optional integration warnings (development / degraded mode) ──
    if not production:
        for key in ("SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY",
                    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            if not _raw(source, key):
                warnings.append(f"{key} is not set (running degraded; feature may be unavailable)")

    return errors, warnings


def assert_valid_startup_config() -> None:
    """Raise on invalid configuration; called once during startup."""
    errors, _warnings = validate_config()
    if errors:
        raise RuntimeError(
            "Configuration validation failed:\n  - " + "\n  - ".join(errors)
        )
