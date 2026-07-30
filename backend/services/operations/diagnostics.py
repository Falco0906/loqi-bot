from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from services.persistence.config import get_repository_provider

log = logging.getLogger("loqi")

_BUILD_METADATA: dict[str, str] = {}
_STARTUP_TIME: datetime | None = None


def _read_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except Exception:
        return os.getenv("GIT_COMMIT", "")


_BUILD_METADATA["commit"] = _read_commit()
_BUILD_METADATA["build_timestamp"] = datetime.now(timezone.utc).isoformat()


def get_build_metadata() -> dict[str, str]:
    return dict(_BUILD_METADATA)


def set_startup_time() -> None:
    global _STARTUP_TIME
    _STARTUP_TIME = datetime.now(timezone.utc)


def get_startup_time() -> datetime | None:
    return _STARTUP_TIME


REQUIRED_CONFIG: dict[str, str] = {
    "OPENAI_API_KEY": "OpenAI API key for AI generation",
}

SUPABASE_CONFIG: dict[str, str] = {
    "SUPABASE_URL": "Supabase project URL",
    "SUPABASE_KEY": "Supabase API key (anon or service_role)",
}

STRIPE_LIVE_CONFIG: dict[str, str] = {
    "STRIPE_SECRET_KEY": "Stripe secret key for live billing",
    "STRIPE_WEBHOOK_SECRET": "Stripe webhook signing secret",
    "STRIPE_PUBLISHABLE_KEY": "Stripe publishable key",
}


def get_required_vars() -> dict[str, str]:
    provider = get_repository_provider()
    required = dict(REQUIRED_CONFIG)
    if provider.value == "supabase":
        required.update(SUPABASE_CONFIG)
    if os.getenv("BILLING_PROVIDER_MODE", "mock") == "live":
        required.update(STRIPE_LIVE_CONFIG)
    if os.getenv("EMAIL_PROVIDER", "console") == "resend":
        required["EMAIL_API_KEY"] = "Resend API key for transactional email"
        required["EMAIL_FROM"] = "Sender email address for transactional email"
        required["EMAIL_REPLY_TO"] = "Reply-to address for transactional email"
    return required


def validate_config() -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    required = get_required_vars()
    for var, description in required.items():
        if not os.getenv(var):
            errors.append({
                "variable": var,
                "description": description,
                "status": "missing",
            })
    return errors


def log_config_warnings() -> None:
    errors = validate_config()
    if errors:
        log.warning("Configuration validation issues (%d):", len(errors))
        for err in errors:
            log.warning("  - %s: %s (%s)", err["variable"], err["description"], err["status"])


def startup_diagnostics(app: Any) -> None:
    from services.persistence.config import get_repository_provider
    provider = get_repository_provider()
    build = get_build_metadata()

    log.info("=" * 60)
    log.info("Loqi Backend Startup Diagnostics")
    log.info("=" * 60)
    log.info("Application:      Loqi")
    log.info("Version:          %s", _get_version())
    log.info("Environment:      %s", os.getenv("ENVIRONMENT", "development"))
    log.info("Repository:       %s", provider.value)
    log.info("Commit:           %s", build.get("commit", "")[:12] if build.get("commit") else "unknown")
    log.info("Build Timestamp:  %s", build.get("build_timestamp", "unknown"))

    errors = validate_config()
    if errors:
        log.warning("Configuration issues:")
        for err in errors:
            log.warning("  - %s: %s", err["variable"], err["description"])

    routes = [route.path for route in app.routes if hasattr(route, "path")]
    log.info("Routes:           %d", len(routes))

    duration = ""
    if _STARTUP_TIME:
        elapsed = datetime.now(timezone.utc) - _STARTUP_TIME
        duration = f"{elapsed.total_seconds():.3f}s"
    log.info("Startup duration: %s", duration)
    log.info("=" * 60)


def _get_version() -> str:
    return os.getenv("APP_VERSION", "0.2.0")
