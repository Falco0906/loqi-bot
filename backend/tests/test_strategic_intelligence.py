"""PR6 — deterministic Strategic Intelligence over real domain records."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.conversations.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationStatus,
    ConversationThread,
)
from services.conversations.conversation_store import conversation_store
from services.persistence import reset_connection_manager, set_connection_manager
from services.persistence.database import SupabaseConnectionManager
from services.strategic.collector import collect_workspace_signals
from services.strategic.models import StrategicSignal
from services.strategic.patterns import detect_patterns
from services.strategic.service import StrategicIntelligenceService

from tests.test_knowledge_service import FakeSupabaseClient  # noqa: E402
import main as main_module  # noqa: E402


OWNER_A = "owner-a"
OWNER_B = "owner-b"
WORKSPACE_A = "ws-a"
WORKSPACE_B = "ws-b"
CAMPAIGN_A = "campaign-a"
CAMPAIGN_B = "campaign-b"


def _install_db(store):
    client = FakeSupabaseClient(store)
    manager = SupabaseConnectionManager(url="http://test", key="test-key")
    manager._client = client
    set_connection_manager(manager)


def _lead(lead_id: str, industry: str = "Advisory") -> dict:
    return {
        "id": lead_id,
        "name": f"Lead {lead_id}",
        "title": "Managing Partner",
        "company": f"Company {lead_id}",
        "industry": industry,
    }


def _conversation(campaign_id: str, lead_id: str, *, positive: bool = False):
    cid = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    convo = Conversation(
        conversation_id=cid,
        provider_id="provider",
        provider_type="gmail",
        external_thread_id=f"external-{cid}",
        subject="Question about implementation",
        status=ConversationStatus.SENT,
        participants=[
            ConversationParticipant("owner@example.com", "Owner", "sender"),
            ConversationParticipant("lead@example.com", "Lead", "contact"),
        ],
        campaign_id=campaign_id,
        lead_id=lead_id,
    )
    conversation_store.create_conversation(convo)
    conversation_store.add_thread(ConversationThread(
        thread_id=thread_id,
        conversation_id=cid,
        external_thread_id=f"external-{cid}",
        provider_id="provider",
        subject=convo.subject,
    ))
    conversation_store.add_message(ConversationMessage(
        conversation_id=cid,
        thread_id=thread_id,
        direction="outbound",
        body="We help advisory teams run outbound.",
        subject=convo.subject,
    ))
    if positive:
        conversation_store.add_message(ConversationMessage(
            conversation_id=cid,
            thread_id=thread_id,
            direction="inbound",
            body="We are interested, but implementation and setup are concerns.",
            subject="Re: implementation",
            classification={"category": "interested", "confidence": 0.9},
        ))
    return convo


@pytest.fixture(autouse=True)
def _reset_persistence():
    reset_connection_manager()
    yield
    reset_connection_manager()


@pytest.fixture
def activity(monkeypatch):
    leads = [_lead(f"lead-{i}") for i in range(10)]
    campaign = {
        "id": CAMPAIGN_A,
        "name": "Advisory campaign",
        "status": "active",
        "leads": leads,
        "lead_count": len(leads),
        "strategy": {"messaging_angle": "implementation simplicity"},
    }
    conversations = [
        _conversation(CAMPAIGN_A, lead["id"], positive=i < 3)
        for i, lead in enumerate(leads)
    ]
    monkeypatch.setattr(
        "services.strategic.collector.load_workspace_state",
        lambda owner_id, include_details=True: {
            "campaigns": [campaign] if owner_id == OWNER_A else [],
            "drafts": [],
        },
    )
    async def workspace_for_owner(owner_id):
        return WORKSPACE_A if owner_id == OWNER_A else WORKSPACE_B

    monkeypatch.setattr("services.workspace_state._async_workspace", workspace_for_owner)
    return campaign, conversations


class TestSignalCollection:
    def test_collects_real_campaign_conversation_and_classification_signals(self, activity):
        signals, summary = collect_workspace_signals(OWNER_A)
        types = {signal.signal_type for signal in signals}

        assert summary["conversation_count"] == 10
        assert "outbound_sent" in types
        assert "inbound_reply" in types
        assert "reply_classified" in types
        assert "objection" in types
        assert all(signal.campaign_id == CAMPAIGN_A for signal in signals)

    def test_collection_is_workspace_scoped(self, activity):
        signals, summary = collect_workspace_signals(OWNER_B)
        assert signals == []
        assert summary["campaign_ids"] == []


class TestPatternDetection:
    def test_campaign_pattern_requires_meaningful_sample_and_has_evidence(self, activity):
        signals, _ = collect_workspace_signals(OWNER_A)
        patterns = detect_patterns(signals)
        campaign = next(pattern for pattern in patterns if pattern.update_type == "performance")

        assert campaign.structured_analysis["sent"] == 10
        assert campaign.structured_analysis["replies"] == 3
        assert campaign.structured_analysis["response_rate"] == 0.3
        assert campaign.evidence
        assert all(reference["campaign_id"] == CAMPAIGN_A for reference in campaign.evidence)
        assert all(reference["message_id"] or reference["entity_id"] for reference in campaign.evidence)

    def test_insufficient_campaign_sample_produces_no_pattern(self):
        signals = [
            StrategicSignal(
                signal_id=f"s-{index}", signal_type="outbound_sent", entity_type="message",
                entity_id=f"m-{index}", observed_at="2026-01-01T00:00:00+00:00",
                campaign_id="small", message_id=f"m-{index}", value="sent",
            )
            for index in range(9)
        ]
        assert detect_patterns(signals) == []

    def test_recurring_objection_requires_multiple_conversations(self):
        signals = [
            StrategicSignal(
                signal_id=f"o-{index}", signal_type="objection", entity_type="message",
                entity_id=f"m-{index}", observed_at="2026-01-01T00:00:00+00:00",
                conversation_id=f"c-{index % 2}", value="implementation",
            )
            for index in range(3)
        ]
        patterns = detect_patterns(signals)
        assert len(patterns) == 1
        assert patterns[0].update_type == "objection"


class TestStrategicUpdatePersistence:
    def test_refresh_persists_and_deduplicates_updates(self, monkeypatch, activity):
        store = {}
        _install_db(store)
        service = StrategicIntelligenceService()

        first = asyncio.run(service.refresh(OWNER_A))
        second = asyncio.run(service.refresh(OWNER_A))

        assert first["new_updates"] >= 1
        assert second["new_updates"] == 0
        assert second["refreshed_updates"] >= 1
        assert len(store["strategic_updates"]) == first["new_updates"]
        assert len(store["audit_log"]) >= first["new_updates"]

    def test_no_activity_returns_truthful_empty_refresh(self, monkeypatch):
        store = {}
        _install_db(store)
        monkeypatch.setattr(
            "services.strategic.collector.load_workspace_state",
            lambda owner_id, include_details=True: {"campaigns": [], "drafts": []},
        )
        async def workspace_for_owner(owner_id):
            return WORKSPACE_A

        monkeypatch.setattr("services.workspace_state._async_workspace", workspace_for_owner)
        result = asyncio.run(StrategicIntelligenceService().refresh(OWNER_A))
        assert result["updates"] == []
        assert result["patterns_found"] == 0
        assert store.get("strategic_updates", []) == []

    def test_restart_and_owner_isolation(self, monkeypatch, activity):
        store = {}
        _install_db(store)
        service = StrategicIntelligenceService()
        result = asyncio.run(service.refresh(OWNER_A))
        update_id = result["updates"][0]["id"]

        reset_connection_manager()
        _install_db(store)
        restarted = StrategicIntelligenceService()
        restored = asyncio.run(restarted.get_update(OWNER_A, update_id))
        hidden = asyncio.run(restarted.get_update(OWNER_B, update_id))

        assert restored is not None
        assert restored["id"] == update_id
        assert restored["evidence"]
        assert hidden is None

    def test_archive_removes_update_from_active_reads(self, monkeypatch, activity):
        store = {}
        _install_db(store)
        service = StrategicIntelligenceService()
        result = asyncio.run(service.refresh(OWNER_A))
        update_id = result["updates"][0]["id"]

        archived = asyncio.run(service.archive_update(OWNER_A, update_id))
        active = asyncio.run(service.list_updates(OWNER_A))

        assert archived["status"] == "archived"
        assert all(item["id"] != update_id for item in active)


class TestStrategicUpdateRoutes:
    def test_routes_derive_owner_and_hide_other_workspace_updates(self, monkeypatch, activity):
        store = {}
        _install_db(store)

        async def owner_a(request, session_token):
            return OWNER_A

        async def owner_b(request, session_token):
            return OWNER_B

        monkeypatch.setattr(main_module, "_workspace_owner", owner_a)
        refresh = asyncio.run(main_module.refresh_strategic_updates("session", object()))
        update_id = refresh["updates"][0]["id"]

        monkeypatch.setattr(main_module, "_workspace_owner", owner_b)
        listing = asyncio.run(main_module.list_strategic_updates("session", object()))
        with pytest.raises(Exception) as error:
            asyncio.run(main_module.get_strategic_update("session", update_id, object()))

        assert listing["updates"] == []
        assert getattr(error.value, "status_code", None) == 404
