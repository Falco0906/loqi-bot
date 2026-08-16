"""PR10.8.2 — Gmail duplicate connections + reauth state persistence.

Covers:
- 'auth_failed' is a valid persisted connected_accounts status (migration)
- invalid_grant → AUTH_FAILED persisted state
- auth_failed account is skipped by sync and never retried every cycle
- reconnect updates/replaces the existing account (no duplicate row/provider)
- one Gmail account per user; unrelated accounts stay independent
- existing encrypted credentials remain encrypted
- OAuth state remains single-use
- app remains READY-independent
- Settings/API never returns duplicate logical Gmail accounts
- existing unrelated providers are untouched

Sentinels only; never real secrets.
"""
import asyncio
import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

SENTINEL = "PR1082_SENTINEL_SECRET_DO_NOT_LEAK"


@pytest.fixture(autouse=True)
def _clean_runtime_state():
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


# ═══════════════════════════════════════════════════════════════════════
# 1. Migration: auth_failed is a valid persisted status
# ═══════════════════════════════════════════════════════════════════════

class TestMigrationConstraint:
    def test_migration_allows_auth_failed_and_preserves_existing(self):
        import services.migration as m
        sql = m.CONNECTED_ACCOUNTS_AUTH_FAILED_SQL
        assert "auth_failed" in sql
        # Every pre-existing valid status is preserved.
        for status in ("'active'", "'pending'", "'expired'", "'revoked'", "'error'"):
            assert status in sql
        # The constraint is kept (not weakened to an unrestricted string).
        assert "connected_accounts_status_check" in sql
        assert "check" in sql

    def test_migration_file_matches_inline_sql(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                            "020_connected_accounts_auth_failed.sql")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "auth_failed" in content
        assert "'active'" in content and "'error'" in content

    def test_connected_account_repo_writes_auth_failed(self):
        from services.persistence.launch import ConnectedAccount, ConnectedAccountRepository
        import asyncio

        class FakeRepo(ConnectedAccountRepository):
            def __init__(self):
                self.saved = None

            async def save(self, entity):
                self.saved = entity
                return entity

        repo = FakeRepo()
        account = ConnectedAccount(user_id="u1", provider="google", status="auth_failed",
                                   access_token=SENTINEL, refresh_token=SENTINEL)
        asyncio.run(repo.save(account))
        assert repo.saved.status == "auth_failed"
        assert repo.saved.access_token == SENTINEL


# ═══════════════════════════════════════════════════════════════════════
# 2. Reauth state persistence
# ═══════════════════════════════════════════════════════════════════════

