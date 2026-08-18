"""PR10.8.3 — Security audit regression suite.

Confirms the security fixes for confirmed findings:

1. Session tokens are redacted from request logs (never logged in paths).
2. Provider routes enforce ownership (IDOR: user A cannot act on user B's
   provider via disconnect/health/sync/status).
3. The Telegram webhook is authenticated when a secret is configured.
4. The legacy /providers/connect route is disabled in production.
5. send_draft cannot send a draft owned by another user.
6. Conversation reply/follow-up routes cannot act on another user's
   conversation.
7. Production config requires TELEGRAM_WEBHOOK_SECRET when the bot is active.

Deterministic sentinels only — never real credentials.
"""
import asyncio
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

SENTINEL = "PR1083_SENTINEL_SECRET_DO_NOT_LEAK"
SENTINEL_SESSION = "PR1083_SENTINEL_SESSION_TOKEN"


@pytest.fixture(autouse=True)
def _clean_runtime_state(monkeypatch):
    from services.communication import provider_registry as pr
    from services.communication.communication_store import store as comm_store
    from services.outbound import outbound_registry as or_reg
    from services.conversations.conversation_store import conversation_store

    def _reset():
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

    _reset()
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    yield
    _reset()


def _provider_record(pid, email, user_id="owner-a", status="healthy"):
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


class _Status:
    def __init__(self, value):
        self.value = value


def _fake_instance(status_value="healthy"):
    inst = MagicMock()
    inst.health = lambda: _Status(status_value)
    inst._user_id = "owner-a"
    inst._connected = True
    return inst


# ═══════════════════════════════════════════════════════════════════════
# 1. Session-token redaction in logs
# ═══════════════════════════════════════════════════════════════════════

class TestSessionTokenRedaction:
    def test_redact_session_path(self):
        from services.operations.middleware import redact_session_path
        assert redact_session_path("/api/web/session/abc123/providers") == \
            "/api/web/session/[REDACTED]/providers"
        assert redact_session_path("/api/web/session/abc123/drafts/d1/approve") == \
            "/api/web/session/[REDACTED]/drafts/d1/approve"
        # Non-session paths are unchanged.
        assert redact_session_path("/health") == "/health"
        assert redact_session_path("/api/auth/gmail/url") == "/api/auth/gmail/url"

    def test_middleware_logs_redacted_path(self, caplog):
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
                resp = client.get(f"/api/web/session/{SENTINEL_SESSION}/providers")
            assert resp.status_code == 200
        # The application's own logs must never contain the session token and
        # must show the redacted path. (The httpx test-client request log is
        # test infra, not the application logger.)
        app_records = [r for r in caplog.records if r.name == "loqi"]
        assert app_records, "expected application log records"
        assert not any(SENTINEL_SESSION in (r.getMessage() or "") for r in app_records)
        assert any("[REDACTED]" in (r.getMessage() or "") for r in app_records)


# ═══════════════════════════════════════════════════════════════════════
# 2. Provider route IDOR
# ═══════════════════════════════════════════════════════════════════════

class TestProviderRouteOwnership:
    def _setup(self, monkeypatch):
        import main as main_module
        from services.communication.communication_store import store
        # A provider owned by "owner-b" (the victim).
        store._providers["prov-b"] = _provider_record("prov-b", "victim@b.com", user_id="owner-b")
        store._user_providers["owner-b"] = ["prov-b"]
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-a"))
        return main_module

    def test_health_denied_for_another_users_provider(self, monkeypatch):
        m = self._setup(monkeypatch)
        with pytest.raises(Exception) as exc:
            asyncio.run(m.provider_health("tok", "prov-b", MagicMock()))
        assert exc.value.status_code == 404

    def test_disconnect_denied_for_another_users_provider(self, monkeypatch):
        m = self._setup(monkeypatch)
        with pytest.raises(Exception) as exc:
            asyncio.run(m.provider_disconnect("tok", "prov-b", MagicMock()))
        assert exc.value.status_code == 404

    def test_sync_denied_for_another_users_provider(self, monkeypatch):
        m = self._setup(monkeypatch)
        with pytest.raises(Exception) as exc:
            asyncio.run(m.provider_sync("tok", "prov-b", MagicMock()))
        assert exc.value.status_code == 404

    def test_status_denied_for_another_users_provider(self, monkeypatch):
        m = self._setup(monkeypatch)
        with pytest.raises(Exception) as exc:
            asyncio.run(m.provider_status("tok", "prov-b", MagicMock()))
        assert exc.value.status_code == 404

    def test_owner_can_access_own_provider(self, monkeypatch):
        import main as m
        from services.communication.communication_store import store
        m = self._setup(monkeypatch)
        store._providers["prov-a"] = _provider_record("prov-a", "a@a.com", user_id="owner-a")
        store._user_providers["owner-a"] = ["prov-a"]
        monkeypatch.setattr(m, "_workspace_owner", AsyncMock(return_value="owner-a"))
        monkeypatch.setattr(m, "get_provider", lambda pid: _fake_instance("healthy"))
        result = asyncio.run(m.provider_health("tok", "prov-a", MagicMock()))
        assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════════
# 3. Telegram webhook authentication
# ═══════════════════════════════════════════════════════════════════════

