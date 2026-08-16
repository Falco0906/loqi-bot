"""PR10.8.1 — Gmail OAuth credential failure cleanup & re-auth recovery.

Covers:
- invalid_grant classification (permanent reauth vs transient)
- no infinite refresh retry; provider enters explicit reauth-required state
- subsequent sync cycles skip reauth-required providers cleanly
- transient 5xx / network failures stay isolated and retryable
- one broken provider never stops other providers; app stays ready
- reauthentication clears the failure state and resumes sync
- credentials encrypted on persistence; no duplicate provider/account
- safe logging (no raw bodies, no tokens/client secrets)
- OAuth state remains single-use and validated
- PR8/PR9 reply/follow-up and inbox-filtering behavior preserved

All Google calls are mocked. Sentinels only — never real secrets.
"""
import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

SENTINEL_TOKEN = "PR1081_SENTINEL_ACCESS_TOKEN"
SENTINEL_REFRESH = "PR1081_SENTINEL_REFRESH_TOKEN"
SENTINEL_SECRET = "PR1081_SENTINEL_CLIENT_SECRET"
RAW_BODY_MARKER = "PR1081_RAW_RESPONSE_BODY_MARKER_NEVER_LOG"


@pytest.fixture(autouse=True)
def _clean_provider_state():
    """Reset the provider registry + communication store before each test."""
    from services.communication import provider_registry as pr
    from services.communication.communication_store import store as comm_store
    from services.outbound import outbound_registry as or_reg

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
    from services.communication import provider_registry
    from services.communication.gmail_provider import GmailProvider
    provider_registry.register_provider(GmailProvider)
    yield


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body) if isinstance(body, dict) else str(body)

    def json(self):
        if isinstance(self._body, dict):
            return self._body
        raise ValueError("not json")


def _mock_refresh(post_mock, status, body):
    """Patch requests.post so the token endpoint returns (status, body)."""
    import requests
    from services.communication import gmail_provider as gp
    real_post = requests.post

    def fake_post(url, **kwargs):
        if url == gp.TOKEN_URL:
            return _FakeResponse(status, body)
        return real_post(url, **kwargs)

    post_mock.side_effect = fake_post


# ═══════════════════════════════════════════════════════════════════════
# 1. Classification
# ═══════════════════════════════════════════════════════════════════════

class TestClassification:
    def test_invalid_grant_classified_permanent(self):
        from services.gmail_auth_failure import classify_refresh_status
        assert classify_refresh_status(400, "invalid_grant") == "reauth_required"
        assert classify_refresh_status(400, "unauthorized_client") == "reauth_required"

    def test_transient_statuses_remain_transient(self):
        from services.gmail_auth_failure import classify_refresh_status
        assert classify_refresh_status(500, "") == "transient"
        assert classify_refresh_status(503, "") == "transient"
        assert classify_refresh_status(429, "") == "transient"
        assert classify_refresh_status(408, "") == "transient"
        assert classify_refresh_status(200, "") == "success"

    def test_invalid_grant_raises_typed_error(self):
        from services.gmail_auth_failure import (
            raise_for_token_response, GmailReauthRequired, GmailTransientError,
        )
        with pytest.raises(GmailReauthRequired):
            raise_for_token_response(_FakeResponse(400, {"error": "invalid_grant"}))
        with pytest.raises(GmailTransientError):
            raise_for_token_response(_FakeResponse(500, {}))


# ═══════════════════════════════════════════════════════════════════════
# 2. No infinite retry + reauth-required state
# ═══════════════════════════════════════════════════════════════════════

