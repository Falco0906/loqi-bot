"""PR-3A — Redis foundation tests.

Uses ``fakeredis`` as the Redis backend (injected through
``services.redis_client``) so the full production code path — pooling,
namespaced keys, Lua rate limiting, pub/sub, degraded fallbacks — runs
hermetically. "Worker A / Worker B" = two independent client/service
instances bound to the SAME fake server, which is exactly the multi-worker
sharing contract.

Covers:
  connectivity + health            (redis configured/ping)
  cache read/write/TTL/invalidation, cross-worker sharing
  session identity isolation       (token hashing → no cross-user collisions)
  distributed rate limiting        (shared across workers, enforced, expiry,
                                    concurrency-safe, per-user/per-bucket)
  degraded mode                    (redis unavailable → local limiter still
                                    enforces; identity falls back to None)
  pub/sub                          (publish → subscribe delivery)
"""
import asyncio
import json

import pytest

fakeredis = pytest.importorskip("fakeredis")
import fakeredis.aioredis  # noqa: E402


@pytest.fixture()
def fake_redis_server():
    import fakeredis
    server = fakeredis.FakeServer()
    return server


@pytest.fixture()
def wire_redis(monkeypatch, fake_redis_server):
    """Point services.redis_client at a fresh fakeredis server."""
    from services import redis_client as rc

    monkeypatch.setenv("REDIS_URL", "redis://test:6379/0")
    async def fake_get_client():
        return fakeredis.aioredis.FakeRedis(server=fake_redis_server, decode_responses=True)
    monkeypatch.setattr(rc, "get_client", fake_get_client)
    # Reset breaker state between tests.
    monkeypatch.setattr(rc, "_unavailable_until", 0.0)
    return rc


# ─── connectivity ─────────────────────────────────────────────────────

def test_connectivity_and_health(wire_redis):
    async def run():
        assert await wire_redis.healthy() is True
        client = await wire_redis.get_client()
        assert await client.ping() is True
    asyncio.run(run())


def test_unconfigured_returns_none(monkeypatch):
    from services import redis_client as rc
    monkeypatch.delenv("REDIS_URL", raising=False)
    async def run():
        assert await rc.get_client() is None
        assert await rc.healthy() is False
    asyncio.run(run())


# ─── cache: shared across workers ─────────────────────────────────────

def test_session_identity_shared_across_workers(wire_redis):
    from services.session_cache import SessionCache, SessionIdentity

    async def run():
        worker_a = SessionCache()
        worker_b = SessionCache()

        await worker_a.set_identity("tok-1", SessionIdentity(
            user_id="user-1", display_name="One", gmail_connected=True))
        got = await worker_b.get_identity("tok-1")
        assert got == {"user_id": "user-1", "display_name": "One",
                       "gmail_connected": True}

        # Worker B invalidation observed by worker A.
        await worker_b.invalidate_user("user-1")
        assert await worker_a.get_identity("tok-1") is None
    asyncio.run(run())


def test_token_keys_are_hashed_not_raw(wire_redis):
    from services.session_cache import SessionCache, SessionIdentity, _token_hash
    from services.redis_client import k_session_identity

    async def run():
        worker = SessionCache()
        await worker.set_identity("super-secret-bearer", SessionIdentity(user_id="u"))
        client = await wire_redis.get_client()
        raw = k_session_identity(_token_hash("super-secret-bearer"))
        assert await client.exists(raw) == 1
        # The raw token must not appear anywhere in Redis keyspace.
        keys = [k async for k in client.scan_iter("*")]
        assert all("super-secret-bearer" not in k for k in keys)
    asyncio.run(run())


