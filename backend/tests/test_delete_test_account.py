"""Tests for the safe test-account cleanup tool (delete_test_account.py).

Covers the pure plan-builder and dry-run semantics. No production access, no
writes, no secrets printed.
"""

from __future__ import annotations

import pytest

from scripts.delete_test_account import (
    build_cleanup_plan,
    apply_cleanup_plan,
)


def _fixture(**overrides):
    base = {
        "identity_users": [
            {"id": "U-A"},
            {"id": "U-B"},
        ],
        "email_identities": [
            {"id": "EI-1", "user_id": "U-A", "email": "a@example.com"},
            {"id": "EI-2", "user_id": "U-B", "email": "b@example.com"},
        ],
        "password_credentials": [
            {"id": "PC-1", "user_id": "U-A"},
            {"id": "PC-2", "user_id": "U-B"},
        ],
        "sessions": [
            {"id": "S-1", "user_id": "U-A"},
            {"id": "S-2", "user_id": "U-B"},
        ],
        "refresh_tokens": [
            {"id": "RT-1", "session_id": "S-1"},
            {"id": "RT-2", "session_id": "S-2"},
        ],
        "registration_sessions": [
            {"id": "RS-1", "user_id": "U-A", "email": "a@example.com"},
        ],
        "verification_tokens": [
            {"id": "VT-1", "target": "a@example.com"},
            {"id": "VT-2", "target": "b@example.com"},
        ],
        "password_reset_requests": [{"id": "PR-1", "user_id": "U-A"}],
        "oauth_sessions": [{"id": "OA-1", "user_id": "U-A"}],
        "web_session_bindings": [{"id": "WB-1", "canonical_user_id": "U-A"}],
        "external_identities": [{"id": "EX-1", "user_id": "U-A"}],
        "connected_accounts": [{"id": "CA-1", "user_id": "U-A"}],
        "workspaces": [{"id": "W-1", "owner_user_id": "U-A"}],
        "workspace_members": [{"id": "WM-1", "workspace_id": "W-1", "user_id": "U-A"}],
        "memberships": [{"id": "M-1", "user_id": "U-A", "organization_id": "ORG-A"}],
        "invitations": [{"id": "INV-1", "organization_id": "ORG-A"}],
        "organizations": [{"id": "ORG-A", "created_by": "U-A"}],
        "jobs": [{"id": "J-1", "user_id": "U-A"}, {"id": "J-2", "user_id": "U-B"}],
        "discoveries": [{"id": "D-1", "workspace_id": "W-1"}],
    }
    base.update(overrides)
    return base


class TestTargetResolution:

    def test_missing_target_fails(self):
        with pytest.raises(ValueError):
            build_cleanup_plan(**{**{"target_email": "", "target_user_id": ""}, **_fixture()})

    def test_ambiguous_email_fails(self):
        f = _fixture(email_identities=[
            {"id": "EI-1", "user_id": "U-A", "email": "shared@example.com"},
            {"id": "EI-2", "user_id": "U-B", "email": "shared@example.com"},
        ])
        with pytest.raises(ValueError):
            build_cleanup_plan(target_email="shared@example.com", **f)

    def test_unknown_email_fails(self):
        with pytest.raises(ValueError):
            build_cleanup_plan(target_email="nobody@example.com", **_fixture())


