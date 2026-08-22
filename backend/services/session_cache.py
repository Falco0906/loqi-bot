"""Session identity cache — PR-3A Redis-backed implementation of the
Phase-2B contract.

What is cached (and nothing more):
    {user_id, display_name, gmail_connected}   ← minimal per-token identity

NEVER cached here: access/refresh tokens, OAuth credentials, messages,
conversations, provider secrets. Supabase remains the authoritative source;
this cache only removes repeated identity lookups and is shared across all
backend workers via Redis.

Key design (see services/redis_client.py):
    loqi:v1:session:identity:<sha256(salt:token)[:32]>   ← raw tokens never stored
    loqi:v1:session:user_tokens:<sha256(user_id)>        ← reverse index (set)

Degraded mode:
    When Redis is unconfigured/unavailable the cache transparently uses a
    bounded process-local mirror. Semantics are unchanged for callers; the
    only cost of an outage is losing cross-worker sharing for up to TTL.

Invalidation contract:
    - TTL (15s) bounds staleness absolutely.
    - invalidate_user(user_id): gmail connect/disconnect, credential changes.
    - invalidate_token(token): logout / session revocation for a known bearer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

IDENTITY_TTL_SECONDS = int(os.getenv("SESSION_IDENTITY_TTL_SECONDS", "15"))
LOCAL_MIRROR_MAX = 2000

# Sentinel returned by backends to signal "redis unavailable" distinctly from
# "key not found" (None).
UNAVAILABLE = object()


@dataclass(frozen=True)
class SessionIdentity:
    """The minimum session data any hot path actually needs."""

    user_id: str
    display_name: str = ""
    gmail_connected: bool = False


def _token_hash(token: str) -> str:
    salt = os.getenv("REDIS_KEY_SALT", os.getenv("REDIS_KEY_PREFIX", "loqi"))
    return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()[:32]


def _user_hash(user_id: str) -> str:
    salt = os.getenv("REDIS_KEY_SALT", os.getenv("REDIS_KEY_PREFIX", "loqi"))
    return hashlib.sha256(f"{salt}:user:{user_id}".encode()).hexdigest()[:32]


class RedisIdentityBackend:
    """Async Redis storage. All failures degrade via UNAVAILABLE."""

    def __init__(self) -> None:
        from services import redis_client
        self._rc = redis_client

    async def get(self, key: str):
        def op(client):
            return client.get(key)
        raw = await self._rc.run_with_timeout(op, fallback=UNAVAILABLE)
        if raw is UNAVAILABLE or raw is None:
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: dict, ttl: int) -> None:
        def op(client):
            return client.set(key, json.dumps(value, separators=(",", ":")), ex=ttl)
        await self._rc.run_with_timeout(op, fallback=False)

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        def op(client):
            return client.delete(*keys)
        await self._rc.run_with_timeout(op, fallback=0)

    async def add_to_set(self, set_key: str, member: str, ttl: int) -> None:
        def op(client):
            pipe = client.pipeline()
            pipe.sadd(set_key, member)
            pipe.expire(set_key, ttl)
            return pipe.execute()
        await self._rc.run_with_timeout(op, fallback=None)

    async def read_set(self, set_key: str) -> list[str]:
        def op(client):
            return client.smembers(set_key)
        members = await self._rc.run_with_timeout(op, fallback=UNAVAILABLE)
        return list(members) if members not in (UNAVAILABLE, None) else []


class LocalMirror:
    """Process-local fallback used ONLY while Redis is unavailable, plus as a
    same-process fast path after writes. Bounded + TTL'd like Phase 2B."""

    def __init__(self, max_entries: int = LOCAL_MIRROR_MAX):
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[dict]:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: str, value: dict, ttl: int) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self.max_entries and key not in self._entries:
                expired = [k for k, (exp, _) in self._entries.items() if exp <= now]
                for k in expired:
                    self._entries.pop(k, None)
                while len(self._entries) >= self.max_entries:
                    self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (now + ttl, value)

    def delete_many(self, keys) -> None:
        with self._lock:
            for k in keys:
                self._entries.pop(k, None)


class SessionCache:
    """Public API (unchanged names from Phase 2B; methods are now async).

    Callers: main.py::_cached_session_identity (+ invalidation call sites)
    and tests. Multi-worker safe when REDIS_URL is configured: worker A's
    set_identity is visible to worker B, and A's invalidate_user drops B's
    cached entries on the next read.
    """

    def __init__(
        self,
        ttl_seconds: int | None = None,
        backend: Any | None = None,
        enable_local_mirror: bool = True,
    ):
        self.ttl = int(
            ttl_seconds if ttl_seconds is not None
            else os.getenv("SESSION_IDENTITY_TTL_SECONDS", "15")
        )
        self.backend = backend or RedisIdentityBackend()
        self.local = LocalMirror() if enable_local_mirror else None

    @staticmethod
    def _identity_key(token: str) -> str:
        from services.redis_client import k_session_identity
        return k_session_identity(_token_hash(token))

    @staticmethod
    def _user_tokens_key(user_id: str) -> str:
        return f"usertokens:{_user_hash(user_id)}"

    async def get_identity(self, token: str) -> Optional[dict]:
        """Return {'user_id','display_name','gmail_connected'} or None."""
        if not token:
            return None
        key = self._identity_key(token)
        data = await self.backend.get(key)
        if data is UNAVAILABLE:
            # Degraded mode: serve the local mirror if warm (≤ TTL old),
            # expanded to the same shape as a Redis hit.
            warm = self.local.get(key) if self.local else None
            if not warm or not warm.get("u"):
                return None
            return {
                "user_id": str(warm["u"]),
                "display_name": str(warm.get("d") or ""),
                "gmail_connected": bool(warm.get("g")),
            }
        if data is None:
            return None
        if self.local:
            self.local.set(key, data, self.ttl)
        return {
            "user_id": str(data.get("u") or ""),
            "display_name": str(data.get("d") or ""),
            "gmail_connected": bool(data.get("g")),
        } if data.get("u") else None

    async def set_identity(self, token: str, identity) -> None:
        if not token or not identity or not getattr(identity, "user_id", ""):
            return
        compact = {
            "u": identity.user_id,
            "d": identity.display_name or "",
            "g": bool(identity.gmail_connected),
        }
        key = self._identity_key(token)
        await self.backend.set(key, compact, self.ttl)
        await self.backend.add_to_set(
            self._user_tokens_key(identity.user_id), key, self.ttl
        )
        if self.local:
            self.local.set(key, compact, self.ttl)

    async def invalidate_token(self, token: str) -> None:
        if not token:
            return
        key = self._identity_key(token)
        await self.backend.delete(key)
        if self.local:
            self.local.delete_many([key])

    async def invalidate_user(self, user_id: str) -> None:
        if not user_id:
            return
        set_key = self._user_tokens_key(user_id)
        keys = await self.backend.read_set(set_key)
        if keys:
            await self.backend.delete(set_key, *keys)
        if self.local:
            # Local mirror is keyed identically; drop every entry belonging to
            # this user by scanning (bounded to LOCAL_MIRROR_MAX entries).
            victims = []
            for key, (_, data) in list(self.local._entries.items()):
                if data.get("u") == user_id:
                    victims.append(key)
            self.local.delete_many(victims)

    def clear_local_only(self) -> None:
        if self.local:
            self.local.delete_many(list(self.local._entries.keys()))


session_cache = SessionCache()
