"""Regression tests: drafts with no recipient email are guarded at email execution.

LinkedIn-only leads (no email) stay reviewable and approvable for research and
prospecting, but must never reach Gmail. Guards live at the email-execution
boundaries:

  - send_draft: returns "This lead has no email address" without resolving a
    provider or invoking the executor.
  - schedule_draft: same guard.
  - campaign launch dispatch: skips no-email drafts, reports them as
    failed with the explicit error, and never calls the executor for them.
  - provider-draft creation after approval does not create a Gmail draft for no-email drafts.

No Supabase or Gmail runs: stores/providers are faked like the other suites.
"""
import asyncio
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

import main as main_module  # noqa: E402
import services.outbound.service as outbound_service  # noqa: E402
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
    @pytest.fixture
    def canonical_drafts(self, monkeypatch):
        """Exercise send/schedule through their canonical-Draft boundary.

        The outbound DraftStore is a projection, so the endpoint must not be
        tested by seeding it alone. This fixture supplies the authoritative
        workspace draft read and avoids an unrelated Supabase dependency.
        """
        drafts: dict[str, dict] = {}

        async def fake_owner(request, session_token):
            return OWNER

        async def fake_workspace(request, owner_id):
            return "workspace-test"

        def fake_workspace_drafts(owner_id, session_token="", workspace_id=""):
            assert owner_id == OWNER
            assert workspace_id == "workspace-test"
            return list(drafts.values())

        monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda request: SESSION)
        monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", fake_owner)
        monkeypatch.setattr(main_module.workspace_access, "resolve_legacy_workspace_id", fake_workspace)
        monkeypatch.setattr(main_module, "_workspace_drafts", fake_workspace_drafts)
        monkeypatch.setattr(workspace_state, "load_drafts_only", lambda owner_id, workspace_id="": fake_workspace_drafts(owner_id, workspace_id=workspace_id))
        return drafts

    @staticmethod
    def _canonical_draft(draft: DraftMessage) -> dict:
        return {
            "id": draft.id,
            "campaign_id": draft.workflow_id,
            "status": "approved",
            "subject": draft.subject,
            "text": draft.body,
            "lead": {
                "email": draft.recipient.email,
                "name": draft.recipient.name,
            },
        }

    @pytest.fixture(autouse=True)
    def _restore_executor(self):
        original = main_module.outbound_executor
        service_original = outbound_service.outbound_executor
        yield
        main_module.outbound_executor = original
        outbound_service.outbound_executor = service_original

    def test_send_draft_without_recipient_email_is_blocked(self, canonical_drafts):
        draft = make_outbound_draft("draft-no-email-send", email="")
        canonical_drafts[draft.id] = self._canonical_draft(draft)

        class ExplodingExecutor:
            def execute(self, action, params):
                raise AssertionError("executor must never run for a no-email draft")

        main_module.outbound_executor = ExplodingExecutor()
        outbound_service.outbound_executor = main_module.outbound_executor
        import asyncio
        body = asyncio.run(main_module.send_draft("ANY", draft.id, FakeRequest(SESSION)))
        assert body.get("ok") is False
        assert body.get("error") == NO_EMAIL_ERROR
        assert outbound_draft_store_module.draft_store.get(draft.id).status == DraftStatus.APPROVED

    def test_send_draft_with_email_passes_guard(self, canonical_drafts):
        draft = make_outbound_draft("draft-with-email-send", email="lead@example.com")
        canonical_drafts[draft.id] = self._canonical_draft(draft)

        class ExplodingExecutor:
            def execute(self, action, params):
                raise AssertionError("executor must never run without a provider")

        main_module.outbound_executor = ExplodingExecutor()
        outbound_service.outbound_executor = main_module.outbound_executor
        import asyncio
        body = asyncio.run(main_module.send_draft("ANY", draft.id, FakeRequest(SESSION)))
        assert body.get("ok") is False
        assert body.get("error") == "No Gmail outbound provider registered"

    def test_schedule_draft_without_recipient_email_is_blocked(self, canonical_drafts):
        draft = make_outbound_draft("draft-no-email-schedule", email="")
        canonical_drafts[draft.id] = self._canonical_draft(draft)
        import asyncio
        payload = main_module.ScheduleDraftRequest(send_at="2026-08-11T12:00:00Z")
        body = asyncio.run(main_module.schedule_draft("ANY", draft.id, payload, FakeRequest(SESSION)))
        assert body.get("ok") is False
        assert body.get("error") == NO_EMAIL_ERROR