class TestReauthState:
    def _provider(self, post_mock, refresh_status=400):
        from services.communication.gmail_provider import GmailProvider
        _mock_refresh(post_mock, refresh_status, {"error": "invalid_grant", "error_description": "revoked"})
        provider = GmailProvider()
        provider.connect(
            auth_token="tok", user_id="user-1", email="a@b.com",
            refresh_token=SENTINEL_REFRESH, client_id="cid", client_secret=SENTINEL_SECRET,
        )
        provider._token_expiry = 0  # force refresh on next _ensure_auth
        return provider

    def test_invalid_grant_no_infinite_retry(self, monkeypatch):
        import requests
        post_mock = MagicMock()
        _mock_refresh(post_mock, 400, {"error": "invalid_grant", "error_description": "revoked"})
        monkeypatch.setattr(requests, "post", post_mock)
        from services.gmail_auth_failure import GmailReauthRequired
        from services.communication.gmail_provider import GmailProvider
        provider = GmailProvider()
        provider.connect(
            auth_token="tok", user_id="user-1", email="a@b.com",
            refresh_token=SENTINEL_REFRESH, client_id="cid", client_secret=SENTINEL_SECRET,
        )
        provider._token_expiry = 0
        with pytest.raises(GmailReauthRequired):
            provider._ensure_auth()
        # Exactly one token-endpoint attempt — no retry loop.
        token_calls = [c for c in post_mock.call_args_list if c.args and "token" in str(c.args[0])]
        assert len(token_calls) == 1

    def test_provider_enters_reauth_required(self, monkeypatch):
        import requests
        from services.gmail_auth_failure import GmailReauthRequired
        from services.communication.gmail_provider import GmailProvider
        from services.communication.communication_store import store
        from services.communication.provider_models import ProviderStatus
        post_mock = MagicMock()
        _mock_refresh(post_mock, 400, {"error": "invalid_grant", "error_description": "revoked"})
        monkeypatch.setattr(requests, "post", post_mock)
        monkeypatch.setattr("services.supabase.mark_connected_account_auth_failed", lambda *a, **k: True)
        provider = GmailProvider()
        provider.connect(
            auth_token="tok", user_id="user-1", email="a@b.com",
            refresh_token=SENTINEL_REFRESH, client_id="cid", client_secret=SENTINEL_SECRET,
        )
        provider._token_expiry = 0
        with pytest.raises(GmailReauthRequired):
            provider._ensure_auth()
        assert provider._connected is False
        assert store.get_provider(provider._provider_id).status is ProviderStatus.AUTH_FAILED

    def test_reauth_required_persisted_to_account_row(self, monkeypatch):
        from services.communication.gmail_provider import GmailProvider
        marked = {}
        monkeypatch.setattr("services.supabase.mark_connected_account_auth_failed",
                            lambda uid, provider="google": marked.update(uid=uid) or True)
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH)
        provider.mark_reauth_required()
        assert marked.get("uid") == "user-1"

    def test_subsequent_sync_skips_reauth_required_provider(self, monkeypatch):
        import asyncio
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry
        from services.communication.inbox_sync_engine import InboxSyncEngine
        from services.gmail_auth_failure import GmailReauthRequired
        import requests
        post_mock = MagicMock()
        _mock_refresh(post_mock, 400, {"error": "invalid_grant", "error_description": "revoked"})
        monkeypatch.setattr(requests, "post", post_mock)
        monkeypatch.setattr("services.supabase.mark_connected_account_auth_failed", lambda *a, **k: True)

        provider = GmailProvider()
        record = provider.connect(auth_token="tok", user_id="user-1", email="a@b.com",
                                  refresh_token=SENTINEL_REFRESH)
        provider_registry.register_instance(record.id, provider)
        # First sync hits the doomed refresh and marks the provider.
        with pytest.raises(GmailReauthRequired):
            provider.sync(cursor="")
        assert provider._connected is False
        calls = {"n": 0}
        provider.sync = lambda cursor="": calls.__setitem__("n", calls["n"] + 1) or MagicMock()

        async def _run():
            engine = InboxSyncEngine(interval_seconds=60)
            await engine.sync_once()
            await engine.stop()

        asyncio.run(_run())
        assert calls["n"] == 0  # skipped — no sync attempt, no refresh attempt


# ═══════════════════════════════════════════════════════════════════════
# 3. Transient isolation
# ═══════════════════════════════════════════════════════════════════════

