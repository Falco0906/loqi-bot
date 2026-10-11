"""Offline RPC-contract tests. The fake database models transaction commit/replay.

These do not substitute for executing migration 048 against a test PostgreSQL DB.
"""
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

from services.campaigns import api, creation, service
from services.persistence.launch import CampaignRepository
from services.workspace import state

LEAD = "00000000-0000-4000-8000-000000000041"


def database_error(code, message):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


@pytest.fixture
def database(monkeypatch):
    db = SimpleNamespace(rows={}, links=set(), commits=0, calls=0, lose_response=False, error=None, reload_error=None, lock=threading.Lock())

    class Read:
        def __init__(self): self.filters = {}
        def select(self, *_args): return self
        def eq(self, key, value): self.filters[key] = value; return self
        def limit(self, *_args): return self
        def execute(self):
            with db.lock:
                rows = [row for row in db.rows.values() if all(row.get(key) == value for key, value in self.filters.items())]
                return SimpleNamespace(data=rows)

    class RPC:
        def __init__(self, arguments): self.args = arguments
        def execute(self):
            args = self.args
            with db.lock:
                db.calls += 1
                if db.error: raise db.error
                campaign_id = args["p_campaign_id"]
                prior = db.rows.get(campaign_id)
                if prior:
                    if prior["metadata"]["creation_request_hash"] != args["p_request_hash"]:
                        raise database_error("23514", "Idempotency key belongs to a different request")
                    return SimpleNamespace(data={"campaign": prior, "created": False})
                row = {**args["p_campaign"], "id": campaign_id, "workspace_id": args["p_workspace_id"],
                       "created_by": args["p_actor_user_id"], "metadata": {"creation_request_hash": args["p_request_hash"]}}
                db.rows[campaign_id] = row
                db.links.update((campaign_id, lead_id) for lead_id in args["p_lead_ids"])
                db.commits += 1
                if db.lose_response:
                    db.lose_response = False
                    raise httpx.ReadTimeout("response lost after commit")
                return SimpleNamespace(data={"campaign": row, "created": True})

    class Client:
        def table(self, table): assert table == "campaigns"; return Read()
        def rpc(self, name, args): assert name == "create_workspace_campaign_once"; return RPC(args)

    monkeypatch.setattr(CampaignRepository, "_client", lambda _self: Client())
    async def authorized(_workspace, lead): return {"id": lead["workspace_lead_id"], "workspace_lead_id": lead["workspace_lead_id"]}
    monkeypatch.setattr(service, "_authorize_selected_lead", authorized)
    async def authorize(_request, **_kwargs): return "actor", "token", "workspace"
    monkeypatch.setattr(api, "_authorized_workspace", authorize)
    def load(_actor, campaign_id, *, workspace_id, strict):
        assert strict
        if db.reload_error: raise db.reload_error
        row = db.rows.get(campaign_id)
        if row is None or row["workspace_id"] != workspace_id: return None
        leads = [{"id": lead_id} for cid, lead_id in db.links if cid == campaign_id]
        return {**row, "leads": leads, "lead_count": len(leads)}
    monkeypatch.setattr(state, "load_campaign_state", load)
    monkeypatch.setattr(state, "append_event", Mock(return_value=True))
    monkeypatch.setattr(service, "publish", Mock())
    monkeypatch.setattr(service, "get_activity_repository", lambda: SimpleNamespace(append_campaign_created=lambda **_kwargs: None))
    monkeypatch.setattr("services.workspace.timeline.record_campaign_created", Mock())
    monkeypatch.setattr(service, "_feedback", lambda: SimpleNamespace(on_campaign_created=Mock()))
    monkeypatch.setattr(service, "maybe_auto_strategy", AsyncMock(side_effect=AssertionError("Implicit strategy generation is forbidden")))
    return db


def payload(key="intent", name="Selected prospects"):
    return api.SaveCampaignRequest(name=name, objective="Meet buyers", idempotency_key=key, leads=[{"workspace_lead_id": LEAD}])


async def create(request=None):
    return await api.save_campaign("_", request or payload(), SimpleNamespace())


@pytest.mark.asyncio
async def test_lost_response_recovers_commit_after_fresh_repository_instance(database):
    database.lose_response = True
    with pytest.raises(httpx.ReadTimeout): await create()
    recovered = await create()
    assert recovered["ok"] and recovered["campaign"]["lead_count"] == 1
    assert database.commits == 1 and len(database.links) == 1
    assert database.calls == 1  # Recovery reads the durable row, not an application cache.


