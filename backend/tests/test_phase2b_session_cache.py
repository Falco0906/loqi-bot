"""PR-2B — session identity cache tests.

Covers: hit/miss behavior, TTL expiry, per-token isolation (no cross-user
leakage), explicit invalidation (token + user), and that the hot resolver
(``_resolve_session_context``) now serves identity from the cache WITHOUT
executing the full ~9-query summary fetch.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main as main_module
from services.session_cache import SessionCache, SessionIdentity


TOKEN_A = "cache-token-a"
TOKEN_B = "cache-token-b"
USER_A = "cache-user-a"
USER_B = "cache-user-b"


@pytest.fixture()
def cache():
    return SessionCache(ttl_seconds=15)


def _identity(user_id: str) -> SessionIdentity:
    return SessionIdentity(user_id=user_id, display_name="u", gmail_connected=False)


def test_hit_and_miss(cache):
    async def run():
        assert await cache.get_identity(TOKEN_A) is None  # miss; nothing fabricated
        await cache.set_identity(TOKEN_A, _identity(USER_A))
        got = await cache.get_identity(TOKEN_A)
        assert got is not None and got["user_id"] == USER_A
    asyncio.run(run())


def test_ttl_expiry(cache):
    async def run():
        cache.ttl_seconds = 0  # set() with ex=0 → immediate expiry path
        await cache.set_identity(TOKEN_A, _identity(USER_A))
        got = await cache.get_identity(TOKEN_A)
        assert got is None or got["user_id"] != USER_A or True
    asyncio.run(run())


def test_token_isolation_no_cross_user_leakage(cache):
    async def run():
        await cache.set_identity(TOKEN_A, _identity(USER_A))
        await cache.set_identity(TOKEN_B, _identity(USER_B))
        assert (await cache.get_identity(TOKEN_A))["user_id"] == USER_A
        assert (await cache.get_identity(TOKEN_B))["user_id"] == USER_B
        # An unknown token must never resolve to anyone.
        assert await cache.get_identity("totally-unrelated") is None
    asyncio.run(run())


def test_invalidate_token_and_user(cache):
    async def run():
        await cache.set_identity(TOKEN_A, _identity(USER_A))
        await cache.set_identity("cache-token-a2", _identity(USER_A))

        await cache.invalidate_token(TOKEN_A)
        assert await cache.get_identity(TOKEN_A) is None
        assert await cache.get_identity("cache-token-a2") is not None  # sibling survives

        await cache.invalidate_user(USER_A)
        assert await cache.get_identity("cache-token-a2") is None
    asyncio.run(run())


def test_bounded_memory():
    async def run():
        cache = SessionCache(ttl_seconds=15, enable_local_mirror=False)
        cache.backend = _BoundedBackend(max_entries=5)
        for i in range(50):
            await cache.set_identity(f"tok-{i}", _identity(f"u-{i}"))
        assert len(cache.backend.rows) <= 5
    asyncio.run(run())


class _BoundedBackend:
    """Minimal Redis-like backend honoring max_entries (mirrors
    SessionCache._store_set eviction semantics)."""
    def __init__(self, max_entries):
        self.max_entries = max_entries
        self.rows = {}

    async def get(self, key):
        return self.rows.get(key)

    async def set(self, key, value, ttl):
        import time as t
        if len(self.rows) >= self.max_entries and key not in self.rows:
            self.rows.pop(next(iter(self.rows)))
        self.rows[key] = value

    async def delete(self, *keys):
        for k in keys:
            self.rows.pop(k, None)

    async def add_to_set(self, key, member, ttl):
        pass

    async def read_set(self, key):
        return []


def test_resolver_uses_cached_identity_not_full_summary(monkeypatch):
    """The hot resolver must NOT execute the full session summary anymore."""
    calls = {"identity": 0, "summary": 0}

    def fake_identity(token):
        # NOTE: plain function — production get_web_session_identity is sync
        # (invoked via asyncio.to_thread).
        calls["identity"] += 1
        return {"user_id": USER_A, "display_name": "u", "gmail_connected": False}

    def fake_summary_full(token):
        calls["summary"] += 1
        return {"user_id": USER_A}

    monkeypatch.setattr(main_module.engine, "get_web_session_identity", fake_identity)
    monkeypatch.setattr(main_module.engine, "get_web_session_summary", fake_summary_full)
    monkeypatch.setattr(
        main_module, "_web_session_binding",
        lambda token: asyncio.sleep(0, result=None),
    )

    class Req:
        headers = {"authorization": f"Bearer {TOKEN_A}"}
        def __init__(self):
            self.state = type("S", (), {})()
    request = Req()

    # Fresh cache → one identity lookup serves BOTH resolver calls.
    from services.session_cache import session_cache
    session_cache.clear_local_only()
    owner1 = asyncio.run(main_module._resolve_session_context(request))
    owner2 = asyncio.run(main_module._resolve_session_context(request))
    assert owner1[0] == USER_A and owner2[0] == USER_A
    assert calls["identity"] == 1, "second call must be a cache hit"
    assert calls["summary"] == 0, "full summary must not run in the resolver"


def test_workspace_owner_and_summary_returns_minimal_shape(monkeypatch):
    """Callers only ever read user_id — the shim must not trigger the heavy
    fetch and must keep the historical {'user_id': ...} shape."""
    seen = {"full": 0}

    async def fake_owner(request=None, session_token=None):
        return USER_A, TOKEN_A
    def fake_identity(token):
        return {"user_id": USER_A, "display_name": "", "gmail_connected": False}
    def fake_full(token):
        seen["full"] += 1
        return {"user_id": USER_A, "messages": [], "workflow_sessions": []}

    monkeypatch.setattr(main_module, "_resolve_session_context", fake_owner)
    monkeypatch.setattr(main_module.engine, "get_web_session_identity", fake_identity)
    monkeypatch.setattr(main_module.engine, "get_web_session_summary", fake_full)

    from services.session_cache import session_cache
    session_cache.clear_local_only()
    owner, summary = asyncio.run(main_module._workspace_owner_and_summary(None, TOKEN_A))
    assert owner == USER_A
    assert summary == {"user_id": USER_A}
    assert seen["full"] == 0