class TestTransientIsolation:
    def test_transient_5xx_does_not_mark_reauth(self, monkeypatch):
        import requests
        from services.gmail_auth_failure import GmailTransientError
        from services.communication.gmail_provider import GmailProvider
        from services.communication.communication_store import store
        from services.communication.provider_models import ProviderStatus
        post_mock = MagicMock()
        _mock_refresh(post_mock, 503, {})
        monkeypatch.setattr(requests, "post", post_mock)
        provider = GmailProvider()
        provider.connect(auth_token="tok", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH)
        provider._token_expiry = 0
        with pytest.raises(GmailTransientError):
            provider._ensure_auth()
        # Still connected and healthy — a single transient failure must not
        # disable the provider.
        assert provider._connected is True
        assert store.get_provider(provider._provider_id).status is ProviderStatus.HEALTHY

    def test_network_failure_isolated_and_not_reauth(self, monkeypatch):
        import requests
        from services.gmail_auth_failure import GmailTransientError
        from services.communication.gmail_provider import GmailProvider
        post_mock = MagicMock(side_effect=requests.ConnectionError("network down"))
        monkeypatch.setattr(requests, "post", post_mock)
        provider = GmailProvider()
        provider.connect(auth_token="tok", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH)
        provider._token_expiry = 0
        with pytest.raises(GmailTransientError):
            provider._ensure_auth()
        assert provider._connected is True

    def test_one_broken_provider_does_not_stop_others(self):
        import asyncio
        from services.communication import provider_registry
        from services.communication.inbox_sync_engine import InboxSyncEngine
        from services.communication.provider_models import (
            SyncResult, ProviderType, ProviderStatus,
        )

        class Broken:
            provider_type = ProviderType.GMAIL
            _provider_id = "broken-1"
            _connected = True
            _user_id = "user-b"

            def sync(self, cursor=""):
                raise RuntimeError("broken provider boom")

        class Good:
            provider_type = ProviderType.GMAIL
            _provider_id = "good-1"
            _connected = True
            _user_id = "user-g"

            def sync(self, cursor=""):
                return SyncResult(provider_id="good-1", cursor="new", errors=[])

        provider_registry.register_instance("broken-1", Broken())
        provider_registry.register_instance("good-1", Good())

        async def _run():
            engine = InboxSyncEngine(interval_seconds=60)
            result = await engine.sync_once()
            await engine.stop()
            return result

        result = asyncio.run(_run())
        assert result["providers"] == 2
        assert len(result["results"]) == 1  # only the good provider produced a result
        assert result["results"][0].provider_id == "good-1"

    def test_application_remains_ready_when_provider_disconnected(self):
        from services import lifecycle
        lifecycle.set_ready()
        # Simulate the failure path; readiness state must be untouched.
        from services.communication.gmail_provider import GmailProvider
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH)
        provider.mark_reauth_required()
        assert lifecycle.is_ready() is True
        lifecycle.set_starting()


# ═══════════════════════════════════════════════════════════════════════
# 4. Reauthentication flow
# ═══════════════════════════════════════════════════════════════════════

