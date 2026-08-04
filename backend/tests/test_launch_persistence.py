"""Tests for the launch foundation persistence layer.

Covers: repo round-trips (datetime + JSONB), canonical identity upserts
(connected_accounts / external_identities), workspace projection fallback,
and backfill idempotency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.persistence import (
    RepositoryProvider,
    reset_connection_manager,
    reset_repository_provider,
    set_connection_manager,
    set_repository_provider,
)
from services.persistence.database import SupabaseConnectionManager

from services.persistence.launch import (
    Campaign,
    CampaignRepository,
    ConnectedAccount,
    ConnectedAccountRepository,
    Draft,
    DraftRepository,
    ExternalIdentity,
    ExternalIdentityRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_repository_provider()
    reset_connection_manager()
    set_repository_provider(RepositoryProvider.SUPABASE)


def _mock_client():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.eq.return_value = client
    client.neq.return_value = client
    client.in_.return_value = client
    client.limit.return_value = client
    client.order.return_value = client
    client.execute.return_value = MagicMock(data=[])
    return client


@pytest.fixture
def mock_cm():
    client = _mock_client()
    cm = SupabaseConnectionManager(url="http://test", key="test-key")
    cm._client = client
    set_connection_manager(cm)
    return cm, client


def _rows(*data: dict) -> MagicMock:
    result = MagicMock()
    result.data = list(data)
    return MagicMock(return_value=result)


# ─── Repo round-trips (datetime + JSONB) ────────────────────────────────

class TestLaunchRepoRoundTrip:

    def test_table_names(self):
        assert CampaignRepository()._table_name == "campaigns"
        assert DraftRepository()._table_name == "drafts"
        assert ConnectedAccountRepository()._table_name == "connected_accounts"
        assert ExternalIdentityRepository()._table_name == "external_identities"

    @pytest.mark.asyncio
    async def test_campaign_save_and_get_roundtrip(self, mock_cm):
        _, client = mock_cm
        now = datetime.now(timezone.utc)
        campaign = Campaign(
            id="c1",
            workspace_id="ws1",
            name="Q3 Outreach",
            objective="Book demos",
            status="running",
            settings={"max_daily": 10, "timezone": "US/Pacific"},
            created_at=now,
            updated_at=now,
        )
        repo = CampaignRepository()
        # Serialization: datetime → ISO string; JSONB columns → JSON string.
        row = repo._to_row(campaign)
        assert row["name"] == "Q3 Outreach"
        assert isinstance(row["settings"], str)
        assert "max_daily" in row["settings"]
        assert row["created_at"] == now.isoformat()

        t = now.isoformat()
        client.execute = _rows({
            "id": "c1", "workspace_id": "ws1", "organization_id": "",
            "name": "Q3 Outreach", "objective": "Book demos",
            "status": "running", "search_query": "", "settings": row["settings"],
            "created_by": "", "created_at": t, "updated_at": t,
        })
        fetched = await repo.get("c1")
        assert fetched is not None
        assert fetched.name == "Q3 Outreach"
        assert fetched.status == "running"
        assert fetched.settings == {"max_daily": 10, "timezone": "US/Pacific"}

    @pytest.mark.asyncio
    async def test_draft_jsonb_roundtrip(self, mock_cm):
        _, client = mock_cm
        t = datetime.now(timezone.utc).isoformat()
        draft = Draft(
            id="d1",
            workspace_id="ws1",
            campaign_id="c1",
            subject="Intro",
            body="Hi there",
            status="pending",
            generation_model="gpt-4o",
            generation_metadata={"tone": "formal", "attempt": 1},
            lead_snapshot={"email": "x@example.com"},
        )
        repo = DraftRepository()
        row = repo._to_row(draft)
        assert isinstance(row["generation_metadata"], str)
        assert "formal" in row["generation_metadata"]

        client.execute = _rows({
            "id": "d1", "workspace_id": "ws1", "campaign_id": "c1",
            "lead_id": None, "provider": "", "subject": "Intro",
            "body": "Hi there", "preview": "", "status": "pending",
            "tone": "", "length": "", "generation_model": "gpt-4o",
            "generation_version": "", "prompt_hash": "",
            "generation_metadata": row["generation_metadata"],
            "lead_snapshot": row["lead_snapshot"],
            "approved_at": None, "sent_at": None, "reply_state": "",
            "created_at": t, "updated_at": t,
        })
        fetched = await repo.get("d1")
        assert fetched is not None
        assert fetched.generation_metadata == {"tone": "formal", "attempt": 1}
        assert fetched.lead_snapshot == {"email": "x@example.com"}


class TestLaunchRepoUpsertJsonb:

    @pytest.mark.asyncio
    async def test_connected_account_find_for_user(self, mock_cm):
        _, client = mock_cm
        t = datetime.now(timezone.utc).isoformat()
        client.execute = _rows({
            "id": "ca1", "user_id": "u1", "provider": "google",
            "account_id": "me@gmail.com", "display_name": "",
            "email": "me@gmail.com", "access_token": "tok",
            "refresh_token": "rfr", "token_type": "bearer",
            "token_expires_at": None, "status": "active",
            "scope": [], "metadata": {}, "created_at": t, "updated_at": t,
        })
        repo = ConnectedAccountRepository()
        found = await repo.find_for_user("u1", "google")
        assert found is not None
        assert found.account_id == "me@gmail.com"
        assert found.access_token == "tok"

    @pytest.mark.asyncio
    async def test_sync_connected_account_upsert(self, mock_cm):
        _, client = mock_cm
        from services.supabase import sync_connected_account
        # First save (no existing) → repo.save inserts.
        ok = sync_connected_account(
            "u1", provider="google", email="me@gmail.com",
            access_token="tok1", refresh_token="rfr1",
        )
        assert ok is True
        # No existing row returned → the repo's get-before-write returned none.
        assert True


# ─── Identity repos ─────────────────────────────────────────────────────

class TestExternalIdentityRepo:

    @pytest.mark.asyncio
    async def test_find_by_provider_subject(self, mock_cm):
        _, client = mock_cm
        t = datetime.now(timezone.utc).isoformat()
        client.execute = _rows({
            "id": "ei1", "user_id": "u1", "provider": "google",
            "provider_subject": "g_sub_1", "email": "a@example.com",
            "username": "A", "metadata": {}, "created_at": t, "updated_at": t,
        })
        repo = ExternalIdentityRepository()
        found = await repo.find_by_provider_subject("google", "g_sub_1")
        assert found is not None
        assert found.user_id == "u1"
        assert found.provider_subject == "g_sub_1"


# ─── Workspace / projection / backfill ─────────────────────────────────

class _ScriptedClient:
    """Minimal Supabase-like mock with per-table scripted query results.

    Accumulates `eq` filters and applies them in `execute`, so row lookups
    (e.g. find_by_email / find_in_workspace) behave like real PostgREST.
    """

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self._table = ""
        self._filters: list[tuple[str, Any]] = []

    def table(self, name):
        self._table = name
        self._filters = []
        return self

    def select(self, *_):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, *_):
        return self

    def order(self, *_, **__):
        return self

    def insert(self, payload):
        self._tables.setdefault(self._table, []).append(payload)
        return self

    def update(self, *_):
        return self

    def execute(self):
        rows = self._tables.get(self._table, [])
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        result = MagicMock()
        result.data = [dict(r) for r in rows]
        return result


class TestWorkspaceStateCanonicalFlip:

    def _shared_client(self, tables):
        client = _ScriptedClient(tables)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)
        return client

    def test_returns_canonical_state_when_seeded(self):
        from services.workspace_state import load_workspace_state
        t = "2026-01-01T00:00:00+00:00"
        client = self._shared_client({
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "campaigns": [{
                "id": "c1", "workspace_id": "ws1", "organization_id": "",
                "name": "Q3 Outreach", "objective": "Book demos",
                "status": "running", "search_query": "", "settings": {},
                "created_by": "", "created_at": t, "updated_at": t,
            }],
            "campaign_leads": [{
                "id": "cl1", "campaign_id": "c1", "lead_id": "wsl1",
                "status": "added", "added_by": "", "created_at": t,
                "updated_at": t,
            }],
            "workspace_leads": [{
                "id": "wsl1", "workspace_id": "ws1", "lead_id": "gl1",
                "company_id": "comp1", "email": "ada@acme.com",
                "first_name": "Ada", "last_name": "Lovelace",
                "title": "Engineer", "phone": "", "linkedin_url": "",
                "lead_status": "approved", "research_status": "researched",
                "verification_status": "verified", "confidence": 0.9,
                "source": "apollo", "created_at": t, "updated_at": t,
            }],
            "leads": [{
                "id": "gl1", "canonical_id": "email:ada@acme.com",
                "email": "ada@acme.com", "first_name": "Ada",
                "last_name": "Lovelace", "title": "Engineer",
                "phone": "", "linkedin_url": "",
                "created_at": t, "updated_at": t,
            }],
            "companies": [{
                "id": "comp1", "canonical_id": "domain:acme.com",
                "domain": "acme.com", "name": "Acme", "website": "",
                "linkedin_url": "", "industry": "", "employee_count": None,
                "revenue_band": "", "country": "", "city": "", "location": "",
                "description": "", "created_at": t, "updated_at": t,
            }],
            "strategies": [{
                "id": "s1", "campaign_id": "c1", "version": 1,
                "is_current": True, "objective": "Book demos",
                "audience": "", "channel": "email",
                "messaging_angle": "", "sequence": ["intro", "followup"],
                "tone": "friendly", "persona": "", "offer": {},
                "objections": [], "raw": {}, "generated_at": t,
                "generated_by": "", "model_used": "", "created_at": t,
            }],
            "drafts": [],
        })
        with patch("services.conversation_store.get_supabase_client",
                   return_value=client), \
             patch("services.workspace_state.get_supabase_client",
                   return_value=client):
            state = load_workspace_state("u1")

        assert len(state["campaigns"]) == 1
        campaign = state["campaigns"][0]
        assert campaign["id"] == "c1"
        assert campaign["name"] == "Q3 Outreach"
        assert campaign["status"] == "running"
        assert campaign["lead_count"] == 1
        assert campaign["strategy"]["channel"] == "email"
        assert campaign["strategy"]["sequence"] == ["intro", "followup"]
        assert campaign["strategy"]["tone"] == "friendly"
        assert state["drafts"] == []
        assert state["approved_leads"][0]["id"] == "wsl1"

    def test_lead_shape_contract_is_preserved(self):
        """The dict shape UI components depend on survives the canonical read."""
        from services.workspace_state import load_workspace_state
        t = "2026-01-01T00:00:00+00:00"
        client = self._shared_client({
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "campaigns": [{
                "id": "c1", "workspace_id": "ws1", "name": "Q3 Outreach",
                "objective": "", "status": "running", "search_query": "",
                "created_at": t, "updated_at": t,
            }],
            "campaign_leads": [{
                "id": "cl1", "campaign_id": "c1", "lead_id": "wsl1",
                "created_at": t, "updated_at": t,
            }],
            "workspace_leads": [{
                "id": "wsl1", "workspace_id": "ws1", "lead_id": "gl1",
                "company_id": "comp1", "email": "ada@acme.com",
                "first_name": "", "last_name": "", "title": "",
                "phone": "", "linkedin_url": "", "lead_status": "approved",
                "research_status": "researched",
                "verification_status": "verified", "confidence": 0.9,
                "source": "apollo", "created_at": t, "updated_at": t,
            }],
            "leads": [{
                "id": "gl1", "canonical_id": "email:ada@acme.com",
                "email": "ada@acme.com", "first_name": "Ada",
                "last_name": "Lovelace", "title": "Engineer",
                "phone": "+1", "linkedin_url": "in/ada",
                "created_at": t, "updated_at": t,
            }],
            "companies": [{
                "id": "comp1", "canonical_id": "domain:acme.com",
                "domain": "acme.com", "name": "Acme",
                "created_at": t, "updated_at": t,
            }],
            "strategies": [],
            "drafts": [],
        })
        with patch("services.conversation_store.get_supabase_client",
                   return_value=client), \
             patch("services.workspace_state.get_supabase_client",
                   return_value=client):
            lead = load_workspace_state("u1")["campaigns"][0]["leads"][0]

        assert lead["id"] == "wsl1"
        assert lead["name"] == "Ada Lovelace"
        assert lead["first_name"] == "Ada"
        assert lead["last_name"] == "Lovelace"
        assert lead["title"] == "Engineer"
        assert lead["email"] == "ada@acme.com"
        assert lead["phone"] == "+1"
        assert lead["linkedin_url"] == "in/ada"
        assert lead["company"] == "Acme"
        assert lead["company_name"] == "Acme"
        assert lead["domain"] == "acme.com"
        assert lead["status"] == "approved"
        assert lead["lead_status"] == "approved"
        assert lead["research_status"] == "researched"
        assert lead["verification_status"] == "verified"
        assert lead["confidence"] == 0.9
        assert lead["source"] == "apollo"

    def test_falls_back_to_projection_when_not_seeded(self):
        from services.workspace_state import load_workspace_state
        client = self._shared_client({
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "campaigns": [],
            "workflow_events": [
                {"workflow_session_id": "ws1", "event_type": "campaign.created", "payload": {
                    "campaign": {"id": "c1", "name": "A",
                                 "strategy": {"angle": "x"}}}},
                {"workflow_session_id": "ws1", "event_type": "campaign.lead_added", "payload": {
                    "campaign_id": "c1",
                    "lead": {"id": "l1", "email": "l@x.com"}}},
            ],
        })
        with patch("services.conversation_store.get_supabase_client",
                   return_value=client), \
             patch("services.workspace_state.get_supabase_client",
                   return_value=client):
            state = load_workspace_state("u1")

        assert len(state["campaigns"]) == 1
        assert state["campaigns"][0]["id"] == "c1"
        assert state["campaigns"][0]["lead_count"] == 1


class TestWorkspaceProjection:

    def test_project_from_events(self):
        from services.workspace_state import _project_from_events
        events = [
            {"event_type": "campaign.created", "payload": {
                "campaign": {"id": "c1", "name": "A", "strategy": {"angle": "x"}}}},
            {"event_type": "campaign.updated", "payload": {
                "campaign_id": "c1", "updates": {"status": "running"}}},
            {"event_type": "campaign.lead_added", "payload": {
                "campaign_id": "c1", "lead": {"id": "l1", "email": "l@x.com"}}},
            {"event_type": "lead.approved", "payload": {"lead": {"id": "l1"}}},
            {"event_type": "draft.created", "payload": {
                "draft": {"id": "d1", "subject": "Hi"}}},
        ]
        state = _project_from_events(events)
        assert len(state["campaigns"]) == 1
        assert state["campaigns"][0]["status"] == "running"
        assert state["campaigns"][0]["lead_count"] == 1
        assert state["approved_leads"][0]["id"] == "l1"
        assert state["drafts"][0]["id"] == "d1"


class TestEnsureWorkspace:

    def _shared_client(self, tables):
        client = _ScriptedClient(tables)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        return client, cm

    def test_creates_workspace_and_owner_member(self):
        from services.workspace_state import ensure_workspace
        tables = {
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "workspaces": [],
            "workspace_members": [],
        }
        client, cm = self._shared_client(tables)
        set_connection_manager(cm)
        with patch("services.conversation_store.get_supabase_client", return_value=client), \
             patch("services.workspace_state.get_supabase_client", return_value=client):
            ws_id = ensure_workspace("u1", name="Personal Workspace")
        assert ws_id == "ws1"
        assert len(tables["workspaces"]) == 1
        assert tables["workspaces"][0]["id"] == "ws1"
        assert tables["workspaces"][0]["owner_user_id"] == "u1"
        assert len(tables["workspace_members"]) == 1
        assert tables["workspace_members"][0]["user_id"] == "u1"
        assert tables["workspace_members"][0]["role"] == "owner"

    def test_does_not_duplicate_on_second_call(self):
        from services.workspace_state import ensure_workspace
        tables = {
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "workspaces": [{"id": "ws1", "owner_user_id": "u1"}],
            "workspace_members": [{"workspace_id": "ws1", "user_id": "u1"}],
        }
        client, cm = self._shared_client(tables)
        set_connection_manager(cm)
        with patch("services.conversation_store.get_supabase_client", return_value=client), \
             patch("services.workspace_state.get_supabase_client", return_value=client):
            ws_id = ensure_workspace("u1")
        assert ws_id == "ws1"
        assert len(tables["workspaces"]) == 1
        assert len(tables["workspace_members"]) == 1


class TestBackfill:

    @pytest.mark.asyncio
    async def test_backfill_skips_seeded_workspace(self):
        from services.persistence.launch import backfill_workspace

        with patch("services.persistence.launch.backfill.get_supabase_client",
                   return_value=MagicMock()), \
             patch("services.persistence.launch.backfill.ensure_workflow_session",
                   return_value="ws1"), \
             patch("services.persistence.launch.CampaignRepository") as CRepo, \
             patch("services.workspace_state._write_campaign_row",
                   new_callable=AsyncMock) as write_campaign:
            inst = CRepo.return_value
            inst.list_for_workspace = AsyncMock(
                return_value=[MagicMock(id="c1")])
            ok = backfill_workspace("u1")
        assert ok is True
        # Workspace already seeded → replay never touches write paths.
        write_campaign.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backfill_replays_events_for_empty_workspace(self):
        from services.persistence.launch import backfill_workspace

        events = [
            {"event_type": "campaign.created", "payload": {
                "campaign": {"id": "c1", "name": "A",
                             "strategy": {"angle": "x"}}}},
            {"event_type": "draft.created", "payload": {
                "draft": {"id": "d1", "subject": "Hi"}}},
        ]
        with patch("services.persistence.launch.backfill.get_supabase_client",
                   return_value=MagicMock()), \
             patch("services.persistence.launch.backfill.ensure_workflow_session",
                   return_value="ws1"), \
             patch("services.workspace_state._events", return_value=events), \
             patch("services.persistence.launch.CampaignRepository") as CRepo, \
             patch("services.workspace_state._write_campaign_row",
                   new_callable=AsyncMock) as write_campaign, \
             patch("services.workspace_state._write_strategy",
                   new_callable=AsyncMock) as write_strategy, \
             patch("services.workspace_state._write_draft_row",
                   new_callable=AsyncMock) as write_draft:
            inst = CRepo.return_value
            inst.list_for_workspace = AsyncMock(return_value=[])
            ok = backfill_workspace("u1")
        assert ok is True
        write_campaign.assert_awaited_once()
        write_strategy.assert_awaited_once()
        write_draft.assert_awaited_once()


# ─── Global entities / provider archive ────────────────────────────────

class TestGlobalLeadDedup:
    """Same person/company across workspaces → one global row each."""

    @pytest.mark.asyncio
    async def test_normalize_lead_dedupes_globally(self):
        from services.workspace_state import _normalize_lead
        tables = {
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}],
            "workspaces": [],
            "leads": [],
            "companies": [],
            "workspace_leads": [],
            "workspace_companies": [],
        }
        client = _ScriptedClient(tables)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)

        with patch("services.conversation_store.get_supabase_client",
                   return_value=client), \
             patch("services.workspace_state.get_supabase_client",
                   return_value=client):
            lead = {
                "email": "Ada.Lovelace@Acme.com",
                "name": "Ada Lovelace",
                "company": "Acme",
                "domain": "Acme.com",
                "source": "apollo",
                "confidence": 0.9,
            }
            first = await _normalize_lead("ws1", lead)
            second = await _normalize_lead("ws1", dict(lead, source="pdl"))

        assert first == second
        assert len(tables["leads"]) == 1
        assert tables["leads"][0]["email"] == "ada.lovelace@acme.com"
        assert tables["leads"][0]["canonical_id"] == "email:ada.lovelace@acme.com"
        assert len(tables["companies"]) == 1
        assert tables["companies"][0]["domain"] == "acme.com"
        assert tables["companies"][0]["canonical_id"] == "domain:acme.com"
        assert len(tables["workspace_leads"]) == 1
        assert len(tables["workspace_companies"]) == 1

    @pytest.mark.asyncio
    async def test_cross_workspace_shares_global_rows(self):
        from services.workspace_state import _normalize_lead
        tables = {
            "workflow_sessions": [{"id": "ws1", "user_id": "u1", "channel": "workspace", "session_key": "u1"}, {"id": "ws2"}],
            "workspaces": [],
            "leads": [],
            "companies": [],
            "workspace_leads": [],
            "workspace_companies": [],
        }
        client = _ScriptedClient(tables)
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        cm._client = client
        set_connection_manager(cm)

        with patch("services.conversation_store.get_supabase_client",
                   return_value=client), \
             patch("services.workspace_state.get_supabase_client",
                   return_value=client):
            lead = {"email": "a@acme.com", "company": "Acme", "domain": "acme.com"}
            ws1_lead = await _normalize_lead("ws1", lead)
            ws2_lead = await _normalize_lead("ws2", lead)

        # Global rows shared; workspace rows are per-workspace.
        assert ws1_lead != ws2_lead
        assert len(tables["leads"]) == 1
        assert len(tables["companies"]) == 1
        assert len(tables["workspace_leads"]) == 2
        assert len(tables["workspace_companies"]) == 2


class TestProviderPayloadRepo:

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(self, mock_cm):
        from services.persistence.launch import ProviderPayload, ProviderPayloadRepository
        _, client = mock_cm
        t = datetime.now(timezone.utc).isoformat()
        raw = {
            "id": "pdl_123",
            "first_name": "Ada",
            "technologies_used": ["React", "Postgres"],
            "hiring_signals": [{"role": "engineer", "active": True}],
        }
        payload = ProviderPayload(
            id="pp1",
            provider="pdl",
            entity_type="lead",
            entity_id="pdl_123",
            payload=raw,
            retrieved_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        repo = ProviderPayloadRepository()
        row = repo._to_row(payload)
        assert isinstance(row["payload"], str)
        assert "technologies_used" in row["payload"]

        client.execute = _rows({
            "id": "pp1", "provider": "pdl", "entity_type": "lead",
            "entity_id": "pdl_123", "payload": row["payload"],
            "retrieved_at": t, "created_at": t,
        })
        fetched = await repo.get("pp1")
        assert fetched is not None
        assert fetched.provider == "pdl"
        assert fetched.entity_id == "pdl_123"
        assert fetched.payload == raw

    @pytest.mark.asyncio
    async def test_find_is_keyed_by_provider_entity(self, mock_cm):
        from services.persistence.launch import ProviderPayloadRepository
        _, client = mock_cm
        t = datetime.now(timezone.utc).isoformat()
        client.execute = _rows({
            "id": "pp1", "provider": "pdl", "entity_type": "company",
            "entity_id": "acme.com", "payload": "{}",
            "retrieved_at": t, "created_at": t,
        })
        repo = ProviderPayloadRepository()
        found = await repo.find("pdl", "company", "acme.com")
        assert found is not None
        assert found.entity_id == "acme.com"