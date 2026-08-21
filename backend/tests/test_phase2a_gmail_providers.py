"""PR-2A — Gmail provider store correctness regression tests.

Reproduces the exact production failure:
    OAuth callback says "✓ Gmail Connected" → popup closes →
    /providers returns nothing → UI shows "No Gmail accounts connected".

Root cause: /providers read the IN-MEMORY communication store while the
durable record lived in ``connected_accounts``. These tests pin the new
contract:

  A. OAuth persistence → /providers returns the provider (durable path).
  B. /providers survives a full in-memory registry wipe (process boundary).
  C. Tenant isolation: user B never sees user A's provider.
  D. Reconnect replaces — exactly one active Gmail record per user.
  E. Failed persistence → callback reports FAILURE and rolls back runtime.
  F. Concurrent same-user connects serialize (no duplicates).
  G. Different users connect concurrently without blocking each other.
  H. Callback postMessage payload reflects the true persistence outcome.

Supabase is faked at the ``services.supabase`` seam; everything above that
seam (orchestration, locking, rollback, verification, /providers read path)
is the real production code.
"""
import asyncio
import json
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main as main_module
import services.supabase as supabase_module

USER_A = "2a-user-aaaaaaaa"
USER_B = "2a-user-bbbbbbbb"


class FakeDurableStore:
    """In-memory stand-in for connected_accounts with upsert semantics.

    NOTE: ``sync_connected_account`` is deliberately a PLAIN function — the
    production one is synchronous (invoked via asyncio.to_thread), and these
    tests must exercise the same calling convention.
    """

    def __init__(self):
        self.rows: dict[str, dict] = {}  # user_id -> row
        self.fail_persist = False
        self.gates: dict[str, threading.Event] = {}  # user_id -> gate
        self._lock = threading.Lock()
        self.concurrent = 0
        self.max_concurrent = 0

    def reset(self) -> None:
        with self._lock:
            self.rows.clear()
            self.fail_persist = False
            self.gates.clear()
            self.concurrent = 0
            self.max_concurrent = 0

    def sync_connected_account(self, user_id, *, provider="google", email="",
                               account_id="", communication_provider_id="",
                               access_token="", refresh_token="",
                               token_expiry=None, **_ignored) -> bool:
        if self.fail_persist:
            return False
        if provider != "google":
            return True
        gate = self.gates.get(user_id)
        if gate is not None:
            gate.wait()
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            time.sleep(0.01)  # widen the window to expose overlap bugs
            with self._lock:
                row = self.rows.get(user_id)
                if row is None:
                    row = {
                        "row_id": f"row-{len(self.rows) + 1}",
                        "email": "",
                        "account_id": "",
                        "status": "active",
                        "communication_provider_id": "",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "last_synced_at": "",
                    }
                    self.rows[user_id] = row
                if email:
                    row["email"] = email
                if account_id:
                    row["account_id"] = account_id
                if communication_provider_id:
                    row["communication_provider_id"] = communication_provider_id
                return True
        finally:
            with self._lock:
                self.concurrent -= 1

    def get_durable_providers_for_user(self, user_id, provider="google") -> list[dict]:
        if provider != "google":
            return []
        with self._lock:
            row = self.rows.get(user_id)
            if row is None:
                return []
            return [dict(row)]

    # Test-side view of raw rows
    def raw_row(self, user_id):
        with self._lock:
            row = self.rows.get(user_id)
            return dict(row) if row else None


@pytest.fixture()
def durable(monkeypatch):
    """Fresh fake store wired into the services.supabase seam each test."""
    fake = FakeDurableStore()
    monkeypatch.setattr(supabase_module, "sync_connected_account", fake.sync_connected_account)
    monkeypatch.setattr(
        supabase_module, "get_durable_providers_for_user",
        fake.get_durable_providers_for_user,
    )
    yield fake


@pytest.fixture()
def clean_runtime(monkeypatch):
    """Reset every in-memory provider registry around each test.

    Also stubs GmailProvider.health so tests never make live Google/Supabase
    calls from status probes — the health *endpoint* is out of scope here.
    """
    from services.communication.provider_models import ProviderStatus
    monkeypatch.setattr(
        main_module.GmailProvider, "health",
        lambda self: ProviderStatus.HEALTHY,
    )
    yield
    communication_store = main_module.communication_store
    for pid in list(communication_store._providers.keys()):
        try:
            main_module.remove_instance(pid)
        except Exception:
            pass
    communication_store._providers.clear()
    communication_store._user_providers.clear()
    main_module._gmail_connect_locks.clear()


@pytest.fixture()
def api(monkeypatch):
    """Test client bound to ONLY the routes under test (no middleware)."""
    app = FastAPI()

    @app.get("/api/auth/gmail/callback")
    async def callback(code: str = "", state: str = "", error: str = ""):
        return await main_module.gmail_auth_callback(code=code, state=state, error=error)

    @app.get("/api/web/session/_/providers")
    async def providers(request: object = None):
        return await main_module.provider_list(session_token="_", request=request)

    client = TestClient(app, raise_server_exceptions=False)
    return client


