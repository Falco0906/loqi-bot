"""Regression tests: drafts with no recipient email are guarded at email execution.

LinkedIn-only leads (no email) stay reviewable and approvable for research and
prospecting, but must never reach Gmail. Guards live at the email-execution
boundaries:

  - send_draft: returns "This lead has no email address" without resolving a
    provider or invoking the executor.
  - schedule_draft: same guard.
  - _dispatch_campaign_sends (Launch): skips no-email drafts, reports them as
    failed with the explicit error, and never calls the executor for them.
  - _call_outbound_approval: does not create a Gmail draft for no-email drafts.

No Supabase or Gmail runs: stores/providers are faked like the other suites.
"""
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

import main as main_module  # noqa: E402
import services.workspace_state as workspace_state  # noqa: E402
from services.outbound import outbound_registry  # noqa: E402
from services.outbound.outbound_models import (  # noqa: E402
    ApprovalState,
    DraftMessage,
    DraftStatus,
    Recipient,
)
from services.outbound.draft_store import DraftStore  # noqa: E402
import services.outbound.draft_store as outbound_draft_store_module  # noqa: E402
from services.communication import provider_registry as comm_registry  # noqa: E402

OWNER = "owner-0000-0000-0000-000000000001"
SESSION = "session-under-test"

NO_EMAIL_ERROR = "This lead has no email address"


class FakeComm:
    def __init__(self, user_id, email="", connected=True):
        self._user_id = user_id
        self._mailbox_email = email
        self._connected = connected

    def disconnect(self):
        self._connected = False


class FakeOutbound:
    provider_type = "gmail"

    def __init__(self, provider_id):
        self._provider_id = provider_id


def register_provider(provider_id: str, user_id: str, email: str = "") -> str:
    pid = provider_id or str(uuid.uuid4())
    comm_registry.register_instance(pid, FakeComm(user_id=user_id, email=email))
    outbound_registry.register_instance(pid, FakeOutbound(pid))
    return pid


def clear_providers() -> None:
    comm_registry._instances.clear()
    outbound_registry._instances.clear()


@pytest.fixture(autouse=True)
def clean_registries():
    clear_providers()
    outbound_draft_store_module.draft_store.clear()
    yield
    clear_providers()
    outbound_draft_store_module.draft_store.clear()


def make_outbound_draft(
    draft_id: str,
    email: str,
    provider_id: str = "campaign",
    status: DraftStatus = DraftStatus.APPROVED,
) -> DraftMessage:
    draft = DraftMessage(
        id=draft_id,
        provider_id=provider_id,
        subject="Subject",
        body="Body",
        recipient=Recipient(email=email, name="Lead"),
        sender=Recipient(email="", name=""),
        status=status,
        approval_state=ApprovalState.APPROVED if status == DraftStatus.APPROVED else ApprovalState.PENDING,
    )
    outbound_draft_store_module.draft_store.create(draft)
    return draft


class FakeRequest:
    """Minimal Request stand-in: the endpoints only read Authorization headers."""

    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


class TestSendAndScheduleEndpointGuard:
    @pytest.fixture(scope="module")
    def owner(self):
        return "7de769b4-d450-4033-95ab-2718129f905a"

    @pytest.fixture(scope="module")
    def mint_token(self):
        def _mint():
            import asyncio
            from services.identity import api as identity_api
            svc = identity_api._get_service()
            session, _ = asyncio.run(
                svc._session_svc.create_session(
                    user_id="7de769b4-d450-4033-95ab-2718129f905a", organization_id=""
                )
            )
            return session.id
        return _mint

    @pytest.fixture(autouse=True)
    def _restore_executor(self):
        original = main_module.outbound_executor
        yield
        main_module.outbound_executor = original

    def test_send_draft_without_recipient_email_is_blocked(self, mint_token):
        draft = make_outbound_draft("draft-no-email-send", email="")

        class ExplodingExecutor:
            def execute(self, action, params):
                raise AssertionError("executor must never run for a no-email draft")

        main_module.outbound_executor = ExplodingExecutor()
        import asyncio
        body = asyncio.run(main_module.send_draft("ANY", draft.id, FakeRequest(mint_token())))
        assert body.get("ok") is False
        assert body.get("error") == NO_EMAIL_ERROR
        assert outbound_draft_store_module.draft_store.get(draft.id).status == DraftStatus.APPROVED

    def test_send_draft_with_email_passes_guard(self, mint_token):
        draft = make_outbound_draft("draft-with-email-send", email="lead@example.com")

        class ExplodingExecutor:
            def execute(self, action, params):
                raise AssertionError("executor must never run without a provider")

        main_module.outbound_executor = ExplodingExecutor()
        import asyncio
        body = asyncio.run(main_module.send_draft("ANY", draft.id, FakeRequest(mint_token())))
        assert body.get("ok") is False
        assert body.get("error") == "No Gmail outbound provider registered"

    def test_schedule_draft_without_recipient_email_is_blocked(self, mint_token):
        draft = make_outbound_draft("draft-no-email-schedule", email="")
        import asyncio
        payload = main_module.ScheduleDraftRequest(send_at="2026-08-11T12:00:00Z")
        body = asyncio.run(main_module.schedule_draft("ANY", draft.id, payload, FakeRequest(mint_token())))
        assert body.get("ok") is False
        assert body.get("error") == NO_EMAIL_ERROR