class TestReauthentication:
    def test_reauth_clears_failure_state(self, monkeypatch):
        """Reconnect (sync_connected_account) returns the row to active."""
        from services.persistence.launch import ConnectedAccount
        from services.supabase import sync_connected_account, is_connected_account_reauth_required

        class FakeRepo:
            def __init__(self):
                self.account = ConnectedAccount(
                    user_id="user-1", provider="google", email="a@b.com",
                    access_token="old", refresh_token="old", status="auth_failed",
                )

            async def find_for_user(self, uid, provider):
                return self.account

            async def save(self, entity):
                self.account = entity
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        assert is_connected_account_reauth_required("user-1", "google") is True
        ok = sync_connected_account("user-1", provider="google", email="a@b.com",
                                    access_token="new-token", refresh_token="new-refresh")
        assert ok is True
        assert is_connected_account_reauth_required("user-1", "google") is False

    def test_new_credentials_encrypted_on_persistence(self, monkeypatch):
        from services.supabase import sync_connected_account
        from services.credential_crypto import is_encrypted
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.saved = None

            async def find_for_user(self, uid, provider):
                return None

            async def save(self, entity):
                self.saved = entity
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        ok = sync_connected_account("user-1", provider="google", email="a@b.com",
                                    access_token=SENTINEL_TOKEN, refresh_token=SENTINEL_REFRESH)
        assert ok is True
        assert is_encrypted(repo.saved.access_token)
        assert is_encrypted(repo.saved.refresh_token)

    def test_restored_provider_uses_new_credentials(self):
        from services.communication.gmail_provider import GmailProvider
        provider = GmailProvider()
        provider.connect(
            auth_token="NEW_ACCESS", user_id="user-1", email="a@b.com",
            refresh_token="NEW_REFRESH", client_id="cid", client_secret="csec",
        )
        assert provider._access_token == "NEW_ACCESS"
        assert provider._refresh_token == "NEW_REFRESH"

    def test_no_duplicate_provider_on_reconnect(self, monkeypatch):
        """Reconnecting replaces the existing provider instance for the user."""
        import main as main_module
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry
        # First (reauth-required) provider for user-1.
        old = GmailProvider()
        old_record = old.connect(auth_token="old", user_id="user-1", email="a@b.com",
                                 refresh_token=SENTINEL_REFRESH)
        provider_registry.register_instance(old_record.id, old)
        old.mark_reauth_required()
        assert len(provider_registry.list_providers()) == 1
        # Reconnect.
        main_module._remove_existing_gmail_provider("user-1")
        assert len(provider_registry.list_providers()) == 0
        new = GmailProvider()
        new_record = new.connect(auth_token="NEW", user_id="user-1", email="a@b.com",
                                 refresh_token="NEW_REFRESH")
        provider_registry.register_instance(new_record.id, new)
        gmail_for_user = [
            p for p in provider_registry.list_providers().values()
            if getattr(p, "_user_id", "") == "user-1"
        ]
        assert len(gmail_for_user) == 1

    def test_upsert_reuses_existing_account_row(self, monkeypatch):
        from services.supabase import sync_connected_account
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.saved_count = 0

            async def find_for_user(self, uid, provider):
                return ConnectedAccount(
                    user_id=uid, provider=provider, email="a@b.com",
                    access_token="old", refresh_token="old", status="auth_failed",
                )

            async def save(self, entity):
                self.saved_count += 1
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        ok = sync_connected_account("user-1", provider="google", email="a@b.com",
                                    access_token="x", refresh_token="y")
        assert ok is True
        # Update-in-place — one save, no new insert/duplicate record.
        assert repo.saved_count == 1


# ═══════════════════════════════════════════════════════════════════════
# 5. Logging sanitization
# ═══════════════════════════════════════════════════════════════════════

class TestLoggingSanitization:
    def test_invalid_grant_logs_safe_metadata_only(self, monkeypatch, caplog):
        import logging
        import requests
        from services.gmail_auth_failure import GmailReauthRequired
        from services.communication.gmail_provider import GmailProvider
        post_mock = MagicMock()
        _mock_refresh(post_mock, 400, {
            "error": "invalid_grant",
            "error_description": RAW_BODY_MARKER,
        })
        monkeypatch.setattr(requests, "post", post_mock)
        monkeypatch.setattr("services.supabase.mark_connected_account_auth_failed", lambda *a, **k: True)
        provider = GmailProvider()
        provider.connect(auth_token=SENTINEL_TOKEN, user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH, client_secret=SENTINEL_SECRET)
        provider._token_expiry = 0
        with caplog.at_level(logging.WARNING):
            with pytest.raises(GmailReauthRequired):
                provider._ensure_auth()
        joined = caplog.text
        assert "gmail_auth_reauth_required" in joined
        assert "action=reauth_required" in joined
        assert SENTINEL_TOKEN not in joined
        assert SENTINEL_REFRESH not in joined
        assert SENTINEL_SECRET not in joined
        assert RAW_BODY_MARKER not in joined

    def test_raw_response_body_not_logged(self, monkeypatch, caplog):
        import logging
        import requests
        from services.gmail_auth_failure import GmailTransientError
        from services.communication.gmail_provider import GmailProvider
        post_mock = MagicMock()
        _mock_refresh(post_mock, 500, {"error": "backend_error", "detail": RAW_BODY_MARKER})
        monkeypatch.setattr(requests, "post", post_mock)
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL_REFRESH)
        provider._token_expiry = 0
        with caplog.at_level(logging.INFO):
            with pytest.raises(GmailTransientError):
                provider._ensure_auth()
        assert RAW_BODY_MARKER not in caplog.text

    def test_outbound_refresh_failure_sanitized(self, monkeypatch, caplog):
        import logging
        import requests
        from services.gmail_auth_failure import GmailReauthRequired
        from services.outbound.gmail_outbound import GmailOutboundProvider
        post_mock = MagicMock()
        _mock_refresh(post_mock, 400, {"error": "invalid_grant", "error_description": RAW_BODY_MARKER})
        monkeypatch.setattr(requests, "post", post_mock)
        outbound = GmailOutboundProvider()
        outbound.configure(
            provider_id="p1", access_token=SENTINEL_TOKEN, refresh_token=SENTINEL_REFRESH,
            client_id="cid", client_secret=SENTINEL_SECRET, token_expiry=0, user_id="user-1",
        )
        with caplog.at_level(logging.INFO):
            with pytest.raises(GmailReauthRequired):
                outbound._refresh_auth()
        assert SENTINEL_TOKEN not in caplog.text
        assert SENTINEL_REFRESH not in caplog.text
        assert SENTINEL_SECRET not in caplog.text
        assert RAW_BODY_MARKER not in caplog.text


