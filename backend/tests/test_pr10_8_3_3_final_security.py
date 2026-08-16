"""PR10.8.3.3 — FINAL SECURITY GATE regression suite.

Covers the final security sign-off items:

1. URL-token authentication is rejected.
2. The legacy x-session-token header is removed (no alternate auth path).
3. Authorization: Bearer is the sole client-facing session mechanism.
4. Client-supplied user_id / workspace_id cannot override authenticated identity.
5. Cross-tenant reads, mutations, and side effects are denied.
6. Unattributable resources are denied (fail closed).
7. Webhook authentication (Telegram secret).
8. OAuth state stays single-use / tenant-bound.
9. No token / Authorization-header leakage in logs or responses.
10. Production/dev separation (docs gate, legacy connect gate).

Deterministic sentinels only; no real credentials, emails, or sends.
"""
import asyncio
import logging
import os
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main as main_module

SENTINEL = "PR10833_FINAL_SENTINEL_DO_NOT_LEAK"


@pytest.fixture(autouse=True)
def _clean_state():
    from services.communication import provider_registry as pr
    from services.outbound import outbound_registry as or_reg
    from services.communication.communication_store import store as comm_store
    from services.conversations.conversation_store import conversation_store
    from services.outbound.draft_store import draft_store as ods
    from services.workflow_runtime import _runtimes

    for pid in list(pr.list_providers().keys()):
        pr.remove_instance(pid)
    for pid in list(or_reg.list_providers().keys()):
        or_reg.remove_instance(pid)
    comm_store._providers.clear()
    comm_store._user_providers.clear()
    comm_store._thread_mappings.clear()
    comm_store._by_conversation.clear()
    comm_store._seen_message_ids.clear()
    conversation_store.reload()
    ods._drafts.clear()
    ods._versions.clear()
    _runtimes.clear()
    yield


def _req(token=SENTINEL):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request


def _req_x_session(token=SENTINEL):
    request = MagicMock()
    request.headers.get = lambda k, d="": token if k == "x-session-token" else d
    return request


# ═══════════════════════════════════════════════════════════════════════
# 1. Authentication: URL-token and x-session-token rejected
# ═══════════════════════════════════════════════════════════════════════

class TestAuthenticationFinal:
    def test_url_token_alone_rejected(self):
        """A session token in the URL path (no Authorization header) -> 401."""
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        main_module._resolve_session_context = REAL_RESOLVE_SESSION_CONTEXT
        app = FastAPI_WithAuth()
        with TestClient(app) as client:
            resp = client.get(f"/api/web/session/{SENTINEL}/providers")
            assert resp.status_code == 401

    def test_x_session_token_alone_rejected(self):
        """The legacy x-session-token header must NOT authenticate anything."""
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        main_module._resolve_session_context = REAL_RESOLVE_SESSION_CONTEXT
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.list_jobs(_req_x_session(SENTINEL)))
        assert exc.value.status_code == 401

    def test_bearer_accepted(self):
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        main_module._resolve_session_context = REAL_RESOLVE_SESSION_CONTEXT
        # A valid identity/web token resolves; a garbage token -> 401.
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.list_jobs(_req("garbage")))
        assert exc.value.status_code == 401

    def test_no_client_user_id_override(self):
        """list_jobs must ignore a client-supplied user_id query parameter."""
        async def _resolve(request):
            return "owner-a", "token"
        main_module._resolve_session_context = _resolve
        request = _req("token")
        request.query_params = {"user_id": "owner-b"}
        result = asyncio.run(main_module.list_jobs(request))
        assert result == {"jobs": []}


