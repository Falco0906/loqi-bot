"""In-process fixed-window rate limiter (PR10.5).

Design choice:
- Fixed-window algorithm (wall-clock aligned) — deterministic, bounded memory,
  trivially safe under concurrency within one process.
- In-memory only: this is a per-instance limiter. Loqi is currently deployed
  as a single Dockerized FastAPI instance; if the deployment scales to multiple
  instances, this limiter provides no cross-instance guarantee and must be
  replaced by a shared atomic store (e.g. Redis) — that is a documented
  limitation, not a hidden multi-instance claim.

Safety:
- Bucket keys are derived server-side (web-session user id, or normalized
  client IP). Client-supplied identifiers are never read.
- Limits are checked BEFORE route execution, so outbound sends are rejected
  before any side effect occurs.
- Memory is bounded: expired windows are pruned and the bucket dict is capped.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

WINDOW_SECONDS = 60
MAX_BUCKETS = 50000

DEFAULT_LIMITS = {
    "auth": 20,
    "ai": 20,
    "outbound": 30,
    "webhook": 120,
    "default": 300,
}

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
    """Fixed-window per-instance limiter.

    Thread-safe for async use via an asyncio.Lock. Buckets are keyed by
    ``category:identity`` and aligned to a 60s wall-clock window.
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

    def _now_window(self, now: int) -> int:
        return now - (now % self.window_seconds)

    async def allow(self, key: str, limit: int) -> tuple[bool, int | None]:
        """Return ``(allowed, retry_after_seconds)``. Applies the limit for a
        single identity bucket; ``limit<=0`` means unlimited."""
        if not self.enabled or limit <= 0:
            return True, None
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
