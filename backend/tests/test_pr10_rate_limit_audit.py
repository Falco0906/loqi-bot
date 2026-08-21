"""PR10 — Rate-limiting adversarial audit regression tests.

Confirms at the middleware level (not just the limiter class):

- authenticated rate-limit identity is derived server-side from the session
- client-supplied user_id / workspace_id / x-session-token / X-Forwarded-For /
  arbitrary identity headers cannot switch rate-limit buckets
- User A's limit does not throttle User B
- 429 response is safe (no identity/counter/token leak) and carries Retry-After
- health/readiness endpoints are not rate limited
- a limiter failure fails closed (does not bypass limits)

Deterministic sentinels only; no real credentials/tokens.
"""
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main as main_module
from services.rate_limit import rate_limiter

TOKEN_A = "rl-token-a"
TOKEN_B = "rl-token-b"
USER_A = "rl-user-a"
USER_B = "rl-user-b"
SENTINEL = "PR10_RL_SENTINEL"


@pytest.fixture(autouse=True)
def _isolated_limiter(monkeypatch):
    asyncio.run(rate_limiter.clear())
    monkeypatch.setattr(rate_limiter, "enabled", True)
    monkeypatch.setattr(rate_limiter, "limits", dict(rate_limiter.limits))
    rate_limiter.limits["ai"] = 3
    rate_limiter.limits["outbound"] = 3
    rate_limiter.limits["default"] = 3
    mapping = {TOKEN_A: USER_A, TOKEN_B: USER_B}
    # PR-P1.1: the middleware now resolves identity via the cheap
    # get_web_session_user_id lookup instead of the full session summary.
    monkeypatch.setattr(
        main_module.engine,
        "get_web_session_user_id",
        lambda token: mapping.get(token),
    )
    yield
    asyncio.run(rate_limiter.clear())


def _make_app():
    app = FastAPI()
    app.add_exception_handler(Exception, main_module.unhandled_exception_handler)
    app.middleware("http")(main_module.rate_limit_middleware)

    @app.get("/api/web/session/_/conversations/x/reasoning")
    async def ai_work():
        return {"ok": True}

    @app.get("/api/web/session/_/conversations/x/reply")
    async def outbound_send():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


def _req(app, path, token=None, extra_headers=None):
    headers = dict(extra_headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return TestClient(app, raise_server_exceptions=False).get(path, headers=headers)


class TestIdentityBypass:
    def test_authenticated_identity_is_server_derived(self):
        app = _make_app()
        # token-a resolves to user-a; the bucket is u:user-a.
        for _ in range(3):
            resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
            assert resp.status_code == 200
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        assert resp.status_code == 429

    def test_client_supplied_user_id_cannot_bypass(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        # Adding ?user_id=<victim> must NOT switch buckets.
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning?user_id=rl-user-b", token=TOKEN_A)
        assert resp.status_code == 429

    def test_x_session_token_header_cannot_bypass(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        # A forged x-session-token header must be ignored (token-a already used
        # its bucket).
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A, extra_headers={"x-session-token": TOKEN_B})
        assert resp.status_code == 429

    def test_forwarded_headers_cannot_bypass(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A, extra_headers={
            "X-Forwarded-For": "203.0.113.9",
            "X-Real-IP": "203.0.113.9",
            "X-Identity": USER_B,
            "x-user-id": USER_B,
        })
        assert resp.status_code == 429

    def test_unauthenticated_uses_server_client_ip_not_spoofable(self, monkeypatch):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reply", extra_headers={"X-Forwarded-For": "203.0.113.9"})
        # The X-Forwarded-For value must not grant a fresh bucket; the server's
        # request.client.host is used.
        resp = _req(app, "/api/web/session/_/conversations/x/reply", extra_headers={"X-Forwarded-For": "203.0.113.10"})
        assert resp.status_code == 429


class TestFairness:
    def test_user_a_does_not_throttle_user_b(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        assert _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A).status_code == 429
        # User B is on an independent bucket.
        assert _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_B).status_code == 200

    def test_different_categories_independent(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        # Outbound category is a separate bucket for the same user.
        assert _req(app, "/api/web/session/_/conversations/x/reply", token=TOKEN_A).status_code == 200


class TestResponseSafety:
    def test_429_response_is_safe(self):
        app = _make_app()
        for _ in range(3):
            _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        assert resp.status_code == 429
        body = resp.json()
        assert body.get("detail") == "Rate limit exceeded. Please try again shortly."
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1
        # No identity, counter, token, or implementation detail leaks.
        for leaked in (USER_A, TOKEN_A, SENTINEL, "bucket", "count", "window", "user_id"):
            assert leaked not in resp.text

    def test_health_is_exempt(self):
        app = _make_app()
        # Exhaust the default bucket, then health must still work.
        for _ in range(4):
            _req(app, "/health")
        assert _req(app, "/health").status_code == 200


class TestFailClosed:
    def test_limiter_exception_fails_closed(self, monkeypatch):
        app = _make_app()

        async def _boom(*args, **kwargs):
            raise RuntimeError(f"limiter-boom-{SENTINEL}")

        monkeypatch.setattr(rate_limiter, "allow", _boom)
        resp = _req(app, "/api/web/session/_/conversations/x/reasoning", token=TOKEN_A)
        # Fail-closed: a limiter fault surfaces as 500 (blocked), never a
        # pass-through that would let abuse through.
        assert resp.status_code == 500
        assert SENTINEL not in resp.text
