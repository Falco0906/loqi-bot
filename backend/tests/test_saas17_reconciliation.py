"""SaaS-1.7 — legacy synthetic web-user reconciliation tests.

Verifies the reconciliation plan builder (pure logic, no DB):
- one-to-one synthetic → canonical mapping
- already-reconciled rows are not re-mapped
- missing canonical user → orphaned (never mutated)
- no binding → orphaned
- ambiguous binding → orphaned
- unrelated user untouched
- duplicate target ownership → skipped
- repeated execution is idempotent
"""

from __future__ import annotations

from scripts.reconcile_web_sessions import build_reconciliation_plan


def _plan(web_users, bindings=None, identity_ids=None, **tables):
    return build_reconciliation_plan(
        web_users=web_users,
        bindings=bindings or [],
        identity_user_ids=identity_ids or {"C-1", "C-2"},
        workspaces=tables.get("workspaces", []),
        connected_accounts=tables.get("connected_accounts", []),
        external_identities=tables.get("external_identities", []),
    )


class TestReconciliationPlan:

    def test_one_to_one_mapping_rekeys_records(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            workspaces=[{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
            connected_accounts=[{
                "id": "ca-1", "user_id": "S-1",
                "organization_id": "org-a", "provider": "google", "account_id": "acct-1",
            }],
            external_identities=[{
                "id": "ei-1", "user_id": "S-1", "provider": "google", "provider_subject": "sub-1",
            }],
        )
        assert len(plan.mapped) == 1
        entry = plan.mapped[0]
        assert entry["canonical_user_id"] == "C-1"
        assert entry["workspaces"] == ["ws-1"]
        assert entry["connected_accounts"] == ["ca-1"]
        assert entry["external_identities"] == ["ei-1"]
        assert plan.counts == {"workspaces": 1, "connected_accounts": 1, "external_identities": 1}

    def test_already_reconciled_row_not_remapped(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            workspaces=[{"id": "ws-1", "owner_user_id": "C-1", "organization_id": "org-a"}],
        )
        assert plan.mapped[0]["workspaces"] == []

    def test_no_binding_is_orphaned(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-none"}],
            workspaces=[{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
        )
        assert plan.mapped == []
        assert plan.orphaned[0]["reason"] == "no_binding"

    def test_missing_canonical_user_is_orphaned(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "GHOST"}],
            identity_ids={"C-1"},
            workspaces=[{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
        )
        assert plan.mapped == []
        assert plan.orphaned[0]["reason"] == "missing_canonical_user"

    def test_ambiguous_binding_is_orphaned(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[
                {"session_key": "tok-1", "canonical_user_id": "C-1"},
                {"session_key": "tok-1", "canonical_user_id": "C-2"},
            ],
            workspaces=[{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
        )
        assert plan.mapped == []
        assert plan.orphaned[0]["reason"] == "no_binding"

    def test_unrelated_user_untouched(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            # A normal (non-web) user's workspace must not be re-keyed.
            workspaces=[{"id": "ws-x", "owner_user_id": "REAL-USER", "organization_id": "org-a"}],
        )
        # The web user is mapped but owns nothing to re-key; the unrelated
        # workspace is never referenced by the plan.
        assert plan.mapped[0]["workspaces"] == []
        all_rekeyed = {i for e in plan.mapped for i in e["workspaces"]}
        assert "ws-x" not in all_rekeyed

    def test_duplicate_target_ownership_skipped(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            connected_accounts=[
                {"id": "ca-1", "user_id": "S-1", "organization_id": "org-a", "provider": "google", "account_id": "acct-1"},
                {"id": "ca-2", "user_id": "C-1", "organization_id": "org-a", "provider": "google", "account_id": "acct-1"},
            ],
        )
        assert plan.mapped[0]["connected_accounts"] == []
        assert len(plan.skipped_duplicates) == 1

    def test_repeated_execution_is_idempotent(self):
        snapshot = (
            [{"id": "S-1", "telegram_id": "web:tok-1"}],
            [{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            {"C-1"},
            [{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
            [],
            [],
        )
        first = build_reconciliation_plan(
            web_users=snapshot[0], bindings=snapshot[1], identity_user_ids=snapshot[2],
            workspaces=snapshot[3], connected_accounts=snapshot[4], external_identities=snapshot[5],
        )
        assert first.mapped[0]["workspaces"] == ["ws-1"]
        # After re-keying, the same snapshot represents an already-reconciled state.
        second = build_reconciliation_plan(
            web_users=snapshot[0], bindings=snapshot[1], identity_user_ids=snapshot[2],
            workspaces=[{"id": "ws-1", "owner_user_id": "C-1", "organization_id": "org-a"}],
            connected_accounts=snapshot[4], external_identities=snapshot[5],
        )
        assert second.mapped[0]["workspaces"] == []

    def test_dry_run_returns_counts_without_mutation(self):
        plan = _plan(
            web_users=[{"id": "S-1", "telegram_id": "web:tok-1"}],
            bindings=[{"session_key": "tok-1", "canonical_user_id": "C-1"}],
            workspaces=[{"id": "ws-1", "owner_user_id": "S-1", "organization_id": "org-a"}],
        )
        from scripts.reconcile_web_sessions import apply_reconciliation_plan
        summary = apply_reconciliation_plan(plan, dry_run=True)
        assert summary["workspaces_to_rekey"] == 1
        assert "applied_updates" not in summary