class TestOutboundApprovalAdapterGuard:
    def test_no_email_draft_skips_gmail_draft_creation(self, monkeypatch):
        draft = make_outbound_draft(
            "draft-adapt-no-email", email="", status=DraftStatus.PENDING_APPROVAL
        )
        register_provider("prov-a", OWNER, email="a@x.com")
        calls = []

        def fake_create_draft(*args, **kwargs):
            calls.append((args, kwargs))

        monkeypatch.setattr(outbound_registry, "create_draft", fake_create_draft)
        main_module._call_outbound_approval(draft.id, {})
        assert calls == []

    def test_with_email_still_creates_gmail_draft(self, monkeypatch):
        draft = make_outbound_draft(
            "draft-adapt-email", email="lead@example.com", status=DraftStatus.PENDING_APPROVAL
        )
        provider = register_provider("prov-b", OWNER, email="a@x.com")
        captured = {}

        def fake_create_draft(provider_id, outbound_draft):
            captured["provider_id"] = provider_id
            captured["draft_id"] = outbound_draft.id
            return SimpleNamespace(external_draft_id="ext-1", thread_id="th-1")

        monkeypatch.setattr(outbound_registry, "create_draft", fake_create_draft)
        main_module._call_outbound_approval(draft.id, {})
        assert captured == {"provider_id": provider, "draft_id": draft.id}


def _durable_draft(draft_id: str, campaign_id: str = "c-1", status: str = "approved",
                   email: str = "ada@acme.com") -> dict:
    return {
        "id": draft_id,
        "campaign_id": campaign_id,
        "lead_id": f"lead-{draft_id}",
        "lead": {"email": email, "name": "Ada Lovelace"},
        "subject": "Hi",
        "text": "Body",
        "body": "Body",
        "status": status,
    }


def _campaign(**overrides) -> dict:
    campaign = {
        "id": "c-1",
        "name": "Outbound",
        "objective": "Book demos",
        "status": "planning",
        "lead_count": 2,
    }
    campaign.update(overrides)
    return campaign


class _FakeFeedback:
    def on_campaign_launched(self, session_token: str, campaign_id: str) -> None:
        return None


class TestLaunchDispatchGuard:
    @pytest.fixture
    def env(self, monkeypatch):
        """Fresh outbound store + fake workspace_state for one launch."""
        original_store = outbound_draft_store_module.draft_store
        outbound_draft_store_module.draft_store = DraftStore()
        state = {
            "drafts": [],
            "campaigns": [_campaign()],
            "campaign_updates": [],
            "draft_updates": [],
        }
        calls: list[dict] = []

        async def fake_owner(session_token: str, request=None) -> str:
            return "owner-1"

        def fake_campaigns(owner_id: str, session_token: str = "") -> list[dict]:
            return list(state["campaigns"])

        def fake_drafts(owner_id: str, session_token: str = "") -> list[dict]:
            return list(state["drafts"])

        async def fake_persist_campaign(owner_id: str, campaign_id: str, updates: dict) -> bool:
            state["campaign_updates"].append((campaign_id, dict(updates)))
            return True

        async def fake_persist_draft(owner_id: str, draft_id: str, updates: dict) -> bool:
            state["draft_updates"].append((draft_id, dict(updates)))
            for d in state["drafts"]:
                if d["id"] == draft_id:
                    d.update(updates)
            return True

        def fake_execute(kind: str, payload: dict) -> dict:
            calls.append(payload)
            return {"ok": True, "send_result": {"thread_id": "th-1", "external_message_id": "em-1"}}

        monkeypatch.setattr(main_module, "_workspace_owner", fake_owner)
        monkeypatch.setattr(main_module, "_workspace_campaigns", fake_campaigns)
        monkeypatch.setattr(main_module, "_workspace_drafts", fake_drafts)
        monkeypatch.setattr(workspace_state, "persist_campaign_update_awaited", fake_persist_campaign)
        monkeypatch.setattr(workspace_state, "persist_draft_update_awaited", fake_persist_draft)
        monkeypatch.setattr(main_module, "_find_outbound_gmail_provider_id", lambda: "prov-1")
        monkeypatch.setattr(main_module, "publish", lambda *a, **k: None)
        monkeypatch.setattr(main_module, "record_campaign_launched", lambda *a, **k: None)
        monkeypatch.setattr(main_module, "_get_feedback", lambda: _FakeFeedback())
        monkeypatch.setattr(main_module.outbound_executor, "execute", fake_execute)

        yield {"state": state, "calls": calls}
        outbound_draft_store_module.draft_store = original_store

    async def test_launch_skips_no_email_draft_and_sends_the_rest(self, env):
        env["state"]["drafts"] = [
            _durable_draft("d-with-email", email="ada@acme.com"),
            _durable_draft("d-no-email", email=""),
        ]
        result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")

        assert result["total"] == 2
        assert result["sent"] == 1
        assert result["failed"] == 1
        assert [c["draft_id"] for c in env["calls"]] == ["d-with-email"]

        failed = [r for r in result["results"] if r["draft_id"] == "d-no-email"]
        assert failed == [{"draft_id": "d-no-email", "ok": False, "error": NO_EMAIL_ERROR}]

        sent_marks = {draft_id for draft_id, u in env["state"]["draft_updates"] if u.get("status") == "sent"}
        assert sent_marks == {"d-with-email"}, "no-email draft must never be marked sent"

    async def test_launch_only_no_email_drafts_fails_everything(self, env):
        env["state"]["drafts"] = [_durable_draft("d-no-email", email="")]
        result = await main_module._dispatch_campaign_sends("tok-1", _campaign(), "owner-1")

        assert result["total"] == 1
        assert result["sent"] == 0
        assert result["failed"] == 1
        assert env["calls"] == []
        assert result["results"] == [{"draft_id": "d-no-email", "ok": False, "error": NO_EMAIL_ERROR}]
