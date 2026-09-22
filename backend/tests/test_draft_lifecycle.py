"""PR — Draft Lifecycle: sent drafts leave the actionable queue.

Covers:
  A. An approved durable draft stays in the Approved queue (approve toggle
     still works; no 409).
  B. A sent durable draft can never be approved (409 "Draft already sent").
  C. Durable sent status survives a reload: persist_draft_update_awaited
     writes the row, load_drafts_only reads it back as "sent" with sent_at.
  D. send_draft on a SENT/SENDING outbound draft returns
     {"ok": False, "error": "Draft already sent"} and never reaches the
     outbound executor (no double Gmail send).
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

import services.workspace.state as workspace_state
from services.drafts import api as drafts_api
from services.drafts import service as drafts_service
import services.outbound.service as outbound_service
from services.outbound.api import send_draft
from services.outbound.outbound_models import DraftMessage, DraftStatus, Recipient
from services.persistence.launch.models import Draft



def _fake_owner(owner_id: str):
    async def fake_owner(request, session_token: str) -> str:
        return owner_id

    return fake_owner


def _fake_workspace(workspace_id: str = "workspace-1"):
    async def fake_workspace(request, owner_id: str) -> str:
        return workspace_id

    return fake_workspace


def _sent_outbound_draft(status: DraftStatus) -> DraftMessage:
    draft = DraftMessage(
        id=f"draft-{uuid.uuid4().hex[:8]}",
        provider_id="prov-1",
        subject="Hello",
        body="Body",
        recipient=Recipient(email="lead@acme.com", name="Lead"),
        sender=Recipient(email="faisal@loqi.com", name="Faisal"),
        status=status,
    )
    return draft


class TestApprovalLifecycle:
    async def test_A_approved_draft_toggle_still_works(self, monkeypatch):
        drafts = [{"id": "d-ap", "status": "approved", "campaign_id": None}]
        state = {"drafts": drafts, "campaigns": []}
        persisted: list[tuple[str, str, dict, str]] = []

        async def fake_persist(
            user_id: str, draft_id: str, updates: dict, workspace_id: str = ""
        ) -> bool:
            persisted.append((user_id, draft_id, updates, workspace_id))
            return True

        monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", _fake_owner("owner-1"))
        monkeypatch.setattr(
            drafts_api.workspace_access, "resolve_legacy_workspace_id",
            _fake_workspace(),
        )
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False, workspace_id="": state,
        )
        monkeypatch.setattr(
            workspace_state, "persist_draft_update_awaited", fake_persist)

        result = await drafts_api.approve_draft("token", "d-ap", MagicMock())

        assert result["ok"] is True
        assert result["draft"]["status"] == "pending"
        assert persisted[-1][2]["status"] == "pending"
        assert persisted[-1][3] == "workspace-1"

    async def test_B_approve_sent_draft_rejected_409(self, monkeypatch):
        drafts = [{"id": "d-sent", "status": "sent", "campaign_id": None}]
        monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", _fake_owner("owner-1"))
        monkeypatch.setattr(
            drafts_api.workspace_access, "resolve_legacy_workspace_id",
            _fake_workspace(),
        )
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False, workspace_id="": {
                "drafts": drafts, "campaigns": []
            },
        )

        with pytest.raises(Exception) as exc_info:
            await drafts_api.approve_draft("token", "d-sent", MagicMock())
        assert getattr(exc_info.value, "status_code", None) == 409
        assert "already sent" in str(exc_info.value.detail)

    async def test_B2_approve_sending_draft_rejected_409(self, monkeypatch):
        drafts = [{"id": "d-sending", "status": "sending", "campaign_id": None}]
        monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", _fake_owner("owner-1"))
        monkeypatch.setattr(
            drafts_api.workspace_access, "resolve_legacy_workspace_id",
            _fake_workspace(),
        )
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False, workspace_id="": {
                "drafts": drafts, "campaigns": []
            },
        )

        with pytest.raises(Exception) as exc_info:
            await drafts_api.approve_draft("token", "d-sending", MagicMock())
        assert getattr(exc_info.value, "status_code", None) == 409

    async def test_C_pending_approval_returns_and_preserves_other_drafts(self, monkeypatch):
        drafts = [
            {
                "id": "d-pending",
                "status": "pending",
                "campaign_id": "campaign-1",
                "lead": {"name": "First lead"},
            },
            {
                "id": "d-other",
                "status": "pending",
                "campaign_id": "campaign-1",
                "lead": {"name": "Other lead"},
            },
        ]
        state = {"drafts": drafts, "campaigns": [{"id": "campaign-1"}]}
        persisted: list[tuple[str, str, dict, str]] = []
        emitted = AsyncMock()

        async def fake_persist(
            user_id: str, draft_id: str, updates: dict, workspace_id: str = ""
        ) -> bool:
            persisted.append((user_id, draft_id, updates, workspace_id))
            return True

        monkeypatch.setattr(drafts_api.identity_dependencies, "authenticated_user_id", _fake_owner("owner-1"))
        monkeypatch.setattr(
            drafts_api.workspace_access, "resolve_legacy_workspace_id",
            _fake_workspace(),
        )
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False, workspace_id="": state,
        )
        monkeypatch.setattr(
            workspace_state, "persist_draft_update_awaited", fake_persist
        )
        monkeypatch.setattr(outbound_service, "create_provider_draft_after_approval", AsyncMock())
        monkeypatch.setattr(drafts_service, "publish_draft_event", emitted)
        monkeypatch.setattr(drafts_service, "publish", lambda *args, **kwargs: None)

        result = await drafts_api.approve_draft("token", "d-pending", MagicMock())

        assert result["ok"] is True
        assert result["draft"]["status"] == "approved"
        assert persisted == [
            ("owner-1", "d-pending", {"status": "approved"}, "workspace-1")
        ]
        assert drafts[1]["status"] == "pending"
        emitted.assert_awaited_once()
        assert emitted.await_args.kwargs["campaign_id"] == "campaign-1"


class TestDurableSentStatus:
    def test_send_claim_status_is_permitted_by_the_durable_draft_constraint(self):
        """The durable compare-and-set must reach the provider send boundary.

        This test protects the production regression where the canonical
        ``sending`` claim was correct but the database constraint still
        reflected the pre-send-state lifecycle from migration 008.
        """
        migration = (
            Path(__file__).resolve().parents[1]
            / "supabase/migrations/047_draft_sending_status.sql"
        ).read_text()

        expected_statuses = {
            "draft",
            "pending",
            "generating",
            "approved",
            "rejected",
            "sending",
            "sent",
            "delivered",
            "failed",
            "scheduled",
            "cancelled",
            "archived",
        }
        for status in expected_statuses:
            assert f"'{status}'" in migration

    def test_C_sent_status_survives_reload(self, monkeypatch):
        rows: dict[str, Draft] = {}
        draft = Draft(
            id="draft-durable-1",
            workspace_id="ws-1",
            campaign_id="campaign-1",
            status="approved",
            subject="Hello",
            body="Body",
        )
        rows[draft.id] = draft

        class FakeRepo:
            async def list_for_workspace(self, workspace_id: str):
                return [d for d in rows.values() if d.workspace_id == workspace_id]

            async def get(self, entity_id: str):
                return rows.get(entity_id)

            async def save(self, entity):
                rows[entity.id] = entity

        monkeypatch.setattr(workspace_state, "DraftRepository", FakeRepo)
        monkeypatch.setattr(workspace_state, "_async_workspace", AsyncMock(return_value="ws-1"))
        monkeypatch.setattr(workspace_state, "get_supabase_client", lambda: MagicMock())

        ok = asyncio.run(workspace_state.persist_draft_update_awaited(
            "user-1", draft.id, {"status": "sent"}))
        assert ok is True

        reloaded = workspace_state.load_drafts_only("user-1")
        row = next(d for d in reloaded if d["id"] == draft.id)
        assert row["status"] == "sent"
        assert row["sent_at"] is not None

        assert rows[draft.id].status == "sent"
        assert rows[draft.id].sent_at is not None


class TestDraftAnalysisCompatibility:
    @pytest.mark.asyncio
    async def test_analysis_preserves_legacy_generation_error_envelope(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise drafts_service.OpenAIError("provider unavailable")

        monkeypatch.setattr(drafts_service, "analyze_draft_with_ai", unavailable)
        monkeypatch.setattr(drafts_service, "analyze_draft_intelligence", unavailable)

        result = await drafts_service.analyze_draft({"draft_text": "Hello"})

        assert result == {
            "ok": False,
            "analysis": None,
            "draft_intelligence": None,
            "error": "provider unavailable",
        }

    @pytest.mark.asyncio
    async def test_question_preserves_legacy_generation_error_envelope(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise drafts_service.OpenAIError("provider unavailable")

        monkeypatch.setattr(drafts_service, "answer_draft_question", unavailable)

        result = await drafts_service.ask_draft_question(
            {"question": "What should I improve?", "draft_text": "Hello"},
        )

        assert result == {
            "ok": False,
            "answer": "provider unavailable",
            "error": None,
        }


class TestSendDraftGuard:
    @staticmethod
    def _canonical_guard(monkeypatch, draft):
        async def resolve(*_args, **_kwargs):
            return "owner-1", "workspace-1", {"id": draft.id, "status": draft.status.value}, draft
        monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", resolve)

    async def test_D_send_draft_on_sent_returns_ok_false_without_executor(self, monkeypatch):
        draft = _sent_outbound_draft(DraftStatus.SENT)
        self._canonical_guard(monkeypatch, draft)
        calls: list = []

        def fake_send(*args, **kwargs):
            calls.append((args, kwargs))
            return {"ok": True, "send_result": {}}

        monkeypatch.setattr(outbound_service, "outbound_executor",
                            MagicMock(send_hydrated_draft=fake_send))

        result = await send_draft("token", draft.id, MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}
        assert calls == []

    async def test_D2_send_draft_on_sending_returns_ok_false_without_executor(self, monkeypatch):
        draft = _sent_outbound_draft(DraftStatus.SENDING)
        self._canonical_guard(monkeypatch, draft)
        calls: list = []

        def fake_send(*args, **kwargs):
            calls.append((args, kwargs))
            return {"ok": True, "send_result": {}}

        monkeypatch.setattr(outbound_service, "outbound_executor",
                            MagicMock(send_hydrated_draft=fake_send))

        result = await send_draft("token", draft.id, MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}
        assert calls == []

    async def test_D2b_non_actionable_draft_never_reaches_executor(self, monkeypatch):
        draft = _sent_outbound_draft(DraftStatus.DRAFT)
        self._canonical_guard(monkeypatch, draft)
        executor = MagicMock()
        monkeypatch.setattr(outbound_service, "outbound_executor", executor)

        result = await send_draft("token", draft.id, MagicMock())

        assert result == {"ok": False, "error": "Draft is not approved for sending"}
        executor.send_hydrated_draft.assert_not_called()

    async def test_D3_durable_sent_draft_guard_fires_before_sync(self, monkeypatch):
        """A durable-row sent draft is caught before projection hydration."""
        monkeypatch.setattr(outbound_service.identity_dependencies, "authenticated_user_id", _fake_owner("owner-1"))
        monkeypatch.setattr(
            workspace_state,
            "load_drafts_only",
            lambda uid, **_kwargs: [{"id": "d-durable-sent", "status": "sent"}],
        )
        outbound = _sent_outbound_draft(DraftStatus.SENT)
        self._canonical_guard(monkeypatch, outbound)

        result = await send_draft("token", "d-durable-sent", MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}

    @pytest.mark.asyncio
    async def test_D4_cancelled_send_claim_blocks_a_second_provider_call(self, monkeypatch):
        """A lost HTTP response cannot make a second request send Gmail twice."""
        draft = _sent_outbound_draft(DraftStatus.APPROVED)
        canonical = {"id": draft.id, "status": "approved"}
        claimed = {"value": False}
        provider_calls: list[str] = []
        entered = threading.Event()
        release = threading.Event()

        async def resolve(*_args, **_kwargs):
            return "owner-1", "workspace-1", canonical, draft

        async def claim(*_args, **_kwargs):
            if claimed["value"]:
                return False
            claimed["value"] = True
            return True

        def blocking_send(*_args, **_kwargs):
            provider_calls.append("gmail")
            entered.set()
            assert release.wait(timeout=1)
            return {"ok": True, "send_result": {"thread_id": "thread", "external_message_id": "message"}}

        monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", resolve)
        monkeypatch.setattr(outbound_service.workspace_state, "claim_draft_for_send", claim)
        monkeypatch.setattr(outbound_service, "resolve_provider_for_draft", lambda *_args: "provider-1")
        monkeypatch.setattr(
            outbound_service,
            "outbound_executor",
            MagicMock(send_hydrated_draft=blocking_send),
        )
        monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)

        first = asyncio.create_task(outbound_service.send_outbound_draft(MagicMock(), draft.id))
        assert await asyncio.to_thread(entered.wait, 1)

        # Simulate a client/network cancellation while the provider worker is
        # still executing.  Its durable claim remains the source of truth.
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        second = await outbound_service.send_outbound_draft(MagicMock(), draft.id)
        assert second == {"ok": False, "error": "Draft already sent"}
        assert provider_calls == ["gmail"]

        release.set()
