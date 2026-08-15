"""PR10.8.3.2 — Adversarial API authorization / IDOR audit regression suite.

Attempts to break tenant isolation through the actual HTTP route handlers:

- User A (attacker) is given User B's (victim's) real resource identifiers and
  attempts to read / modify / side-effect them.
- Parameters are treated as attacker-controlled; client-supplied user_id must
  never establish authorization.
- Chained (confused-deputy) relationships are tested (draft->provider->user).
- List endpoints are checked for cross-tenant leakage.
- Error responses are checked not to leak resource existence.

Sentinels only; no real credentials, emails, or outbound sends.
"""
import asyncio
import sys
import os
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException

import main as main_module
from services.outbound.draft_store import draft_store as outbound_draft_store
from services.outbound.outbound_models import DraftMessage, Recipient
from services.communication.communication_store import store as comm_store
from services.communication.gmail_provider import GmailProvider
from services.communication import provider_registry



class _FakeJobStorage:
    """In-memory job storage so IDOR tests never touch real Supabase."""

    def __init__(self):
        self.jobs = {}
        self.results = {}
        self.order = []

    def create_job(self, job):
        self.jobs[job.id] = job
        self.order.append(job.id)
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def update_job(self, job_id, **fields):
        job = self.jobs.get(job_id)
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
        return job

    def store_search_results(self, job_id, leads):
        self.results[job_id] = list(leads)
        return True

    def get_search_results(self, job_id):
        return self.results.get(job_id, [])

    def list_active_jobs(self, user_id):
        return [j for j in self.jobs.values() if j.user_id == user_id]

    def list_recent_jobs(self, user_id, limit=20):
        return [j for j in self.jobs.values() if j.user_id == user_id][:limit]


OWNER_A = "owner-a"
OWNER_B = "owner-b"
TOKEN_A = "token-a"
TOKEN_B = "token-b"

_OWNERS = {TOKEN_A: OWNER_A, TOKEN_B: OWNER_B}


@pytest.fixture(autouse=True)
def _clean_runtime_state(monkeypatch):
    from services.communication import provider_registry as pr
    from services.outbound import outbound_registry as or_reg
    from services.conversations.conversation_store import conversation_store

    for pid in list(pr.list_providers().keys()):
        pr.remove_instance(pid)
    for pid in list(or_reg.list_providers().keys()):
        or_reg.remove_instance(pid)
    comm_store._providers.clear()
    comm_store._user_providers.clear()
    comm_store._thread_mappings.clear()
    comm_store._by_conversation.clear()
    comm_store._seen_message_ids.clear()
    conversation_store.reload()
    outbound_draft_store._drafts.clear()
    outbound_draft_store._versions.clear()
    from services.workflow_runtime import _runtimes
    _runtimes.clear()
    from services.job_engine import job_manager
    job_manager._storage = _FakeJobStorage()
    # Deterministic per-token owner resolution for two-user tests.
    async def _resolve(request):
        token = main_module._session_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        return _OWNERS.get(token, "test-owner"), token
    monkeypatch.setattr(main_module, "_resolve_session_context", _resolve)

    async def _owner(request, session_token=""):
        token = main_module._session_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        return _OWNERS.get(token, "test-owner")
    monkeypatch.setattr(main_module, "_workspace_owner", _owner)
    yield


def _req(token):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request


def _provider(pid, user_id):
    from services.communication.provider_models import (
        CommunicationProvider, ProviderType, ProviderStatus,
    )
    comm_store._providers[pid] = CommunicationProvider(
        id=pid, provider_type=ProviderType.GMAIL, user_id=user_id,
        status=ProviderStatus.HEALTHY,
        metadata={"email": f"{user_id}@x.com", "account_id": f"{user_id}@x.com"},
    )


def _victim_draft(draft_id, provider_id="prov-b"):
    draft = DraftMessage(
        id=draft_id, provider_id=provider_id,
        subject="Victim draft", body="secret",
        recipient=Recipient(email="victim-target@x.com", name="Target"),
        sender=Recipient(email="victim@x.com", name="Victim"),
    )
    outbound_draft_store.create(draft)
    return draft


# ═══════════════════════════════════════════════════════════════════════
# A. Outbound draft IDOR (get / approve / reject / cancel / approve-all)
# ═══════════════════════════════════════════════════════════════════════

