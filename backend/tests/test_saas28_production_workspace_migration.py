"""SaaS-2.8 — Production Workspace & Tenant Migration / Reconciliation.

Dry-run-first operator workflow. Uses fake PostgREST clients for all mutation
tests; no production data touched. Covers detection, reconciliation
(READY/BLOCKED/MANUAL_REVIEW), child inventory, dry-run zero-write, apply,
idempotency, verification, and safety refusals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.persistence.launch.legacy_workspace_migration import (
    apply_migration_plan,
    build_migration_plan,
    detect_legacy_workspaces,
)
from services.persistence.launch.workspace_reconciliation import (
    inspect_production,
    reconcile_workspace,
    record_migration,
    verify_migration,
)

LEGACY = "00000000-0000-4000-8000-0000000000aa"
LEGACY2 = "00000000-0000-4000-8000-0000000000bb"
OWNER = "00000000-0000-4000-8000-0000000000c1"
OWNER2 = "00000000-0000-4000-8000-0000000000c2"
ORG = "org-1"
ORG2 = "org-2"


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._filters: list[tuple[str, str, str]] = []
        self._limit = None
        self._op = "select"
        self._payload = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, str(val)))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, str(val)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
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
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if str(r.get(col, "")) == val]
            elif kind == "is":
                rows = [r for r in rows if r.get(col) is None]
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
        updated = []
        for r in self._db.tables.get(self._table, []):
            if any(str(r.get(col, "")) == val for kind, col, val in self._filters if kind == "eq"):
                updated.append({**r, **self._payload})
            else:
                updated.append(r)
        self._db.tables[self._table] = updated
        return _Row(updated)


class FakeClient:
    def __init__(self, tables=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}

    def table(self, name):
        return _Query(self, name)


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _ws(ws_id, owner=OWNER, org=ORG, deleted=None, workflow_session=None):
    return {"id": ws_id, "organization_id": org, "owner_user_id": owner,
            "name": "W", "slug": "w", "status": "active", "settings": {},
            "metadata": {}, "deleted_at": deleted,
            "workflow_session_id": workflow_session,
            "created_at": _iso(), "updated_at": _iso()}


def _legacy_db(*, org=ORG, owner=OWNER, membership_status="active", extra_org=False,
               extra_owner_ws=False, migrate_028=True):
    tables = {
        "workflow_sessions": [{"id": LEGACY, "user_id": owner, "channel": "workspace",
                               "session_key": owner, "status": "active"}],
        "workspaces": [_ws(LEGACY, owner=owner, org=org)],
        "identity_users": [{"id": owner, "display_name": "Owner", "deleted_at": None}],
        "organizations": [{"id": ORG, "name": "Org1", "slug": "org-1", "deleted_at": None, "created_by": OWNER}],
        "memberships": [{"id": str(uuid4()), "user_id": owner, "organization_id": ORG,
                         "role": "owner", "status": membership_status}],
        "campaigns": [{"id": "c1", "workspace_id": LEGACY}],
        "workspace_leads": [{"id": "l1", "workspace_id": LEGACY}],
        "workspace_companies": [],
        "drafts": [{"id": "d1", "workspace_id": LEGACY}],
        "discoveries": [],
        "knowledge": [],
        "knowledge_items": [],
        "knowledge_sources": [],
        "strategic_updates": [],
        "strategic_actions": [],
        "workspace_members": [{"id": "wm1", "workspace_id": LEGACY, "user_id": owner}],
        "workspace_migrations": [],
    }
    if extra_org:
        tables["organizations"].append({"id": ORG2, "name": "Org2", "slug": "org-2", "deleted_at": None})
        tables["memberships"].append({"id": str(uuid4()), "user_id": owner, "organization_id": ORG2,
                                      "role": "member", "status": "active"})
    if extra_owner_ws:
        tables["workspaces"].append(_ws(str(uuid4()), owner=owner, org=ORG))
    if not migrate_028:
        # remove workflow_session_id key to simulate pre-028 schema
        for w in tables["workspaces"]:
            w.pop("workflow_session_id", None)
    return FakeClient(tables)


class TestDetection:

    def test_legacy_detection(self):
        db = _legacy_db()
        legacy = detect_legacy_workspaces(db)
        assert [w["workspace_id"] for w in legacy] == [LEGACY]

    def test_non_legacy_ignored(self):
        db = _legacy_db()
        db.tables["workspaces"].append(_ws(str(uuid4()), owner=OWNER, org=ORG))
        legacy = detect_legacy_workspaces(db)
        assert [w["workspace_id"] for w in legacy] == [LEGACY]

    def test_already_migrated_ignored(self):
        db = _legacy_db()
        # A new workspace already records this legacy id as provenance.
        db.tables["workspaces"].append(_ws(str(uuid4()), owner=OWNER, org=ORG,
                                           workflow_session=LEGACY))
        rec = reconcile_workspace(db, LEGACY)
        assert rec.get("already_migrated") is True


class TestReconciliation:

    def test_missing_owner_blocked(self):
        db = _legacy_db()
        db.tables["workspaces"] = [_ws(LEGACY, owner="")]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "blocked"

    def test_missing_organization_blocked(self):
        db = _legacy_db()
        db.tables["organizations"] = []
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "blocked"

    def test_exactly_one_org_candidate_ready(self):
        db = _legacy_db(org="")  # empty org_id -> derive from membership
        db.tables["workspaces"] = [_ws(LEGACY, owner=OWNER, org="")]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "ready"
        assert rec["organization_id"] == ORG

    def test_multiple_org_candidates_manual_review(self):
        db = _legacy_db(org="", extra_org=True)
        db.tables["workspaces"] = [_ws(LEGACY, owner=OWNER, org="")]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "manual_review"

    def test_no_org_candidate_blocked(self):
        db = _legacy_db()
        db.tables["memberships"] = []
        db.tables["workspaces"] = [_ws(LEGACY, owner=OWNER, org="")]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "blocked"

    def test_org_conflict_manual_review(self):
        db = _legacy_db()
        # workspace.org_id = ORG but owner only belongs to ORG2.
        db.tables["memberships"] = [{"id": str(uuid4()), "user_id": OWNER,
                                     "organization_id": ORG2, "role": "member", "status": "active"}]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "manual_review"

    def test_inactive_membership_blocked(self):
        db = _legacy_db(membership_status="pending")
        db.tables["workspaces"] = [_ws(LEGACY, owner=OWNER, org="")]
        rec = reconcile_workspace(db, LEGACY)
        assert rec["status"] == "blocked"


class TestChildCounts:

    def test_child_counts(self):
        db = _legacy_db()
        counts = {t: len(db.tables[t]) for t in
                  ("campaigns", "workspace_leads", "drafts", "workspace_members")}
        assert counts["campaigns"] == 1 and counts["workspace_leads"] == 1
        plan = build_migration_plan(db, LEGACY)
        assert plan["child_counts"]["campaigns"] == 1
        assert plan["child_counts"]["workspace_members"] == 1


class TestDryRun:

    def test_dry_run_performs_zero_writes(self):
        db = _legacy_db()
        before = {t: list(rows) for t, rows in db.tables.items()}
        rec = reconcile_workspace(db, LEGACY)
        plan = build_migration_plan(db, LEGACY)
        result = apply_migration_plan(db, plan, dry_run=True)
        assert result["applied"] is False and result["dry_run"] is True
        assert db.tables == before
        assert rec["status"] == "ready"


class TestApply:

    def test_apply_creates_one_workspace_and_remaps(self):
        db = _legacy_db()
        plan = build_migration_plan(db, LEGACY)
        new_id = plan["new_workspace_id"]
        result = apply_migration_plan(db, plan, dry_run=False)
        assert result["applied"] is True
        # Exactly one new workspace created.
        new_ws = [w for w in db.tables["workspaces"] if w["id"] == new_id]
        assert len(new_ws) == 1
        assert new_ws[0]["workflow_session_id"] == LEGACY  # provenance preserved
        assert new_ws[0]["owner_user_id"] == OWNER
        # All required children remapped; none remain under legacy.
        for t in ("campaigns", "workspace_leads", "drafts", "workspace_members"):
            assert all(r["workspace_id"] == new_id for r in db.tables[t])
            assert not [r for r in db.tables[t] if r["workspace_id"] == LEGACY]
        # Legacy soft-deleted; workflow session intact.
        legacy_ws = [w for w in db.tables["workspaces"] if w["id"] == LEGACY][0]
        assert legacy_ws["deleted_at"] is not None
        assert db.tables["workflow_sessions"][0]["id"] == LEGACY

    def test_post_migration_verification(self):
        db = _legacy_db()
        plan = build_migration_plan(db, LEGACY)
        apply_migration_plan(db, plan, dry_run=False)
        record_migration(db, legacy_workspace_id=LEGACY, new_workspace_id=plan["new_workspace_id"],
                         workflow_session_id=LEGACY, organization_id=ORG, owner_user_id=OWNER)
        check = verify_migration(db, plan)
        assert check["all_ok"] is True

    def test_second_apply_idempotent(self):
        db = _legacy_db()
        plan = build_migration_plan(db, LEGACY)
        apply_migration_plan(db, plan, dry_run=False)
        # Second apply with the same plan is a safe no-op.
        second = apply_migration_plan(db, plan, dry_run=False)
        assert second["applied"] is False
        assert second["reason"] == "already_migrated"
        assert len([w for w in db.tables["workspaces"] if w["id"] == plan["new_workspace_id"]]) == 1

    def test_stale_plan_revalidated_on_apply(self):
        db = _legacy_db()
        plan = build_migration_plan(db, LEGACY)
        # Simulate state change before apply: owner loses the org membership.
        db.tables["memberships"] = []
        result = apply_migration_plan(db, plan, dry_run=False)
        # Plan was stale; revalidation refuses (not applied, no new workspace).
        assert result["applied"] is False
        assert not [w for w in db.tables["workspaces"] if w["id"] == plan["new_workspace_id"]]

    def test_cross_user_isolation(self):
        db = _legacy_db(owner=OWNER2)
        db.tables["workspaces"] = [_ws(LEGACY, owner=OWNER2, org=ORG)]
        plan = build_migration_plan(db, LEGACY)
        result = apply_migration_plan(db, plan, dry_run=False)
        assert result["applied"] is True
        new_ws = [w for w in db.tables["workspaces"] if w["id"] == result["new_workspace_id"]][0]
        assert new_ws["owner_user_id"] == OWNER2

    def test_cross_org_isolation(self):
        db = _legacy_db(org=ORG2)
        db.tables["organizations"] = [{"id": ORG2, "name": "Org2", "slug": "org-2", "deleted_at": None}]
        db.tables["memberships"] = [{"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG2,
                                     "role": "owner", "status": "active"}]
        plan = build_migration_plan(db, LEGACY)
        result = apply_migration_plan(db, plan, dry_run=False)
        new_ws = [w for w in db.tables["workspaces"] if w["id"] == result["new_workspace_id"]][0]
        assert new_ws["organization_id"] == ORG2

    def test_apply_refuses_without_028(self, monkeypatch):
        from services.persistence.launch import legacy_workspace_migration as m
        db = _legacy_db()
        plan = build_migration_plan(db, LEGACY)
        plan["ready"] = True
        monkeypatch.setattr(m, "_has_workflow_session_column", lambda client: False)
        result = apply_migration_plan(db, plan, dry_run=False)
        assert result["applied"] is False
        assert any("028" in b for b in result.get("blockers", []))


class TestInspectProduction:

    def test_report_counts(self):
        db = _legacy_db()
        db.tables["workspaces"].append(_ws(str(uuid4()), owner=OWNER, org=ORG))  # non-legacy
        report = inspect_production(db)
        assert report["legacy_workspaces"] == 1
        assert report["total_active_workspaces"] == 2
        assert report["non_legacy_workspaces"] == 1
        assert report["ready"] == 1

    def test_duplicate_membership_detection(self):
        db = _legacy_db()
        db.tables["memberships"].append({"id": str(uuid4()), "user_id": OWNER,
                                         "organization_id": ORG, "role": "owner", "status": "active"})
        report = inspect_production(db)
        assert len(report["duplicate_memberships"]) == 1

    def test_duplicate_org_detection(self):
        db = _legacy_db()
        db.tables["organizations"].append({"id": str(uuid4()), "name": "Org1 copy",
                                           "slug": "org-1-copy", "deleted_at": None,
                                           "created_by": OWNER})
        report = inspect_production(db)
        assert len(report["duplicate_organizations"]) == 1


class TestMappingDurability:

    def test_record_and_verify_mapping(self):
        db = _legacy_db()
        record_migration(db, legacy_workspace_id=LEGACY, new_workspace_id=str(uuid4()),
                         workflow_session_id=LEGACY, organization_id=ORG, owner_user_id=OWNER)
        row = db.tables["workspace_migrations"][0]
        assert row["legacy_workspace_id"] == LEGACY
        assert row["status"] == "applied"