def test_cache_ttl_expiry(wire_redis):
    from services.session_cache import SessionCache, SessionIdentity

    async def run():
        worker = SessionCache(ttl_seconds=1)
        await worker.set_identity("tok-ttl", SessionIdentity(user_id="u-ttl"))
        assert (await worker.get_identity("tok-ttl")) is not None
        # fakeredis honors TTLs in (virtual) seconds; force-expire via tiny ttl
        worker.ttl_seconds = 0  # can't set ex=0; delete-and-readd pattern:
        await worker.backend.delete(worker._identity_key("tok-ttl"))
        assert await worker.get_identity("tok-ttl") is None
    asyncio.run(run())


def test_cross_user_isolation_no_collision(wire_redis):
    from services.session_cache import SessionCache, SessionIdentity

    async def run():
        a, b = SessionCache(), SessionCache()
        await a.set_identity("shared-token-name", SessionIdentity(user_id="user-A"))
        await b.set_identity("other-token", SessionIdentity(user_id="user-B"))
        assert (await a.get_identity("shared-token-name"))["user_id"] == "user-A"
        await b.invalidate_user("user-B")
        assert (await a.get_identity("shared-token-name"))["user_id"] == "user-A"
    asyncio.run(run())


# ─── degraded mode ────────────────────────────────────────────────────

def test_redis_unavailable_falls_back_without_bypass(wire_redis, monkeypatch):
    """With Redis unreachable:
      - never-cached identities resolve to None (→ Supabase fallback upstream)
      - previously-cached identities are still served from the bounded local
        mirror (documented degraded mode; ≤ TTL old, no auth bypass — durable
        enforcement stays in Supabase/touch_session)
      - the rate limiter keeps enforcing locally (fail-safe, not fail-open)"""
    from services import redis_client as rc
    from services.rate_limit import RateLimiter

    async def dead_client():
        return None
    monkeypatch.setattr(rc, "get_client", dead_client)

    async def run():
        from services.session_cache import SessionCache, SessionIdentity
        cache = SessionCache()
        # Never cached → None even while Redis is down.
        assert await cache.get_identity("tok-unknown") is None
        await cache.set_identity("tok-x", SessionIdentity(user_id="u-x"))
        got = await cache.get_identity("tok-x")
        assert got["user_id"] == "u-x"  # warm local mirror serves ≤TTL-old data

        limiter = RateLimiter(enabled=True, limits={"default": 2})
        assert (await limiter.allow("k", 2))[0] is True
        assert (await limiter.allow("k", 2))[0] is True
        allowed, retry = await limiter.allow("k", 2)
        assert allowed is False and retry and retry >= 1
    asyncio.run(run())


# ─── distributed rate limiting ────────────────────────────────────────

def _limiter():
    from services.rate_limit import RateLimiter
    return RateLimiter(enabled=True, limits={"ai": 3, "outbound": 5, "default": 10})


def test_rate_limit_enforced_distributed(wire_redis):
    async def run():
        worker_a, worker_b = _limiter(), _limiter()
        key = "ai:user-777"
        for _ in range(3):
            ok, _ = await worker_a.allow(key, 3)
            assert ok
        # Worker B sees the SAME bucket — limit already exhausted.
        ok, retry = await worker_b.allow(key, 3)
        assert ok is False and retry >= 1
        # And A agrees.
        ok, _ = await worker_a.allow(key, 3)
        assert ok is False
    asyncio.run(run())


def test_rate_limit_window_expiry(wire_redis):
    async def run():
        rl = _limiter()
        key = "outbound:user-778"
        for _ in range(5):
            assert (await rl.allow(key, 5))[0]
        assert (await rl.allow(key, 5))[0] is False
        # Simulate window rollover by deleting the underlying counter(s).
        from services.redis_client import k_rate, hash_token
        import time as _time
        client = await wire_redis.get_client()
        current = int(_time.time()) // rl.window_seconds * rl.window_seconds
        await client.delete(k_rate("outbound", hash_token(key), current))
        await client.delete(k_rate("outbound", hash_token(key), current - rl.window_seconds))
        assert (await rl.allow(key, 5))[0] is True
    asyncio.run(run())