class TestOutboundDraftIdor:
    def test_get_victim_draft_denied(self):
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.outbound_get_draft("_", "draft-victim", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_approve_victim_draft_denied(self):
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.outbound_approve_draft("_", "draft-victim", False, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_reject_victim_draft_denied(self):
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.outbound_reject_draft("_", "draft-victim", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_cancel_victim_draft_schedule_denied(self):
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.cancel_schedule_draft("_", "draft-victim", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_owner_can_approve_own_draft(self):
        _provider("prov-a", OWNER_A)
        _victim_draft("draft-owner", "prov-a")
        result = asyncio.run(main_module.outbound_get_draft("_", "draft-owner", _req(TOKEN_A)))
        assert result["ok"] is True

    def test_approve_all_only_touches_owner_drafts(self):
        _provider("prov-a", OWNER_A)
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-a", "prov-a")
        _victim_draft("draft-b", "prov-b")
        payload = MagicMock()
        payload.auto = False
        result = asyncio.run(main_module.outbound_approve_all("_", payload, _req(TOKEN_A)))
        result_ids = [r["draft_id"] for r in result.get("results", [])]
        assert "draft-b" not in result_ids


# ═══════════════════════════════════════════════════════════════════════
# B. Job IDOR (get / results / list + parameter substitution)
# ═══════════════════════════════════════════════════════════════════════

class TestJobIdor:
    def _create_job_for(self, user_id):
        from services.job_engine import job_manager
        import asyncio as _a
        job = _a.run(job_manager.create_search_job(user_id, "query", discovery_id="d-1"))
        return job["job_id"]

    def test_get_victim_job_denied(self):
        victim_job = self._create_job_for(OWNER_B)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.get_job(victim_job, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_get_own_job_allowed(self):
        own_job = self._create_job_for(OWNER_A)
        result = asyncio.run(main_module.get_job(own_job, _req(TOKEN_A)))
        assert str(result["id"]) == own_job

    def test_get_victim_job_results_denied(self):
        victim_job = self._create_job_for(OWNER_B)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.get_job_results(victim_job, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_list_jobs_does_not_leak_other_user(self):
        self._create_job_for(OWNER_B)
        self._create_job_for(OWNER_A)
        result = asyncio.run(main_module.list_jobs(_req(TOKEN_A)))
        job_ids = [str(j.get("id")) for j in result["jobs"]]
        from services.job_engine import job_manager
        victim_jobs = job_manager.list_recent_jobs(OWNER_B)
        victim_ids = {str(j.get("id")) for j in victim_jobs}
        assert not (victim_ids & set(job_ids))


# ═══════════════════════════════════════════════════════════════════════
# C. Workflow IDOR (status / approve / pause / resume / cancel)
# ═══════════════════════════════════════════════════════════════════════

class TestWorkflowIdor:
    def _victim_workflow(self):
        from services.workflow_runtime import create_runtime
        wf = create_runtime({"goal": "x"}, session_token=TOKEN_B, workflow_id="wf-b")
        return wf.workflow_id

    def test_get_victim_workflow_denied(self):
        wf_id = self._victim_workflow()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.get_workflow_status("_", wf_id, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_approve_victim_workflow_denied(self):
        wf_id = self._victim_workflow()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.approve_workflow_step("_", wf_id, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_pause_victim_workflow_denied(self):
        wf_id = self._victim_workflow()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.pause_workflow_endpoint("_", wf_id, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_cancel_victim_workflow_denied(self):
        wf_id = self._victim_workflow()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.cancel_workflow_endpoint("_", wf_id, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_owner_can_read_own_workflow(self):
        wf_id = self._victim_workflow()
        result = asyncio.run(main_module.get_workflow_status("_", wf_id, _req(TOKEN_B)))
        assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════════
# D. Provider data IDOR (threads / messages)
# ═══════════════════════════════════════════════════════════════════════

class TestProviderDataIdor:
    def test_victim_provider_threads_denied(self):
        _provider("prov-b", OWNER_B)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.provider_threads("_", "prov-b", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_victim_provider_messages_denied(self):
        _provider("prov-b", OWNER_B)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.provider_messages("_", "prov-b", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_owner_provider_threads_allowed(self):
        _provider("prov-a", OWNER_A)
        result = asyncio.run(main_module.provider_threads("_", "prov-a", _req(TOKEN_A)))
        assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════════
# E. Draft history IDOR + batch status IDOR
# ═══════════════════════════════════════════════════════════════════════

class TestDraftHistoryAndBatchIdor:
    def test_victim_draft_history_denied(self):
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.draft_rewrite_history("_", "draft-victim", _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_victim_batch_status_denied(self):
        from main import batch_jobs
        victim_campaign = "campaign-b"
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        batch_jobs[batch_id] = {"campaign_id": victim_campaign, "status": "processing"}
        main_module._workspace_campaigns = lambda owner_id, session_token="": (
            [{"id": "campaign-a"}] if owner_id == OWNER_A else []
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.batch_status("_", batch_id, _req(TOKEN_A)))
        assert exc.value.status_code == 404
        batch_jobs.pop(batch_id, None)


# ═══════════════════════════════════════════════════════════════════════
# F. Chained (confused-deputy) + parameter substitution
# ═══════════════════════════════════════════════════════════════════════

class TestChainedAndSubstitution:
    def test_draft_provider_chain_victim_denied(self):
        # Victim draft references victim provider; attacker supplies both.
        _provider("prov-b", OWNER_B)
        _victim_draft("draft-victim", "prov-b")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main_module.outbound_approve_draft("_", "draft-victim", False, _req(TOKEN_A)))
        assert exc.value.status_code == 404

    def test_list_jobs_ignores_client_supplied_user_id(self):
        from services.job_engine import job_manager
        import asyncio as _a
        _a.run(job_manager.create_search_job(OWNER_B, "victim-query", discovery_id="d-1"))
        # Attacker lists with ?user_id=<victim> — must be ignored.
        request = _req(TOKEN_A)
        request.query_params = {"user_id": OWNER_B}
        result = asyncio.run(main_module.list_jobs(request))
        job_ids = [str(j.get("id")) for j in result["jobs"]]
        victim_ids = {str(j.get("id")) for j in job_manager.list_recent_jobs(OWNER_B)}
        assert not (victim_ids & set(job_ids))
