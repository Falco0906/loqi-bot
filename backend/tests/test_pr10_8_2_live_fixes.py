"""PR10.8.2 live-fix regression — duplicate Gmail accounts + session-token exposure.

Backend contract for the Settings Connected Accounts UI:
- exactly ONE active Gmail account per (user, provider) reaches the API
- reconnect replaces (never stacks) the store provider record
- auth_failed status is surfaced accurately by the API
- Settings API/UI never expose the raw session token
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

SENTINEL = "PR1082LIVE_SENTINEL_SECRET"


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
    yield


def _provider_record(pid, email, account_id="", status="healthy", user_id="owner-1"):
    from services.communication.provider_models import (
        CommunicationProvider, ProviderType, ProviderStatus,
    )
    return CommunicationProvider(
        id=pid,
        provider_type=ProviderType.GMAIL,
        user_id=user_id,
        status=ProviderStatus(status),
        metadata={"email": email, "account_id": account_id},
    )


def _fake_instance(status_value="healthy"):
    inst = MagicMock()
    inst.health = lambda: _Status(status_value)
    return inst


class _Status:
    def __init__(self, value):
        self.value = value


# ═══════════════════════════════════════════════════════════════════════
# 1. Store enforces one logical account per (user, provider type)
# ═══════════════════════════════════════════════════════════════════════

class TestStoreLogicalAccount:
    def test_reconnect_replaces_store_record(self):
        from services.communication.communication_store import store
        from services.communication.gmail_provider import GmailProvider

        old = GmailProvider()
        old_record = old.connect(auth_token="old", user_id="owner-1", email="faisal96kp@gmail.com",
                                 refresh_token=SENTINEL)
        assert len(store.get_user_providers("owner-1")) == 1

        new = GmailProvider()
        new_record = new.connect(auth_token="new", user_id="owner-1", email="faisal96kp@gmail.com",
                                 account_id="sub-123", refresh_token=SENTINEL)
        providers = store.get_user_providers("owner-1")
        # The old record is REPLACED, not stacked.
        assert len(providers) == 1
        assert providers[0].id == new_record.id
        assert old_record.id not in store._providers

    def test_distinct_users_stay_distinct(self):
        from services.communication.communication_store import store
        from services.communication.gmail_provider import GmailProvider

        GmailProvider().connect(auth_token="t", user_id="user-a", email="a@x.com",
                                refresh_token=SENTINEL)
        GmailProvider().connect(auth_token="t", user_id="user-b", email="a@x.com",
                                refresh_token=SENTINEL)
        assert len(store.get_user_providers("user-a")) == 1
        assert len(store.get_user_providers("user-b")) == 1
        assert len(store.list_providers()) == 2

    def test_remove_existing_gmail_provider_cleans_store(self):
        import main as main_module
        from services.communication.communication_store import store
        from services.communication.gmail_provider import GmailProvider
        from services.communication import provider_registry

        provider = GmailProvider()
        record = provider.connect(auth_token="old", user_id="owner-1", email="a@b.com",
                                  refresh_token=SENTINEL)
        provider_registry.register_instance(record.id, provider)
        assert len(store.get_user_providers("owner-1")) == 1

        main_module._remove_existing_gmail_provider("owner-1")
        # The communication store is cleaned too — no stale entry remains.
        assert len(store.get_user_providers("owner-1")) == 0
        assert record.id not in store._providers


# ═══════════════════════════════════════════════════════════════════════
# 2. Settings API returns exactly one canonical Gmail account
# ═══════════════════════════════════════════════════════════════════════

class TestSettingsApiCanonical:
    def test_provider_list_one_canonical_even_with_stale_records(self, monkeypatch):
        """Belt-and-suspenders: even if stale records exist in the store, the
        API collapses them to one logical Gmail account keyed on email."""
        import main as main_module
        from services.communication.communication_store import store

        store._providers["p-old"] = _provider_record("p-old", "faisal96kp@gmail.com", account_id="")
        store._providers["p-new"] = _provider_record("p-new", "faisal96kp@gmail.com", account_id="sub-1")
        store._user_providers["owner-1"] = ["p-old", "p-new"]

        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-1"))

        def _fake_get(pid):
            return _fake_instance("healthy")

        monkeypatch.setattr(main_module, "get_provider", _fake_get)
        result = asyncio.run(main_module.provider_list("token", MagicMock()))
        assert result["ok"] is True
        assert len(result["providers"]) == 1
        assert result["providers"][0]["email"] == "faisal96kp@gmail.com"

    def test_provider_list_surfaces_auth_failed(self, monkeypatch):
        import main as main_module
        from services.communication.communication_store import store

        store._providers["p-auth"] = _provider_record("p-auth", "a@b.com", account_id="s1",
                                                      status="auth_failed")
        store._user_providers["owner-1"] = ["p-auth"]
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-1"))

        def _fake_get(pid):
            return _fake_instance("auth_failed")

        monkeypatch.setattr(main_module, "get_provider", _fake_get)
        result = asyncio.run(main_module.provider_list("token", MagicMock()))
        assert result["providers"][0]["status"] == "auth_failed"

    def test_settings_api_response_has_no_session_token(self, monkeypatch):
        import main as main_module
        from services.communication.communication_store import store
        store._providers["p1"] = _provider_record("p1", "a@b.com", account_id="s1")
        store._user_providers["owner-1"] = ["p1"]
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-1"))
        monkeypatch.setattr(main_module, "get_provider", lambda pid: _fake_instance("healthy"))
        result = asyncio.run(main_module.provider_list("token", MagicMock()))
        assert "session_token" not in result
        assert "session_token" not in result["providers"][0]

    def test_settings_page_does_not_render_session_token(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend",
                            "app", "(dashboard)", "settings", "page.tsx")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Session Token" not in content


# ═══════════════════════════════════════════════════════════════════════
# 3. Reconnect / status lifecycle through the API-visible store
# ═══════════════════════════════════════════════════════════════════════

class TestReconnectLifecycle:
    def test_reauth_failed_reconnect_restores_active_and_one_record(self):
        """auth_failed -> reconnect -> active, still exactly one store record."""
        from services.communication.communication_store import store
        from services.communication.gmail_provider import GmailProvider

        provider = GmailProvider()
        record = provider.connect(auth_token="t", user_id="owner-1", email="a@b.com",
                                  refresh_token=SENTINEL)
        provider.mark_reauth_required()
        assert len(store.get_user_providers("owner-1")) == 1
        assert store.get_provider(record.id).status.value == "auth_failed"

        # Reconnect replaces the record and restores healthy status.
        fresh = GmailProvider()
        fresh_record = fresh.connect(auth_token="new", user_id="owner-1", email="a@b.com",
                                     account_id="s1", refresh_token="new-refresh")
        providers = store.get_user_providers("owner-1")
        assert len(providers) == 1
        assert providers[0].id == fresh_record.id
        assert store.get_provider(fresh_record.id).status.value == "healthy"


# ═══════════════════════════════════════════════════════════════════════
# 4. Disconnect fully removes the logical provider from every store/registry
# ═══════════════════════════════════════════════════════════════════════

class TestDisconnectRemovesEverywhere:
    def test_disconnect_removes_provider_from_all_stores(self):
        from services.communication import provider_registry
        from services.communication.communication_store import store as comm_store
        from services.outbound import outbound_registry as or_reg
        from services.communication.gmail_provider import GmailProvider

        provider = GmailProvider()
        record = provider.connect(auth_token="t", user_id="owner-1", email="a@b.com",
                                  refresh_token=SENTINEL)
        provider_registry.register_instance(record.id, provider)
        or_reg.register_instance(record.id, object())
        assert record.id in comm_store._providers
        assert record.id in provider_registry.list_providers()
        assert record.id in or_reg.list_providers()

        ok = provider_registry.disconnect_provider(record.id)
        assert ok is True
        assert record.id not in comm_store._providers
        assert record.id not in comm_store._user_providers.get("owner-1", [])
        assert record.id not in provider_registry.list_providers()
        assert record.id not in or_reg.list_providers()
        assert len(comm_store.get_user_providers("owner-1")) == 0


# ═══════════════════════════════════════════════════════════════════════
# 5. auth_failed status survives startup restore and is surfaced by the API
# ═══════════════════════════════════════════════════════════════════════

class TestStartupRestoreSurfacesStatus:
    def test_restore_auth_failed_yields_one_auth_failed_provider(self, monkeypatch):
        """Simulate the startup restore of an auth_failed account (as observed
        live: 'Provider restoration complete: 0 restored, 3 reauth-required')."""
        import main as main_module
        from services.communication.communication_store import store
        from services.communication.gmail_provider import GmailProvider

        row = {
            "id": "7de769b4-0000-0000-0000-000000000000",
            "google_provider_id": "google-faisal96kp@gmail.com",
            "google_refresh_token": SENTINEL,
            "google_access_token": SENTINEL,
            "email": "faisal96kp@gmail.com",
            "account_id": "faisal96kp@gmail.com",
            "google_client_id": "cid",
            "google_client_secret": "sec",
            "token_expiry": "",
            "status": "auth_failed",
        }
        monkeypatch.setattr("services.supabase.load_all_provider_credentials", lambda: [row])
        monkeypatch.setattr("services.supabase.reconcile_connected_account_duplicates", lambda *a, **k: 0)
        main_module._restore_providers_on_startup()

        providers = store.get_user_providers("7de769b4-0000-0000-0000-000000000000")
        assert len(providers) == 1
        assert providers[0].status.value == "auth_failed"
        # The API surfaces auth_failed (never a stale healthy).
        monkeypatch.setattr(main_module, "_workspace_owner",
                            AsyncMock(return_value="7de769b4-0000-0000-0000-000000000000"))
        monkeypatch.setattr(main_module, "get_provider",
                            lambda pid: _fake_instance("auth_failed"))
        result = asyncio.run(main_module.provider_list("tok", MagicMock()))
        assert len(result["providers"]) == 1
        assert result["providers"][0]["status"] == "auth_failed"


# ═══════════════════════════════════════════════════════════════════════
# 6. Backfill diagnostics removed (no TMP-DIAG, no traceback spam)
# ═══════════════════════════════════════════════════════════════════════

class TestBackfillDiagnosticsRemoved:
    def test_no_tmp_diag_in_backfill_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "services",
                            "persistence", "launch", "backfill.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "TMP-DIAG" not in content
        assert "traceback.format_exc" not in content
        assert "marker-filtered listing failed" not in content

    def test_no_tmp_diag_in_main_lifespan(self):
        path = os.path.join(os.path.dirname(__file__), "..", "main.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "backfill TMP-DIAG" not in content

    def test_pending_sessions_marker_failure_falls_back_cleanly(self):
        from services.persistence.launch import backfill

        class _Data:
            def __init__(self, rows):
                self.data = rows

        class _SeqClient:
            """table()->select() first call raises (marker filter), second succeeds."""

            def __init__(self, rows):
                self._rows = rows
                self._n = 0

            def table(self, name):
                return _SeqTable(self, name)

        class _SeqTable:
            def __init__(self, client, name):
                self._client = client
                self._name = name

            def select(self, *a, **k):
                self._client._n += 1
                if self._client._n == 1:
                    raise OSError(11, "Resource temporarily unavailable")
                return _SeqBuilder(self._client._rows)

        class _SeqBuilder:
            def __init__(self, rows):
                self._rows = rows

            def eq(self, *_a, **_k):
                return self

            def is_(self, *_a, **_k):
                return self

            def execute(self):
                return _Data(self._rows)

        pending = backfill._pending_sessions(_SeqClient([{"id": "s1", "user_id": "u1"}]))
        assert pending == [("s1", "u1")]


# ═══════════════════════════════════════════════════════════════════════
# 7. Forced-duplicate prevention (the ACTUAL live root cause)
# ═══════════════════════════════════════════════════════════════════════

class TestForcedDuplicatePrevention:
    def test_connect_twice_yields_exactly_one_provider_everywhere(self):
        """Reconnect twice for the same user → ONE provider in the store,
        ONE in provider_registry, ONE outbound — the exact live scenario."""
        import main as main_module
        from services.communication.communication_store import store
        from services.communication import provider_registry
        from services.outbound import outbound_registry as or_reg
        from services.communication.gmail_provider import GmailProvider

        for i in range(2):
            with main_module._GMAIL_PROVIDER_CONNECT_LOCK:
                main_module._remove_existing_gmail_provider("owner-1")
                p = GmailProvider()
                rec = p.connect(auth_token=f"t{i}", user_id="owner-1",
                                email="faisal96kp@gmail.com", refresh_token=f"r{i}")
                provider_registry.register_instance(rec.id, p)

        assert len(store.get_user_providers("owner-1")) == 1
        assert len([p for p in provider_registry.list_providers().values()
                    if getattr(p, "_user_id", "") == "owner-1"]) == 1
        # Provider registry holds exactly one Gmail instance for the user.
        gmail_instances = [
            pid for pid, inst in provider_registry.list_providers().items()
            if getattr(inst, "_user_id", "") == "owner-1"
            and getattr(inst, "provider_type", None).value == "gmail"
        ]
        assert len(gmail_instances) == 1
        # Outbound registry synchronized: at most one entry (may be none).
        or_gmail = [pid for pid in or_reg.list_providers().keys()]
        assert len(or_gmail) <= 1

    def test_concurrent_connects_race_yields_one(self):
        """Two threads connect the same user concurrently — the store lock +
        the connect lock converge on ONE provider."""
        import threading
        import main as main_module
        from services.communication.communication_store import store
        from services.communication import provider_registry
        from services.communication.gmail_provider import GmailProvider

        results = []

        def worker(n):
            try:
                with main_module._GMAIL_PROVIDER_CONNECT_LOCK:
                    main_module._remove_existing_gmail_provider("racer")
                    p = GmailProvider()
                    rec = p.connect(auth_token=f"t{n}", user_id="racer",
                                    email="faisal96kp@gmail.com", refresh_token=f"r{n}")
                    provider_registry.register_instance(rec.id, p)
                results.append("ok")
            except Exception as e:  # noqa: BLE001
                results.append(f"err:{type(e).__name__}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == ["ok"] * 6
        assert len(store.get_user_providers("racer")) == 1
        gmail_instances = [
            pid for pid, inst in provider_registry.list_providers().items()
            if getattr(inst, "_user_id", "") == "racer"
            and getattr(inst, "provider_type", None).value == "gmail"
        ]
        assert len(gmail_instances) == 1

    def test_persisted_auth_failed_never_surfaced_as_healthy(self, monkeypatch):
        """A valid runtime access token must not mask a revoked refresh token."""
        import main as main_module
        from services.communication.communication_store import store

        store._providers["p-h"] = _provider_record("p-h", "faisal96kp@gmail.com",
                                                   account_id="s1", status="healthy")
        store._user_providers["owner-1"] = ["p-h"]
        monkeypatch.setattr(main_module, "_workspace_owner", AsyncMock(return_value="owner-1"))
        monkeypatch.setattr(main_module, "get_provider", lambda pid: _fake_instance("healthy"))
        monkeypatch.setattr("services.supabase.is_connected_account_reauth_required",
                            lambda *a, **k: True)
        result = asyncio.run(main_module.provider_list("tok", MagicMock()))
        assert result["providers"][0]["status"] == "auth_failed"

    def test_reconnect_after_auth_failed_yields_one_active(self, monkeypatch):
        """auth_failed persisted -> successful reconnect -> one active provider."""
        import main as main_module
        from services.communication.communication_store import store
        from services.communication import provider_registry
        from services.communication.gmail_provider import GmailProvider

        p = GmailProvider()
        rec = p.connect(auth_token="old", user_id="owner-1", email="a@b.com",
                        refresh_token=SENTINEL)
        provider_registry.register_instance(rec.id, p)
        p.mark_reauth_required()

        with main_module._GMAIL_PROVIDER_CONNECT_LOCK:
            main_module._remove_existing_gmail_provider("owner-1")
            fresh = GmailProvider()
            fresh_rec = fresh.connect(auth_token="new", user_id="owner-1", email="a@b.com",
                                      refresh_token="new-refresh")
            provider_registry.register_instance(fresh_rec.id, fresh)

        providers = store.get_user_providers("owner-1")
        assert len(providers) == 1
        assert providers[0].id == fresh_rec.id
        assert providers[0].status.value == "healthy"
        assert len([x for x in provider_registry.list_providers().values()
                    if getattr(x, "_user_id", "") == "owner-1"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# 8. Startup runtime reconciliation (PR10.8.2.2)
# ═══════════════════════════════════════════════════════════════════════

class TestStartupRuntimeReconciliation:
    def test_reconcile_collapses_duplicate_runtime_providers(self):
        """If a process accumulated two store records for the same user, the
        startup reconciliation keeps the newest healthy one and removes the
        rest from the store + provider registry + outbound registry."""
        import main as main_module
        from services.communication.communication_store import store
        from services.communication import provider_registry
        from services.outbound import outbound_registry as or_reg

        # Inject a genuine duplicate runtime state (pre-fix stacking): two
        # store records + two registry instances for the same user/type.
        store._providers["p-old"] = _provider_record("p-old", "faisal96kp@gmail.com",
                                                     account_id="s1", status="healthy")
        store._providers["p-new"] = _provider_record("p-new", "faisal96kp@gmail.com",
                                                     account_id="s1", status="healthy")
        store._user_providers["owner-1"] = ["p-old", "p-new"]
        provider_registry.register_instance("p-old", _fake_instance("healthy"))
        provider_registry.register_instance("p-new", _fake_instance("healthy"))
        or_reg.register_instance("p-old", object())
        or_reg.register_instance("p-new", object())
        assert len(store.get_user_providers("owner-1")) == 2

        main_module._reconcile_runtime_providers()

        providers = store.get_user_providers("owner-1")
        assert len(providers) == 1
        gmail_instances = [
            pid for pid in provider_registry.list_providers().keys()
        ]
        assert len(gmail_instances) == 1
        assert len(or_reg.list_providers()) == 1

    def test_reconcile_prefers_healthy_over_auth_failed(self):
        import main as main_module
        from services.communication.communication_store import store

        store._providers["p-auth"] = _provider_record("p-auth", "a@b.com", account_id="s1",
                                                      status="auth_failed")
        store._providers["p-healthy"] = _provider_record("p-healthy", "a@b.com", account_id="s1",
                                                         status="healthy")
        store._user_providers["owner-1"] = ["p-auth", "p-healthy"]

        main_module._reconcile_runtime_providers()
        remaining = store.get_user_providers("owner-1")
        assert len(remaining) == 1
        assert remaining[0].id == "p-healthy"