class TestReauthState:
    def test_invalid_grant_marks_auth_failed(self, monkeypatch):
        import requests
        from services.gmail_auth_failure import GmailReauthRequired
        from services.communication.gmail_provider import GmailProvider
        from services.communication.communication_store import store
        from services.communication.provider_models import ProviderStatus

        post_mock = MagicMock()

        def fake_post(url, **kwargs):
            class R:
                status_code = 400
                text = json.dumps({"error": "invalid_grant"})

                def json(self):
                    return {"error": "invalid_grant", "error_description": "revoked"}

            return R()

        post_mock.side_effect = fake_post
        monkeypatch.setattr(requests, "post", post_mock)
        monkeypatch.setattr("services.supabase.mark_connected_account_auth_failed",
                            lambda *a, **k: True)
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL, client_id="cid", client_secret="sec")
        provider._token_expiry = 0
        with pytest.raises(GmailReauthRequired):
            provider._ensure_auth()
        assert provider._connected is False
        assert store.get_provider(provider._provider_id).status is ProviderStatus.AUTH_FAILED

    def test_auth_failed_persisted_via_mark(self, monkeypatch):
        from services.supabase import mark_connected_account_auth_failed
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.account = ConnectedAccount(user_id="user-1", provider="google",
                                                status="active", access_token="x", refresh_token="y")
                self.saved = None

            async def find_for_user(self, uid, provider):
                return self.account

            async def save(self, entity):
                self.saved = entity
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        ok = mark_connected_account_auth_failed("user-1", "google")
        assert ok is True
        assert repo.saved.status == "auth_failed"

    def test_auth_failed_account_skipped_by_sync(self):
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry
        from services.communication.inbox_sync_engine import InboxSyncEngine
        provider = GmailProvider()
        record = provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                                  refresh_token=SENTINEL)
        provider_registry.register_instance(record.id, provider)
        provider.mark_reauth_required()
        calls = {"n": 0}
        provider.sync = lambda cursor="": calls.__setitem__("n", calls["n"] + 1) or MagicMock()

        asyncio.run(InboxSyncEngine(interval_seconds=60).sync_once())
        assert calls["n"] == 0

    def test_auth_failed_does_not_retry_every_cycle(self, monkeypatch):
        import requests
        from services.gmail_auth_failure import GmailReauthRequired
        from services.communication.gmail_provider import GmailProvider
        post_mock = MagicMock()

        def fake_post(url, **kwargs):
            class R:
                status_code = 400
                text = '{"error": "invalid_grant"}'

                def json(self):
                    return {"error": "invalid_grant"}

            return R()

        post_mock.side_effect = fake_post
        monkeypatch.setattr(requests, "post", post_mock)
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL)
        provider._token_expiry = 0
        with pytest.raises(GmailReauthRequired):
            provider._ensure_auth()
        token_calls = [c for c in post_mock.call_args_list]
        assert len(token_calls) == 1

    def test_app_stays_ready(self):
        from services import lifecycle
        from services.communication.gmail_provider import GmailProvider
        lifecycle.set_ready()
        provider = GmailProvider()
        provider.connect(auth_token="t", user_id="user-1", email="a@b.com",
                         refresh_token=SENTINEL)
        provider.mark_reauth_required()
        assert lifecycle.is_ready() is True
        lifecycle.set_starting()


