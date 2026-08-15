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
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

import services.workspace_state as workspace_state
from services.outbound.draft_store import draft_store as outbound_draft_store
from services.outbound.outbound_models import DraftMessage, DraftStatus, Recipient
from services.persistence.launch.models import Draft

import main as main_module  # noqa: E402


def _fake_owner(owner_id: str):
    async def fake_owner(request, session_token: str) -> str:
        return owner_id

    return fake_owner


@pytest.fixture(autouse=True)
def _clean_outbound_store():
    outbound_draft_store._drafts.clear()
    yield
    outbound_draft_store._drafts.clear()


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
    outbound_draft_store.create(draft)
    return draft


class TestApprovalLifecycle:
    async def test_A_approved_draft_toggle_still_works(self, monkeypatch):
        drafts = [{"id": "d-ap", "status": "approved", "campaign_id": None}]
        state = {"drafts": drafts, "campaigns": []}
        persisted: list[tuple[str, str, dict]] = []

        async def fake_persist(user_id: str, draft_id: str, updates: dict) -> bool:
            persisted.append((user_id, draft_id, updates))
            return True

        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False: state,
        )
        monkeypatch.setattr(
            workspace_state, "persist_draft_update_awaited", fake_persist)

        result = await main_module.approve_draft("token", "d-ap", MagicMock())

        assert result["ok"] is True
        assert result["draft"]["status"] == "pending"
        assert persisted[-1][2]["status"] == "pending"

    async def test_B_approve_sent_draft_rejected_409(self, monkeypatch):
        drafts = [{"id": "d-sent", "status": "sent", "campaign_id": None}]
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False: {"drafts": drafts, "campaigns": []},
        )

        with pytest.raises(Exception) as exc_info:
            await main_module.approve_draft("token", "d-sent", MagicMock())
        assert getattr(exc_info.value, "status_code", None) == 409
        assert "already sent" in str(exc_info.value.detail)

    async def test_B2_approve_sending_draft_rejected_409(self, monkeypatch):
        drafts = [{"id": "d-sending", "status": "sending", "campaign_id": None}]
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            workspace_state, "load_workspace_state",
            lambda uid, include_details=False: {"drafts": drafts, "campaigns": []},
        )

        with pytest.raises(Exception) as exc_info:
            await main_module.approve_draft("token", "d-sending", MagicMock())
        assert getattr(exc_info.value, "status_code", None) == 409


class TestDurableSentStatus:
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
        monkeypatch.setattr(workspace_state, "_session_id", lambda user_id: "ws-1")
        monkeypatch.setattr("services.supabase.get_supabase_client", lambda: MagicMock())

        ok = asyncio.run(workspace_state.persist_draft_update_awaited(
            "user-1", draft.id, {"status": "sent"}))
        assert ok is True

        reloaded = workspace_state.load_drafts_only("user-1")
        row = next(d for d in reloaded if d["id"] == draft.id)
        assert row["status"] == "sent"
        assert row["sent_at"] is not None

        assert rows[draft.id].status == "sent"
        assert rows[draft.id].sent_at is not None


class TestSendDraftGuard:
    async def test_D_send_draft_on_sent_returns_ok_false_without_executor(self, monkeypatch):
        draft = _sent_outbound_draft(DraftStatus.SENT)
        calls: list = []

        def fake_execute(action_type: str, params: dict):
            calls.append((action_type, params))
            return {"ok": True, "send_result": {}}

        monkeypatch.setattr(main_module, "outbound_executor",
                            MagicMock(execute=fake_execute))

        result = await main_module.send_draft("token", draft.id, MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}
        assert calls == []

    async def test_D2_send_draft_on_sending_returns_ok_false_without_executor(self, monkeypatch):
        draft = _sent_outbound_draft(DraftStatus.SENDING)
        calls: list = []

        def fake_execute(action_type: str, params: dict):
            calls.append((action_type, params))
            return {"ok": True, "send_result": {}}

        monkeypatch.setattr(main_module, "outbound_executor",
                            MagicMock(execute=fake_execute))

        result = await main_module.send_draft("token", draft.id, MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}
        assert calls == []

    async def test_D3_durable_sent_draft_guard_fires_before_sync(self, monkeypatch):
        """A durable-row sent draft is caught before _sync_draft_to_outbound."""
        synced: list = []
        monkeypatch.setattr(main_module, "_workspace_owner", _fake_owner("owner-1"))
        monkeypatch.setattr(
            main_module, "_workspace_drafts",
            lambda uid, tok="": [{"id": "d-durable-sent", "status": "sent"}],
        )
        monkeypatch.setattr(main_module, "_sync_draft_to_outbound",
                            lambda draft, tok: synced.append(draft))

        result = await main_module.send_draft("token", "d-durable-sent", MagicMock())

        assert result == {"ok": False, "error": "Draft already sent"}
        assert synced == []
