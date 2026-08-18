"""SaaS-2.5 — Complete Tenant Isolation Audit & Security Hardening.

Regression coverage for the concrete hardening applied in SaaS-2.5:

  * get_discovery constrained to the caller's workspace (defense-in-depth so a
    foreign discovery id cannot return another tenant's PII at the query layer).
  * workspace-context only surfaces the authenticated owner's own providers
    (durable provider records must not leak across tenants).
  * workspace-context only returns conversation intelligence for a conversation
    the caller provably owns (client-supplied conversation_id must not read
    another tenant's memory/timeline).

Uses fake/in-memory clients and monkeypatched stores. No production data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


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

    def insert(self, payload):
        self._op = "insert"
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
        return _Row([])


class FakeClient:
    def __init__(self, tables=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}

    def table(self, name):
        return _Query(self, name)


def _iso():
    return datetime.now(timezone.utc).isoformat()


class TestGetDiscoveryWorkspaceScoping:

    @pytest.mark.asyncio
    async def test_foreign_discovery_returns_none_at_query_layer(self, monkeypatch):
        from services import discovery
        db = FakeClient({"discoveries": [
            {"id": "disc-A", "workspace_id": "ws-A", "created_at": _iso(),
             "updated_at": _iso(), "status": "completed"},
            {"id": "disc-B", "workspace_id": "ws-B", "created_at": _iso(),
             "updated_at": _iso(), "status": "completed"},
        ]})
        monkeypatch.setattr(discovery, "get_supabase_client", lambda: db)

        # A workspace-A user cannot fetch B's discovery even by id.
        assert discovery.get_discovery("disc-B", workspace_id="ws-A") is None
        # Own discovery is returned when scoped.
        assert discovery.get_discovery("disc-A", workspace_id="ws-A") is not None
        # Workspace-B discovery returns under its own workspace.
        assert discovery.get_discovery("disc-B", workspace_id="ws-B") is not None


class TestWorkspaceContextProviderScoping:

    def _prov(self, pid, user_id, email):
        from services.communication.provider_models import (
            CommunicationProvider, ProviderStatus, ProviderType,
        )
        return CommunicationProvider(
            id=pid, provider_type=ProviderType.GMAIL, user_id=user_id,
            status=ProviderStatus.HEALTHY, metadata={"email": email},
            last_sync=_iso(),
        )

    def test_only_own_providers_surfaced(self, monkeypatch):
        import main as main_module
        from enum import Enum

        class _H(Enum):
            healthy = "healthy"

        class _Health:
            def health(self):
                return _H.healthy

        prov_a = self._prov("p-A", "user-A", "a@loqi.ai")
        prov_b = self._prov("p-B", "user-B", "b@loqi.ai")

        # Stub the heavy workspace helpers to empty, and the provider store to
        # two tenants' providers.
        monkeypatch.setattr(main_module, "campaign_store", _StubDict())
        monkeypatch.setattr(main_module, "draft_store", _StubDict())
        monkeypatch.setattr(main_module, "build_snapshot",
                            lambda *a, **k: {"campaigns": [], "campaign_count": 0,
                                             "campaigns_ready": 0, "campaigns_draft_review": 0,
                                             "drafts": {}, "total_leads": 0, "jobs": {},
                                             "memory": {}, "timeline": []})
        monkeypatch.setattr(main_module, "get_active_runtimes", lambda *a, **k: [])
        monkeypatch.setattr(main_module, "calculate_progress", lambda *a, **k: 0)

        class _Store:
            def list_providers(self):
                return [prov_a, prov_b]
        monkeypatch.setattr(main_module, "communication_store", _Store())
        monkeypatch.setattr(main_module, "get_provider", lambda pid: _Health() if pid == "p-A" else _Health())

        ctx = main_module._build_copilot_workspace_context(
            "token", user_id="user-A",
        )
        provider_ids = [p["id"] for p in ctx.get("providers", [])]
        assert provider_ids == ["p-A"]
        # The other tenant's provider is never exposed.
        assert "p-B" not in provider_ids
        assert all(p["email"] == "a@loqi.ai" for p in ctx["providers"])

    def test_conversation_intelligence_gated_by_ownership(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(main_module, "campaign_store", _StubDict())
        monkeypatch.setattr(main_module, "draft_store", _StubDict())
        monkeypatch.setattr(main_module, "build_snapshot",
                            lambda *a, **k: {"campaigns": [], "campaign_count": 0,
                                             "campaigns_ready": 0, "campaigns_draft_review": 0,
                                             "drafts": {}, "total_leads": 0, "jobs": {},
                                             "memory": {}, "timeline": []})
        monkeypatch.setattr(main_module, "get_active_runtimes", lambda *a, **k: [])
        monkeypatch.setattr(main_module, "calculate_progress", lambda *a, **k: 0)
        monkeypatch.setattr(main_module, "communication_store", _StubStore([]))

        class _Mem:
            buying_signals = []
            current_stage = type("S", (), {"value": "x"})()
            summary = "secret summary"
            open_questions = []
            outstanding_objections = []
            pain_points = []
            business_goals = []
            competitor_mentioned = False
            decision_makers = []
            last_recommendation = ""
            last_followup = ""
            key_risks = []
            key_opportunities = []
            urgency = ""
            decision_confidence = 0
            top_objection = ""

        # memory store has data for the foreign conversation id.
        monkeypatch.setattr(main_module, "memory_store", _MemStore({"conv-9": _Mem()}))
        monkeypatch.setattr(main_module, "get_conversation_events", lambda cid: [])

        class _Convo:
            owner_id = "user-other"

        # The conversation provably belongs to a DIFFERENT owner -> denied.
        monkeypatch.setattr(main_module, "_conversation_owned_by", lambda convo, owner: False)

        class _ConvStore:
            def get_conversation(self, cid):
                return _Convo()
        # The function imports conversation_store from the module, not main.
        import services.conversations.conversation_store as conv_module
        monkeypatch.setattr(conv_module, "conversation_store", _ConvStore())

        ctx = main_module._build_copilot_workspace_context(
            "token", conversation_id="conv-9", user_id="user-A",
        )
        assert "conversation_intelligence" not in ctx


class _StubDict:
    def get(self, *a, **k):
        return []


class _StubStore:
    def __init__(self, providers):
        self._p = providers

    def list_providers(self):
        return self._p


class _MemStore:
    def __init__(self, data):
        self._data = data

    def get(self, cid):
        return self._data.get(cid)