def _set_owner(monkeypatch, user_id: str) -> None:
    async def fake_owner(request=None, session_token=None):
        return user_id
    monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)


def _wipe_memory_registries():
    cs = main_module.communication_store
    for pid in list(cs._providers.keys()):
        try:
            main_module.remove_instance(pid)
        except Exception:
            pass
    cs._providers.clear()
    cs._user_providers.clear()


async def _connect(user_id: str, email: str = "owner@gmail.com") -> object:
    return await main_module._perform_gmail_oauth_persistence(
        user_id=user_id,
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        email=email,
        account_id=email.split("@")[0],
    )


# ────────────────────────────────────────────────────────────────
# TEST A — OAuth persistence → /providers returns the provider
# ────────────────────────────────────────────────────────────────

def test_a_oauth_persistence_visible_via_providers(durable, api, monkeypatch, clean_runtime):
    _set_owner(monkeypatch, USER_A)
    monkeypatch.setattr(main_module, "_resolve_oauth_state_user", _fake_resolve(USER_A))
    monkeypatch.setattr(
        "services.google_auth.exchange_code_for_tokens",
        lambda code: {
            "access_token": "at", "refresh_token": "rt",
            "email": "owner@gmail.com", "account_id": "owner",
        },
    )

    resp = api.get("/api/auth/gmail/callback", params={"code": "c", "state": "s"})
    assert resp.status_code == 200
    assert "✓ Gmail Connected" in resp.text
    payload = json.loads(_extract_payload(resp.text))
    assert payload["ok"] is True

    # The acceptance sequence: ONE /providers call right after success.
    listed = api.get("/api/web/session/_/providers")
    body = listed.json()
    assert listed.status_code == 200 and body["ok"] is True
    gmail = [p for p in body["providers"] if p.get("email") == "owner@gmail.com"]
    assert len(gmail) == 1


# ────────────────────────────────────────────────────────────────
# TEST H — postMessage payload contract consumed by the frontend
# ────────────────────────────────────────────────────────────────
# The Settings handler (frontend/app/(dashboard)/settings/page.tsx) branches
# on exactly this payload: ok=true → ONE fetchProviders(); ok=false → error,
# no refresh. These assertions pin the wire format the UI depends on.

def test_h_success_payload_contract(durable, api, monkeypatch, clean_runtime):
    _set_owner(monkeypatch, USER_A)
    monkeypatch.setattr(main_module, "_resolve_oauth_state_user", _fake_resolve(USER_A))
    monkeypatch.setattr(
        "services.google_auth.exchange_code_for_tokens",
        lambda code: {"access_token": "at", "refresh_token": "rt",
                      "email": "owner@gmail.com", "account_id": "owner"},
    )
    resp = api.get("/api/auth/gmail/callback", params={"code": "c", "state": "s"})
    payload = json.loads(_extract_payload(resp.text))
    assert payload["ok"] is True
    assert payload["provider_id"]
    assert payload["email"] == "owner@gmail.com"
    assert payload["error"] == ""


def test_h_failure_payload_contract(durable, api, monkeypatch, clean_runtime):
    _set_owner(monkeypatch, USER_A)
    monkeypatch.setattr(main_module, "_resolve_oauth_state_user", _fake_resolve(USER_A))
    durable.fail_persist = True
    monkeypatch.setattr(
        "services.google_auth.exchange_code_for_tokens",
        lambda code: {"access_token": "at", "refresh_token": "rt",
                      "email": "owner@gmail.com", "account_id": "owner"},
    )
    resp = api.get("/api/auth/gmail/callback", params={"code": "c", "state": "s"})
    payload = json.loads(_extract_payload(resp.text))
    assert payload["ok"] is False
    assert payload["error"], "failure must carry a safe error message"
    # Never leak credentials through the postMessage channel.
    assert "at" != payload["error"] and "test-refresh-token" not in payload["error"]


def _fake_resolve(user_id):
    async def resolve(state: str) -> str:
        return user_id
    return resolve


