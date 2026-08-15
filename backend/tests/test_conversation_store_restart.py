"""Conversation persistence restart round-trip tests (file-backed store).

Simulates a backend restart against the persisted snapshot:
  - create conversation -> persist -> "restart" (reload) -> verify the full
    API surface (list/get/messages/timeline/reasoning) survives with ids,
    statuses, classifications, threads and timeline intact.
  - a pending .simulate_replies.json event must attach to the restored
    conversation after restart instead of creating an orphan thread; the
    Inbox must keep surfacing it; no orphan conversation/thread/message
    may be created.
"""
import asyncio
import os
import random
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.communication import reply_simulator as sim
from services.conversations import persistence
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply
from services.conversations.timeline import TimelineEventType

import main as main_module  # noqa: E402

SIM_PROVIDER_ID = "sim_reply"
OWNER_EMAIL = "faisal@loqi.com"
CONTACT_EMAIL = "jordan@bella-vista.com"


@pytest.fixture(autouse=True)
def _clean_simulator(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMULATE_REPLIES", raising=False)
    monkeypatch.delenv("SIMULATE_ACCELERATED", raising=False)
    monkeypatch.delenv("SIMULATE_REPLY_MULTIPLIER", raising=False)
    monkeypatch.delenv("SIMULATE_REPLY_WEIGHTS", raising=False)
    monkeypatch.setattr(sim, "STATE_FILE", str(tmp_path / "simulate_replies.json"))
    monkeypatch.setattr(sim, "rng", random.Random(7))
    monkeypatch.setattr(sim, "_pending", [])
    monkeypatch.setattr(sim, "_loaded", False)


def _auth_request(token="session-under-test"):
    """Build a request carrying the session token via Authorization header only."""
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request


def _make_conversation(body="Hi Jordan, would Loqi be a fit for Bella Vista?"):
    return create_conversation_from_send(
        provider_id=SIM_PROVIDER_ID,
        provider_type="gmail",
        external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
        external_message_id=f"outbound_{uuid.uuid4().hex[:12]}",
        subject="Quick question about Loqi",
        from_email=OWNER_EMAIL,
        from_name="Faisal",
        to_email=CONTACT_EMAIL,
        to_name="Jordan Parker",
        body=body,
        campaign_id="cmp-restart",
        workflow_id="wf-restart",
        lead_id="lead-restart-1",
        owner_id="test-owner",
    )


def _interested_reply(conversation_id, external_message_id):
    return handle_reply(
        conversation_id=conversation_id,
        external_message_id=external_message_id,
        from_email=CONTACT_EMAIL,
        from_name="Jordan Parker",
        to_email=OWNER_EMAIL,
        to_name="Faisal",
        subject="Re: Quick question about Loqi",
        body="Thanks — we're actually interested, could you share more?",
    )


def _simulate_restart():
    """Drop all in-memory state and rehydrate from the persisted snapshot."""
    conversation_store.reload()


def _timeline_signature(conversation_id) -> list[tuple[str, str]]:
    return [
        (e.event_id, e.event_type.value)
        for e in conversation_store.get_timeline(conversation_id)
    ]


class TestRoundTrip:
    def test_full_roundtrip_preserves_conversation_state(self):
        convo = _make_conversation()
        convo_id = convo.conversation_id
        thread = conversation_store.get_threads_for_conversation(convo_id)[0]
        inbound = _interested_reply(convo_id, f"inbound_{uuid.uuid4().hex[:12]}")
        assert convo.status == ConversationStatus.INTERESTED

        assert os.path.exists(persistence.STATE_FILE), "mutation must persist"

        pre_snapshot = {
            "convo": convo.to_dict(),
            "messages": [m.to_dict() for m in conversation_store.get_messages_for_conversation(convo_id)],
            "timeline": _timeline_signature(convo_id),
        }

        _simulate_restart()

        # Inbox surface
        listed = conversation_store.list_conversations(limit=100)
        assert [c.conversation_id for c in listed] == [convo_id]

        # Conversation fields
        restored = conversation_store.get_conversation(convo_id)
        assert restored is not None
        assert restored.conversation_id == pre_snapshot["convo"]["conversation_id"]
        assert restored.status == ConversationStatus.INTERESTED
        assert restored.campaign_id == "cmp-restart"
        assert restored.workflow_id == "wf-restart"
        assert restored.lead_id == "lead-restart-1"
        assert restored.provider_id == SIM_PROVIDER_ID
        assert restored.external_thread_id == convo.external_thread_id
        assert restored.subject == convo.subject
        assert restored.message_count == 2
        assert restored.metadata.get("last_reply_category") == "interested"
        assert restored.metadata.get("last_message_preview") == pre_snapshot["convo"]["metadata"]["last_message_preview"]
        assert [p.to_dict() for p in restored.participants] == [
            p.to_dict() for p in convo.participants
        ]

        # Threads
        restored_threads = conversation_store.get_threads_for_conversation(convo_id)
        assert len(restored_threads) == 1
        assert restored_threads[0].thread_id == thread.thread_id
        assert restored_threads[0].conversation_id == convo_id
        assert restored_threads[0].external_thread_id == thread.external_thread_id

        # Messages
        restored_msgs = conversation_store.get_messages_for_conversation(convo_id)
        assert len(restored_msgs) == 2
        outbound = [m for m in restored_msgs if m.direction == "outbound"][0]
        assert outbound.message_id == pre_snapshot["messages"][0]["message_id"]
        assert outbound.external_message_id == pre_snapshot["messages"][0]["external_message_id"]
        assert outbound.body == pre_snapshot["messages"][0]["body"]
        assert outbound.to_email == CONTACT_EMAIL
        restored_inbound = [m for m in restored_msgs if m.direction == "inbound"][0]
        assert restored_inbound.message_id == inbound.message_id
        assert restored_inbound.classification == inbound.classification
        assert restored_inbound.classification.get("category") == "interested"
        assert restored_inbound.from_email == CONTACT_EMAIL
        assert restored_inbound.sent_at.tzinfo is not None

        # Timeline: identical ids, types, and order
        assert _timeline_signature(convo_id) == pre_snapshot["timeline"]
        types = [t for _, t in _timeline_signature(convo_id)]
        assert types[:2] == ["campaign_created", "email_sent"]
        assert types[-2:] == ["reply_received", "reply_classified"]

        # External thread mapping resolves to the restored conversation
        assert conversation_store.find_by_external_thread(convo.external_thread_id).conversation_id == convo_id

    def test_status_metadata_update_survives_roundtrip(self):
        convo = _make_conversation()
        convo_id = convo.conversation_id
        convo.metadata["follow_up_plan"] = {
            "should_follow_up": True,
            "priority": "high",
            "objective": "provide_pricing",
        }
        conversation_store.update_conversation(convo)

        _simulate_restart()

        restored = conversation_store.get_conversation(convo_id)
        assert restored.status == ConversationStatus.SENT
        assert restored.metadata["follow_up_plan"]["objective"] == "provide_pricing"
        assert restored.updated_at.tzinfo is not None
        assert restored.created_at.tzinfo is not None

    def test_reasoning_route_serves_restored_conversation(self):
        convo = _make_conversation()
        _interested_reply(convo.conversation_id, f"inbound_{uuid.uuid4().hex[:12]}")

        _simulate_restart()

        result = asyncio.run(
            main_module.get_conversation_reasoning_route("_", convo.conversation_id, _auth_request())
        )
        assert result["ok"] is True
        reasoning = result["reasoning"]
        assert reasoning is not None
        for key in ("decision", "priority", "confidence", "risk"):
            assert key in reasoning, f"reasoning missing {key}"

    def test_inbox_route_surfaces_restored_conversation(self):
        convo = _make_conversation()
        _simulate_restart()
        result = asyncio.run(main_module.list_conversations_route("_", _auth_request()))
        ids = [c["conversation_id"] for c in result["conversations"]]
        assert convo.conversation_id in ids


class TestSimulatorRestart:
    def test_pending_reply_attaches_to_restored_conversation(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        import json
        weights = {s.key: 0 for s in sim.SCENARIOS}
        weights["interested"] = 100
        monkeypatch.setenv("SIMULATE_REPLY_WEIGHTS", json.dumps(weights))

        convo = _make_conversation()
        convo_id = convo.conversation_id
        context = {
            "conversation_id": convo_id,
            "external_thread_id": convo.external_thread_id,
            "subject": convo.subject,
            "from_email": OWNER_EMAIL,
            "from_name": "Faisal",
            "to_email": CONTACT_EMAIL,
            "to_name": "Jordan Parker",
            "body": "Hi Jordan, would Loqi be a fit?",
            "campaign_id": "cmp-restart",
            "workflow_id": "wf-restart",
            "lead": {"name": "Jordan Parker", "company": "Bella Vista", "role": "Operations Manager"},
            "objective": "Book discovery calls",
        }
        sim.maybe_schedule(context)
        assert sim.pending_count() == 1
        fire_at = sim._pending[0]["fire_at"]

        # ── Restart: store rehydrated, simulator queue reloaded from disk ──
        _simulate_restart()
        sim._loaded = False
        sim._pending[:] = []
        sim._load_state()
        assert sim.pending_count() == 1

        fired = sim.fire_due(now=sim._parse_dt(fire_at))
        assert len(fired) == 1, "pending reply must fire after restart"

        # Reply attached to the RESTORED conversation (no orphan)
        restored = conversation_store.get_conversation(convo_id)
        assert restored is not None
        assert restored.message_count == 2
        assert restored.status == ConversationStatus.INTERESTED
        assert restored.metadata.get("last_reply_category") == "interested"

        inbound = [m for m in conversation_store.get_messages_for_conversation(convo_id)
                   if m.direction == "inbound"]
        assert len(inbound) == 1
        assert inbound[0].conversation_id == convo_id
        assert inbound[0].from_email == CONTACT_EMAIL
        assert inbound[0].classification.get("category") == "interested"

        timeline_types = {e.event_type for e in conversation_store.get_timeline(convo_id)}
        assert TimelineEventType.REPLY_RECEIVED in timeline_types
        assert TimelineEventType.REPLY_CLASSIFIED in timeline_types

        # Inbox still surfaces it
        result = asyncio.run(main_module.list_conversations_route("_", _auth_request()))
        ids = [c["conversation_id"] for c in result["conversations"]]
        assert convo_id in ids

        # ── Zero orphan state anywhere ──
        all_conversations = conversation_store.list_conversations(limit=100)
        assert len(all_conversations) == 1
        assert all_conversations[0].conversation_id == convo_id
        assert all(
            t.conversation_id in {c.conversation_id for c in all_conversations}
            for t in conversation_store.get_threads_for_conversation(convo_id)
        )
        assert all(
            m.conversation_id in {c.conversation_id for c in all_conversations}
            for m in conversation_store.get_messages_for_conversation(convo_id)
        )
        assert all(
            cid in {c.conversation_id for c in all_conversations}
            for cid in {e.conversation_id for e in conversation_store.get_timeline(convo_id)}
        )
        assert all(
            c.conversation_id != c.external_thread_id for c in all_conversations
        )


class TestUnknownConversationGuard:
    def test_handle_reply_unknown_id_creates_no_orphan_state(self):
        unknown_id = f"convo_{uuid.uuid4().hex[:12]}"
        result = _interested_reply(unknown_id, f"inbound_{uuid.uuid4().hex[:12]}")

        assert result is None
        assert conversation_store.list_conversations(limit=100) == []
        assert conversation_store.get_conversation(unknown_id) is None
        assert conversation_store.get_threads_for_conversation(unknown_id) == []
        assert conversation_store.get_messages_for_conversation(unknown_id) == []
        assert conversation_store.get_timeline(unknown_id) == []
        assert conversation_store.find_by_external_thread(unknown_id) is None