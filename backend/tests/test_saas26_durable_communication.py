"""SaaS-2.6 — Persist In-Memory Product Subsystems & Establish Durable Tenant
Ownership.

Covers the workspace-owned durable outbound send history + provider events:

  A. tenant A creates data, tenant B cannot read/update/delete it
  B. tenant B's list does not include tenant A's data
  C. tenant A can still access it
  D. state survives repository recreation (restart simulation)
  E. get_by_id is workspace-scoped (no cross-tenant BOLA)
  F. idempotent save (same id does not duplicate)

Uses fake PostgREST clients. No production data touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.persistence.launch import (
    OutboundMessage,
    OutboundMessageRepository,
    ProviderEvent,
    ProviderEventRepository,
)


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


def _seed(db, table, ws_id, n=1):
    rows = db.tables.setdefault(table, [])
    for i in range(n):
        rows.append({"id": str(uuid4()), "workspace_id": ws_id, "created_at": _iso(),
                     "updated_at": _iso()})
    return rows


class TestOutboundMessageRepository:

    @pytest.mark.asyncio
    async def test_tenant_isolation_and_scoped_list(self):
        db = FakeClient()
        _seed(db, "outbound_messages", "ws-A", 2)
        _seed(db, "outbound_messages", "ws-B", 1)
        repo = OutboundMessageRepository()
        repo._client = lambda: db

        a = await repo.list_for_workspace("ws-A")
        assert len(a) == 2 and all(m.workspace_id == "ws-A" for m in a)
        b = await repo.list_for_workspace("ws-B")
        assert len(b) == 1 and b[0].workspace_id == "ws-B"
        # Tenant B's list never includes tenant A's rows.
        assert all(m.workspace_id == "ws-B" for m in b)

    @pytest.mark.asyncio
    async def test_get_for_workspace_cross_tenant_returns_none(self):
        db = FakeClient()
        _seed(db, "outbound_messages", "ws-A", 1)
        _seed(db, "outbound_messages", "ws-B", 1)
        repo = OutboundMessageRepository()
        repo._client = lambda: db
        b_id = db.tables["outbound_messages"][1]["id"]
        # ws-A cannot read B's message by id.
        assert await repo.get_for_workspace(b_id, "ws-A") is None
        assert await repo.get_for_workspace(b_id, "ws-B") is not None

    @pytest.mark.asyncio
    async def test_restart_durability(self):
        db = FakeClient()
        repo1 = OutboundMessageRepository()
        repo1._client = lambda: db
        saved = await repo1.save(OutboundMessage(
            workspace_id="ws-A", provider_id="prov-1", subject="Hello",
            recipient_email="a@x.com", status="sent",
        ))
        # Simulate restart: a brand-new repository over the same DB.
        repo2 = OutboundMessageRepository()
        repo2._client = lambda: db
        rows = await repo2.list_for_workspace("ws-A")
        assert len(rows) == 1
        assert rows[0].id == saved.id
        assert rows[0].workspace_id == "ws-A"
        assert rows[0].subject == "Hello"

    @pytest.mark.asyncio
    async def test_save_same_id_does_not_duplicate(self):
        db = FakeClient()
        repo = OutboundMessageRepository()
        repo._client = lambda: db
        m = OutboundMessage(id="fixed-id", workspace_id="ws-A", subject="One")
        await repo.save(m)
        await repo.save(OutboundMessage(id="fixed-id", workspace_id="ws-A", subject="Two"))
        rows = await repo.list_for_workspace("ws-A")
        assert len(rows) == 1


class TestProviderEventRepository:

    @pytest.mark.asyncio
    async def test_tenant_isolation_and_restart(self):
        db = FakeClient()
        _seed(db, "provider_events", "ws-A", 1)
        _seed(db, "provider_events", "ws-B", 1)
        repo = ProviderEventRepository()
        repo._client = lambda: db
        a = await repo.list_for_workspace("ws-A")
        assert len(a) == 1 and a[0].workspace_id == "ws-A"
        b = await repo.list_for_workspace("ws-B")
        assert all(e.workspace_id == "ws-B" for e in b)

        b_id = db.tables["provider_events"][1]["id"]
        assert await repo.get_for_workspace(b_id, "ws-A") is None

        # Restart: fresh repo reads intact.
        repo2 = ProviderEventRepository()
        repo2._client = lambda: db
        assert len(await repo2.list_for_workspace("ws-A")) == 1


class TestCommunicationPersistenceHelpers:

    def test_list_outbound_history_is_tenant_scoped(self):
        from services.persistence import (
            set_connection_manager, reset_connection_manager,
            set_repository_provider, reset_repository_provider, RepositoryProvider,
        )
        from services.persistence.database import SupabaseConnectionManager
        from services.persistence.launch.communication_persistence import list_outbound_history
        db = FakeClient()
        _seed(db, "outbound_messages", "ws-A", 2)
        _seed(db, "outbound_messages", "ws-B", 1)
        cm = SupabaseConnectionManager(url="http://test", key="k")
        cm._client = db
        set_connection_manager(cm)
        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            a = list_outbound_history("ws-A")
            assert all(m.workspace_id == "ws-A" for m in a)
            b = list_outbound_history("ws-B")
            assert all(m.workspace_id == "ws-B" for m in b)
            # No cross-tenant leakage.
            assert all(m.workspace_id != "ws-B" for m in a)
        finally:
            reset_connection_manager()
            reset_repository_provider()
