"""PR-2B — Session data caching layer.

Purpose
-------
``get_web_session_summary`` costs ~9-10 sequential Supabase round trips and
was being executed multiple times per request (middleware, resolvers,
handlers). Most consumers only need the owning *identity*:

    {user_id, display_name, gmail_connected}

This module provides a small, bounded, per-token TTL cache for exactly that
minimal identity object. It deliberately stores NO credentials, tokens,
secrets, messages, or workflow payloads.

Redis swap point (pre-launch plan)
----------------------------------
Every read/write goes through ``SessionCache._store_get/_store_set/_store_del``.
Swapping to Redis later means replacing those three methods (or the private
``_entries`` mapping) with a Redis client — no caller changes required. Until
then a process-local dict is used; values are non-sensitive identities, so a
multi-process deployment simply keeps one small identity map per worker with
identical semantics (TTL bounds staleness to ``ttl_seconds``).

Invalidation contract
---------------------
- TTL (default 15s) bounds any staleness automatically.
- ``invalidate_token(token)`` must be called wherever a web-session is
  revoked/bound/unbound.
- ``invalidate_user(user_id)`` must be called whenever per-user flags that
  live in the identity change — currently gmail connect/disconnect.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionIdentity:
    """The minimum session data any hot path actually needs."""

    user_id: str
    display_name: str = ""
    gmail_connected: bool = False


class TTLCache:
    """Bounded monotonic-clock TTL map. Thread-safe."""

    def __init__(self, max_entries: int = 2000):
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class SessionCache:
    """Per-token identity cache. One instance per process (module singleton).

    Keys are the raw web-session tokens — isolated by construction, so there
    is no cross-user leakage path: a hit requires the exact bearer token.
    """

    def __init__(self, ttl_seconds: float = 15.0, max_entries: int = 2000):
        self.ttl_seconds = ttl_seconds
        self._cache = TTLCache(max_entries=max_entries)
        self._user_index: dict[str, set[str]] = {}  # user_id -> {tokens}
        self._index_lock = threading.Lock()

    # ── backend swap point ────────────────────────────────────────────
    def _store_get(self, key: str):
        return self._cache.get(key)

    def _store_set(self, key: str, value: SessionIdentity) -> None:
        expires_at = time.monotonic() + self.ttl_seconds
        with self._cache._lock:
            if len(self._cache._entries) >= self._cache.max_entries and key not in self._cache._entries:
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._cache._entries.items() if exp <= now]
                for k in expired:
                    self._cache._entries.pop(k, None)
                while len(self._cache._entries) >= self._cache.max_entries:
                    self._cache._entries.pop(next(iter(self._cache._entries)))
            self._cache._entries[key] = (expires_at, value)

    def _store_del(self, key: str) -> None:
        self._cache.delete(key)

    # ── public API ────────────────────────────────────────────────────
    def get_identity(self, token: str) -> SessionIdentity | None:
        if not token:
            return None
        return self._store_get(f"tok:{token}")

    def set_identity(self, token: str, identity: SessionIdentity) -> None:
        if not token or not identity or not identity.user_id:
            # Never cache anonymous/unknown resolutions.
            return
        self._store_set(f"tok:{token}", identity)
        with self._index_lock:
            self._user_index.setdefault(identity.user_id, set()).add(token)

    def invalidate_token(self, token: str) -> None:
        if not token:
            return
        identity = self._store_get(f"tok:{token}")
        self._store_del(f"tok:{token}")
        if identity:
            with self._index_lock:
                tokens = self._user_index.get(identity.user_id)
                if tokens:
                    tokens.discard(token)
                    if not tokens:
                        self._user_index.pop(identity.user_id, None)

    def invalidate_user(self, user_id: str) -> None:
        """Drop every cached token belonging to this user (e.g. after the
        gmail_connected flag flips on connect/disconnect)."""
        if not user_id:
            return
        with self._index_lock:
            tokens = list(self._user_index.get(user_id, ()))
            self._user_index.pop(user_id, None)
        for token in tokens:
            self._store_del(f"tok:{token}")

    def clear(self) -> None:
        self._cache.clear()
        with self._index_lock:
            self._user_index.clear()


session_cache = SessionCache(ttl_seconds=15.0, max_entries=2000)
