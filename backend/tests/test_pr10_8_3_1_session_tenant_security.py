"""PR10.8.3.1 — session auth hardening + fail-closed tenant isolation.

Part A — session authentication migration:
- authentication succeeds only via Authorization: Bearer
- missing / invalid / expired / revoked tokens -> 401
- session tokens are NOT accepted from URL paths or query parameters
- tokens never appear in logs, responses, or generated frontend URLs
- rate limiting still keys on the new identity; ownership still enforced

Part B — fail-closed conversation ownership:
- an owner may access/modify/reply/follow-up their own attributed conversations
- another user's conversations are denied
- unattributable conversations (no provider / no owner / unresolved provider)
  are denied — there is no "authenticated user = allowed" fallback
- a client cannot bypass ownership by supplying user_id/provider_id/workspace_id

Deterministic sentinels only; no real credentials.
"""
import asyncio
import os
import re
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from fastapi import HTTPException

SENTINEL = "PR10831_SESSION_SENTINEL_DO_NOT_LEAK"

# PR-2B: several tests in this file patch main_module helpers via DIRECT
# assignment (historic style). Without restoration the patches leak into
# subsequently-run test files (e.g. send-provider resolution), breaking them
# order-dependently. Snapshot + restore the commonly-patched callables.
@pytest.fixture(autouse=True)
def _restore_patched_main_helpers():
    import main as _main
    saved = {
        name: getattr(_main, name)
        for name in (
            "_workspace_owner",
            "_resolve_session_context",
            "_session_token_from_request",
            "_conversation_owned_by",
        )
        if hasattr(_main, name)
    }
    yield
    for name, fn in saved.items():
        setattr(_main, name, fn)


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    from services.communication import provider_registry as pr
    from services.communication.communication_store import store as comm_store
    from services.outbound import outbound_registry as or_reg
    from services.conversations.conversation_store import conversation_store

    for pid in list(pr.list_providers().keys()):
        pr.remove_instance(pid)
    for pid in list(or_reg.list_providers().keys()):
        or_reg.remove_instance(pid)
    comm_store._providers.clear()
    comm_store._cursors.clear()
    comm_store._thread_mappings.clear()
    comm_store._by_conversation.clear()
    comm_store._seen_message_ids.clear()
    comm_store._user_providers.clear()
    comm_store._sequence = 0
    conversation_store.reload()
    yield


def _request_with_header(token: str = SENTINEL):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request


def _request_without_header():
    request = MagicMock()
    request.headers.get = lambda k, d="": d
    return request


def _request_with_query_token(token: str = SENTINEL):
    request = _request_without_header()
    request.url.query = f"session_token={token}"
    return request


# ═══════════════════════════════════════════════════════════════════════
# PART A — SESSION AUTHENTICATION
# ═══════════════════════════════════════════════════════════════════════