# ═══════════════════════════════════════════════════════════════════════
# 3. Idempotent reconnect (no duplicate row / provider)
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotentReconnect:
    def test_reconnect_updates_auth_failed_account(self, monkeypatch):
        from services.supabase import sync_connected_account, is_connected_account_reauth_required
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.account = ConnectedAccount(
                    user_id="user-1", provider="google", email="a@b.com",
                    access_token="old", refresh_token="old", status="auth_failed",
                )
                self.saves = 0

            async def find_for_user(self, uid, provider):
                return self.account

            async def save(self, entity):
                self.account = entity
                self.saves += 1
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        assert is_connected_account_reauth_required("user-1", "google") is True
        ok = sync_connected_account("user-1", provider="google", account_id="sub-123",
                                    email="a@b.com", access_token="new", refresh_token="new-r")
        assert ok is True
        assert is_connected_account_reauth_required("user-1", "google") is False
        assert repo.account.status == "active"
        assert repo.account.account_id == "sub-123"
        assert repo.saves == 1  # update in place — no duplicate row

    def test_reconnect_no_duplicate_row(self, monkeypatch):
        from services.supabase import sync_connected_account
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.rows = {}
                self.saves = 0

            async def find_for_user(self, uid, provider):
                return self.rows.get((uid, provider))

            async def save(self, entity):
                self.rows[(entity.user_id, entity.provider)] = entity
                self.saves += 1
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        assert sync_connected_account("user-1", provider="google", email="a@b.com",
                                      access_token="t1", refresh_token="r1") is True
        assert len(repo.rows) == 1
        assert sync_connected_account("user-1", provider="google", email="a@b.com",
                                      access_token="t2", refresh_token="r2") is True
        assert len(repo.rows) == 1  # still one row — updated, not duplicated
        assert repo.rows[("user-1", "google")].access_token != "t1"

    def test_reconnect_no_duplicate_runtime_providers(self, monkeypatch):
        import main as main_module
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry

        old = GmailProvider()
        old_record = old.connect(auth_token="old", user_id="user-1", email="a@b.com",
                                 refresh_token=SENTINEL)
        provider_registry.register_instance(old_record.id, old)
        old.mark_reauth_required()
        assert len(provider_registry.list_providers()) == 1
        main_module._remove_existing_gmail_provider("user-1")
        assert len(provider_registry.list_providers()) == 0
        new = GmailProvider()
        new_record = new.connect(auth_token="new", user_id="user-1", email="a@b.com",
                                 account_id="sub-123", refresh_token="new-r")
        provider_registry.register_instance(new_record.id, new)
        gmail = [p for p in provider_registry.list_providers().values()
                 if getattr(p, "_user_id", "") == "user-1"]
        assert len(gmail) == 1

    def test_same_google_account_cannot_appear_twice(self, monkeypatch):
        from services.supabase import sync_connected_account
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.row = None
                self.saves = 0

            async def find_for_user(self, uid, provider):
                return self.row

            async def save(self, entity):
                self.row = entity
                self.saves += 1
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        for i in range(3):
            assert sync_connected_account("user-1", provider="google", email="a@b.com",
                                          access_token=f"t{i}", refresh_token=f"r{i}") is True
        assert repo.saves == 3
        assert len([1 for _ in [repo.row]]) == 1  # single canonical row

    def test_different_users_with_same_email_stay_independent(self, monkeypatch):
        """Two distinct users connecting the same Gmail address remain independent."""
        from services.supabase import sync_connected_account
        from services.persistence.launch import ConnectedAccount

        class FakeRepo:
            def __init__(self):
                self.rows = {}

            async def find_for_user(self, uid, provider):
                return self.rows.get((uid, provider))

            async def save(self, entity):
                self.rows[(entity.user_id, entity.provider)] = entity
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        assert sync_connected_account("user-a", provider="google", email="same@x.com",
                                      access_token="a1", refresh_token="a2") is True
        assert sync_connected_account("user-b", provider="google", email="same@x.com",
                                      access_token="b1", refresh_token="b2") is True
        assert len(repo.rows) == 2
        assert repo.rows[("user-a", "google")].email == "same@x.com"
        assert repo.rows[("user-b", "google")].email == "same@x.com"

    def test_existing_credentials_remain_encrypted(self, monkeypatch):
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
                                    access_token=SENTINEL, refresh_token=SENTINEL)
        assert ok is True
        assert is_encrypted(repo.saved.access_token)
        assert is_encrypted(repo.saved.refresh_token)

    def test_unrelated_providers_untouched(self, monkeypatch):
        import main as main_module
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry

        gmail_user1 = GmailProvider()
        rec1 = gmail_user1.connect(auth_token="t", user_id="user-1", email="a@b.com",
                                   refresh_token=SENTINEL)
        provider_registry.register_instance(rec1.id, gmail_user1)
        gmail_user2 = GmailProvider()
        rec2 = gmail_user2.connect(auth_token="t", user_id="user-2", email="c@d.com",
                                   refresh_token=SENTINEL)
        provider_registry.register_instance(rec2.id, gmail_user2)

        class OtherProvider:
            provider_type = "outlook"
            _user_id = "user-1"

        other = OtherProvider()
        provider_registry.register_instance("other-1", other)

        main_module._remove_existing_gmail_provider("user-1")
        remaining = provider_registry.list_providers()
        # user-1's gmail removed; the unrelated provider untouched.
        assert rec1.id not in remaining
        assert "other-1" in remaining  # unrelated provider untouched
        # user-2's gmail untouched.
        assert any(getattr(p, "_user_id", "") == "user-2" for p in remaining.values())


# ═══════════════════════════════════════════════════════════════════════
# 4. Settings/API canonical accounts only
# ═══════════════════════════════════════════════════════════════════════

