"""PR-3A — Centralized Redis infrastructure.

Single access layer for ALL Redis usage in the backend. Application code
never imports ``redis`` directly — it imports this module.

Configuration (environment):
    REDIS_URL            e.g. redis://default:pass@host:6379/0  (or rediss:// for TLS)
    REDIS_KEY_PREFIX     optional namespace override (default "loqi")
    REDIS_TIMEOUT_SECONDS per-operation timeout (default 2.0)

Availability strategy (documented contract, enforced by callers):
    CACHE        → miss/failure degrades to the durable source of truth
    SESSION      → durable auth (Supabase) remains authoritative; Redis only
                   accelerates/coordinates
    RATE LIMIT   → failure falls back to the process-local limiter (fail-closed
                   per instance, never an open gate)
    PUB/SUB      → delivery may be missed; clients refetch durable state

Logging never includes URLs, passwords, tokens or values — only key shapes,
sizes and error types.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "loqi")
OPERATION_TIMEOUT = float(os.getenv("REDIS_TIMEOUT_SECONDS", "2.0"))

_client = None           # redis.asyncio.Redis | None
_unavailable_until = 0.0  # monotonic circuit-breaker timestamp
_FAILURE_BACKOFF = 5.0   # seconds; after a failure, skip Redis briefly


def is_configured() -> bool:
    """True when REDIS_URL is present in the environment."""
    return bool(os.getenv("REDIS_URL", "").strip())


def _marker() -> str:
    """Short, non-reversible marker of the configured URL for logs."""
    url = os.getenv("REDIS_URL", "")
    return hashlib.sha256(url.encode()).hexdigest()[:8] if url else "none"


async def get_client():
    """Return the shared pooled async client, or None when unconfigured.

    A short circuit-breaker window after a connection failure prevents every
    request from paying the connect timeout while Redis is down.
    """
    global _client, _unavailable_until
    import time

    if not is_configured():
        return None
    if time.monotonic() < _unavailable_until:
        return None
    if _client is not None:
        return _client

    try:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            os.environ["REDIS_URL"],
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=OPERATION_TIMEOUT,
            socket_connect_timeout=OPERATION_TIMEOUT,
            health_check_interval=30,
        )
        await _client.ping()
        log.info("redis_connected url_marker=%s pool=shared", _marker())
        return _client
    except Exception as error:  # noqa: BLE001 — degraded mode must never raise
        log.warning(
            "redis_connect_failed error_type=%s url_marker=%s backoff_seconds=%.1f",
            type(error).__name__, _marker(), _FAILURE_BACKOFF,
        )
        _client = None
        _unavailable_until = time.monotonic() + _FAILURE_BACKOFF
        return None


async def close() -> None:
    """Graceful shutdown (called from app lifespan)."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001
            pass
        _client = None


async def healthy() -> bool:
    """Explicit health probe used by readiness checks."""
    client = await get_client()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001
        return False


async def run_with_timeout(op: Callable[[], Awaitable[Any]], fallback: Any) -> Any:
    """Execute a Redis operation; on ANY failure log + return ``fallback``.

    This is THE degraded-mode gate: every caller funnels through here so a
    Redis outage can only ever mean 'behave as if Redis is absent'.
    """
    global _unavailable_until
    import time

    client = await get_client()
    if client is None:
        return fallback
    try:
        return await asyncio_wait_for(op(client), OPERATION_TIMEOUT)
    except Exception as error:  # noqa: BLE001
        log.warning("redis_op_failed error_type=%s", type(error).__name__)
        # Connection-class failures trip the breaker; op errors just degrade.
        _unavailable_until = time.monotonic() + _FAILURE_BACKOFF
        return fallback


async def asyncio_wait_for(aw: Awaitable[Any], timeout: float) -> Any:
    import asyncio
    return await asyncio.wait_for(aw, timeout)


# ─── Key namespace ────────────────────────────────────────────────────────
# loqi:v1:<domain>:<scope>:<id>
# - versioned ("v1") so a future format change can coexist with old keys
# - ids are either server-generated uuids or NON-REVERSIBLE hashes
#   (bearer tokens are NEVER used raw — see hash_token)

VERSION = "v1"


def k_session_identity(token_hash: str) -> str:
    return f"{KEY_PREFIX}:{VERSION}:session:identity:{token_hash}"


def k_session_binding(session_id: str) -> str:
    return f"{KEY_PREFIX}:{VERSION}:session:binding:{session_id}"


def k_rate(category: str, identity_hash: str, window: int) -> str:
    return f"{KEY_PREFIX}:{VERSION}:rate:{category}:{identity_hash}:{window}"


def k_event_channel(scope: str, scope_id: str) -> str:
    return f"{KEY_PREFIX}:{VERSION}:events:{scope}:{scope_id}"


def hash_token(token: str) -> str:
    """Non-reversible cache-key derivation for bearer/session tokens."""
    salt = os.getenv("REDIS_KEY_SALT", KEY_PREFIX)
    return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()[:32]