class TestTelegramWebhookAuth:
    def test_webhook_rejected_without_secret_when_configured(self, monkeypatch):
        from fastapi import HTTPException
        import main as main_module
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret-abc")
        request = MagicMock()
        request.headers.get = lambda *a, **k: ""
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.telegram_webhook(request))
        assert exc.value.status_code == 403

    def test_webhook_accepted_with_matching_secret(self, monkeypatch):
        import main as main_module
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret-abc")
        request = MagicMock()
        request.headers.get = lambda *a, **k: "webhook-secret-abc"
        request.json = AsyncMock(return_value={})
        with patch.object(main_module, "process_message", lambda *a, **k: None):
            result = asyncio.run(main_module.telegram_webhook(request))
        assert result == {"status": "ok"}

    def test_webhook_accepted_when_secret_not_configured(self):
        import main as main_module
        request = MagicMock()
        request.json = AsyncMock(return_value={})
        with patch.object(main_module, "process_message", lambda *a, **k: None):
            result = asyncio.run(main_module.telegram_webhook(request))
        assert result == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
# 4. Legacy /providers/connect disabled in production
# ═══════════════════════════════════════════════════════════════════════

class TestLegacyConnectProductionGuard:
    def test_provider_connect_rejected_in_production(self, monkeypatch):
        import main as main_module
        monkeypatch.setenv("ENVIRONMENT", "production")
        payload = MagicMock()
        payload.provider_type = "gmail"
        payload.auth_token = SENTINEL
        payload.email = "a@a.com"
        payload.scope = ""
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.provider_connect("tok", payload))
        assert exc.value.status_code == 403

    def test_provider_connect_allowed_in_development(self, monkeypatch):
        import main as main_module
        from services.communication.communication_store import store
        from services.communication import provider_registry
        from services.communication.gmail_provider import GmailProvider
        provider_registry.register_provider(GmailProvider)
        monkeypatch.setenv("ENVIRONMENT", "development")
        payload = MagicMock()
        payload.provider_type = "gmail"
        payload.auth_token = "fake-token"
        payload.email = "a@a.com"
        payload.scope = ""
        request = MagicMock()
        request.headers.get = lambda k, d="": "Bearer tok" if k == "authorization" else d
        # GmailProvider.connect stores a provider record; no network calls.
        result = asyncio.run(main_module.provider_connect("_", payload, request))
        assert result["ok"] is True
        assert len(store.get_user_providers("tok")) == 1


# ═══════════════════════════════════════════════════════════════════════
# 5. send_draft cross-user draft ownership
# ═══════════════════════════════════════════════════════════════════════

class TestSendDraftOwnership:
    def test_send_denied_for_another_users_draft(self, monkeypatch):
        import main as main_module
        from services.outbound.draft_store import draft_store
        from services.outbound.outbound_models import DraftMessage, Recipient
        from services.communication.communication_store import store

        store._providers["prov-b"] = _provider_record("prov-b", "victim@b.com", user_id="owner-b")
        draft = DraftMessage(
            id="draft-b-1",
            provider_id="prov-b",
            subject="Victim draft",
            body="Secret body",
            recipient=Recipient(email="victim-target@x.com", name="Target"),
            sender=Recipient(email="victim@b.com", name="Victim"),
        )
        draft_store.create(draft)
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-a"))
        request = MagicMock()
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.send_draft("tok", "draft-b-1", request))
        # Safe not-found (no existence leak): a foreign draft is 404, not 403.
        assert exc.value.status_code == 404
        draft_store.delete("draft-b-1")


# ═══════════════════════════════════════════════════════════════════════
# 6. Conversation reply/follow-up ownership
# ═══════════════════════════════════════════════════════════════════════

class TestConversationSendOwnership:
    def _convo(self):
        from services.conversations.integration import create_conversation_from_send
        from services.communication.communication_store import store
        store._providers["prov-b"] = _provider_record("prov-b", "victim@b.com", user_id="owner-b")
        return create_conversation_from_send(
            provider_id="prov-b",
            provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"msg_{uuid.uuid4().hex[:12]}",
            subject="Victim convo",
            from_email="victim@b.com", from_name="Victim",
            to_email="target@x.com", to_name="Target",
            body="hello",
        )

    def test_reply_denied_for_another_users_conversation(self, monkeypatch):
        import main as main_module
        convo = self._convo()
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-a"))
        payload = MagicMock()
        payload.body = "reply"
        payload.test_recipient = ""
        payload.thread_id = ""
        request = MagicMock()
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.send_conversation_reply_route(
                "tok", convo.conversation_id, payload, request,
            ))
        # Safe not-found (no existence leak): foreign conversation is 404.
        assert exc.value.status_code == 404

    def test_followup_denied_for_another_users_conversation(self, monkeypatch):
        import main as main_module
        convo = self._convo()
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-a"))
        payload = MagicMock()
        payload.body = "follow-up"
        payload.test_recipient = ""
        payload.thread_id = ""
        request = MagicMock()
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.send_conversation_followup_route(
                "tok", convo.conversation_id, payload, request,
            ))
        # Safe not-found (no existence leak): foreign conversation is 404.
        assert exc.value.status_code == 404

    def test_timeline_denied_for_another_users_conversation(self, monkeypatch):
        import main as main_module
        convo = self._convo()
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-a"))
        request = MagicMock()
        with pytest.raises(Exception) as exc:
            asyncio.run(main_module.communication_timeline("tok", convo.conversation_id, request))
        # Safe not-found (no existence leak): foreign conversation is 404.
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 7. Production config: webhook secret
# ═══════════════════════════════════════════════════════════════════════

class TestWebhookSecretConfig:
    def test_production_requires_webhook_secret_when_bot_active(self):
        from services import config_validation as cv
        errors, _ = cv.validate_config({
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_WEBHOOK_SECRET": "",
        })
        assert any("TELEGRAM_WEBHOOK_SECRET" in e for e in errors)

    def test_production_ok_with_webhook_secret(self):
        from services import config_validation as cv
        errors, _ = cv.validate_config({
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_WEBHOOK_SECRET": "webhook-secret",
        })
        assert not any("TELEGRAM_WEBHOOK_SECRET" in e for e in errors)
