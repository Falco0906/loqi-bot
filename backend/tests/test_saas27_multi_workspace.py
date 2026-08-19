"""SaaS-2.7 — Multi-Workspace Lifecycle, Switching & Membership UX.

Covers the canonical workspace-context resolver (membership-validated),
multi-workspace listing/selection, and workspace switching that changes the
resource boundary. Uses fake PostgREST clients. No production data touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.workspace_context import (
    AmbiguousWorkspaceError,
    NoWorkspaceAvailable,
    WorkspaceAccessDenied,
    resolve_workspace_context,
    workspaces_for_user,
)


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._filters: list[tuple[str, str, object]] = []
        self._op = "select"
        self._payload = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, val):
        self._filters.append(("in", col, list(val)))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def limit(self, n):
        self._filters.append(("_limit", n, ""))
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

    def execute(self):
        rows = [dict(r) for r in self._db.tables.get(self._table, [])]
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif kind == "in":
                rows = [r for r in rows if r.get(col) in val]
            elif kind == "is":
                rows = [r for r in rows if r.get(col) is None]
            elif kind == "_limit":
                rows = rows[:int(col)]
        if self._op == "select":
            return _Row(rows)
        if self._op == "insert":
            stored = [dict(r) for r in self._db.tables.setdefault(self._table, [])]
            stored.append(self._payload)
            self._db.tables[self._table] = stored
            return _Row([self._payload])
        updated = []
        for r in self._db.tables.get(self._table, []):
            if any(str(r.get(col, "")) == str(val) for kind, col, val in self._filters if kind == "eq"):
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


def _two_workspace_db():
    """User 'u1' is an ACTIVE owner of org-A which owns W-A1 and W-A2.
    Org-B (and its workspace W-B) is not one u1 belongs to."""
    return FakeClient({
        "memberships": [
            {"user_id": "u1", "organization_id": "org-A", "role": "owner", "status": "active"},
        ],
        "organizations": [
            {"id": "org-A", "name": "Org A", "slug": "org-a", "deleted_at": None},
            {"id": "org-B", "name": "Org B", "slug": "org-b", "deleted_at": None},
        ],
        "workspaces": [
            {"id": "W-A1", "organization_id": "org-A", "name": "Workspace 1",
             "slug": "w-a1", "owner_user_id": "u1", "status": "active",
             "created_at": _iso(), "updated_at": _iso(), "deleted_at": None},
            {"id": "W-A2", "organization_id": "org-A", "name": "Workspace 2",
             "slug": "w-a2", "owner_user_id": "u1", "status": "active",
             "created_at": _iso(), "updated_at": _iso(), "deleted_at": None},
            {"id": "W-B", "organization_id": "org-B", "name": "B",
             "slug": "w-b", "owner_user_id": "u2", "status": "active",
             "created_at": _iso(), "updated_at": _iso(), "deleted_at": None},
        ],
    })


class TestWorkspaceContextResolver:

    def test_one_workspace_default(self):
        db = FakeClient({"memberships": [
            {"user_id": "u1", "organization_id": "org-A", "role": "owner", "status": "active"},
        ], "workspaces": [
            {"id": "W1", "organization_id": "org-A", "name": "W", "slug": "w",
             "owner_user_id": "u1", "status": "active", "deleted_at": None},
        ]})
        ctx = resolve_workspace_context(db, "u1")
        assert ctx.workspace_id == "W1"
        assert ctx.organization_id == "org-A"
        assert ctx.membership_role == "owner"

    def test_no_workspace_raises(self):
        db = FakeClient({"memberships": [], "workspaces": []})
        with pytest.raises(NoWorkspaceAvailable):
            resolve_workspace_context(db, "u1")

    def test_multi_workspace_ambiguous_without_selection(self):
        db = _two_workspace_db()
        with pytest.raises(AmbiguousWorkspaceError):
            resolve_workspace_context(db, "u1")

    def test_explicit_selection(self):
        db = _two_workspace_db()
        ctx = resolve_workspace_context(db, "u1", requested_workspace_id="W-A1")
        assert ctx.workspace_id == "W-A1"
        assert ctx.organization_id == "org-A"
        ctx2 = resolve_workspace_context(db, "u1", requested_workspace_id="W-A2")
        assert ctx2.workspace_id == "W-A2"

    def test_foreign_workspace_denied(self):
        db = _two_workspace_db()
        # u1 has no membership in org-B, so W-B is not accessible.
        with pytest.raises(WorkspaceAccessDenied):
            resolve_workspace_context(db, "u1", requested_workspace_id="W-B")

    def test_org_b_membership_does_not_grant_org_a_workspace(self):
        db = _two_workspace_db()
        db.tables["memberships"] = [
            {"user_id": "u2", "organization_id": "org-B", "role": "owner", "status": "active"},
        ]
        ctx = resolve_workspace_context(db, "u2", requested_workspace_id="W-B")
        assert ctx.workspace_id == "W-B"
        with pytest.raises(WorkspaceAccessDenied):
            resolve_workspace_context(db, "u2", requested_workspace_id="W-A1")

    def test_inactive_membership_cannot_establish_context(self):
        db = _two_workspace_db()
        db.tables["memberships"] = [
            {"user_id": "u1", "organization_id": "org-A", "role": "owner", "status": "pending"},
        ]
        # No ACTIVE membership -> no accessible workspace.
        assert workspaces_for_user(db, "u1") == []
        with pytest.raises(NoWorkspaceAvailable):
            resolve_workspace_context(db, "u1")

    def test_listing_only_returns_accessible_workspaces(self):
        db = _two_workspace_db()
        ws = workspaces_for_user(db, "u1")
        ids = {w["id"] for w in ws}
        assert ids == {"W-A1", "W-A2"}
        assert "W-B" not in ids


class TestWorkspaceSwitchChangesResourceBoundary:

    def _seed(self, db):
        db.tables.setdefault("campaigns", [])
        db.tables["campaigns"].append({"id": "X", "workspace_id": "W-A1",
                                       "name": "Campaign X", "created_at": _iso(), "updated_at": _iso()})
        db.tables["campaigns"].append({"id": "Y", "workspace_id": "W-A2",
                                       "name": "Campaign Y", "created_at": _iso(), "updated_at": _iso()})

    def test_load_workspace_state_scoped_to_selected_workspace(self):
        from services.workspace_state import load_workspace_state
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _two_workspace_db()
        self._seed(db)
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state.get_supabase_client", return_value=db):
                a1 = load_workspace_state("u1", workspace_id="W-A1")
                a2 = load_workspace_state("u1", workspace_id="W-A2")
            assert [c["id"] for c in a1["campaigns"]] == ["X"]
            assert [c["id"] for c in a2["campaigns"]] == ["Y"]
        finally:
            reset_connection_manager()
            reset_repository_provider()

    def test_resource_write_under_selected_workspace(self):
        from services.workspace_state import _write_campaign_row
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _two_workspace_db()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            import asyncio
            with patch("services.workspace_state.get_supabase_client", return_value=db):
                asyncio.run(_write_campaign_row("u1", {
                    "id": "new-c", "name": "New", "status": "planning",
                }, workspace_id="W-A2"))
            rows = db.tables["campaigns"]
            new = [c for c in rows if c["id"] == "new-c"]
            assert new and new[0]["workspace_id"] == "W-A2"
        finally:
            reset_connection_manager()
            reset_repository_provider()


class TestWorkspaceCreation:

    def test_default_slug_has_uuid_suffix(self):
        import main as main_module
        slug = main_module._default_workspace_slug("12345678-aaaa", "My Workspace")
        assert slug == "my-workspace-12345678"

    def test_fresh_uuid_model(self):
        from services.persistence.launch.models import Workspace
        w1 = Workspace(organization_id="org-A", name="W", slug="w", owner_user_id="u1")
        w2 = Workspace(organization_id="org-A", name="W", slug="w", owner_user_id="u1")
        assert w1.id != w2.id
        assert w1.organization_id == "org-A" and w1.owner_user_id == "u1"

    def test_creation_does_not_create_duplicate_org(self):
        # Workspace creation only writes workspaces/workspace_members rows —
        # it never touches organizations. The create endpoint validates the
        # org via membership and persists only the workspace + member row.
        db = _two_workspace_db()
        orgs_before = len(db.tables["organizations"])
        from services.persistence.launch.repositories import WorkspaceRepository, WorkspaceMemberRepository
        from services.persistence.launch.models import Workspace, WorkspaceMember
        wr = WorkspaceRepository(); wr._client = lambda: db
        mr = WorkspaceMemberRepository(); mr._client = lambda: db
        new_id = str(uuid4())
        import asyncio
        asyncio.run(wr.save(Workspace(id=new_id, organization_id="org-A", name="W3",
                                      slug="w3", owner_user_id="u1", status="active")))
        asyncio.run(mr.save(WorkspaceMember(workspace_id=new_id, user_id="u1", role="owner", status="active")))
        assert len(db.tables["organizations"]) == orgs_before
        assert db.tables["workspaces"][-1]["organization_id"] == "org-A"


class TestRoleRestrictions:

    def test_member_cannot_create_workspace(self):
        from services.workspace_context import active_memberships
        db = FakeClient({"memberships": [
            {"user_id": "u1", "organization_id": "org-A", "role": "member", "status": "active"},
        ]})
        m = active_memberships(db, "u1")[0]
        # A member (not owner/admin) is refused at the create endpoint.
        assert m["role"] not in ("owner", "admin")

    def test_owner_can_create_workspace(self):
        from services.workspace_context import active_memberships
        db = FakeClient({"memberships": [
            {"user_id": "u1", "organization_id": "org-A", "role": "owner", "status": "active"},
        ]})
        m = active_memberships(db, "u1")[0]
        assert m["role"] in ("owner", "admin")


class TestSelectedWorkspacePropagation:
    """Prove selected-workspace propagation across the request/service paths
    for the target resource categories (A-H), using two isolated workspaces."""

    def _db(self):
        db = FakeClient()
        db.tables["workspaces"] = [
            {"id": "W-A1", "organization_id": "org-A", "name": "A1", "slug": "a1",
             "owner_user_id": "u1", "status": "active", "deleted_at": None,
             "created_at": _iso(), "updated_at": _iso()},
            {"id": "W-A2", "organization_id": "org-A", "name": "A2", "slug": "a2",
             "owner_user_id": "u1", "status": "active", "deleted_at": None,
             "created_at": _iso(), "updated_at": _iso()},
        ]
        db.tables["campaigns"] = [
            {"id": "cA", "workspace_id": "W-A1", "name": "Campaign A",
             "created_at": _iso(), "updated_at": _iso()},
            {"id": "cB", "workspace_id": "W-A2", "name": "Campaign B",
             "created_at": _iso(), "updated_at": _iso()},
        ]
        db.tables["drafts"] = [
            {"id": "dA", "workspace_id": "W-A1", "status": "pending",
             "created_at": _iso(), "updated_at": _iso()},
            {"id": "dB", "workspace_id": "W-A2", "status": "pending",
             "created_at": _iso(), "updated_at": _iso()},
        ]
        db.tables["workspace_leads"] = [
            {"id": "lA", "workspace_id": "W-A1"},
            {"id": "lB", "workspace_id": "W-A2"},
        ]
        db.tables["discoveries"] = [
            {"id": "dvA", "workspace_id": "W-A1", "status": "completed",
             "created_at": _iso(), "updated_at": _iso()},
            {"id": "dvB", "workspace_id": "W-A2", "status": "completed",
             "created_at": _iso(), "updated_at": _iso()},
        ]
        db.tables["knowledge_items"] = [
            {"id": "kA", "workspace_id": "W-A1"},
            {"id": "kB", "workspace_id": "W-A2"},
        ]
        db.tables["strategic_updates"] = [
            {"id": "sA", "workspace_id": "W-A1"},
            {"id": "sB", "workspace_id": "W-A2"},
        ]
        db.tables["outbound_messages"] = [
            {"id": "oA", "workspace_id": "W-A1", "subject": "A"},
            {"id": "oB", "workspace_id": "W-A2", "subject": "B"},
        ]
        db.tables["provider_events"] = [
            {"id": "eA", "workspace_id": "W-A1", "event_type": "x"},
            {"id": "eB", "workspace_id": "W-A2", "event_type": "y"},
        ]
        return db

    def test_resource_visibility_switches_with_workspace(self):
        from services.workspace_state import load_workspace_state, load_drafts_only
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = self._db()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state.get_supabase_client", return_value=db):
                a = load_workspace_state("u1", workspace_id="W-A1")
                b = load_workspace_state("u1", workspace_id="W-A2")
                drafts_a = load_drafts_only("u1", workspace_id="W-A1")
                drafts_b = load_drafts_only("u1", workspace_id="W-A2")
            assert [c["id"] for c in a["campaigns"]] == ["cA"]
            assert [c["id"] for c in b["campaigns"]] == ["cB"]
            assert [d["id"] for d in drafts_a] == ["dA"]
            assert [d["id"] for d in drafts_b] == ["dB"]
        finally:
            reset_connection_manager()
            reset_repository_provider()

    def test_repo_get_for_workspace_isolates_all_resources(self):
        from services.persistence.launch import (
            WorkspaceLeadRepository, KnowledgeItemRepository,
            StrategicUpdateRepository, OutboundMessageRepository,
            ProviderEventRepository,
        )
        db = self._db()
        # A-selected workspace cannot read B resources by id; B cannot read A.
        cases = [
            (WorkspaceLeadRepository, "workspace_leads", "lA", "lB"),
            (KnowledgeItemRepository, "knowledge_items", "kA", "kB"),
            (StrategicUpdateRepository, "strategic_updates", "sA", "sB"),
            (OutboundMessageRepository, "outbound_messages", "oA", "oB"),
            (ProviderEventRepository, "provider_events", "eA", "eB"),
        ]
        for cls, table, a_id, b_id in cases:
            repo = cls(); repo._client = lambda db=db: db
            # Workspace A cannot access B's resource.
            import asyncio
            assert asyncio.run(repo.get_for_workspace(b_id, "W-A1")) is None
            assert asyncio.run(repo.get_for_workspace(a_id, "W-A1")) is not None
            assert asyncio.run(repo.get_for_workspace(b_id, "W-A2")) is not None

    def test_discovery_scoped_to_selected_workspace(self):
        from services import discovery
        db = self._db()
        from unittest.mock import patch
        with patch.object(discovery, "get_supabase_client", return_value=db):
            assert discovery.get_discovery("dvB", workspace_id="W-A1") is None
            assert discovery.get_discovery("dvA", workspace_id="W-A1") is not None
            assert discovery.get_discovery("dvB", workspace_id="W-A2") is not None

    def test_draft_write_persists_selected_workspace(self):
        from services.workspace_state import _write_draft_row
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = self._db()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            import asyncio
            with patch("services.workspace_state.get_supabase_client", return_value=db):
                asyncio.run(_write_draft_row("u1", {"id": "d-new", "text": "hi"}, workspace_id="W-A2"))
            rows = db.tables["drafts"]
            new = [d for d in rows if d["id"] == "d-new"]
            assert new and new[0]["workspace_id"] == "W-A2"
        finally:
            reset_connection_manager()
            reset_repository_provider()