@pytest.mark.asyncio
async def test_concurrent_same_key_commits_one_campaign_and_one_attachment(database):
    results = await asyncio.gather(*(create() for _ in range(8)))
    assert len({result["campaign"]["id"] for result in results}) == 1
    assert database.commits == len(database.rows) == len(database.links) == 1
    service.maybe_auto_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_materially_changed_payload_rejected(database):
    await create()
    with pytest.raises(HTTPException) as error: await create(payload(name="Different intent"))
    assert error.value.status_code == 409
    assert database.commits == 1


@pytest.mark.asyncio
async def test_concurrent_conflicting_payload_rejected(database):
    results = await asyncio.gather(create(), create(payload(name="Different intent")), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1 and failures[0].status_code == 409
    assert database.commits == 1


@pytest.mark.asyncio
async def test_unrelated_intent_and_authorized_workspace_actor_scopes_are_distinct(database, monkeypatch):
    first = await create()
    second = await create(payload(key="new-intent"))
    async def other_workspace(_request, **_kwargs): return "actor", "token", "other-workspace"
    monkeypatch.setattr(api, "_authorized_workspace", other_workspace)
    third = await create()
    async def other_actor(_request, **_kwargs): return "other-actor", "token", "workspace"
    monkeypatch.setattr(api, "_authorized_workspace", other_actor)
    fourth = await create()
    assert len({result["campaign"]["id"] for result in [first, second, third, fourth]}) == 4


@pytest.mark.asyncio
async def test_authorization_failure_prevents_creation(database, monkeypatch):
    async def forbidden(_request, **_kwargs): raise HTTPException(403, "Workspace denied")
    monkeypatch.setattr(api, "_authorized_workspace", forbidden)
    with pytest.raises(HTTPException): await create()
    assert database.rows == {} and database.calls == 0


@pytest.mark.asyncio
async def test_hydration_failure_does_not_delete_committed_campaign(database):
    database.reload_error = RuntimeError("projection failure")
    with pytest.raises(RuntimeError, match="projection failure"): await create()
    assert database.commits == 1
    database.reload_error = None
    assert (await create())["campaign"]["lead_count"] == 1
    assert database.commits == 1


@pytest.mark.asyncio
async def test_missing_post_commit_hydration_reports_recoverable_outcome(database, monkeypatch):
    loader = state.load_campaign_state
    monkeypatch.setattr(state, "load_campaign_state", lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException) as error:
        await create()
    assert error.value.status_code == 503
    assert "committed" in error.value.detail and "same key" in error.value.detail
    assert database.commits == len(database.rows) == len(database.links) == 1
    monkeypatch.setattr(state, "load_campaign_state", loader)
    assert (await create())["campaign"]["lead_count"] == 1
    assert database.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code,message", [("PGRST202", "RPC unavailable"), ("23514", "Invalid schema constraint"), ("42501", "permission denied for function")])
async def test_unrelated_schema_and_configuration_errors_propagate(database, code, message):
    database.error = database_error(code, message)
    with pytest.raises(APIError) as caught: await create()
    assert caught.value is database.error
    assert database.rows == {}


@pytest.mark.asyncio
async def test_stored_strategy_and_campaign_are_not_overwritten_on_replay(database):
    original = await create()
    campaign_id = original["campaign"]["id"]
    database.rows[campaign_id]["name"] = "Later user edit"
    recovered = await create()
    assert recovered["campaign"]["name"] == "Later user edit"
    assert database.commits == 1


def test_transaction_sql_contract_uses_existing_tables_and_scoped_locks():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/048_campaign_creation_idempotency.sql").read_text()
    assert "pg_advisory_xact_lock" in sql and "for update" in sql
    assert "creation_request_hash" in sql and "v_campaign.created_by" in sql
    assert "jsonb_typeof(v_campaign.metadata) = 'string'" in sql
    assert "l.workspace_id = p_workspace_id" in sql and "for share" in sql
    assert "insert into campaigns" in sql and "insert into campaign_leads" in sql
    assert "create table" not in sql.lower()
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "exception when" not in sql.lower()  # A failed attachment cannot commit half the transaction.


def test_creation_identity_normalizes_defaults_but_does_not_dedupe_intent():
    first = creation.creation_identity("workspace", "actor", "key", {"name": "Same"})
    assert first == creation.creation_identity("workspace", "actor", "key", {"name": "Same", "objective": "", "leads": []})
    assert first[0] != creation.creation_identity("workspace", "actor", "new-key", {"name": "Same"})[0]
    leads = [{"workspace_lead_id": "one"}, {"workspace_lead_id": "two"}]
    assert creation.creation_identity("workspace", "actor", "key", {"name": "Same", "leads": leads}) == creation.creation_identity("workspace", "actor", "key", {"name": "Same", "leads": list(reversed(leads))})


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, [], {"created": True, "campaign": None}])
async def test_unconfirmed_rpc_response_is_not_success(monkeypatch, response):
    client = SimpleNamespace(rpc=lambda *_args: SimpleNamespace(execute=lambda: SimpleNamespace(data=response)))
    monkeypatch.setattr(CampaignRepository, "_client", lambda _self: client)
    with pytest.raises(RuntimeError, match="commit was not confirmed"):
        await CampaignRepository().create_once(
            campaign_id="campaign", workspace_id="workspace", actor_user_id="actor",
            request_hash="hash", campaign={"name": "Campaign", "objective": "", "status": "planning", "search_query": "", "discovery_id": ""}, lead_ids=[],
        )


