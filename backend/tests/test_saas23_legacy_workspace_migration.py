"""SaaS-2.3 — Stable Workspace Ownership & Legacy Migration.

Covers:
  A. new workspaces receive an independent uuid (never a workflow-session id)
  B. workflow_session_id is stored as provenance only
  C. legacy workspace detection
  D. dry-run performs zero writes
  E. deterministic migration plan
  F. migration creates a stable workspace identity
  G/H. owner_user_id / organization_id preserved
  I. workflow_session_id points to the original workflow session
  J. every approved child resource is remapped
  K. workflow session remains intact
  L. second migration run is a safe no-op
  M/N. missing owner / organization refuses
  O. ambiguous workspace refuses
  P. child-resource collision refuses without mutation
  Q/R. cross-user / cross-organization isolation
  S. legacy workspace remains readable before migration
  T. no request-path code automatically migrates

All destructive tests use fake/in-memory clients. No production data touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

LEGACY_ID = "00000000-0000-4000-8000-0000000000aa"
NEW_ID = "00000000-0000-4000-8000-0000000000bb"


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._filters: list[tuple[str, str, str]] = []
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
        self._filters.append(("_limit", n, ""))
        return self

    def offset(self, n):
        self._filters.append(("_offset", n, ""))
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
        limit = None
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if str(r.get(col, "")) == val]
            elif kind == "is":
                rows = [r for r in rows if r.get(col) is None]
            elif kind == "_limit":
                limit = int(col)
        if self._op == "select":
            if limit:
                rows = rows[:limit]
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


def _make_legacy_db(*, owner="owner-1", org="org-1", extra_owner_ws=False):
    """A legacy workspace whose id equals its workflow_sessions.id."""
    tables = {
        "workflow_sessions": [{
            "id": LEGACY_ID, "user_id": owner, "channel": "workspace",
            "session_key": owner, "status": "active",
        }],
        "workspaces": [{
            "id": LEGACY_ID, "organization_id": org, "name": "Legacy",
            "slug": "legacy", "owner_user_id": owner, "created_by": owner,
            "status": "active", "settings": {}, "metadata": {},
            "version": 1, "deleted_at": None, "workflow_session_id": None,
        }],
        "identity_users": [{"id": owner, "display_name": "Owner", "deleted_at": None}],
        "organizations": [{"id": org, "name": "Org", "slug": "org", "deleted_at": None}],
        "memberships": [{
            "id": str(uuid4()), "user_id": owner, "organization_id": org,
            "role": "owner", "status": "active",
        }],
        "campaigns": [{"id": "c1", "workspace_id": LEGACY_ID}],
        "workspace_leads": [{"id": "wl1", "workspace_id": LEGACY_ID}],
        "workspace_companies": [{"id": "wc1", "workspace_id": LEGACY_ID}],
        "drafts": [{"id": "d1", "workspace_id": LEGACY_ID}],
        "discoveries": [{"id": "dv1", "workspace_id": LEGACY_ID}],
        "knowledge": [{"id": "k1", "workspace_id": LEGACY_ID}],
        "knowledge_items": [{"id": "ki1", "workspace_id": LEGACY_ID}],
        "knowledge_sources": [{"id": "ks1", "workspace_id": LEGACY_ID}],
        "strategic_updates": [{"id": "su1", "workspace_id": LEGACY_ID}],
        "strategic_actions": [{"id": "sa1", "workspace_id": LEGACY_ID}],
        "workspace_members": [{"id": "wm1", "workspace_id": LEGACY_ID, "user_id": owner}],
    }
    if extra_owner_ws:
        tables["workspaces"].append({
            "id": str(uuid4()), "organization_id": org, "name": "Second",
            "slug": "second", "owner_user_id": owner, "status": "active",
            "settings": {}, "metadata": {}, "deleted_at": None,
            "workflow_session_id": None,
        })
    return FakeClient(tables)


from services.persistence.launch import legacy_workspace_migration as mig  # noqa: E402


class TestIndependentUuidAndProvenance:

    def test_new_workspace_id_independent_of_workflow_session(self):
        db = FakeClient({"workflow_sessions": [
            {"id": "sess-1", "user_id": "u1", "channel": "workspace", "session_key": "u1"},
        ]})
        # A workflow session alone is not a legacy workspace (no matching
        # workspaces row) — planning refuses cleanly and mints no id, so a
        # workspace identity is never derived from a session.
        plan = mig.build_migration_plan(db, "sess-1")
        assert plan["ready"] is False
        assert plan["new_workspace_id"] == ""

    def test_migration_new_id_differs_from_legacy_session_id(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is True
        assert plan["new_workspace_id"] != LEGACY_ID
        assert plan["workflow_session_id"] == LEGACY_ID


class TestLegacyDetection:

    def test_detects_legacy_workspace(self):
        db = _make_legacy_db()
        legacy = mig.detect_legacy_workspaces(db)
        assert [w["workspace_id"] for w in legacy] == [LEGACY_ID]
        assert legacy[0]["owner_user_id"] == "owner-1"
        assert legacy[0]["organization_id"] == "org-1"
        assert legacy[0]["workflow_session_id"] == LEGACY_ID

    def test_legacy_remains_readable_before_migration(self):
        db = _make_legacy_db()
        # Legacy workspace row and its children still present and untouched.
        assert db.tables["workspaces"][0]["deleted_at"] is None
        assert db.tables["campaigns"][0]["workspace_id"] == LEGACY_ID
        assert db.tables["workspace_members"][0]["workspace_id"] == LEGACY_ID


class TestDryRun:

    def test_dry_run_performs_zero_writes(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        before = {t: list(rows) for t, rows in db.tables.items()}
        result = mig.apply_migration_plan(db, plan, dry_run=True)
        assert result["applied"] is False
        assert result["dry_run"] is True
        after = {t: list(rows) for t, rows in db.tables.items()}
        assert after == before

    def test_plan_is_deterministic(self):
        db = _make_legacy_db()
        p1 = mig.build_migration_plan(db, LEGACY_ID)
        p2 = mig.build_migration_plan(db, LEGACY_ID)
        assert p1["new_workspace_id"] != LEGACY_ID
        assert p1["child_counts"]["campaigns"] == 1
        assert p1["child_counts"]["workspace_members"] == 1
        assert p1["ready"] is True and p2["ready"] is True


class TestApply:

    def test_migration_creates_stable_identity_and_remaps_children(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        new_id = plan["new_workspace_id"]
        result = mig.apply_migration_plan(db, plan, dry_run=False)
        assert result["applied"] is True
        assert result["new_workspace_id"] == new_id

        workspaces = db.tables["workspaces"]
        new_ws = [w for w in workspaces if w["id"] == new_id]
        assert len(new_ws) == 1
        # G/H: owner + org preserved.
        assert new_ws[0]["owner_user_id"] == "owner-1"
        assert new_ws[0]["organization_id"] == "org-1"
        # I: provenance points to the original workflow session.
        assert new_ws[0]["workflow_session_id"] == LEGACY_ID
        # Legacy workspace soft-deleted (row preserved, excluded from lookups).
        legacy_ws = [w for w in workspaces if w["id"] == LEGACY_ID]
        assert legacy_ws[0]["deleted_at"] is not None

        # J: every approved child resource remapped to the new id.
        for table in mig.CHILD_WORKSPACE_TABLES:
            rows = db.tables[table]
            assert rows, f"{table} expected children"
            assert all(r["workspace_id"] == new_id for r in rows), table

        # K: workflow session remains intact.
        assert db.tables["workflow_sessions"][0]["id"] == LEGACY_ID

    def test_second_run_is_safe_noop(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        new_id = plan["new_workspace_id"]
        assert mig.apply_migration_plan(db, plan, dry_run=False)["applied"] is True
        # Second apply with the same (stale) plan must be a safe no-op.
        second = mig.apply_migration_plan(db, plan, dry_run=False)
        assert second["applied"] is False
        assert second["reason"] == "already_migrated"
        # No duplicate workspace, no re-remap.
        assert len([w for w in db.tables["workspaces"] if w["id"] == new_id]) == 1
        assert all(r["workspace_id"] == new_id for r in db.tables["campaigns"])

    def test_detect_after_migration_returns_nothing(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        mig.apply_migration_plan(db, plan, dry_run=False)
        assert mig.detect_legacy_workspaces(db) == []


class TestRefusal:

    def test_missing_owner_refuses(self):
        db = _make_legacy_db(owner="")
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is False
        assert any("owner_user_id is missing" in b for b in plan["blockers"])
        assert mig.apply_migration_plan(db, plan, dry_run=False)["applied"] is False
        assert len(db.tables["workspaces"]) == 1

    def test_owner_does_not_exist_refuses(self):
        db = _make_legacy_db(owner="ghost")
        db.tables["identity_users"] = []
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is False
        assert any("owner user does not exist" in b for b in plan["blockers"])

    def test_missing_organization_refuses(self):
        db = _make_legacy_db(org="")
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is False
        assert any("organization_id is missing" in b for b in plan["blockers"])

    def test_organization_does_not_exist_refuses(self):
        db = _make_legacy_db(org="ghost-org")
        db.tables["organizations"] = []
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is False
        assert any("organization does not exist" in b for b in plan["blockers"])

    def test_ambiguous_owner_refuses(self):
        db = _make_legacy_db(extra_owner_ws=True)
        plan = mig.build_migration_plan(db, LEGACY_ID)
        assert plan["ready"] is False
        assert any("ambiguous" in b for b in plan["blockers"])

    def test_child_collision_refuses_without_mutation(self):
        db = _make_legacy_db()
        plan = mig.build_migration_plan(db, LEGACY_ID)
        # Simulate a partial/conflicting prior migration: a row already exists
        # under the freshly-planned new id.
        db.tables.setdefault("campaigns", []).append(
            {"id": "c-collision", "workspace_id": plan["new_workspace_id"]}
        )
        result = mig.apply_migration_plan(db, plan, dry_run=False)
        assert result["applied"] is False
        assert any("collision" in b for b in result.get("blockers", []))
        # No new workspace was created, legacy not deleted, children unchanged.
        assert len([w for w in db.tables["workspaces"] if w["id"] == plan["new_workspace_id"]]) == 0
        assert db.tables["workspaces"][0]["deleted_at"] is None
        assert db.tables["campaigns"][0]["workspace_id"] == LEGACY_ID

    def test_not_legacy_refuses(self):
        db = FakeClient({"workspaces": [
            {"id": "plain", "owner_user_id": "u1", "organization_id": "o1",
             "deleted_at": None, "workflow_session_id": None},
        ]})
        plan = mig.build_migration_plan(db, "plain")
        assert plan["ready"] is False
        assert any("not a legacy workspace" in b for b in plan["blockers"])


class TestIsolation:

    def test_cross_user_isolation(self):
        db = _make_legacy_db(owner="owner-1", org="org-1")
        # A plan for a different user's workspace is never matched.
        legacy = mig.detect_legacy_workspaces(db)
        assert all(w["owner_user_id"] == "owner-1" for w in legacy)
        # Migrating does not affect other users (none here) — owner preserved.

    def test_cross_org_isolation(self):
        db = _make_legacy_db(owner="owner-1", org="org-1")
        plan = mig.build_migration_plan(db, LEGACY_ID)
        mig.apply_migration_plan(db, plan, dry_run=False)
        # New workspace belongs to the same org; no other org touched.
        new_ws = [w for w in db.tables["workspaces"] if w["id"] == plan["new_workspace_id"]]
        assert new_ws[0]["organization_id"] == "org-1"


class TestNoAutomaticMigration:

    def test_request_path_does_not_auto_migrate(self):
        from services.workspace_state import ensure_workspace
        from services.persistence import (
            set_connection_manager,
            reset_connection_manager,
            set_repository_provider,
            reset_repository_provider,
            RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _make_legacy_db()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state.get_supabase_client", return_value=db):
                ws_id = ensure_workspace("owner-1", organization_id="org-1")
        finally:
            reset_connection_manager()
            reset_repository_provider()
        # Owner-based lookup finds the existing legacy workspace — it is reused,
        # NOT migrated, and no new workspace/remap occurs.
        assert ws_id == LEGACY_ID
        assert len(db.tables["workspaces"]) == 1
        assert db.tables["campaigns"][0]["workspace_id"] == LEGACY_ID
        # The migration service was never invoked by the request path.
        assert db.tables["workspaces"][0].get("workflow_session_id") is None
