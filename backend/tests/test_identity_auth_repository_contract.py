"""Regression: Supabase identity/auth repository methods must return domain
models, not raw PostgREST dicts.

Production bug: SupabaseOAuthSessionRepository.find_by_state returned a raw
dict, so services.oauth_state.consume_state raised
`AttributeError: 'dict' object has no attribute 'is_used'`, breaking the Gmail
OAuth connect callback. The same contract bug affected email-identity and
password-credential lookups (which would break email/password login).

These tests drive the REAL Supabase repositories against a fake PostgREST
client and assert the returned objects are model instances whose properties/
methods work, and that consume_state's validation still enforces single-use
and expiry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.persistence.repositories import (
    SupabaseEmailIdentityRepository,
    SupabaseOAuthSessionRepository,
    SupabasePasswordCredentialRepository,
)
from services.identity.models import (
    EmailIdentity,
    PasswordCredential,
)
from services.identity.models.oauth_session import OAuthSession
from services import oauth_state


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._eq: list[tuple[str, str]] = []
        self._limit = None
        self._op = "select"
        self._payload = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._eq.append((col, str(val)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, *_a, **_k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        rows = [dict(r) for r in self._db.tables.get(self._table, [])]
        for col, val in self._eq:
            rows = [r for r in rows if str(r.get(col, "")) == val]

        if self._op == "select":
            if self._limit:
                rows = rows[: self._limit]
            return _Row(rows)

        if self._op == "delete":
            ids = {r.get("id") for r in rows}
            self._db.tables[self._table] = [
                r for r in self._db.tables.get(self._table, []) if r.get("id") not in ids
            ]
            return _Row([])

        if self._op == "insert":
            stored = [dict(r) for r in self._db.tables.setdefault(self._table, [])]
            stored.append(self._payload)
            self._db.tables[self._table] = stored
            return _Row([self._payload])

        # update: replace the matching row in place
        updated = []
        for r in self._db.tables.get(self._table, []):
            if any(str(r.get(col, "")) == val for col, val in self._eq):
                merged = {**r, **self._payload}
                updated.append(merged)
            else:
                updated.append(r)
        self._db.tables[self._table] = updated
        return _Row(updated)


class FakeClient:
    def __init__(self, tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return _Query(self, name)


def _iso(dt):
    return dt.isoformat()


_FUTURE = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))
_PAST = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))


def _oauth_row(state="st", used=None, expires_at=_FUTURE):
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "state": state,
        "provider_type": "oauth_state",
        "code_verifier": "verifier",
        "nonce": "",
        "redirect_uri": "",
        "user_id": "user-1",
        "context": "",
        "expires_at": expires_at,
        "used_at": used,
        "created_at": _FUTURE,
    }


class TestOAuthSessionRepositoryContract:

    @pytest.mark.asyncio
    async def test_find_by_state_returns_model_not_dict(self):
        repo = SupabaseOAuthSessionRepository()
        repo._client = lambda: FakeClient({"oauth_sessions": [_oauth_row()]})

        result = await repo.find_by_state("st")
        assert isinstance(result, OAuthSession)
        assert not isinstance(result, dict)
        assert result.is_used is False
        assert result.is_expired is False
        result.mark_used()
        assert result.is_used is True

    @pytest.mark.asyncio
    async def test_consume_state_consumes_valid_unused(self, monkeypatch):
        repo = SupabaseOAuthSessionRepository()
        db = FakeClient({"oauth_sessions": [_oauth_row(state="st")]})
        repo._client = lambda: db
        monkeypatch.setattr(oauth_state, "_repo", lambda: repo)

        user_id, _context = await oauth_state.consume_state("st")
        assert user_id == "user-1"
        # The stored row is now marked used (single-use enforced).
        stored = db.tables["oauth_sessions"][0]
        assert stored.get("used_at") is not None

    @pytest.mark.asyncio
    async def test_consume_state_rejects_used_state(self, monkeypatch):
        repo = SupabaseOAuthSessionRepository()
        repo._client = lambda: FakeClient({"oauth_sessions": [_oauth_row(state="st", used=_iso(datetime.now(timezone.utc)))]})
        monkeypatch.setattr(oauth_state, "_repo", lambda: repo)

        user_id, _context = await oauth_state.consume_state("st")
        assert user_id is None

    @pytest.mark.asyncio
    async def test_consume_state_rejects_expired_state(self, monkeypatch):
        repo = SupabaseOAuthSessionRepository()
        db = FakeClient({"oauth_sessions": [_oauth_row(state="st", expires_at=_PAST)]})
        repo._client = lambda: db
        monkeypatch.setattr(oauth_state, "_repo", lambda: repo)

        user_id, _context = await oauth_state.consume_state("st")
        assert user_id is None
        # Expired state is rejected BEFORE consumption — used_at unchanged.
        assert db.tables["oauth_sessions"][0].get("used_at") is None

    @pytest.mark.asyncio
    async def test_find_by_state_missing_returns_none(self):
        repo = SupabaseOAuthSessionRepository()
        repo._client = lambda: FakeClient({"oauth_sessions": []})
        assert await repo.find_by_state("missing") is None


class TestEmailIdentityRepositoryContract:

    @pytest.mark.asyncio
    async def test_find_by_email_returns_model(self):
        repo = SupabaseEmailIdentityRepository()
        repo._client = lambda: FakeClient({"email_identities": [{
            "id": "00000000-0000-4000-8000-000000000002",
            "user_id": "user-1",
            "email": "a@example.com",
            "is_verified": True,
            "is_primary": True,
            "verified_at": _FUTURE,
            "created_at": _FUTURE,
        }]})

        result = await repo.find_by_email("a@example.com")
        assert isinstance(result, EmailIdentity)
        assert not isinstance(result, dict)
        assert result.is_verified is True
        assert result.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_find_by_user_id_returns_models(self):
        repo = SupabaseEmailIdentityRepository()
        repo._client = lambda: FakeClient({"email_identities": [{
            "id": "00000000-0000-4000-8000-000000000002",
            "user_id": "user-1",
            "email": "a@example.com",
            "is_verified": False,
            "is_primary": True,
            "verified_at": None,
            "created_at": _FUTURE,
        }]})

        results = await repo.find_by_user_id("user-1")
        assert results and isinstance(results[0], EmailIdentity)
        assert results[0].is_verified is False

    @pytest.mark.asyncio
    async def test_find_primary_by_user_id_returns_model(self):
        repo = SupabaseEmailIdentityRepository()
        repo._client = lambda: FakeClient({"email_identities": [{
            "id": "00000000-0000-4000-8000-000000000002",
            "user_id": "user-1",
            "email": "a@example.com",
            "is_verified": True,
            "is_primary": True,
            "verified_at": _FUTURE,
            "created_at": _FUTURE,
        }]})

        result = await repo.find_primary_by_user_id("user-1")
        assert isinstance(result, EmailIdentity)
        assert result.is_primary is True


class TestPasswordCredentialRepositoryContract:

    @pytest.mark.asyncio
    async def test_find_by_user_id_returns_model(self):
        repo = SupabasePasswordCredentialRepository()
        repo._client = lambda: FakeClient({"password_credentials": [{
            "id": "00000000-0000-4000-8000-000000000003",
            "user_id": "user-1",
            "password_hash": "hashed-value",
            "created_at": _FUTURE,
            "last_changed_at": _FUTURE,
        }]})

        result = await repo.find_by_user_id("user-1")
        assert isinstance(result, PasswordCredential)
        assert not isinstance(result, dict)
        assert str(result.password_hash) == "hashed-value"


class TestNoRawDictEscapes:

    @pytest.mark.asyncio
    async def test_none_of_the_five_methods_return_raw_dicts(self):
        oauth_repo = SupabaseOAuthSessionRepository()
        oauth_repo._client = lambda: FakeClient({"oauth_sessions": [_oauth_row()]})
        assert not isinstance(await oauth_repo.find_by_state("st"), dict)

        ei_repo = SupabaseEmailIdentityRepository()
        ei_repo._client = lambda: FakeClient({"email_identities": [{
            "id": "00000000-0000-4000-8000-000000000002", "user_id": "u",
            "email": "a@example.com", "is_verified": True, "is_primary": True,
            "verified_at": _FUTURE, "created_at": _FUTURE,
        }]})
        assert not isinstance(await ei_repo.find_by_email("a@example.com"), dict)
        assert not isinstance(await ei_repo.find_primary_by_user_id("u"), dict)
        results = await ei_repo.find_by_user_id("u")
        assert results and not isinstance(results[0], dict)

        pc_repo = SupabasePasswordCredentialRepository()
        pc_repo._client = lambda: FakeClient({"password_credentials": [{
            "id": "00000000-0000-4000-8000-000000000003", "user_id": "u",
            "password_hash": "h", "created_at": _FUTURE, "last_changed_at": _FUTURE,
        }]})
        assert not isinstance(await pc_repo.find_by_user_id("u"), dict)