@pytest.mark.asyncio
async def test_creation_lookup_outage_is_not_missing_campaign(monkeypatch):
    monkeypatch.setattr(CampaignRepository, "_client", lambda _self: None)
    with pytest.raises(RuntimeError, match="persistence is unavailable"):
        await creation.recover_creation("workspace", "actor", "campaign", "hash")


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", ["timeline", "publication", "feedback"])
async def test_post_commit_failure_recovers_campaign_without_replaying_effects(database, monkeypatch, effect):
    failure = RuntimeError("offline auxiliary effect failed")
    failing = Mock(side_effect=failure)
    if effect == "timeline":
        monkeypatch.setattr("services.workspace.timeline.record_campaign_created", failing)
    elif effect == "publication":
        monkeypatch.setattr(service, "publish", failing)
    else:
        monkeypatch.setattr(service, "_feedback", lambda: SimpleNamespace(on_campaign_created=failing))
    with pytest.raises(RuntimeError) as error:
        await create()
    assert error.value is failure
    assert database.commits == len(database.rows) == len(database.links) == 1
    calls = failing.call_count
    recovered = await create()
    assert recovered["ok"] and recovered["campaign"]["lead_count"] == 1
    assert database.commits == 1 and failing.call_count == calls


@pytest.mark.asyncio
async def test_activity_failure_is_observable_without_failing_committed_creation(database, monkeypatch, caplog):
    append = Mock(side_effect=RuntimeError("offline activity unavailable"))
    monkeypatch.setattr(service, "get_activity_repository", lambda: SimpleNamespace(append_campaign_created=append))
    result = await create()
    assert result["ok"] and database.commits == 1
    assert "workspace_activity_append_failed" in caplog.text
    assert (await create())["campaign"]["id"] == result["campaign"]["id"]
    assert append.call_count == 1  # Replay recovers the entity, not a projection repair.


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [True, False])
async def test_compatibility_event_failure_does_not_delete_committed_campaign(database, monkeypatch, caplog, raises):
    append = Mock(side_effect=RuntimeError("offline event unavailable") if raises else None, return_value=False)
    monkeypatch.setattr(state, "append_event", append)
    result = await create()
    # Let the existing bounded thread callback settle; no external work occurs.
    for _ in range(100):
        if "compatibility event append failed" in caplog.text or "campaign_compatibility_event_unconfirmed" in caplog.text:
            break
        await asyncio.sleep(0.001)
    assert "compatibility event append failed" in caplog.text if raises else "campaign_compatibility_event_unconfirmed" in caplog.text
    assert (await create())["campaign"]["id"] == result["campaign"]["id"]
    assert database.commits == 1 and append.call_count == 1


@pytest.mark.asyncio
async def test_replay_rechecks_request_authorization_before_reading_original_campaign(database, monkeypatch):
    await create()
    calls = database.calls
    async def denied(_request, **_kwargs):
        raise HTTPException(404, "Workspace not found")
    monkeypatch.setattr(api, "_authorized_workspace", denied)
    with pytest.raises(HTTPException) as error:
        await create()
    assert error.value.status_code == 404 and database.calls == calls
