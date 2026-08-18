"""Tests for the abandoned-registration cleanup tool.

Covers the conservative SAFE-TO-CLEAN predicate, refusal paths, dry-run
semantics, and the exact record set this tool may delete. Pure plan-builder
tests only — no production access, no writes.
"""

from __future__ import annotations

import pytest

from scripts.cleanup_abandoned_registration import (
    apply_abandoned_plan,
    build_abandoned_plan,
    normalize_email,
)


def _fixture(**overrides):
    base = {
        "registration_sessions": [
            {"id": "RS-1", "email": "pending@example.com", "status": "pending",
             "user_id": "", "expires_at": "2026-08-18T00:00:00+00:00"},
            {"id": "RS-2", "email": "verified@example.com", "status": "verified",
             "user_id": "", "expires_at": "2026-08-18T00:00:00+00:00"},
            {"id": "RS-DONE", "email": "done@example.com", "status": "completed",
             "user_id": "U-DONE", "expires_at": "2026-08-18T00:00:00+00:00"},
            {"id": "RS-ORPHAN", "email": "orphan@example.com", "status": "verified",
             "user_id": "U-ORPHAN", "expires_at": "2026-08-18T00:00:00+00:00"},
        ],
        "verification_tokens": [
            {"id": "VT-1", "target": "pending@example.com", "purpose": "verify_email", "used_at": None},
            {"id": "VT-2", "target": "verified@example.com", "purpose": "verify_email", "used_at": "2026-08-18T00:00:00+00:00"},
            {"id": "VT-3", "target": "done@example.com", "purpose": "verify_email", "used_at": "2026-08-18T00:00:00+00:00"},
            {"id": "VT-4", "target": "orphan@example.com", "purpose": "verify_email", "used_at": None},
        ],
        "email_identities": [
            {"id": "EI-1", "email": "pending@example.com", "user_id": "", "is_verified": False, "is_primary": True},
            {"id": "EI-2", "email": "verified@example.com", "user_id": "", "is_verified": True, "is_primary": True},
            {"id": "EI-DONE", "email": "done@example.com", "user_id": "U-DONE", "is_verified": True, "is_primary": True},
            {"id": "EI-ORPHAN", "email": "orphan@example.com", "user_id": "U-ORPHAN", "is_verified": True, "is_primary": True},
        ],
        "identity_users": [
            {"id": "U-DONE"},
        ],
    }
    base.update(overrides)
    return base


class TestPredicate:

    def test_pending_unverified_is_cleanable(self):
        f = _fixture()
        plan = build_abandoned_plan(target_email="PENDING@Example.com", **f)
        assert plan.target_email == "pending@example.com"  # normalized
        assert "VT-1" in plan.delete["verification_tokens"]
        assert "RS-1" in plan.delete["registration_sessions"]
        assert "EI-1" in plan.delete["email_identities"]
        assert plan.refusal_reason == ""

    def test_verified_but_incomplete_is_cleanable(self):
        plan = build_abandoned_plan(target_email="verified@example.com", **_fixture())
        assert plan.refusal_reason == ""
        assert "RS-2" in plan.delete["registration_sessions"]
        assert "EI-2" in plan.delete["email_identities"]
        assert "VT-2" in plan.delete["verification_tokens"]

    def test_completed_registration_refused(self):
        plan = build_abandoned_plan(target_email="done@example.com", **_fixture())
        assert plan.refusal_reason
        assert plan.delete == {}

    def test_linked_email_identity_refused(self):
        # A linked email identity (even if its user row is absent) must refuse.
        f = _fixture(email_identities=[
            {"id": "EI-X", "email": "weird@example.com", "user_id": "U-GHOST",
             "is_verified": True, "is_primary": True},
        ], registration_sessions=[
            {"id": "RS-X", "email": "weird@example.com", "status": "verified",
             "user_id": "", "expires_at": "2026-08-18T00:00:00+00:00"},
        ])
        plan = build_abandoned_plan(target_email="weird@example.com", **f)
        assert plan.refusal_reason
        assert plan.delete == {}

    def test_registration_referencing_existing_user_refused(self):
        f = _fixture(registration_sessions=[
            {"id": "RS-1", "email": "a@example.com", "status": "verified",
             "user_id": "U-DONE", "expires_at": "2026-08-18T00:00:00+00:00"},
        ], email_identities=[
            {"id": "EI-1", "email": "a@example.com", "user_id": "", "is_verified": True, "is_primary": True},
        ])
        plan = build_abandoned_plan(target_email="a@example.com", **f)
        assert plan.refusal_reason
        assert plan.delete == {}

    def test_unknown_email_is_safe_noop(self):
        plan = build_abandoned_plan(target_email="nobody@example.com", **_fixture())
        assert plan.refusal_reason == ""
        assert plan.delete == {}

    def test_invalid_or_empty_email_refused(self):
        for bad in ("", "   ", "not-an-email"):
            plan = build_abandoned_plan(target_email=bad, **_fixture())
            assert plan.refusal_reason