class TestOutboundApprovalAdapterGuard:
    async def test_no_email_draft_skips_gmail_draft_creation(self, monkeypatch):
        draft = make_outbound_draft(
            "draft-adapt-no-email", email="", status=DraftStatus.PENDING_APPROVAL
        )
        register_provider("prov-a", OWNER, email="a@x.com")
        calls = []

        def fake_create_draft(*args, **kwargs):
            calls.append((args, kwargs))

        monkeypatch.setattr(outbound_registry, "create_draft", fake_create_draft)
        monkeypatch.setattr(outbound_service, "persist_outbound_projection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        await outbound_service.create_provider_draft_after_approval(
            _durable_draft(draft.id, status="pending", email=""), SESSION, OWNER, "workspace-test",
        )
        assert calls == []

    async def test_with_email_still_creates_gmail_draft(self, monkeypatch):
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
        monkeypatch.setattr(outbound_service, "persist_outbound_projection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        await outbound_service.create_provider_draft_after_approval(
            _durable_draft(draft.id, status="pending", email="lead@example.com"), SESSION, OWNER, "workspace-test",
        )
        assert captured == {"provider_id": provider, "draft_id": draft.id}

    async def test_reapproval_with_durable_provider_draft_does_not_create_duplicate(self, monkeypatch):
        provider = register_provider("prov-reapprove", OWNER, email="a@x.com")
        calls = []

        def fake_create_draft(provider_id, outbound_draft):
            calls.append((provider_id, outbound_draft.id))
            return SimpleNamespace(external_draft_id="ext-original", thread_id="th-original")

        monkeypatch.setattr(outbound_registry, "create_draft", fake_create_draft)
        monkeypatch.setattr(outbound_service, "persist_outbound_projection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))

        initial = _durable_draft("draft-reapprove", status="approved", email="lead@example.com")
        await outbound_service.create_provider_draft_after_approval(
            initial, SESSION, OWNER, "workspace-test",
        )

        reapproved = _durable_draft("draft-reapprove", status="approved", email="lead@example.com")
        reapproved["metadata"] = {
            "outbound_projection": {
                "provider_id": provider,
                "external_draft_id": "ext-original",
                "status": "pending_approval",
                "approval_state": "pending",
                "recipient": {"email": "lead@example.com", "name": "Ada Lovelace"},
                "sender": {"email": "a@x.com", "name": ""},
            },
        }
        await outbound_service.create_provider_draft_after_approval(
            reapproved, SESSION, OWNER, "workspace-test",
        )

        assert calls == [(provider, "draft-reapprove")]


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

        def fake_campaigns(owner_id: str, workspace_id: str = "") -> list[dict]:
            return list(state["campaigns"])

        def fake_drafts(owner_id: str, session_token: str = "", workspace_id: str = "") -> list[dict]:
            return list(state["drafts"])

        async def fake_persist_campaign(owner_id: str, campaign_id: str, updates: dict) -> bool:
            state["campaign_updates"].append((campaign_id, dict(updates)))
            return True

        async def fake_persist_draft(
            owner_id: str, draft_id: str, updates: dict, workspace_id: str = "",
        ) -> bool:
            state["draft_updates"].append((draft_id, dict(updates)))
            for d in state["drafts"]:
                if d["id"] == draft_id:
                    d.update(updates)
            return True

        def fake_execute(kind: str, payload: dict) -> dict:
            calls.append(payload)
            return {"ok": True, "send_result": {"thread_id": "th-1", "external_message_id": "em-1"}}

        monkeypatch.setattr(main_module.identity_dependencies, "authenticated_user_id", fake_owner)
        monkeypatch.setattr(main_module, "load_campaigns", fake_campaigns)
        monkeypatch.setattr(main_module, "_workspace_drafts", fake_drafts)
        monkeypatch.setattr(workspace_state, "load_drafts_only", lambda owner_id, workspace_id="": fake_drafts(owner_id, workspace_id=workspace_id))
        monkeypatch.setattr(workspace_state, "persist_campaign_update_awaited", fake_persist_campaign)
        monkeypatch.setattr(workspace_state, "persist_draft_update_awaited", fake_persist_draft)
        monkeypatch.setattr(outbound_service, "find_outbound_gmail_provider_id", lambda: "prov-1")
        monkeypatch.setattr(main_module, "publish", lambda *a, **k: None)
        monkeypatch.setattr(main_module, "record_campaign_launched", lambda *a, **k: None)
        monkeypatch.setattr(main_module, "_get_feedback", lambda: _FakeFeedback())
        monkeypatch.setattr(outbound_service.outbound_executor, "execute", fake_execute)
        monkeypatch.setattr(outbound_service, "persist_outbound_projection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))

        yield {"state": state, "calls": calls}
        outbound_draft_store_module.draft_store = original_store

    async def test_launch_skips_no_email_draft_and_sends_the_rest(self, env):
        env["state"]["drafts"] = [
            _durable_draft("d-with-email", email="ada@acme.com"),
            _durable_draft("d-no-email", email=""),
        ]
        result = await outbound_service.dispatch_campaign_sends(
            "tok-1", _campaign(), "owner-1", workspace_id="workspace-test",
        )

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
        result = await outbound_service.dispatch_campaign_sends(
            "tok-1", _campaign(), "owner-1", workspace_id="workspace-test",
        )

        assert result["total"] == 1
        assert result["sent"] == 0
        assert result["failed"] == 1
        assert env["calls"] == []
        assert result["results"] == [{"draft_id": "d-no-email", "ok": False, "error": NO_EMAIL_ERROR}]
