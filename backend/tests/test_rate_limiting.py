"""PR10.5 — production rate-limiting tests."""
from __future__ import annotations

import asyncio
import os
import sys
import time

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.rate_limit import RateLimiter, classify_rate_limit
from services.config_validation import validate_config

import main as main_module  # noqa: E402


class TestClassifier:
    def test_health_is_exempt(self):
        for path in ("/health", "/", "/docs", "/openapi.json"):
            assert classify_rate_limit(path) == "health"

    def test_auth(self):
        assert classify_rate_limit("/api/auth/gmail/url") == "auth"
        assert classify_rate_limit("/api/v1/auth/login") == "auth"

    def test_ai(self):
        assert classify_rate_limit("/api/web/session/s/c1/generate-reply") == "ai"
        assert classify_rate_limit("/api/web/session/s/campaigns/c1/generate-strategy") == "ai"
        assert classify_rate_limit("/api/web/session/s/strategic-updates/refresh") == "ai"

    def test_outbound(self):
        assert classify_rate_limit("/api/web/session/s/drafts/d1/send") == "outbound"
        assert classify_rate_limit("/api/web/session/s/conversations/c1/reply") == "outbound"
        assert classify_rate_limit("/api/web/session/s/conversations/c1/follow-up") == "outbound"

    def test_webhook_and_default(self):
        assert classify_rate_limit("/webhook") == "webhook"
        assert classify_rate_limit("/api/web/session/s/conversations") == "default"


class TestRateLimiter:
    def test_under_limit_allowed(self):
        limiter = RateLimiter(enabled=True, limits={"default": 5})
        async def run():
            for _ in range(5):
                allowed, _ = await limiter.allow("t:u1", 5)
                assert allowed is True
        asyncio.run(run())

    def test_exceeded_returns_false_with_retry_after(self):
        limiter = RateLimiter(enabled=True, limits={"default": 2})
        async def run():
            assert (await limiter.allow("t:u1", 2))[0] is True
            assert (await limiter.allow("t:u1", 2))[0] is True
            allowed, retry = await limiter.allow("t:u1", 2)
            assert allowed is False
            assert retry is not None and retry >= 1
        asyncio.run(run())

    def test_independent_buckets(self):
        limiter = RateLimiter(enabled=True, limits={"default": 1})
        async def run():
            assert (await limiter.allow("t:a", 1))[0] is True
            assert (await limiter.allow("t:b", 1))[0] is True
            assert (await limiter.allow("t:a", 1))[0] is False
        asyncio.run(run())

    def test_disabled_is_unlimited(self):
        limiter = RateLimiter(enabled=False, limits={"default": 1})
        async def run():
            for _ in range(10):
                assert (await limiter.allow("t:x", 1))[0] is True
        asyncio.run(run())

    def test_expired_buckets_are_pruned(self):
        limiter = RateLimiter(enabled=True, limits={"default": 5})
        limiter._buckets["stale:key"] = (int(time.time()) - 120, 99)
        async def run():
            await limiter.allow("fresh:key", 5)
        asyncio.run(run())
        assert "stale:key" not in limiter._buckets

    def test_bounded_memory(self, monkeypatch):
        monkeypatch.setattr("services.rate_limit.MAX_BUCKETS", 5)
        limiter = RateLimiter(enabled=True, limits={"default": 1}, window_seconds=60)
        async def run():
            for i in range(20):
                await limiter.allow(f"t:{i}", 1)
        asyncio.run(run())
        assert limiter.bucket_count <= 5

    def test_concurrent_requests_cannot_bypass(self):
        limiter = RateLimiter(enabled=True, limits={"default": 3})
        async def hit():
            allowed, _ = await limiter.allow("t:c", 3)
            return allowed
        async def run():
            return await asyncio.gather(*[hit() for _ in range(10)])
        results = asyncio.run(run())
        assert sum(results) == 3


class TestConfigValidation:
    def test_production_cannot_disable(self):
        env = {
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
            "RATE_LIMIT_ENABLED": "false",
        }
        errors, _ = validate_config(env)
        assert any("RATE_LIMIT_ENABLED must not be disabled in production" in e for e in errors)

    def test_invalid_per_minute_rejected(self):
        errors, _ = validate_config({"ENVIRONMENT": "development", "RATE_LIMIT_AI_PER_MINUTE": "abc"})
        assert any("RATE_LIMIT_AI_PER_MINUTE" in e for e in errors)

    def test_valid_production_with_rate_limits_passes(self):
        env = {
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "GOOGLE_REDIRECT_URI": "https://app.tryloqi.com/api/auth/gmail/callback",
            "IDENTITY_PEPPER": "p" * 32,
            "IDENTITY_SIGNING_KEY_DEFAULT": "k" * 32,
            "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
            "RATE_LIMIT_ENABLED": "true",
            "RATE_LIMIT_AI_PER_MINUTE": "10",
        }
        errors, _ = validate_config(env)
        assert errors == []


class TestMiddleware:
    @pytest.fixture(autouse=True)
    def _reset_limiter(self):
        from services.rate_limit import rate_limiter as shared_limiter
        shared_limiter.enabled = True
        shared_limiter.limits["default"] = 2
        shared_limiter.limits["ai"] = 2
        asyncio.run(shared_limiter.clear())
        yield
        shared_limiter.enabled = False
        asyncio.run(shared_limiter.clear())

    def test_exceeding_limit_returns_429(self):
        from fastapi.testclient import TestClient
        client = TestClient(main_module.app)
        ok = [client.get("/api/jobs") for _ in range(2)]
        assert all(r.status_code < 500 for r in ok)
        blocked = client.get("/api/jobs")
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After")
        assert "Rate limit" in blocked.json().get("detail", "")

    def test_health_is_exempt_from_rate_limit(self):
        from fastapi.testclient import TestClient
        client = TestClient(main_module.app)
        for _ in range(10):
            response = client.get("/health")
            assert response.status_code == 200