# ═══════════════════════════════════════════════════════════════════════
# 6. OAuth state single-use (PR10.7 preserved)
# ═══════════════════════════════════════════════════════════════════════

class TestOAuthStateStillValidated:
    def test_state_single_use_and_validated(self):
        from services.oauth_state import issue_state, consume_state
        import asyncio
        state = asyncio.run(issue_state("user-1"))
        user_id, _ = asyncio.run(consume_state(state))
        assert user_id == "user-1"
        assert asyncio.run(consume_state(state)) == (None, None)  # single-use

    def test_invalid_state_rejected(self):
        from services.oauth_state import consume_state
        import asyncio
        assert asyncio.run(consume_state("dev_providers:user-1")) == (None, None)
        assert asyncio.run(consume_state("forged-state")) == (None, None)
        assert asyncio.run(consume_state("")) == (None, None)


# ═══════════════════════════════════════════════════════════════════════
# 7. PR8/PR9 behavior preserved
# ═══════════════════════════════════════════════════════════════════════

class TestExistingBehaviorPreserved:
    def test_reply_idempotency_intact(self):
        from services.conversations.integration import create_conversation_from_send, handle_reply
        from services.conversations.conversation_store import conversation_store
        convo = create_conversation_from_send(
            provider_id="pr1081", provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"o_{uuid.uuid4().hex[:12]}",
            subject="reply intact", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        reply_ext = f"r_{uuid.uuid4().hex[:12]}"
        first = handle_reply(
            conversation_id=convo.conversation_id, external_message_id=reply_ext,
            from_email="c@d.com", from_name="C", to_email="a@b.com", to_name="A",
            subject="Re: reply intact", body="same",
        )
        second = handle_reply(
            conversation_id=convo.conversation_id, external_message_id=reply_ext,
            from_email="c@d.com", from_name="C", to_email="a@b.com", to_name="A",
            subject="Re: reply intact", body="same",
        )
        assert first.message_id == second.message_id
        msgs = [m for m in conversation_store.get_messages_for_conversation(convo.conversation_id)
                if m.external_message_id == reply_ext]
        assert len(msgs) == 1

    def test_followup_readiness_dedup_intact(self):
        from services.communication.inbox_sync_engine import _mark_ready
        from services.conversations.conversation_models import ConversationStatus
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send
        from services.conversations.state_machine import transition
        from services.conversations.timeline import TimelineEventType
        convo = create_conversation_from_send(
            provider_id="pr1081", provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"m_{uuid.uuid4().hex[:12]}",
            subject="followup intact", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        convo.status = transition(convo.status, ConversationStatus.FOLLOW_UP_PENDING)
        conversation_store.update_conversation(convo)
        _mark_ready(convo)
        _mark_ready(convo)
        ready = [e for e in conversation_store.get_timeline(convo.conversation_id)
                 if e.event_type == TimelineEventType.FOLLOW_UP_READY]
        assert len(ready) == 1

    def test_inbox_filtering_intact(self):
        from services.communication.inbound_filter import resolve_inbound_conversation
        # Unrelated inbound from an unknown sender must be dropped (no orphan).
        cid, disposition = resolve_inbound_conversation(
            provider_id="pr1081", provider_user_id="user-1",
            thread_id=f"t_{uuid.uuid4().hex[:12]}",
            sender_email="stranger@unknown.example",
        )
        assert cid is None
        assert disposition is not None