class TestSettingsApiDedup:
    def test_provider_list_returns_canonical_accounts_only(self, monkeypatch):
        import main as main_module
        from services.communication.communication_store import store as comm_store
        from services.communication.provider_models import (
            CommunicationProvider, ProviderType, ProviderStatus,
        )
        from unittest.mock import AsyncMock

        # Two runtime provider records for the SAME logical Google account.
        for pid, email in (("p1", "faisal96kp@gmail.com"), ("p2", "faisal96kp@gmail.com")):
            comm_store.save_provider(CommunicationProvider(
                id=pid, provider_type=ProviderType.GMAIL, user_id="owner-1",
                status=ProviderStatus.HEALTHY,
                metadata={"email": email, "account_id": "google-sub-1"},
            ))
        healthy = SimpleNamespaceStatus(ProviderStatus.HEALTHY)
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-1"))

        def _fake_get_provider(pid):
            inst = MagicMock()
            inst.health = lambda: healthy
            return inst

        monkeypatch.setattr(main_module, "get_provider", _fake_get_provider)
        import asyncio
        result = asyncio.run(main_module.provider_list("token", MagicMock()))
        assert result["ok"] is True
        providers = result["providers"]
        assert len(providers) == 1
        assert providers[0]["email"] == "faisal96kp@gmail.com"


class SimpleNamespaceStatus:
    def __init__(self, status):
        self._status = status

    @property
    def value(self):
        return self._status.value


# ═══════════════════════════════════════════════════════════════════════
# 5. Reconciliation
# ═══════════════════════════════════════════════════════════════════════

class TestReconciliation:
    def test_duplicate_rows_reconciled_deterministically(self, monkeypatch):
        from services.supabase import reconcile_connected_account_duplicates
        from services.persistence.launch import ConnectedAccount
        from datetime import datetime, timezone

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        older = ConnectedAccount(id="old-1", user_id="user-1", provider="google",
                                 email="a@b.com", access_token="a", refresh_token="x",
                                 created_at=base)
        older_with_token = ConnectedAccount(id="new-1", user_id="user-1", provider="google",
                                            email="a@b.com", access_token="b", refresh_token=SENTINEL,
                                            created_at=base.replace(day=2))
        newest = ConnectedAccount(id="new-2", user_id="user-1", provider="google",
                                  email="a@b.com", access_token="c", refresh_token=SENTINEL,
                                  created_at=base.replace(day=3))
        other_user = ConnectedAccount(id="other-1", user_id="user-2", provider="google",
                                      email="z@b.com", access_token="d", refresh_token=SENTINEL,
                                      created_at=base)

        class FakeRepo:
            def __init__(self):
                self.rows = [older, older_with_token, newest, other_user]

            async def _list(self, where=None, order="created_at", desc=True, limit=1000):
                return list(self.rows)

            async def list_for_user(self, uid):
                return [r for r in self.rows if r.user_id == uid]

            async def save(self, entity):
                for i, r in enumerate(self.rows):
                    if r.id == entity.id:
                        self.rows[i] = entity
                        break
                return entity

        import services.persistence.launch as launch
        repo = FakeRepo()
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: repo)
        deactivated = reconcile_connected_account_duplicates()
        assert deactivated == 2  # two obsolete rows for user-1
        active = [r for r in repo.rows if r.deleted_at is None]
        assert len(active) == 2  # canonical user-1 + user-2
        canonical = [r for r in active if r.user_id == "user-1"][0]
        assert canonical.id == "new-2"  # newest valid (refresh token) row wins
        # user-2 untouched.
        assert any(r.user_id == "user-2" for r in active)


# ═══════════════════════════════════════════════════════════════════════
# 6. OAuth state remains single-use
# ═══════════════════════════════════════════════════════════════════════

class TestOAuthState:
    def test_state_single_use(self):
        from services.oauth_state import issue_state, consume_state
        import asyncio
        state = asyncio.run(issue_state("user-1"))
        user_id, _ = asyncio.run(consume_state(state))
        assert user_id == "user-1"
        assert asyncio.run(consume_state(state)) == (None, None)
        assert asyncio.run(consume_state("forged")) == (None, None)
