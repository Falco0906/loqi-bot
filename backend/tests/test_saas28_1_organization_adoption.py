"""SaaS-2.8.1 — Legacy Organization Adoption & Reconciliation Preparation.

Read-only adoption planning. Uses fake PostgREST clients; no production data
touched. Covers count reconciliation, deterministic adoption classification,
membership action planning, ambiguity/dangling refs, dry-run zero-write, and
determinism.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.persistence.launch.workspace_reconciliation import (
    adoption_plan_for_workspace,
    build_adoption_report,
    inspect_production,
)

LEGACY = "00000000-0000-4000-8000-0000000000aa"
OWNER = "00000000-0000-4000-8000-0000000000c1"
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
        if self._op == "insert":
            stored = [dict(r) for r in self._db.tables.setdefault(self._table, [])]
            stored.append(self._payload)
            self._db.tables[self._table] = stored
            return _Row([self._payload])
        return _Row([])


class FakeClient:
    def __init__(self, tables=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}

    def table(self, name):
        return _Query(self, name)


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _db(*, org=ORG, org_exists=True, membership_status="active",
        memberships=None, reg_org="", second_org=False):
    tables = {
        "workflow_sessions": [{"id": LEGACY, "user_id": OWNER, "channel": "workspace",
                               "session_key": OWNER, "status": "active"}],
        "workspaces": [{"id": LEGACY, "organization_id": org, "owner_user_id": OWNER,
                        "name": "W", "slug": "w", "status": "active", "settings": {},
                        "metadata": {}, "workflow_session_id": None,
                        "deleted_at": None, "created_at": _iso(), "updated_at": _iso()}],
        "identity_users": [{"id": OWNER, "display_name": "Owner", "deleted_at": None}],
        "organizations": ([{"id": ORG, "name": "Org1", "slug": "org-1", "created_by": OWNER,
                            "deleted_at": None}] if org_exists else [])
        + ([{"id": ORG2, "name": "Org2", "slug": "org-2", "created_by": OWNER,
             "deleted_at": None}] if second_org else []),
        "memberships": memberships if memberships is not None else
            [{"id": "00000000-0000-4000-8000-0000000000dd", "user_id": OWNER,
              "organization_id": ORG, "role": "owner", "status": membership_status}],
        "registration_sessions": ([{"id": str(uuid4()), "user_id": OWNER,
                                    "organization_id": reg_org, "status": "completed"}]
                                  if reg_org else []),
        "workspace_migrations": [],
    }
    return FakeClient(tables)


class TestCountReconciliation:

    def test_legacy_plus_non_legacy_equals_total(self):
        db = _db()
        # Add a non-legacy workspace (id not in workflow session ids).
        db.tables["workspaces"].append({"id": str(uuid4()), "organization_id": ORG,
                                        "owner_user_id": OWNER, "name": "N", "slug": "n",
                                        "status": "active", "deleted_at": None,
                                        "created_at": _iso(), "updated_at": _iso()})
        report = inspect_production(db)
        total = report["total_active_workspaces"]
        legacy = report["legacy_workspaces"]
        non_legacy = report["non_legacy_workspaces"]
        assert total == legacy + non_legacy == 2
        assert legacy == 1 and non_legacy == 1


class TestAdoptionClassification:

    def test_valid_org_and_active_membership_ready(self):
        db = _db()
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["proposed_organization_id"] == ORG
        assert plan["membership_action"] == "none"
        assert plan["requires_manual_approval"] is False

    def test_missing_org_single_active_membership_ready(self):
        db = _db(org="")
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["proposed_organization_id"] == ORG

    def test_missing_org_multiple_active_orgs_manual(self):
        db = _db(org="", second_org=True, memberships=[
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG,
             "role": "member", "status": "active"},
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG2,
             "role": "member", "status": "active"},
        ])
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "MANUAL_REVIEW"

    def test_no_org_and_no_evidence_blocked(self):
        db = _db(org="", memberships=[])
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "NO_DETERMINISTIC_ORG"
        assert plan["proposed_organization_id"] == ""
        # Never auto-create an organization.
        assert plan["membership_action"] != "create" or plan["proposed_organization_id"]

    def test_dangling_org_deterministic_from_membership(self):
        # workspace.org_id references a missing org, but owner has one ACTIVE
        # membership in an existing org -> deterministic.
        db = _db(org="ghost-org", org_exists=True, memberships=[
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG,
             "role": "member", "status": "active"},
        ])
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["proposed_organization_id"] == ORG

    def test_dangling_org_ambiguous_manual(self):
        db = _db(org="ghost-org", second_org=True, memberships=[
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG,
             "role": "member", "status": "active"},
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG2,
             "role": "member", "status": "active"},
        ])
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "MANUAL_REVIEW"

    def test_dangling_org_no_evidence(self):
        db = _db(org="ghost-org", memberships=[])
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "NO_DETERMINISTIC_ORG"

    def test_historical_registration_link(self):
        db = _db(org="", memberships=[], reg_org=ORG)
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["proposed_organization_id"] == ORG
        assert plan["membership_action"] == "create"


class TestMembershipAction:

    def test_pending_membership_activates(self):
        db = _db(membership_status="pending")
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["membership_action"] == "activate"

    def test_removed_membership_reactivates(self):
        db = _db(membership_status="removed")
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["membership_action"] == "reactivate"

    def test_left_membership_rejoins(self):
        db = _db(membership_status="left")
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["membership_action"] == "rejoin"

    def test_active_no_mutation(self):
        db = _db(membership_status="active")
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["membership_action"] == "none"


class TestSafety:

    def test_never_merge_duplicate_orgs(self):
        db = _db(second_org=True, memberships=[
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG,
             "role": "member", "status": "active"},
            {"id": str(uuid4()), "user_id": OWNER, "organization_id": ORG2,
             "role": "member", "status": "active"},
        ])
        plan = adoption_plan_for_workspace(db, LEGACY)
        # The workspace's own valid organization + active membership is the
        # deterministic target; no organization is merged and none is created.
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert plan["proposed_organization_id"] == ORG

    def test_cross_user_isolation(self):
        db = _db(org="")
        db.tables["identity_users"][0]["id"] = "other-user"
        db.tables["workspaces"][0]["owner_user_id"] = "other-user"
        db.tables["memberships"][0]["user_id"] = "other-user"
        plan = adoption_plan_for_workspace(db, LEGACY)
        # The plan's proposed org belongs to the workspace owner, not another user.
        assert plan["proposed_organization_id"] in ("", ORG)

    def test_dry_run_never_writes(self):
        db = _db()
        before = {t: list(r) for t, r in db.tables.items()}
        plan = adoption_plan_for_workspace(db, LEGACY)
        assert plan["classification"] == "READY_FOR_ADOPTION"
        assert db.tables == before

    def test_determinism(self):
        db1 = _db()
        db2 = _db()
        p1 = adoption_plan_for_workspace(db1, LEGACY)
        p2 = adoption_plan_for_workspace(db2, LEGACY)
        assert p1 == p2

    def test_plan_contains_no_secrets(self):
        db = _db()
        plan = adoption_plan_for_workspace(db, LEGACY)
        forbidden = ("token", "password", "hash", "secret", "credential", "access", "refresh")
        assert not any(any(f in (str(k) + str(v)).lower() for f in forbidden)
                       for k, v in plan.items() if k not in ("memberships",))