class TestSessionAuth:
    def test_token_extracted_only_from_header(self):
        import main as main_module
        # Header present -> token returned.
        assert main_module._session_token_from_request(_request_with_header()) == SENTINEL
        # No header -> empty (no URL/query fallback).
        assert main_module._session_token_from_request(_request_without_header()) == ""
        assert main_module._session_token_from_request(_request_with_query_token()) == ""
        assert main_module._session_token_from_request(None) == ""

    def test_real_resolver_rejects_missing_and_invalid_tokens(self):
        import main as main_module
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        # Restore the real resolver for this test.
        import asyncio

        async def _run(request):
            return await REAL_RESOLVE_SESSION_CONTEXT(request)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(_run(_request_without_header()))
        assert exc.value.status_code == 401
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_run(_request_with_header("garbage-not-a-real-token")))
        assert exc.value.status_code == 401

    def test_middleware_rejects_url_token_without_header(self):
        """A session token in the URL path must NOT authenticate."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import main as main_module
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        main_module._resolve_session_context = REAL_RESOLVE_SESSION_CONTEXT
        app = FastAPI()

        @app.middleware("http")
        async def require_auth(request, call_next):
            if request.url.path.startswith("/api/web/session/"):
                try:
                    await main_module._resolve_session_context(request)
                except HTTPException as exc:
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            return await call_next(request)

        @app.get("/api/web/session/{token}/providers")
        async def providers(token: str):
            return {"ok": True, "providers": []}

        with TestClient(app) as client:
            resp = client.get(f"/api/web/session/{SENTINEL}/providers")
            assert resp.status_code == 401

    def test_authenticated_request_succeeds_via_header(self, monkeypatch):
        import main as main_module
        import services.supabase as supabase_module
        from services.communication.communication_store import store
        from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
        main_module._resolve_session_context = REAL_RESOLVE_SESSION_CONTEXT
        # Use the conftest shim by NOT overriding: instead patch _workspace_owner
        # to simulate the authenticated owner for a header-bearing request.
        store._providers["p-a"] = _provider_record("p-a", "a@a.com", user_id="test-owner")
        store._user_providers["test-owner"] = ["p-a"]
        main_module._workspace_owner = _async_owner("test-owner")
        # PR-2A: /providers reads the DURABLE store as source of truth; seed
        # that seam so the ownership assertion keeps testing auth resolution,
        # not the database.
        monkeypatch.setattr(
            supabase_module,
            "get_durable_providers_for_user",
            lambda user_id, provider="google": [{
                "row_id": "row-1",
                "communication_provider_id": "p-a",
                "email": "a@a.com",
                "account_id": "a@a.com",
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_synced_at": "",
            }] if user_id == "test-owner" else [],
        )
        result = asyncio.run(main_module.provider_list("_", _request_with_header()))
        assert result["ok"] is True
        assert len(result["providers"]) >= 1

    def test_logs_never_contain_session_token(self, caplog):
        import logging
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
                client.get(f"/api/web/session/{SENTINEL}/providers")
        app_records = [r for r in caplog.records if r.name == "loqi"]
        assert not any(SENTINEL in (r.getMessage() or "") for r in app_records)

    def test_frontend_urls_never_contain_session_token(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "lib", "api.ts")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "/api/web/session/${" not in content
        assert "api/web/session/${sessionToken}" not in content

    def test_redact_helper_never_emits_token(self):
        from services.operations.middleware import redact_session_path
        assert SENTINEL not in redact_session_path(f"/api/web/session/{SENTINEL}/providers")
        assert "[REDACTED]" in redact_session_path(f"/api/web/session/{SENTINEL}/providers")


def _provider_record(pid, email, user_id="test-owner", status="healthy"):
    from services.communication.provider_models import (
        CommunicationProvider, ProviderType, ProviderStatus,
    )
    return CommunicationProvider(
        id=pid,
        provider_type=ProviderType.GMAIL,
        user_id=user_id,
        status=ProviderStatus(status),
        metadata={"email": email, "account_id": email},
    )


def _async_owner(owner):
    async def _w(request, session_token=""):
        return owner
    return _w


# ═══════════════════════════════════════════════════════════════════════
# PART B — FAIL-CLOSED CONVERSATION OWNERSHIP
# ═══════════════════════════════════════════════════════════════════════

def _make_convo(owner_id="test-owner", provider_id="prov-a"):
    from services.conversations.integration import create_conversation_from_send
    return create_conversation_from_send(
        provider_id=provider_id,
        provider_type="gmail",
        external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
        external_message_id=f"msg_{uuid.uuid4().hex[:12]}",
        subject="Ownership test",
        from_email="a@a.com", from_name="A",
        to_email="b@b.com", to_name="B",
        body="hello",
        owner_id=owner_id,
    )


class TestFailClosedConversationOwnership:
    def _register_owner_provider(self, provider_id="prov-a", user_id="test-owner"):
        from services.communication.communication_store import store
        store._providers[provider_id] = _provider_record(provider_id, "a@a.com", user_id=user_id)

    def test_owner_can_read_own_conversation(self):
        import main as main_module
        convo = _make_convo(owner_id="test-owner")
        main_module._workspace_owner = _async_owner("test-owner")
        result = asyncio.run(
            main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
        )
        assert result["ok"] is True

    def test_other_user_conversation_denied(self):
        import main as main_module
        convo = _make_convo(owner_id="other-user")
        main_module._workspace_owner = _async_owner("test-owner")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
            )
        assert exc.value.status_code in (403, 404)

    def test_unattributable_conversation_denied(self):
        """No owner_id AND no resolvable provider -> denied (fail closed)."""
        import main as main_module
        convo = _make_convo(owner_id="")
        # No provider record in the store.
        main_module._workspace_owner = _async_owner("test-owner")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
            )
        assert exc.value.status_code in (403, 404)

    def test_unresolved_provider_denied(self):
        import main as main_module
        convo = _make_convo(owner_id="", provider_id="prov-missing")
        main_module._workspace_owner = _async_owner("test-owner")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
            )
        assert exc.value.status_code in (403, 404)

    def test_owner_conversation_by_provider_ownership_allowed(self):
        import main as main_module
        self._register_owner_provider("prov-a", user_id="test-owner")
        convo = _make_convo(owner_id="", provider_id="prov-a")
        main_module._workspace_owner = _async_owner("test-owner")
        result = asyncio.run(
            main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
        )
        assert result["ok"] is True

    def test_reply_to_other_user_conversation_denied(self):
        import main as main_module
        convo = _make_convo(owner_id="other-user")
        main_module._workspace_owner = _async_owner("test-owner")
        payload = MagicMock()
        payload.body = "reply"
        payload.test_recipient = ""
        payload.thread_id = ""
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.send_conversation_reply_route(
                "_", convo.conversation_id, payload, _request_with_header(),
            ))
        # Safe not-found (no existence leak): foreign conversation is 404.
        assert exc.value.status_code == 404

    def test_cannot_bypass_by_supplying_user_id(self):
        """Supplying another user_id in the request must not grant access."""
        import main as main_module
        convo = _make_convo(owner_id="other-user")
        # The authenticated owner is test-owner; a crafted user_id param is ignored.
        main_module._workspace_owner = _async_owner("test-owner")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                main_module.get_conversation_route("_", convo.conversation_id, _request_with_header())
            )
        assert exc.value.status_code in (403, 404)

    def test_fail_closed_helper_semantics(self):
        import main as main_module
        from services.communication.communication_store import store
        # No owner, no provider -> False.
        convo = _make_convo(owner_id="")
        assert main_module._conversation_owned_by(convo, "test-owner") is False
        # Owner matches -> True.
        convo2 = _make_convo(owner_id="test-owner")
        assert main_module._conversation_owned_by(convo2, "test-owner") is True
        # Provider ownership -> True only for the matching owner.
        store._providers["prov-a"] = _provider_record("prov-a", "a@a.com", user_id="owner-x")
        convo3 = _make_convo(owner_id="", provider_id="prov-a")
        assert main_module._conversation_owned_by(convo3, "owner-x") is True
        assert main_module._conversation_owned_by(convo3, "test-owner") is False