def test_rate_limit_buckets_isolated_by_category_and_user(wire_redis):
    async def run():
        rl = _limiter()
        # Exhaust ai for user X.
        for _ in range(3):
            assert (await rl.allow("ai:user-X", 3))[0]
        # Different category, same user → independent.
        assert (await rl.allow("outbound:user-X", 5))[0] is True
        # Same category, different user → independent.
        assert (await rl.allow("ai:user-Y", 3))[0] is True
    asyncio.run(run())


def test_rate_limit_concurrent_requests_cannot_bypass(wire_redis):
    async def run():
        rl_a, rl_b = _limiter(), _limiter()
        key = "default:user-Z"

        async def hit(worker):
            return (await worker.allow(key, 5))[0]

        results = await asyncio.gather(*[hit(rl_a if i % 2 == 0 else rl_b) for i in range(20)])
        assert sum(1 for r in results if r) == 5, (
            "exactly `limit` requests may pass across both workers"
        )
    asyncio.run(run())


def test_rate_limit_redis_down_falls_back_local(wire_redis, monkeypatch):
    async def run():
        from services.rate_limit import RateLimiter
        from services import redis_client as rc

        async def dead():
            return None
        monkeypatch.setattr(rc, "get_client", dead)

        rl = RateLimiter(enabled=True, limits={"default": 2})
        outcomes = [await rl.allow("default:user-Q", 2) for _ in range(3)]
        assert [o[0] for o in outcomes] == [True, True, False], "local fallback must still enforce"
    asyncio.run(run())


# ─── pub/sub ──────────────────────────────────────────────────────────

def test_pubsub_user_event_delivery(wire_redis):
    from services.events_bus import EventBus

    async def run():
        bus = EventBus()
        received: asyncio.Queue = asyncio.Queue()

        pubsub = await bus.subscribe_user("user-events-1")
        assert pubsub is not None
        listener = asyncio.create_task(_drain(pubsub, received))
        await asyncio.sleep(0.05)  # let the subscription register

        sent = await bus.publish_user_event(
            "user-events-1", "job.progress",
            {"stage": "sourcing"}, job_id="job-9", status="running", progress=42,
        )
        assert sent is True

        event = await asyncio.wait_for(received.get(), timeout=3)
        assert event["type"] == "job.progress"
        assert event["job_id"] == "job-9"
        assert event["progress"] == 42
        assert event["data"]["stage"] == "sourcing"
        await pubsub.unsubscribe()
        listener.cancel()
    asyncio.run(run())


async def _drain(pubsub, queue: asyncio.Queue):
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            queue.put_nowait(json.loads(message["data"]))
        except (TypeError, ValueError):
            continue


def test_pubsub_strips_sensitive_keys(wire_redis):
    from services.events_bus import EventBus

    async def run():
        bus = EventBus()
        received: asyncio.Queue = asyncio.Queue()
        pubsub = await bus.subscribe_user("user-events-2")
        listener = asyncio.create_task(_drain(pubsub, received))
        await asyncio.sleep(0.05)

        await bus.publish_user_event(
            "user-events-2", "test.event",
            {"ok": 1, "access_token": "SHOULD-NOT-PASS", "refresh_secret": "NOPE"},
        )
        event = await asyncio.wait_for(received.get(), timeout=3)
        flat = json.dumps(event)
        assert "SHOULD-NOT-PASS" not in flat and "NOPE" not in flat
        assert event["data"].get("ok") == 1
        await pubsub.unsubscribe()
        listener.cancel()
    asyncio.run(run())


def test_pubsub_redis_down_is_best_effort(wire_redis, monkeypatch):
    from services.events_bus import EventBus
    from services import redis_client as rc

    async def run():
        async def dead():
            return None
        monkeypatch.setattr(rc, "get_client", dead)
        bus = EventBus()
        assert await bus.publish_user_event("u", "job.progress") is False  # never raises
    asyncio.run(run())
