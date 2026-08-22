"""Rate limiting (PR10.5 → PR-3A).

Two backends behind one interface:

1. REDIS (distributed) — when ``REDIS_URL`` is configured and reachable.
   Atomic fixed-window counter per ``(category, identity, window)`` using a
   small Lua script (INCR + EXPIRE only on first increment) so concurrent
   requests across ALL workers share one bucket and cannot race past the
   limit. Keys auto-expire after the window → bounded memory, correct reset.

2. PROCESS-LOCAL (degraded fallback) — the original Phase-1 limiter, used
   when Redis is unconfigured or unreachable.

Fallback policy (documented, fail-safe):
    Redis down ⇒ per-instance limiting continues. This is STRICTLY stronger
    than no limiting: every instance still enforces the same limits for the
    identities it sees; we never widen the effective limit beyond
    instances × limit during an outage window, and never disable it.

Identity derivation is unchanged and server-side (web-session user id or
client IP). Client-supplied identifiers are never trusted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)

WINDOW_SECONDS = 60
MAX_BUCKETS = 50000

DEFAULT_LIMITS = {
    "auth": 20,
    "ai": 20,
    "outbound": 30,
    "webhook": 120,
    "default": 300,
}

# Atomic fixed-window counter WITHOUT Lua (works on managed/fake Redis):
#   INCR key            → atomic count
#   EXPIRE key win NX   → set TTL only if none exists; never resets a live
#                         window, so concurrent requests cannot extend/bypass.
# The only theoretical gap (crash between INCR and EXPIRE) is closed by
# issuing EXPIRE NX on every hit.

_HEALTH_PATHS = {"/", "/health", "/ready", "/docs", "/openapi.json", "/redoc"}
_AUTH_MARKERS = ("/auth/", "/signup", "/login", "/verify-email", "/logout")
_AI_MARKERS = (
    "/generate-reply",
    "/refine",
    "/generate-strategy",
    "/generate-drafts",
    "/reasoning",
    "/analyze",
    "/ask",
    "/enrich",
    "/recommend",
    "/strategic-updates/refresh",
)
_OUTBOUND_MARKERS = ("/send", "/schedule", "/reply", "/follow-up", "/cancel-schedule")


def classify_rate_limit(path: str) -> str:
    if path in _HEALTH_PATHS:
        return "health"
    if path == "/webhook":
        return "webhook"
    if any(marker in path for marker in _AUTH_MARKERS):
        return "auth"
    if any(marker in path for marker in _OUTBOUND_MARKERS):
        return "outbound"
    if any(marker in path for marker in _AI_MARKERS):
        return "ai"
    return "default"


def rate_limit_enabled(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    indicator = (source.get("ENVIRONMENT") or source.get("APP_ENV") or "development").strip().lower()
    raw = (source.get("RATE_LIMIT_ENABLED") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Default: enabled in production, disabled in development.
    return indicator == "production"


def limits_from_env(env: dict[str, str] | None = None) -> dict[str, int]:
    source = os.environ if env is None else env
    mapping = {
        "auth": "RATE_LIMIT_AUTH_PER_MINUTE",
        "ai": "RATE_LIMIT_AI_PER_MINUTE",
        "outbound": "RATE_LIMIT_OUTBOUND_PER_MINUTE",
        "webhook": "RATE_LIMIT_WEBHOOK_PER_MINUTE",
        "default": "RATE_LIMIT_DEFAULT_PER_MINUTE",
    }
    limits: dict[str, int] = {}
    for category, var in mapping.items():
        raw = (source.get(var) or "").strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = DEFAULT_LIMITS[category]
        limits[category] = max(value, 1) if value > 0 else DEFAULT_LIMITS[category]
    return limits


class RateLimiter:
    """Fixed-window limiter: Redis (distributed) with local degraded fallback.

    ``allow()`` tries the Redis path first whenever a client is available;
    any failure flips to the process-local window for that call. Both paths
    enforce identical limits and windows.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        limits: dict[str, int] | None = None,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self.enabled = rate_limit_enabled() if enabled is None else enabled
        self.limits = dict(limits_from_env() if limits is None else limits)
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()
        # Test/ops seam: force-local mode regardless of Redis availability.
        self.force_local = os.getenv("RATE_LIMIT_FORCE_LOCAL", "").strip().lower() in {"1", "true", "yes"}

    def _now_window(self, now: int) -> int:
        return now - (now % self.window_seconds)

    async def _allow_redis(self, key: str, limit: int) -> tuple[bool, int | None] | None:
        """Distributed attempt. Returns None when Redis is unusable."""
        from services import redis_client
        from services.redis_client import k_rate, hash_token

        if self.force_local or not redis_client.is_configured():
            return None
        client = await redis_client.get_client()
        if client is None:
            return None
        bucket_key = k_rate(key.split(":", 1)[0], hash_token(key), self._now_window(int(time.time())))
        try:
            pipe = client.pipeline()
            pipe.incr(bucket_key)
            pipe.expire(bucket_key, self.window_seconds, nx=True)
            pipe.ttl(bucket_key)
            count, _, ttl = await asyncio.wait_for(pipe.execute(), redis_client.OPERATION_TIMEOUT)
            if int(count) > limit:
                return False, max(int(ttl) if int(ttl) > 0 else self.window_seconds, 1)
            return True, None
        except Exception as error:  # noqa: BLE001 — degrade to local
            log.warning("rate_limit_redis_failed error_type=%s falling_back=local", type(error).__name__)
            return None

    async def allow(self, key: str, limit: int) -> tuple[bool, int | None]:
        """Return ``(allowed, retry_after_seconds)``. ``limit<=0`` = unlimited."""
        if not self.enabled or limit <= 0:
            return True, None
        distributed = await self._allow_redis(key, limit)
        if distributed is not None:
            return distributed
        return await self._allow_local(key, limit)

    async def _allow_local(self, key: str, limit: int) -> tuple[bool, int | None]:
        now = int(time.time())
        current = self._now_window(now)
        async with self._lock:
            self._prune(now)
            entry = self._buckets.get(key)
            if entry is None or entry[0] != current:
                self._buckets[key] = (current, 1)
                self._cap()
                return True, None
            count = entry[1] + 1
            if count > limit:
                retry_after = self.window_seconds - (now % self.window_seconds)
                return False, max(retry_after, 1)
            self._buckets[key] = (current, count)
            return True, None

    async def clear(self) -> None:
        async with self._lock:
            self._buckets.clear()

    def _prune(self, now: int) -> None:
        current = self._now_window(now)
        expired = [key for key, (window_start, _count) in self._buckets.items()
                   if window_start != current]
        for key in expired:
            self._buckets.pop(key, None)
        self._cap()

    def _cap(self) -> None:
        if len(self._buckets) > MAX_BUCKETS:
            for key in list(self._buckets)[: len(self._buckets) - MAX_BUCKETS]:
                self._buckets.pop(key, None)

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)


rate_limiter = RateLimiter()
