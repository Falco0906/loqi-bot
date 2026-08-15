"""PR5 — Knowledge Foundation: backend regression suite.

Covers:
  1. create Knowledge
  2. read Knowledge
  3. update Knowledge (+ audit trail)
  4. delete/archive Knowledge (soft delete)
  5. list/filter by category + search
  6. ownership isolation (User A cannot see User B)
  7. persistence across backend restart (fresh client + fresh repos)
  8. source metadata/provenance
  9. retrieval/context function (get_knowledge_context)
 10. empty Knowledge state
 11. API validation (bad category, empty/oversized title, unknown id)
 12. audit events recorded for create/update/archive

Persistence is exercised against the real LaunchRepository stack with an
in-memory Supabase client standing in for Postgres; rows survive a simulated
process restart because each restart creates a brand-new connection manager,
repo instances and service instance over the same underlying rows.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.persistence import (
    RepositoryProvider,
    reset_connection_manager,
    set_connection_manager,
)
from services.persistence.database import SupabaseConnectionManager
from services.knowledge.service import KnowledgeService, get_knowledge_context

import main as main_module  # noqa: E402


# ─── In-memory Supabase client (chainable query builder over row dicts) ──

class _Result:
    def __init__(self, data):
        self.data = list(data)


class _FakeQuery:
    def __init__(self, client, table):
        self._client = client
        self._table = table
        self._cols = "*"
        self._wheres = []
        self._limit = None
        self._order = None
        self._op = "select"
        self._payload = None

    def select(self, cols="*"):
        self._cols = cols
        return self

    def eq(self, col, val):
        self._wheres.append((col, val))
        return self

    def in_(self, col, vals):
        self._wheres.append((col, list(vals)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = dict(row)
        return self

    def update(self, row):
        self._op = "update"
        self._payload = dict(row)
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matches(self, row):
        for col, val in self._wheres:
            if row.get(col) != val:
                return False
        return True

    def _apply(self, rows):
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._cols != "*":
            cols = [c.strip() for c in self._cols.split(",")]
            rows = [{c: r.get(c) for c in cols} for r in rows]
        return rows

    def execute(self):
        store = self._client._store.setdefault(self._table, [])
        if self._op == "select":
            return _Result(self._apply([r for r in store if self._matches(r)]))
        if self._op == "insert":
            store.append(dict(self._payload))
            return _Result([dict(self._payload)])
        if self._op == "update":
            updated = [r for r in store if self._matches(r)]
            for r in updated:
                r.update(self._payload)
            return _Result([dict(r) for r in updated])
        if self._op == "delete":
            removed = [r for r in store if self._matches(r)]
            self._client._store[self._table] = [r for r in store if not self._matches(r)]
            return _Result(removed)
        return _Result([])


class FakeSupabaseClient:
    def __init__(self, store=None):
        self._store = store if store is not None else {}

    def table(self, name):
        return _FakeQuery(self, name)


# ─── Fixtures ───────────────────────────────────────────────────────────

OWNER_WS = {"user-1": "ws-k1", "user-2": "ws-k2", "user-3": "ws-k3", "user-4": "ws-k4"}


def _fake_owner(owner_id: str):
    async def fake_owner(request, session_token: str) -> str:
        return owner_id

    return fake_owner


async def _fake_workspace(user_id: str) -> str | None:
    return OWNER_WS.get(user_id)


@pytest.fixture(autouse=True)
def _reset_persistence():
    reset_connection_manager()
    yield
    reset_connection_manager()


@pytest.fixture
def db(monkeypatch):
    """Wires a fresh in-memory Supabase client into the connection manager."""
    store: dict[str, list[dict]] = {}

    def _install(client_store: dict | None = None):
        client = FakeSupabaseClient(client_store if client_store is not None else store)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)
        return client

    _install(store)
    return store


@pytest.fixture
def auth(monkeypatch, db):
    """Resolves session ownership for route-level tests."""
    monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("user-1"))
    monkeypatch.setattr(
        "services.workspace_state._async_workspace", _fake_workspace)
    return {"owner": "user-1", "workspace": "ws-k1"}


@pytest.fixture
def svc():
    return KnowledgeService()


async def _r(route, *args, **kwargs):
    return await route(*args, **kwargs)


class TestCreateRead:
    async def test_1_create_item_returns_persisted_dict(self, db, auth, svc):
        item = await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="company", title="Loqi Positioning",
            summary="AI-native outbound OS",
            content={"products": ["Outbound engine"], "positioning": "AI-native"},
            tags=["ai", "outbound"],
        )
        assert item["id"]
        assert item["category"] == "company"
        assert item["title"] == "Loqi Positioning"
        assert item["source_type"] == "user_input"
        assert item["created_by"] == "user-1"
        assert item["created_at"] is not None
        assert item["updated_at"] is not None
        assert db["knowledge_items"], "item must be written to the durable store"

    async def test_2_read_item_by_id(self, db, auth, svc):
        created = await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="icp", title="Target: Series A growth teams",
            content={"roles": ["Head of Growth"], "sizes": ["10-50 employees"]},
        )
        fetched = await svc.get_item("ws-k1", created["id"])
        assert fetched == created

    async def test_2b_read_unknown_id_returns_none(self, db, auth, svc):
        assert await svc.get_item("ws-k1", "missing") is None


class TestUpdateArchive:
    async def test_3_update_item_fields_and_audit(self, db, auth, svc):
        created = await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="messaging", title="Tone",
            content={"tone": "direct"},
        )
        updated = await svc.update_item(
            owner_id="user-1", workspace_id="ws-k1", item_id=created["id"],
            title="Tone of voice", content={"tone": "direct, confident"},
            tags=["tone"],
        )
        assert updated["title"] == "Tone of voice"
        assert updated["content"]["tone"] == "direct, confident"
        assert updated["tags"] == ["tone"]
        assert updated["updated_at"] != created["updated_at"]

        actions = [a["action"] for a in db["audit_log"]]
        assert "knowledge_item.create" in actions
        assert "knowledge_item.update" in actions

    async def test_4_archive_is_soft_delete(self, db, auth, svc):
        created = await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="sales_offer", title="Pricing",
            content={"pricing": "$99/mo"},
        )
        archived = await svc.archive_item("user-1", "ws-k1", created["id"])
        assert archived is not None

        items = await svc.list_items("ws-k1")
        assert created["id"] not in [i["id"] for i in items]

        row = next(r for r in db["knowledge_items"] if r["id"] == created["id"])
        assert row["deleted_at"] is not None
        actions = [a["action"] for a in db["audit_log"]]
        assert "knowledge_item.archive" in actions

    async def test_4b_archive_unknown_returns_none(self, db, auth, svc):
        assert await svc.archive_item("user-1", "ws-k1", "missing") is None

    async def test_3b_update_unknown_returns_none(self, db, auth, svc):
        assert await svc.update_item(owner_id="user-1", workspace_id="ws-k1",
                                     item_id="missing", title="X") is None


class TestListFilter:
    async def _seed(self, svc):
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="company", title="About Loqi",
                              summary="Outbound OS", tags=["ai"])
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="icp", title="ICP",
                              content={"roles": ["CTO"]})
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="messaging", title="Angle",
                              summary="Value prop angle")

    async def test_5_list_by_category(self, db, auth, svc):
        await self._seed(svc)
        company = await svc.list_items("ws-k1", category="company")
        assert len(company) == 1
        assert company[0]["title"] == "About Loqi"

    async def test_5b_list_search(self, db, auth, svc):
        await self._seed(svc)
        hits = await svc.list_items("ws-k1", q="CTO")
        assert [i["title"] for i in hits] == ["ICP"]
        hits2 = await svc.list_items("ws-k1", q="angle")
        assert [i["title"] for i in hits2] == ["Angle"]

    async def test_10_empty_knowledge_state(self, db, auth, svc):
        assert await svc.list_items("ws-k1") == []
        assert await svc.list_sources("ws-k1") == []


class TestSources:
    async def test_8_create_source_with_provenance(self, db, auth, svc):
        source = await svc.create_source(
            owner_id="user-1", workspace_id="ws-k1",
            title="Pricing sheet notes",
            source_type="user_input",
            content="We bill per seat from $99/mo.",
            metadata={"kind": "manual", "origin": "call with founder"},
        )
        assert source["source_type"] == "user_input"
        assert source["content"].startswith("We bill per seat")
        assert source["metadata"]["origin"] == "call with founder"
        assert source["created_by"] == "user-1"
        assert db["knowledge_sources"], "source must be written to durable store"

    async def test_8b_document_source_keeps_reference(self, db, auth, svc):
        source = await svc.create_source(
            owner_id="user-1", workspace_id="ws-k1",
            title="One-pager.pdf",
            source_type="uploaded_document",
            content="",
            reference="docs/one-pager.pdf",
        )
        assert source["reference"] == "docs/one-pager.pdf"

    async def test_8c_item_source_attribution(self, db, auth, svc):
        item = await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="company", title="From doc",
            source_type="uploaded_document", source_id="src-123",
        )
        assert item["source_type"] == "uploaded_document"
        assert item["source_id"] == "src-123"

    async def test_8d_source_update_and_archive(self, db, auth, svc):
        created = await svc.create_source(
            owner_id="user-1", workspace_id="ws-k1",
            title="Notes", content="v1",
        )
        updated = await svc.update_source(
            owner_id="user-1", workspace_id="ws-k1", source_id=created["id"],
            content="v2",
        )
        assert updated["content"] == "v2"
        assert await svc.archive_source("user-1", "ws-k1", created["id"]) is not None
        assert await svc.list_sources("ws-k1") == []


class TestIsolation:
    async def test_6a_user_a_cannot_see_user_b(self, db, auth, svc):
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="company", title="User A secret")
        await svc.create_item(owner_id="user-2", workspace_id="ws-k2",
                              category="company", title="User B secret")

        a_items = await svc.list_items("ws-k1")
        b_items = await svc.list_items("ws-k2")
        assert [i["title"] for i in a_items] == ["User A secret"]
        assert [i["title"] for i in b_items] == ["User B secret"]

        b_item_id = b_items[0]["id"]
        assert await svc.get_item("ws-k1", b_item_id) is None
        assert await svc.update_item(owner_id="user-1", workspace_id="ws-k1",
                                     item_id=b_item_id, title="hijack") is None
        assert await svc.archive_item("user-1", "ws-k1", b_item_id) is None

    async def test_6b_route_level_isolation(self, db, monkeypatch, svc):
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("user-2"))
        monkeypatch.setattr(
            "services.workspace_state._async_workspace", _fake_workspace)
        await _r(main_module.create_knowledge_item, "tok", main_module.KnowledgeItemCreateRequest(
            category="icp", title="User B's ICP",
        ), MagicMock())
        # user-1 owns a different workspace and must never see it
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("user-1"))
        monkeypatch.setattr(
            "services.workspace_state._async_workspace", _fake_workspace)
        res = await _r(main_module.list_knowledge, "tok", MagicMock(), category="", q="", limit=200)
        assert res["items"] == []
        assert res["ok"] is True


class TestRestartDurability:
    def test_7_persistence_survives_process_restart(self, db):
        """Write with one process (client+repos+service), read back with a
        brand-new instance over the same underlying rows."""
        store = db
        svc1 = KnowledgeService()
        item = asyncio.run(svc1.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="company", title="Loqi",
            summary="AI-native outbound OS",
            content={"differentiators": ["multichannel orchestration"]},
            tags=["outbound"],
            source_type="user_input",
        ))
        source = asyncio.run(svc1.create_source(
            owner_id="user-1", workspace_id="ws-k1",
            title="Notes", content="Original content",
            metadata={"v": 1},
        ))

        # simulate backend restart: fresh client + fresh manager + fresh repos
        reset_connection_manager()
        client = FakeSupabaseClient(store)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)

        svc2 = KnowledgeService()
        items = asyncio.run(svc2.list_items("ws-k1"))
        sources = asyncio.run(svc2.list_sources("ws-k1"))

        assert len(items) == 1
        restored = items[0]
        assert restored["id"] == item["id"]
        assert restored["title"] == "Loqi"
        assert restored["summary"] == "AI-native outbound OS"
        assert restored["content"] == {"differentiators": ["multichannel orchestration"]}
        assert restored["tags"] == ["outbound"]
        assert restored["source_type"] == "user_input"
        assert restored["created_at"] == item["created_at"]
        assert restored["updated_at"] == item["updated_at"]

        assert sources[0]["id"] == source["id"]
        assert sources[0]["content"] == "Original content"
        assert sources[0]["metadata"] == {"v": 1}

    def test_7b_restart_preserves_then_restores_archived(self, db):
        store = db
        svc1 = KnowledgeService()
        item = asyncio.run(svc1.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="icp", title="ICP v1",
        ))
        asyncio.run(svc1.archive_item("user-1", "ws-k1", item["id"]))

        reset_connection_manager()
        client = FakeSupabaseClient(store)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)

        svc2 = KnowledgeService()
        assert asyncio.run(svc2.list_items("ws-k1")) == []
        assert asyncio.run(svc2.get_item("ws-k1", item["id"])) is None
        # the row still exists durably (soft delete) — archiving again is a no-op
        assert asyncio.run(svc2.archive_item("user-1", "ws-k1", item["id"])) is None


class TestRetrievalContext:
    async def test_9_get_knowledge_context_owner_scoped(self, db, auth, svc):
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="company", title="Loqi",
                              summary="AI-native outbound OS",
                              source_type="user_input")
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="sales_offer", title="Pricing",
                              source_type="system_generated", source_id="sig-1")
        await svc.create_item(owner_id="user-2", workspace_id="ws-k2",
                              category="company", title="Other company")

        ctx = await svc.get_knowledge_context("user-1")
        assert ctx["owner_id"] == "user-1"
        assert ctx["workspace_id"] == "ws-k1"
        titles = [i["title"] for i in ctx["items"]]
        assert "Other company" not in titles
        assert "Pricing" in titles and "Loqi" in titles

    async def test_9b_context_category_and_query_filters(self, db, auth, svc):
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="company", title="About",
                              content={"competitors": ["Clearbit"]})
        await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                              category="icp", title="ICP",
                              content={"roles": ["CTO"]})
        ctx = await svc.get_knowledge_context("user-1", categories=["company"])
        assert [i["title"] for i in ctx["items"]] == ["About"]
        ctx2 = await svc.get_knowledge_context("user-1", query="clearbit")
        assert [i["title"] for i in ctx2["items"]] == ["About"]

    async def test_9c_context_bounded_and_attributable(self, db, auth, svc):
        for i in range(6):
            await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                                  category="messaging", title=f"Angle {i}",
                                  source_type="user_input")
        await svc.create_source(owner_id="user-1", workspace_id="ws-k1",
                                title="Source doc", content="detail")
        ctx = await svc.get_knowledge_context("user-1", limit=3)
        assert len(ctx["items"]) == 3
        assert ctx["limit"] == 3
        entry = ctx["items"][0]
        assert {"id", "category", "title", "source_type", "source_id",
                "created_by", "updated_at"} <= set(entry)
        assert len(ctx["sources"]) >= 1
        src = ctx["sources"][0]
        assert {"id", "title", "source_type", "created_at"} <= set(src)

    async def test_9d_context_clamps_limit(self, db, auth, svc):
        for i in range(30):
            await svc.create_item(owner_id="user-1", workspace_id="ws-k1",
                                  category="icp", title=f"I {i}")
        ctx = await svc.get_knowledge_context("user-1", limit=999)
        assert len(ctx["items"]) == 20

    async def test_9e_public_context_function_uses_owner_scope(self, db, auth, svc):
        await svc.create_item(
            owner_id="user-1", workspace_id="ws-k1",
            category="company", title="Canonical context",
        )
        ctx = await get_knowledge_context("user-1", categories=["company"])
        assert [item["title"] for item in ctx["items"]] == ["Canonical context"]


class TestApiValidation:
    async def test_11_create_requires_valid_category(self, db, auth):
        with pytest.raises(Exception) as exc:
            await _r(main_module.create_knowledge_item, "tok",
                     main_module.KnowledgeItemCreateRequest(
                         category="bogus", title="X"), MagicMock())
        assert getattr(exc.value, "status_code", None) == 400

    async def test_11b_create_requires_title(self, db, auth):
        with pytest.raises(Exception) as exc:
            await _r(main_module.create_knowledge_item, "tok",
                     main_module.KnowledgeItemCreateRequest(
                         category="company", title="   "), MagicMock())
        assert getattr(exc.value, "status_code", None) == 400

    async def test_11c_oversized_title_rejected(self, db, auth):
        with pytest.raises(Exception) as exc:
            await _r(main_module.create_knowledge_item, "tok",
                     main_module.KnowledgeItemCreateRequest(
                         category="company", title="x" * 500), MagicMock())
        assert getattr(exc.value, "status_code", None) == 400

    async def test_11d_update_unknown_item_404(self, db, auth):
        with pytest.raises(Exception) as exc:
            await _r(main_module.update_knowledge_item, "tok", "missing",
                     main_module.KnowledgeItemUpdateRequest(title="X"),
                     MagicMock())
        assert getattr(exc.value, "status_code", None) == 404

    async def test_11e_source_validation(self, db, auth):
        with pytest.raises(Exception) as exc:
            await _r(main_module.create_knowledge_source, "tok",
                     main_module.KnowledgeSourceCreateRequest(
                         title="Doc", source_type="bogus"), MagicMock())
        assert getattr(exc.value, "status_code", None) == 400

    async def test_12_route_create_writes_durable_row(self, db, auth):
        res = await _r(main_module.create_knowledge_item, "tok",
                       main_module.KnowledgeItemCreateRequest(
                           category="messaging", title="Approved angle",
                           summary="Lead with outcomes"), MagicMock())
        assert res["ok"] is True
        item_id = res["item"]["id"]
        fetched = await _r(main_module.get_knowledge_item, "tok", item_id, MagicMock())
        assert fetched["item"]["summary"] == "Lead with outcomes"
        row = next(r for r in db["knowledge_items"] if r["id"] == item_id)
        assert row["workspace_id"] == "ws-k1"