class TestOrphanReporting:

    def test_orphan_identity_user_reported_not_deleted(self):
        # Registration references a user that does not exist in identity_users
        # (only U-DONE exists), while the email identity is UNLINKED: the
        # attempt is safely cleanable and the orphan user id is reported but
        # never selected for deletion.
        f = _fixture(email_identities=[
            {"id": "EI-1", "email": "orphan@example.com", "user_id": "",
             "is_verified": True, "is_primary": True},
        ], identity_users=[{"id": "U-DONE"}])
        plan = build_abandoned_plan(target_email="orphan@example.com", **f)
        assert plan.refusal_reason == ""
        assert "U-ORPHAN" in plan.orphan_identity_user_ids
        assert "U-ORPHAN" not in plan.delete  # never in the delete set
        assert "RS-ORPHAN" in plan.delete["registration_sessions"]
        assert "EI-1" in plan.delete["email_identities"]

    def test_linked_identity_with_resolvable_user_refused(self):
        f = _fixture(email_identities=[
            {"id": "EI-DONE", "email": "done@example.com", "user_id": "U-DONE",
             "is_verified": True, "is_primary": True},
        ])
        plan = build_abandoned_plan(target_email="done@example.com", **f)
        assert plan.refusal_reason


class TestApply:

    def test_apply_deletes_only_abandoned_records(self, monkeypatch):
        plan = build_abandoned_plan(target_email="pending@example.com", **_fixture())
        deleted: list[tuple[str, str]] = []

        # Fake that supports the re-read-before-delete (select) plus the delete.
        class _Fake:
            def select(self, *a):
                return self
            def eq(self, col, val):
                if self._mode == "select":
                    self._row = {"status": "pending", "user_id": "", "expires_at": "2000-01-01T00:00:00+00:00",
                                 "target": "pending@example.com", "email": "pending@example.com"}
                else:
                    deleted.append((self._table, str(val)))
                return self
            def limit(self, n):
                return self
            def delete(self):
                self._mode = "delete"
                return self
            def execute(self):
                if self._mode == "select":
                    return type("R", (), {"data": [self._row] if self._row else []})()
                return type("R", (), {"data": []})()
            def __init__(self, table):
                self._table = table
                self._mode = "select"
                self._row = None

        def fake_client():
            class C:
                def table(self, name):
                    return _Fake(name)
            return C()
        monkeypatch.setattr("services.supabase.get_supabase_client", fake_client)

        summary = apply_abandoned_plan(plan, dry_run=False)
        assert summary["applied_updates"] >= 3
        tables = {t for t, _ in deleted}
        assert tables == {"registration_sessions", "verification_tokens", "email_identities"}
        # Never identity_users / credentials / sessions / orgs / billing.
        assert not tables & {"identity_users", "password_credentials", "sessions", "organizations", "billing_customers"}

    def test_dry_run_makes_zero_writes(self, monkeypatch):
        plan = build_abandoned_plan(target_email="pending@example.com", **_fixture())

        def _boom(*a, **k):
            raise AssertionError("dry-run must not touch Supabase")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)

        summary = apply_abandoned_plan(plan, dry_run=True)
        assert "applied_updates" not in summary
        assert summary["total_rows"] >= 3

    def test_apply_never_runs_on_refusal(self, monkeypatch):
        plan = build_abandoned_plan(target_email="done@example.com", **_fixture())
        assert plan.refusal_reason

        def _boom(*a, **k):
            raise AssertionError("refused plan must not touch Supabase")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)
        summary = apply_abandoned_plan(plan, dry_run=False)
        assert "applied_updates" not in summary
        assert plan.delete == {}


class TestIdempotencyAndSummary:

    def test_second_run_is_noop(self):
        f = _fixture()
        # First run removes everything for the email.
        build_abandoned_plan(target_email="pending@example.com", **f)
        # A second run against an already-cleaned snapshot has nothing to do.
        cleaned = _fixture()
        cleaned["registration_sessions"] = [r for r in cleaned["registration_sessions"] if r["email"] != "pending@example.com"]
        cleaned["verification_tokens"] = [v for v in cleaned["verification_tokens"] if v["target"] != "pending@example.com"]
        cleaned["email_identities"] = [e for e in cleaned["email_identities"] if e["email"] != "pending@example.com"]
        plan2 = build_abandoned_plan(target_email="pending@example.com", **cleaned)
        assert plan2.delete == {}
        assert plan2.found == {"registration_sessions": 0, "verification_tokens": 0, "email_identities": 0}

    def test_summary_contains_no_secrets(self):
        plan = build_abandoned_plan(target_email="verified@example.com", **_fixture())
        summary = plan.summarize()
        for table, ids in plan.delete.items():
            assert all(isinstance(i, str) and not any(k in i.lower() for k in ("token", "hash", "password", "secret")) for i in ids)
        assert "deletes_by_table" in summary
        assert "total_rows" in summary

    def test_normalization_matches_signup(self):
        # AuthService._normalize_email is strip + lowercase.
        assert normalize_email("  Mixed@Case.COM  ") == "mixed@case.com"
        assert normalize_email("") == ""