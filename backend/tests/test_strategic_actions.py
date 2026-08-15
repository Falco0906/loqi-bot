"""PR6.1 — explicit Strategic Action approval and execution tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.persistence import reset_connection_manager, set_connection_manager
from services.persistence.database import SupabaseConnectionManager
from services.persistence.launch import StrategicUpdate, StrategicUpdateRepository
from services.strategic.actions import StrategicActionError, StrategicActionService

from tests.test_knowledge_service import FakeSupabaseClient  # noqa: E402
import main as main_module  # noqa: E402


OWNER_A = "action-owner-a"
OWNER_B = "action-owner-b"
WS_A = "action-ws-a"
WS_B = "action-ws-b"


def _install(store):
    manager = SupabaseConnectionManager(url="http://test", key="test-key")
    manager._client = FakeSupabaseClient(store)
    set_connection_manager(manager)


async def _workspace(owner_id):
    return WS_A if owner_id == OWNER_A else WS_B


def _update(workspace_id: str, update_type: str = "messaging") -> StrategicUpdate:
    return StrategicUpdate(
        workspace_id=workspace_id,
        pattern_key=f"pattern-{uuid.uuid4().hex[:8]}",
        title="Observed pattern",
        summary="A repeated observed pattern.",
        update_type=update_type,
        confidence="medium",
        observation="Observed across real records.",
        interpretation="This may matter operationally.",
        recommendation="Consider a focused change.",
        structured_analysis={"angle": "implementation simplicity"},
        evidence=[{
            "signal_id": "sig-1",
            "source_type": "message",
            "conversation_id": "conversation-1",
            "message_id": "message-1",
            "campaign_id": "campaign-1",
            "observed_at": "2026-08-12T00:00:00+00:00",
        }],
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_connection_manager()
    yield
    reset_connection_manager()


@pytest.fixture
def setup(monkeypatch):
    store = {}
    _install(store)
    monkeypatch.setattr("services.workspace_state._async_workspace", _workspace)
    return store


def _save_update(update):
    asyncio.run(StrategicUpdateRepository().save(update))
    return update


class TestProposalLifecycle:
    def test_proposal_requires_evidence_and_does_not_mutate(self, setup):
        update = _save_update(_update(WS_A, "messaging"))
        service = StrategicActionService()

        action = asyncio.run(service.propose(OWNER_A, update.id, "update_messaging"))

        assert action["status"] == "proposed"
        assert action["strategic_update_id"] == update.id
        assert action["proposal"]["evidence"][0]["message_id"] == "message-1"
        assert setup.get("knowledge_items", []) == []
        assert setup.get("strategic_actions")

    def test_insufficient_evidence_has_no_actions(self, setup):
        update = _update(WS_A, "messaging")
        update.evidence = []
        _save_update(update)

        with pytest.raises(StrategicActionError):
            asyncio.run(StrategicActionService().propose(OWNER_A, update.id, "update_messaging"))

    def test_refine_dismiss_and_approve_lifecycle(self, setup):
        update = _save_update(_update(WS_A, "icp"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "refine_icp"))
        refined = asyncio.run(service.refine(
            OWNER_A, action["id"], {"summary": "Refined after review", "tags": ["reviewed"]}))
        approved = asyncio.run(service.approve(OWNER_A, action["id"]))

        assert refined["proposal"]["proposed_change"]["summary"] == "Refined after review"
        assert approved["status"] == "approved"
        assert approved["approved_at"] is not None

        update2 = _save_update(_update(WS_A, "messaging"))
        action2 = asyncio.run(service.propose(OWNER_A, update2.id, "update_messaging"))
        dismissed = asyncio.run(service.dismiss(OWNER_A, action2["id"]))
        assert dismissed["status"] == "dismissed"


class TestActionExecution:
    def test_messaging_execution_creates_provenance_preserving_knowledge(self, setup):
        update = _save_update(_update(WS_A, "messaging"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "update_messaging"))
        asyncio.run(service.approve(OWNER_A, action["id"]))
        completed = asyncio.run(service.execute(OWNER_A, action["id"]))
        repeated = asyncio.run(service.execute(OWNER_A, action["id"]))

        assert completed["status"] == "completed", completed["error"]
        assert completed["result"]["entity_type"] == "knowledge_item"
        assert completed["result"]["entity_id"]
        assert repeated["result"] == completed["result"]
        knowledge = setup["knowledge_items"]
        assert len(knowledge) == 1
        assert knowledge[0]["source_id"] == update.id
        assert knowledge[0]["source_type"] == "system_generated"
        assert json.loads(knowledge[0]["content"])["strategic_action_id"] == action["id"]
        audit_actions = [entry["action"] for entry in setup["audit_log"]]
        assert "strategic_action.proposed" in audit_actions
        assert "strategic_action.approved" in audit_actions
        assert "strategic_action.completed" in audit_actions

    def test_icp_execution_creates_new_item_without_overwrite(self, setup):
        update = _save_update(_update(WS_A, "icp"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "refine_icp"))
        asyncio.run(service.approve(OWNER_A, action["id"]))
        result = asyncio.run(service.execute(OWNER_A, action["id"]))

        assert result["result"]["category"] == "icp"
        assert setup["knowledge_items"][0]["category"] == "icp"

    def test_campaign_execution_creates_planning_campaign_only(self, setup, monkeypatch):
        update = _save_update(_update(WS_A, "performance"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "create_campaign"))
        asyncio.run(service.approve(OWNER_A, action["id"]))
        persisted = []

        async def fake_persist(owner_id, campaign):
            persisted.append((owner_id, campaign))
            return True

        monkeypatch.setattr("services.workspace_state.persist_campaign_row", fake_persist)
        monkeypatch.setattr(
            "services.workspace_state.load_workspace_state",
            lambda owner_id, include_details=False: {"campaigns": []},
        )
        completed = asyncio.run(service.execute(OWNER_A, action["id"]))

        assert completed["status"] == "completed", completed["error"]
        assert persisted[0][0] == OWNER_A
        campaign = persisted[0][1]
        assert campaign["status"] == "planning"
        assert campaign["leads"] == []
        assert campaign["metadata"]["strategic_action_id"] == action["id"]
        assert "send" not in completed["result"]

    def test_execution_requires_approval_and_failed_action_can_retry(self, setup, monkeypatch):
        update = _save_update(_update(WS_A, "performance"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "create_campaign"))
        with pytest.raises(StrategicActionError):
            asyncio.run(service.execute(OWNER_A, action["id"]))
        asyncio.run(service.approve(OWNER_A, action["id"]))

        async def fail_persist(owner_id, campaign):
            return False

        monkeypatch.setattr("services.workspace_state.persist_campaign_row", fail_persist)
        monkeypatch.setattr(
            "services.workspace_state.load_workspace_state",
            lambda owner_id, include_details=False: {"campaigns": []},
        )
        failed = asyncio.run(service.execute(OWNER_A, action["id"]))
        assert failed["status"] == "failed"
        assert failed["error"]

        async def succeed_persist(owner_id, campaign):
            return True

        monkeypatch.setattr("services.workspace_state.persist_campaign_row", succeed_persist)
        completed = asyncio.run(service.execute(OWNER_A, action["id"]))
        assert completed["status"] == "completed"


class TestActionIsolation:
    def test_other_workspace_cannot_access_or_execute_action(self, setup):
        update = _save_update(_update(WS_A, "messaging"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "update_messaging"))

        assert asyncio.run(service.list_actions(OWNER_B, update.id)) == []
        with pytest.raises(StrategicActionError):
            asyncio.run(service.approve(OWNER_B, action["id"]))
        assert setup.get("knowledge_items", []) == []

    def test_action_persists_across_restart(self, setup):
        update = _save_update(_update(WS_A, "messaging"))
        service = StrategicActionService()
        action = asyncio.run(service.propose(OWNER_A, update.id, "update_messaging"))
        asyncio.run(service.approve(OWNER_A, action["id"]))
        completed = asyncio.run(service.execute(OWNER_A, action["id"]))

        reset_connection_manager()
        _install(setup)
        restored = asyncio.run(StrategicActionService().list_actions(OWNER_A, update.id))

        assert restored[0]["id"] == action["id"]
        assert restored[0]["status"] == "completed"
        assert restored[0]["result"] == completed["result"]
        assert restored[0]["proposal"]["strategic_update_id"] == update.id


class TestActionRoutes:
    def test_route_propose_approve_execute_requires_explicit_steps(self, setup, monkeypatch):
        update = _save_update(_update(WS_A, "messaging"))

        async def owner(request, session_token):
            return OWNER_A

        monkeypatch.setattr(main_module, "_workspace_owner", owner)
        proposal = asyncio.run(main_module.propose_strategic_action(
            "session", update.id, object(), {"action_type": "update_messaging"}))
        action_id = proposal["action"]["id"]
        assert proposal["action"]["status"] == "proposed"

        with pytest.raises(Exception):
            asyncio.run(main_module.execute_strategic_action("session", action_id, object()))
        approved = asyncio.run(main_module.approve_strategic_action("session", action_id, object()))
        assert approved["action"]["status"] == "approved"
