"""Automatic abandoned-registration lifecycle cleanup tests.

Covers the periodic cleanup job (run_abandoned_cleanup), the shared predicate
with the automatic expiry gate (require_expired=True), and the lazy signup
reclaim path. All tests use an in-memory fake Supabase client — never the
production database, never writes to production.
"""

from __future__ import annotations

import pytest

from services.identity.registration_cleanup import (
    build_abandoned_plan,
    cleanup_abandoned_email,
    run_abandoned_cleanup,
)

_NOW = "2026-08-18T05:00:00+00:00"
_EXPIRED = "2026-08-18T00:00:00+00:00"   # before _NOW
_ACTIVE = "2099-01-01T00:00:00+00:00"


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._eq = None
        self._limit = None
        self._op = "select"

    def select(self, _sel):
        return self

    def eq(self, col, val):
        self._eq = (col, str(val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        rows = self._db.tables[self._table]
        if self._eq:
            col, val = self._eq
            rows = [r for r in rows if str(r.get(col, "")) == val]
        if self._op == "delete":
            ids = [str(r.get("id", "")) for r in rows]
            kept = [r for r in self._db.tables[self._table] if str(r.get("id", "")) not in ids]
            self._db.tables[self._table] = kept
            for i in ids:
                self._db.deleted.append((self._table, i))
            return type("R", (), {"data": []})()
        if self._limit:
            rows = rows[: self._limit]
        return type("R", (), {"data": rows})


class FakeSupabase:
    def __init__(self, tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.deleted: list[tuple[str, str]] = []

    def table(self, name):
        return _Query(self, name)


def _base_tables(**overrides):
    base = {
        "registration_sessions": [
            {"id": "RS-EXPIRED", "email": "expired@example.com", "status": "pending",
             "user_id": "", "expires_at": _EXPIRED},
            {"id": "RS-VERIFIED", "email": "verified@example.com", "status": "verified",
             "user_id": "", "expires_at": _EXPIRED},
            {"id": "RS-ACTIVE", "email": "active@example.com", "status": "pending",
             "user_id": "", "expires_at": _ACTIVE},
            {"id": "RS-DONE", "email": "done@example.com", "status": "completed",
             "user_id": "U-DONE", "expires_at": _EXPIRED},
        ],
        "verification_tokens": [
            {"id": "VT-1", "target": "expired@example.com", "purpose": "verify_email"},
            {"id": "VT-2", "target": "verified@example.com", "purpose": "verify_email"},
            {"id": "VT-3", "target": "active@example.com", "purpose": "verify_email"},
            {"id": "VT-4", "target": "done@example.com", "purpose": "verify_email"},
        ],
        "email_identities": [
            {"id": "EI-1", "email": "expired@example.com", "user_id": ""},
            {"id": "EI-2", "email": "verified@example.com", "user_id": ""},
            {"id": "EI-3", "email": "active@example.com", "user_id": ""},
            {"id": "EI-DONE", "email": "done@example.com", "user_id": "U-DONE"},
        ],
        "identity_users": [{"id": "U-DONE"}],
    }
    base.update(overrides)
    return base


class TestAutomaticPredicate:

    def test_expired_pending_cleanable(self):
        plan = build_abandoned_plan(
            target_email="expired@example.com", **_base_tables(), require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason == ""
        assert set(plan.delete["registration_sessions"]) == {"RS-EXPIRED"}
        assert set(plan.delete["verification_tokens"]) == {"VT-1"}
        assert set(plan.delete["email_identities"]) == {"EI-1"}

    def test_expired_verified_incomplete_cleanable(self):
        plan = build_abandoned_plan(
            target_email="verified@example.com", **_base_tables(), require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason == ""
        assert "RS-VERIFIED" in plan.delete["registration_sessions"]

    def test_active_non_expired_skipped(self):
        plan = build_abandoned_plan(
            target_email="active@example.com", **_base_tables(), require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason  # "active (non-expired)"
        assert plan.delete == {}

    def test_completed_skipped(self):
        plan = build_abandoned_plan(
            target_email="done@example.com", **_base_tables(), require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason
        assert plan.delete == {}

    def test_manual_mode_does_not_require_expiry(self):
        plan = build_abandoned_plan(
            target_email="active@example.com", **_base_tables(), require_expired=False, now=_NOW,
        )
        assert plan.refusal_reason == ""  # operator explicitly targeted

    def test_never_selects_protected_tables(self):
        plan = build_abandoned_plan(
            target_email="expired@example.com", **_base_tables(), require_expired=True, now=_NOW,
        )
        protected = {"identity_users", "password_credentials", "sessions", "refresh_tokens",
                     "organizations", "workspaces", "workspace_members", "connected_accounts",
                     "external_identities", "billing_customers"}
        assert not (protected & set(plan.delete))

    def test_linked_email_identity_ambiguous_skipped(self):
        tables = _base_tables(email_identities=[
            {"id": "EI-X", "email": "expired@example.com", "user_id": "U-GHOST"},
        ])
        plan = build_abandoned_plan(
            target_email="expired@example.com", **tables, require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason
        assert plan.delete == {}

    def test_orphan_user_reference_reported_not_deleted(self):
        tables = _base_tables(registration_sessions=[
            {"id": "RS-ORPHAN", "email": "orphan@example.com", "status": "verified",
             "user_id": "U-ORPHAN", "expires_at": _EXPIRED},
        ], email_identities=[
            {"id": "EI-1", "email": "orphan@example.com", "user_id": ""},
        ], identity_users=[{"id": "U-DONE"}])
        plan = build_abandoned_plan(
            target_email="orphan@example.com", **tables, require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason == ""
        assert "U-ORPHAN" in plan.orphan_identity_user_ids
        assert "U-ORPHAN" not in plan.delete


class TestPeriodicCleanup:

    def test_periodic_cleans_only_abandoned(self):
        db = FakeSupabase(_base_tables())
        report = run_abandoned_cleanup(dry_run=False, client=db)
        assert report["scanned"] >= 2
        assert report["cleaned_emails"] >= 2  # expired + verified
        assert report["failures"] == 0
        deleted_tables = {t for t, _ in db.deleted}
        assert deleted_tables == {"registration_sessions", "verification_tokens", "email_identities"}
        # done@example.com (completed) and active@example.com (non-expired) untouched.
        assert not any(t == "registration_sessions" and i == "RS-DONE" for t, i in db.deleted)
        assert not any(t == "registration_sessions" and i == "RS-ACTIVE" for t, i in db.deleted)
        assert "U-DONE" not in {i for _, i in db.deleted}

    def test_second_run_is_noop(self):
        db = FakeSupabase(_base_tables())
        run_abandoned_cleanup(dry_run=False, client=db)
        first = len(db.deleted)
        run_abandoned_cleanup(dry_run=False, client=db)
        assert len(db.deleted) == first  # nothing else to clean

    def test_dry_run_periodic_makes_no_writes(self):
        db = FakeSupabase(_base_tables())
        report = run_abandoned_cleanup(dry_run=True, client=db)
        assert db.deleted == []
        assert report["cleaned_emails"] >= 1
        assert "applied_updates" not in report

    def test_one_failing_row_does_not_abort(self):
        db = FakeSupabase(_base_tables())

        original = db.table
        def fail_on_verification_delete(table):
            q = original(table)
            orig_delete = q.delete
            def raising_delete():
                if table == "verification_tokens":
                    raise RuntimeError("boom")
                return orig_delete()
            q.delete = raising_delete
            return q
        db.table = fail_on_verification_delete

        report = run_abandoned_cleanup(dry_run=False, client=db)
        # Other tables still cleaned; failures counted.
        assert report["failures"] >= 1
        assert any(t == "registration_sessions" for t, _ in db.deleted)
        assert any(t == "email_identities" for t, _ in db.deleted)


class TestLazySignupCleanup:

    def test_cleanup_abandoned_email_reclaims(self):
        db = FakeSupabase(_base_tables())
        plan, summary = cleanup_abandoned_email(
            "expired@example.com", dry_run=False, require_expired=True, client=db,
        )
        assert plan.refusal_reason == ""
        assert summary["total_rows"] >= 3
        assert db.deleted  # records removed
        # The email identity is gone → a fresh signup would no longer be blocked.
        remaining = [r for r in db.tables["email_identities"] if r["email"] == "expired@example.com"]
        assert remaining == []

    def test_lazy_refuses_real_account(self):
        db = FakeSupabase(_base_tables())
        plan, _summary = cleanup_abandoned_email(
            "done@example.com", dry_run=False, require_expired=True, client=db,
        )
        assert plan.refusal_reason
        assert db.deleted == []

    def test_lazy_refuses_linked_identity(self):
        db = FakeSupabase(_base_tables(email_identities=[
            {"id": "EI-X", "email": "expired@example.com", "user_id": "U-GHOST"},
        ]))
        plan, _summary = cleanup_abandoned_email(
            "expired@example.com", dry_run=False, require_expired=True, client=db,
        )
        assert plan.refusal_reason
        assert db.deleted == []

    def test_lazy_skips_active_registration(self):
        db = FakeSupabase(_base_tables())
        plan, _summary = cleanup_abandoned_email(
            "active@example.com", dry_run=False, require_expired=True, client=db,
        )
        assert plan.refusal_reason
        assert db.deleted == []


class _DummyEmail:
    async def send_verification_email(self, to, verification_url):
        pass

    async def send_password_reset_email(self, to, reset_url):
        pass


def _build_service():
    from services.security.crypto import InMemoryCryptoService
    from services.identity.repositories import (
        InMemoryEmailIdentityRepository,
        InMemoryMembershipRepository,
        InMemoryOrganizationRepository,
        InMemoryPasswordCredentialRepository,
        InMemoryPasswordResetRepository,
        InMemoryRefreshTokenRepository,
        InMemoryRegistrationSessionRepository,
        InMemorySessionRepository,
        InMemoryUserRepository,
        InMemoryVerificationTokenRepository,
    )
    from services.identity.services import (
        AuthService,
        MembershipService,
        OrganizationService,
        PasswordService,
        SessionService,
        TokenService,
        UserService,
        VerificationService,
    )
    crypto = InMemoryCryptoService()
    repos = {
        "reg_session_repo": InMemoryRegistrationSessionRepository(),
        "vt_repo": InMemoryVerificationTokenRepository(),
        "ei_repo": InMemoryEmailIdentityRepository(),
        "user_repo": InMemoryUserRepository(),
        "pc_repo": InMemoryPasswordCredentialRepository(),
        "org_repo": InMemoryOrganizationRepository(),
        "mem_repo": InMemoryMembershipRepository(),
        "session_repo": InMemorySessionRepository(),
        "rt_repo": InMemoryRefreshTokenRepository(),
        "pr_repo": InMemoryPasswordResetRepository(),
    }
    user_svc = UserService(repos["user_repo"], repos["ei_repo"])
    org_svc = OrganizationService(repos["org_repo"], repos["mem_repo"])
    mem_svc = MembershipService(repos["mem_repo"], repos["user_repo"], repos["org_repo"])
    ver_svc = VerificationService(repos["vt_repo"], repos["ei_repo"], crypto)
    pwd_svc = PasswordService(repos["pc_repo"], repos["user_repo"], crypto)
    ses_svc = SessionService(repos["session_repo"], repos["rt_repo"])
    tok_svc = TokenService(repos["rt_repo"], repos["session_repo"], crypto)
    svc = AuthService(
        email_provider=_DummyEmail(),
        crypto=crypto,
        registration_session_repo=repos["reg_session_repo"],
        verification_token_repo=repos["vt_repo"],
        email_identity_repo=repos["ei_repo"],
        refresh_token_repo=repos["rt_repo"],
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        password_reset_repo=repos["pr_repo"],
    )
    return svc, repos


class TestBeginRegistrationInvokesLazyReclaim:

    @pytest.mark.asyncio
    async def test_begin_registration_calls_reclaim(self, monkeypatch):
        from services.identity.services.auth_service import AuthService
        svc, _repos = _build_service()
        calls = {}

        async def fake_reclaim(email):
            calls["email"] = email

        monkeypatch.setattr(svc, "_reclaim_abandoned_registration", fake_reclaim)

        result = await svc.begin_registration(" Fresh@Example.com ")
        assert calls.get("email") == "fresh@example.com"  # normalized before reclaim
        assert result.registration_session is not None

    @pytest.mark.asyncio
    async def test_begin_registration_continues_after_reclaim_failure(self, monkeypatch):
        from services.identity.services.auth_service import AuthService
        svc, _repos = _build_service()

        async def failing_reclaim(self, email):
            raise RuntimeError("reclaim unavailable")

        monkeypatch.setattr(svc, "_reclaim_abandoned_registration", failing_reclaim)
        result = await svc.begin_registration("fresh2@example.com")
        assert result.registration_session is not None


class TestRuntimeGate:

    def test_disabled_in_development(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        from services.identity.registration_cleanup import abandoned_cleanup_runtime_enabled
        enabled, reason = abandoned_cleanup_runtime_enabled()
        assert enabled is False
        assert "production" in reason

    def test_disabled_in_production_without_flag(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        from services.identity.registration_cleanup import abandoned_cleanup_runtime_enabled
        enabled, reason = abandoned_cleanup_runtime_enabled()
        assert enabled is False
        assert "ENABLED" in reason

    def test_disabled_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", "false")
        from services.identity.registration_cleanup import abandoned_cleanup_runtime_enabled
        enabled, _reason = abandoned_cleanup_runtime_enabled()
        assert enabled is False

    def test_enabled_in_production_with_flag(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        for value in ("true", "1", "yes", "TRUE"):
            monkeypatch.setenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", value)
            from services.identity.registration_cleanup import abandoned_cleanup_runtime_enabled
            enabled, reason = abandoned_cleanup_runtime_enabled()
            assert enabled is True, f"{value} should enable"
            assert reason == "enabled"

    def test_manual_mode_ignores_runtime_gate(self, monkeypatch):
        """The shared predicate itself is gate-agnostic; the operator CLI and
        tests can build plans without the runtime flag (the gate is applied at
        execution boundaries: the periodic loop and the lazy request path)."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        plan = build_abandoned_plan(
            target_email="expired@example.com", **_base_tables(),
            require_expired=True, now=_NOW,
        )
        assert plan.refusal_reason == ""  # predicate itself is pure


class TestLazyReclaimRequestPathSafety:

    @pytest.mark.asyncio
    async def test_reclaim_skipped_in_development(self, monkeypatch):
        """In a non-production runtime, the request-path reclaim must never
        call the shared cleanup (which would otherwise reach Supabase)."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        from services.identity import registration_cleanup

        def _boom(*a, **k):
            raise AssertionError("lazy reclaim must not run in development")
        monkeypatch.setattr(registration_cleanup, "cleanup_abandoned_email", _boom)

        svc, _repos = _build_service()
        result = await svc.begin_registration("dev@example.com")
        assert result.registration_session is not None  # signup unaffected

    @pytest.mark.asyncio
    async def test_reclaim_runs_only_when_explicitly_enabled(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", "true")
        from services.identity import registration_cleanup

        sentinel_client = object()
        calls = {}
        def fake_resolve_client():
            return sentinel_client
        monkeypatch.setattr(registration_cleanup, "resolve_automatic_cleanup_client", fake_resolve_client)

        def fake_cleanup(email, *, dry_run, require_expired, client):
            calls["email"] = email
            calls["dry_run"] = dry_run
            calls["require_expired"] = require_expired
            calls["client_is_sentinel"] = client is sentinel_client
            from services.identity.registration_cleanup import AbandonedPlan
            return AbandonedPlan(target_email=email), {
                "total_rows": 0, "deletes_by_table": {}, "found": {}, "orphan_identity_user_ids": [],
                "refusal_reason": "", "require_expired": True,
            }
        monkeypatch.setattr(registration_cleanup, "cleanup_abandoned_email", fake_cleanup)

        svc, _repos = _build_service()
        await svc.begin_registration("prod@example.com")
        assert calls.get("email") == "prod@example.com"
        assert calls.get("dry_run") is False
        assert calls.get("require_expired") is True
        assert calls.get("client_is_sentinel") is True  # explicit client injection


class TestResolveAutomaticCleanupClient:

    def test_returns_none_in_development(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        from services.identity import registration_cleanup

        def _boom(*a, **k):
            raise AssertionError("must not resolve a client when the gate is off")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)

        assert registration_cleanup.resolve_automatic_cleanup_client() is None

    def test_returns_none_in_production_without_flag(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", raising=False)
        from services.identity import registration_cleanup

        def _boom(*a, **k):
            raise AssertionError("must not resolve a client without the explicit flag")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)

        assert registration_cleanup.resolve_automatic_cleanup_client() is None

    def test_returns_client_when_fully_enabled(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", "true")
        from services.identity import registration_cleanup

        sentinel = object()
        monkeypatch.setattr("services.supabase.get_supabase_client", lambda: sentinel)
        assert registration_cleanup.resolve_automatic_cleanup_client() is sentinel

    def test_automatic_execution_with_injected_fake_mutates_only_fake(self, monkeypatch):
        """The automatic path honors explicit client injection: with both gates
        satisfied but a FAKE client injected, only the fake is mutated — never
        the real external target."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", "true")
        from services.identity import registration_cleanup

        def _boom(*a, **k):
            raise AssertionError("real get_supabase_client must not be used")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)

        db = FakeSupabase(_base_tables())
        report = registration_cleanup.run_abandoned_cleanup(dry_run=False, client=db)
        assert report["cleaned_rows"] >= 1
        assert db.deleted  # only the fake was mutated
        assert not any(t == "identity_users" for t, _ in db.deleted)


class TestNoSecretsInOutput:

    def test_report_contains_counts_only(self):
        db = FakeSupabase(_base_tables())
        report = run_abandoned_cleanup(dry_run=True, client=db)
        for value in report.values():
            assert not isinstance(value, str) or "@" not in value
        assert set(report) == {"scanned", "cleaned_emails", "cleaned_rows", "skipped", "failures", "dry_run"}

    def test_deleted_records_only_ids(self):
        db = FakeSupabase(_base_tables())
        run_abandoned_cleanup(dry_run=False, client=db)
        for _table, rid in db.deleted:
            assert isinstance(rid, str) and "@" not in rid