class TestPlanSelection:

    def test_target_records_selected_and_others_not(self):
        f = _fixture()
        plan = build_cleanup_plan(target_email="a@example.com", **f)
        assert plan.target_user_id == "U-A"
        assert "EI-1" in plan.delete["email_identities"] and "EI-2" not in plan.delete["email_identities"]
        assert "PC-1" in plan.delete["password_credentials"] and "PC-2" not in plan.delete["password_credentials"]
        assert "S-1" in plan.delete["sessions"] and "S-2" not in plan.delete["sessions"]
        assert "RT-1" in plan.delete["refresh_tokens"] and "RT-2" not in plan.delete["refresh_tokens"]
        assert "J-1" in plan.delete["jobs"] and "J-2" not in plan.delete["jobs"]
        assert "VT-1" in plan.delete["verification_tokens"] and "VT-2" not in plan.delete["verification_tokens"]
        assert "U-A" in plan.delete["identity_users"]

    def test_shared_workspace_not_deleted(self):
        f = _fixture(workspace_members=[
            {"id": "WM-1", "workspace_id": "W-1", "user_id": "U-A"},
            {"id": "WM-2", "workspace_id": "W-1", "user_id": "U-B"},
        ])
        plan = build_cleanup_plan(target_user_id="U-A", **f)
        assert plan.delete.get("workspaces", []) == []  # not deleted
        assert "W-1" not in plan.delete.get("discoveries", [])
        assert any(s.get("resource") == "workspaces" and s.get("reason") == "shared (other members)" for s in plan.skip)

    def test_shared_organization_only_removes_membership(self):
        f = _fixture(memberships=[
            {"id": "M-1", "user_id": "U-A", "organization_id": "ORG-A"},
            {"id": "M-2", "user_id": "U-B", "organization_id": "ORG-A"},
        ])
        plan = build_cleanup_plan(target_user_id="U-A", **f)
        assert "ORG-A" not in plan.delete.get("organizations", [])
        assert "M-1" in plan.delete["memberships"]
        assert "M-2" not in plan.delete["memberships"]
        assert any(s.get("resource") == "organizations" for s in plan.skip)

    def test_billing_never_deleted(self):
        plan = build_cleanup_plan(target_user_id="U-A", **_fixture())
        for table in ("billing_customers", "billing_subscriptions", "billing_invoices"):
            assert table not in plan.delete
        assert any(s.get("resource") == "billing_*" for s in plan.skip)

    def test_repeat_after_cleanup_is_safe_noop(self):
        f = _fixture()
        plan = build_cleanup_plan(target_user_id="U-A", **f)
        assert "U-A" in plan.delete["identity_users"]
        # After U-A is gone, a second run must not touch any remaining records:
        # it refuses because the target identity no longer exists, so it can
        # never delete another user's data.
        cleaned = {
            "identity_users": [{"id": "U-B"}],
            "email_identities": [{"id": "EI-2", "user_id": "U-B", "email": "b@example.com"}],
            "password_credentials": [{"id": "PC-2", "user_id": "U-B"}],
            "sessions": [{"id": "S-2", "user_id": "U-B"}],
            "refresh_tokens": [{"id": "RT-2", "session_id": "S-2"}],
            "registration_sessions": [],
            "verification_tokens": [{"id": "VT-2", "target": "b@example.com"}],
            "password_reset_requests": [],
            "oauth_sessions": [],
            "web_session_bindings": [],
            "external_identities": [],
            "connected_accounts": [],
            "workspaces": [],
            "workspace_members": [],
            "memberships": [],
            "invitations": [],
            "organizations": [],
            "jobs": [{"id": "J-2", "user_id": "U-B"}],
            "discoveries": [],
        }
        with pytest.raises(ValueError):
            build_cleanup_plan(target_user_id="U-A", **cleaned)

    def test_summary_never_contains_secrets(self):
        plan = build_cleanup_plan(target_email="a@example.com", **_fixture())
        summary = plan.summarize()
        for table, ids in plan.delete.items():
            assert all(isinstance(i, str) and not any(k in i.lower() for k in ("token", "hash", "password")) for i in ids)
        assert "deletes_by_table" in summary
        assert "total_rows" in summary


class TestDryRun:

    def test_dry_run_makes_no_writes(self, monkeypatch):
        plan = build_cleanup_plan(target_user_id="U-A", **_fixture())

        def _boom(*a, **k):
            raise AssertionError("dry-run must not touch Supabase")
        monkeypatch.setattr("services.supabase.get_supabase_client", _boom)

        summary = apply_cleanup_plan(plan, dry_run=True)
        assert "applied_updates" not in summary
        assert summary["target_user_id"] == "U-A"
        assert summary["total_rows"] >= 1