def _extract_payload(html: str) -> str:
    marker = "payload: "
    idx = html.index(marker)
    depth = 0
    start = idx + len(marker)
    end = start
    for i, ch in enumerate(html[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return html[start:end]


# ────────────────────────────────────────────────────────────────
# TEST B — /providers independent of in-memory registries
# ────────────────────────────────────────────────────────────────

def test_b_providers_survive_registry_wipe(durable, api, monkeypatch, clean_runtime):
    _set_owner(monkeypatch, USER_A)
    asyncio.run(_connect(USER_A))
    assert durable.raw_row(USER_A) is not None

    # Simulate a process boundary: wipe EVERY in-memory provider registry.
    _wipe_memory_registries()
    assert main_module.communication_store.get_user_providers(USER_A) == []

    listed = api.get("/api/web/session/_/providers")
    body = listed.json()
    assert listed.status_code == 200 and body["ok"] is True
    assert [p for p in body["providers"] if p.get("email") == "owner@gmail.com"], (
        "/providers must be served from the durable store, not memory"
    )


# ────────────────────────────────────────────────────────────────
# TEST C — tenant isolation
# ────────────────────────────────────────────────────────────────

def test_c_tenant_isolation(durable, api, monkeypatch, clean_runtime):
    asyncio.run(_connect(USER_A))

    _set_owner(monkeypatch, USER_B)
    listed = api.get("/api/web/session/_/providers")
    body = listed.json()
    assert body["ok"] is True
    assert body["providers"] == [], "User B must never see User A's provider"

    # And A still sees their own.
    _set_owner(monkeypatch, USER_A)
    body = api.get("/api/web/session/_/providers").json()
    assert len([p for p in body["providers"] if p.get("email")]) == 1


# ────────────────────────────────────────────────────────────────
# TEST D — reconnect replaces, never duplicates
# ────────────────────────────────────────────────────────────────

def test_d_reconnect_replaces_not_duplicates(durable, monkeypatch, clean_runtime):
    _set_owner(monkeypatch, USER_A)
    asyncio.run(_connect(USER_A, email="first@gmail.com"))
    first = durable.raw_row(USER_A)
    asyncio.run(_connect(USER_A, email="second@gmail.com"))

    rows = [r for r in durable.rows.values()]
    assert len(rows) == 1, "reconnect must update in place"
    assert rows[0]["email"] == "second@gmail.com"
    assert first["row_id"] == rows[0]["row_id"]

    # Exactly one active runtime+memory provider for the user.
    comm = main_module.communication_store.get_user_providers(USER_A)
    assert len(comm) == 1


# ────────────────────────────────────────────────────────────────
# TEST E — failed persistence reports failure + rolls back runtime
# ────────────────────────────────────────────────────────────────

def test_e_failed_persistence_reports_failure_and_rolls_back(
    durable, api, monkeypatch, clean_runtime,
):
    _set_owner(monkeypatch, USER_A)
    monkeypatch.setattr(main_module, "_resolve_oauth_state_user", _fake_resolve(USER_A))
    monkeypatch.setattr(
        "services.google_auth.exchange_code_for_tokens",
        lambda code: {"access_token": "at", "refresh_token": "rt",
                      "email": "owner@gmail.com", "account_id": "owner"},
    )
    durable.fail_persist = True

    resp = api.get("/api/auth/gmail/callback", params={"code": "c", "state": "s"})
    payload = json.loads(_extract_payload(resp.text))
    assert payload["ok"] is False, "callback must not claim success without durability"
    assert "✗" in resp.text

    # Runtime rollback: no half-connected instance left behind.
    assert main_module.communication_store.get_user_providers(USER_A) == []

    # And /providers reflects reality: nothing connected.
    listed = api.get("/api/web/session/_/providers")
    assert listed.json()["providers"] == []


# ────────────────────────────────────────────────────────────────
# TEST F — concurrent same-user connects serialize
# ────────────────────────────────────────────────────────────────

def test_f_concurrent_same_user_connects_serialize(durable, clean_runtime):
    async def run():
        results = await asyncio.gather(
            _connect(USER_A, email="one@gmail.com"),
            _connect(USER_A, email="two@gmail.com"),
        )
        return results

    results = asyncio.run(run())
    assert all(r is not None for r in results)

    assert len(durable.rows) == 1, "same user must map to one active record"
    assert durable.max_concurrent == 1, "same-user connects must be serialized"

    comm = main_module.communication_store.get_user_providers(USER_A)
    assert len(comm) == 1, "no duplicate runtime providers after concurrent reconnect"


# ────────────────────────────────────────────────────────────────
# TEST G — different users do not block each other
# ────────────────────────────────────────────────────────────────

def test_g_different_users_connect_independently(durable, clean_runtime):
    release_a = threading.Event()
    b_finished = {"done": False}

    async def connect_a():
        durable.gates[USER_A] = release_a  # block ONLY user A's worker thread
        await _connect(USER_A, email="a@gmail.com")

    async def connect_b():
        await _connect(USER_B, email="b@gmail.com")
        b_finished["done"] = True

    async def run():
        task_a = asyncio.create_task(connect_a())
        await asyncio.sleep(0.05)          # let A acquire its lock & block
        await connect_b()                  # B must complete despite A blocked
        assert b_finished["done"], "User B was blocked behind User A"
        assert durable.raw_row(USER_B) is not None
        release_a.set()                    # unblock A
        await task_a

    asyncio.run(run())
    assert durable.raw_row(USER_A) is not None