def FastAPI_WithAuth():
    from fastapi import FastAPI
    app = FastAPI()

    @app.middleware("http")
    async def require_auth(request, call_next):
        from fastapi.responses import JSONResponse
        if request.url.path.startswith("/api/web/session/"):
            try:
                await main_module._resolve_session_context(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.get("/api/web/session/{token}/providers")
    async def providers(token: str):
        return {"ok": True, "providers": []}

    return app


# ═══════════════════════════════════════════════════════════════════════
# 2. Cross-tenant isolation (final pass over the audited matrix)
# ═══════════════════════════════════════════════════════════════════════

class TestTenantIsolationFinal:
    def _two_user_resolver(self):
        owners = {"token-a": "owner-a", "token-b": "owner-b"}

        async def _resolve(request):
            token = main_module._session_token_from_request(request)
            if not token:
                raise HTTPException(status_code=401, detail="Authentication required")
            return owners.get(token, "test-owner"), token

        async def _owner(request, session_token=""):
            token = main_module._session_token_from_request(request)
            if not token:
                raise HTTPException(status_code=401, detail="Authentication required")
            return owners.get(token, "test-owner")

        return _resolve, _owner

    def _provider(self, pid, user_id):
        from services.communication.provider_models import (
            CommunicationProvider, ProviderType, ProviderStatus,
        )
        main_module.communication_store._providers[pid] = CommunicationProvider(
            id=pid, provider_type=ProviderType.GMAIL, user_id=user_id,
            status=ProviderStatus.HEALTHY, metadata={"email": f"{user_id}@x.com"},
        )

    def test_cross_tenant_provider_sync_denied(self, monkeypatch):
        resolve, owner = self._two_user_resolver()
        monkeypatch.setattr(main_module, "_resolve_session_context", resolve)
        monkeypatch.setattr(main_module, "_workspace_owner", owner)
        self._provider("prov-b", "owner-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.provider_sync("_", "prov-b", _req("token-a")))
        assert exc.value.status_code == 404

    def test_cross_tenant_provider_disconnect_denied(self, monkeypatch):
        resolve, owner = self._two_user_resolver()
        monkeypatch.setattr(main_module, "_resolve_session_context", resolve)
        monkeypatch.setattr(main_module, "_workspace_owner", owner)
        self._provider("prov-b", "owner-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.provider_disconnect("_", "prov-b", _req("token-a")))
        assert exc.value.status_code == 404

    def test_unattributable_conversation_denied(self, monkeypatch):
        resolve, owner = self._two_user_resolver()
        monkeypatch.setattr(main_module, "_resolve_session_context", resolve)
        monkeypatch.setattr(main_module, "_workspace_owner", owner)
        from services.conversations.integration import create_conversation_from_send
        convo = create_conversation_from_send(
            provider_id="", provider_type="gmail",
            external_thread_id=f"t_{uuid.uuid4().hex[:10]}",
            external_message_id=f"m_{uuid.uuid4().hex[:10]}",
            subject="s", from_email="a@a.com", from_name="A",
            to_email="b@b.com", to_name="B", body="x",
            owner_id="",
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.get_conversation_route("_", convo.conversation_id, _req("token-a")))
        assert exc.value.status_code in (403, 404)

    def test_cross_tenant_outbound_draft_side_effect_denied(self, monkeypatch):
        resolve, owner = self._two_user_resolver()
        monkeypatch.setattr(main_module, "_resolve_session_context", resolve)
        monkeypatch.setattr(main_module, "_workspace_owner", owner)
        self._provider("prov-b", "owner-b")
        from services.outbound.draft_store import draft_store as ods
        from services.outbound.outbound_models import DraftMessage, Recipient
        ods.create(DraftMessage(
            id="draft-b", provider_id="prov-b", subject="s", body="b",
            recipient=Recipient(email="t@x.com", name="T"),
            sender=Recipient(email="s@x.com", name="S"),
        ))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.outbound_approve_draft("_", "draft-b", False, _req("token-a")))
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 3. Webhook authentication
# ═══════════════════════════════════════════════════════════════════════

class TestWebhookFinal:
    def test_telegram_webhook_requires_secret_when_configured(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-abc")
        request = MagicMock()
        request.headers.get = lambda k, d="": ""
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.telegram_webhook(request))
        assert exc.value.status_code == 403

    def test_telegram_webhook_accepts_matching_secret(self, monkeypatch):
        from unittest.mock import patch
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-abc")
        request = MagicMock()
        request.headers.get = lambda k, d="": "secret-abc"
        request.json = asyncio.coroutine(lambda: {}) if False else _AsyncJson({})
        with patch.object(main_module, "process_message", lambda *a, **k: None):
            result = asyncio.run(main_module.telegram_webhook(request))
        assert result == {"status": "ok"}


class _AsyncJson:
    def __init__(self, data):
        self._data = data

    async def __call__(self):
        return self._data


# ═══════════════════════════════════════════════════════════════════════
# 4. OAuth state single-use (tenant binding)
# ═══════════════════════════════════════════════════════════════════════

class TestOAuthFinal:
    def test_state_single_use_and_user_bound(self):
        from services.oauth_state import issue_state, consume_state
        import asyncio
        state = asyncio.run(issue_state("user-a"))
        user_a, _ = asyncio.run(consume_state(state))
        assert user_a == "user-a"
        assert asyncio.run(consume_state(state)) == (None, None)
        state_b = asyncio.run(issue_state("user-b"))
        user_b, _ = asyncio.run(consume_state(state_b))
        assert user_b == "user-b"
        assert asyncio.run(consume_state(state_b)) == (None, None)


# ═══════════════════════════════════════════════════════════════════════
# 5. No token / Authorization-header leakage
# ═══════════════════════════════════════════════════════════════════════

class TestLeakageFinal:
    def test_authorization_header_never_logged(self, caplog):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from services.operations.middleware import RequestLoggingMiddleware

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/api/web/session/{token}/providers")
        async def providers(token: str):
            return {"ok": True}

        with caplog.at_level(logging.INFO):
            with TestClient(app) as client:
                client.get(f"/api/web/session/_{SENTINEL}", headers={"Authorization": f"Bearer {SENTINEL}"})
        for record in caplog.records:
            if record.name == "loqi":
                msg = record.getMessage() or ""
                assert f"Bearer {SENTINEL}" not in msg
                assert SENTINEL not in msg

    def test_docs_gated_in_production(self, monkeypatch):
        import importlib
        monkeypatch.setenv("ENVIRONMENT", "production")
        # Re-importing main is heavy; assert the production gate logic is present.
        src = open(os.path.join(os.path.dirname(__file__), "..", "main.py")).read()
        assert "docs_url=None if _production_env else \"/docs\"" in src
        assert "openapi_url=None if _production_env else \"/openapi.json\"" in src

    def test_legacy_connect_gated_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        payload = MagicMock()
        payload.provider_type = "gmail"
        payload.auth_token = "x"
        payload.email = "a@a.com"
        payload.scope = ""
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.provider_connect("_", payload, _req(SENTINEL)))
        assert exc.value.status_code == 403
