"""SaaS-2.4 — Resource-by-Resource Tenant Scoping.

Verifies the central security invariant: a request authenticated as user U may
only access resources belonging to a workspace/organization U is authorized
for, and a client-supplied workspace/organization/owner id never grants access.

Uses two independent users/workspaces/organizations and tests the fixed
cross-tenant (BOLA/IDOR) vectors at the repository and service level, plus the
Gmail OAuth state-binding fix at the HTTP boundary.

All destructive tests use fake/in-memory clients. No production data touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.persistence.launch import (
    Campaign,
    CampaignRepository,
    Draft,
    DraftRepository,
    KnowledgeItem,
    KnowledgeItemRepository,
    KnowledgeSource,
    KnowledgeSourceRepository,
    StrategicAction,
    StrategicActionRepository,
    StrategicUpdate,
    StrategicUpdateRepository,
    WorkspaceLead,
    WorkspaceLeadRepository,
)


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


def _seed_two_tenants():
    """Two independent workspaces/organizations with one campaign each."""
    return FakeClient({
        "campaigns": [
            {"id": "campaign-A", "workspace_id": "ws-A", "organization_id": "org-A",
             "name": "A's Campaign", "status": "running", "created_at": _iso(),
             "updated_at": _iso()},
            {"id": "campaign-B", "workspace_id": "ws-B", "organization_id": "org-B",
             "name": "B's Campaign", "status": "running", "created_at": _iso(),
             "updated_at": _iso()},
        ],
        "drafts": [
            {"id": "draft-A", "workspace_id": "ws-A", "status": "pending",
             "created_at": _iso(), "updated_at": _iso()},
            {"id": "draft-B", "workspace_id": "ws-B", "status": "pending",
             "created_at": _iso(), "updated_at": _iso()},
        ],
        "workspace_leads": [
            {"id": "lead-A", "workspace_id": "ws-A"},
            {"id": "lead-B", "workspace_id": "ws-B"},
        ],
        "knowledge_items": [
            {"id": "ki-A", "workspace_id": "ws-A"},
            {"id": "ki-B", "workspace_id": "ws-B"},
        ],
        "knowledge_sources": [
            {"id": "ks-A", "workspace_id": "ws-A"},
            {"id": "ks-B", "workspace_id": "ws-B"},
        ],
        "strategic_updates": [
            {"id": "su-A", "workspace_id": "ws-A"},
            {"id": "su-B", "workspace_id": "ws-B"},
        ],
        "strategic_actions": [
            {"id": "sa-A", "workspace_id": "ws-A", "strategic_update_id": "su-A"},
            {"id": "sa-B", "workspace_id": "ws-B", "strategic_update_id": "su-B"},
        ],
    })


# ─── Repository-level tenant-scoped lookups (Part 8/11) ─────────────────

class TestRepositoryScoping:

    def _repos(self, db):
        return {
            CampaignRepository: CampaignRepository(),
            DraftRepository: DraftRepository(),
            WorkspaceLeadRepository: WorkspaceLeadRepository(),
            KnowledgeItemRepository: KnowledgeItemRepository(),
            KnowledgeSourceRepository: KnowledgeSourceRepository(),
            StrategicUpdateRepository: StrategicUpdateRepository(),
            StrategicActionRepository: StrategicActionRepository(),
        }

    @pytest.mark.asyncio
    async def test_get_for_workspace_is_tenant_scoped(self):
        db = _seed_two_tenants()
        for repo in self._repos(db).values():
            repo._client = lambda db=db: db

        # A user in workspace A cannot fetch B's resource by id; returns None.
        cr = CampaignRepository(); cr._client = lambda: db
        assert await cr.get_for_workspace("campaign-B", "ws-A") is None
        assert (await cr.get_for_workspace("campaign-A", "ws-A")) is not None

        dr = DraftRepository(); dr._client = lambda: db
        assert await dr.get_for_workspace("draft-B", "ws-A") is None
        assert (await dr.get_for_workspace("draft-A", "ws-A")) is not None

        wl = WorkspaceLeadRepository(); wl._client = lambda: db
        assert await wl.get_for_workspace("lead-B", "ws-A") is None
        assert (await wl.get_for_workspace("lead-A", "ws-A")) is not None

        ki = KnowledgeItemRepository(); ki._client = lambda: db
        assert await ki.get_for_workspace("ki-B", "ws-A") is None
        assert (await ki.get_for_workspace("ki-A", "ws-A")) is not None

        ks = KnowledgeSourceRepository(); ks._client = lambda: db
        assert await ks.get_for_workspace("ks-B", "ws-A") is None

        su = StrategicUpdateRepository(); su._client = lambda: db
        assert await su.get_for_workspace("su-B", "ws-A") is None
        assert (await su.get_for_workspace("su-A", "ws-A")) is not None

        sa = StrategicActionRepository(); sa._client = lambda: db
        assert await sa.get_for_workspace("sa-B", "ws-A") is None
        assert (await sa.get_for_workspace("sa-A", "ws-A")) is not None


# ─── Cross-tenant campaign duplicate (highest-severity IDOR) ────────────

class TestDuplicateCampaignScoping:

    @pytest.mark.asyncio
    async def test_foreign_campaign_cannot_be_duplicated(self):
        from services.workspace_state import duplicate_campaign
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _seed_two_tenants()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            # user B resolves to workspace ws-B; A's campaign is in ws-A.
            with patch("services.workspace_state._async_workspace", return_value="ws-B"), \
                 patch("services.workspace_state.get_supabase_client", return_value=db):
                result = await duplicate_campaign("user-B", "campaign-A")
            assert result is None
            # No copy was created.
            assert len(db.tables["campaigns"]) == 2
        finally:
            reset_connection_manager()
            reset_repository_provider()

    @pytest.mark.asyncio
    async def test_own_campaign_can_be_duplicated(self):
        from services.workspace_state import duplicate_campaign
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _seed_two_tenants()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state._async_workspace", return_value="ws-A"), \
                 patch("services.workspace_state.get_supabase_client", return_value=db):
                result = await duplicate_campaign("user-A", "campaign-A")
            assert result is not None
            assert len(db.tables["campaigns"]) == 3
            copy = [c for c in db.tables["campaigns"] if c["id"] == result["id"]]
            assert copy and copy[0]["workspace_id"] == "ws-A"
        finally:
            reset_connection_manager()
            reset_repository_provider()


# ─── Cross-tenant campaign/draft update (defense in depth) ──────────────

class TestUpdateScoping:

    @pytest.mark.asyncio
    async def test_foreign_campaign_update_is_noop(self):
        from services.workspace_state import _update_campaign_row
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _seed_two_tenants()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state._async_workspace", return_value="ws-B"), \
                 patch("services.workspace_state.get_supabase_client", return_value=db):
                await _update_campaign_row("user-B", "campaign-A", {"name": "Hijacked"})
            row = [c for c in db.tables["campaigns"] if c["id"] == "campaign-A"][0]
            assert row["name"] == "A's Campaign"
        finally:
            reset_connection_manager()
            reset_repository_provider()

    @pytest.mark.asyncio
    async def test_foreign_draft_update_is_noop(self):
        from services.workspace_state import _update_draft_row
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        db = _seed_two_tenants()
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            from unittest.mock import patch
            with patch("services.workspace_state._async_workspace", return_value="ws-B"), \
                 patch("services.workspace_state.get_supabase_client", return_value=db):
                await _update_draft_row("user-B", "draft-A", {"status": "approved"})
            row = [d for d in db.tables["drafts"] if d["id"] == "draft-A"][0]
            assert row["status"] == "pending"
        finally:
            reset_connection_manager()
            reset_repository_provider()


# ─── Gmail OAuth state binding (Part 12) ────────────────────────────────

class TestGmailOAuthStateBinding:

    def test_gmail_url_requires_auth(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as client:
            # No auth and no valid session token -> 401 (cannot mint state for
            # an arbitrary id).
            r = client.get("/api/auth/gmail/url")
            assert r.status_code == 401
            # A bare client-supplied id as session_token that does not resolve
            # to a real web session is rejected (credential-planting guard).
            r2 = client.get("/api/auth/gmail/url", params={"session_token": "some-victim-id"})
            assert r2.status_code == 401


# ─── Cross-workspace / cross-org isolation (Part 9) ─────────────────────

class TestIsolation:

    @pytest.mark.asyncio
    async def test_workspace_a_membership_does_not_grant_workspace_b(self):
        db = _seed_two_tenants()
        cr = CampaignRepository(); cr._client = lambda: db
        # A workspace-A user cannot read B's campaign by id.
        assert await cr.get_for_workspace("campaign-B", "ws-A") is None

    @pytest.mark.asyncio
    async def test_list_scoped_to_workspace(self):
        db = _seed_two_tenants()
        cr = CampaignRepository(); cr._client = lambda: db
        rows = await cr.list_for_workspace("ws-A")
        assert [c.id for c in rows] == ["campaign-A"]
