"""PR4.3 — Inbox reply execution E2E: conversation reply send path.

Covers:
  A. Endpoint sends the reply through the outbound executor (SEND_REPLY),
     records the outbound message + EMAIL_SENT timeline event, and moves
     the conversation back to SENT (awaiting the next response).
  B. Duplicate reply sends are rejected once the conversation is awaiting
     a response again (409).
  C. No connected provider -> 503.
  D. State machine allows REPLIED -> SENT and INTERESTED -> SENT.
  E. handle_reply is idempotent by external_message_id (no double
     processing when both sync and simulator fire on the same thread).
  F. create_conversation_from_send maps the external thread in the
     communication store so real Gmail syncs route into the conversation.
  G. Real inbound sync routing: _process_provider_message feeds mapped
     inbound messages into handle_reply (message, classification, status).
"""
import asyncio
from unittest.mock import MagicMock
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.communication import provider_registry as comm_registry
from services.communication.communication_store import store as communication_store
from services.communication.gmail_sync import _process_provider_message
from services.communication.provider_models import MessageDirection, ProviderMessage
from services.communication.reply_simulator import SimProvider
from services.outbound import outbound_registry
from services.conversations.conversation_models import ConversationStatus, ReplyCategory
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply
from services.conversations.state_machine import transition as state_transition
from services.conversations.timeline import TimelineEventType

import main as main_module  # noqa: E402
def _auth_request(token="session-flow"):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request



SESSION = "session-under-test"
PROVIDER = "prov-conv-reply"
CONTACT_EMAIL = "jordan@bella-vista.com"
OWNER_EMAIL = "faisal@loqi.com"


class FakeComm:
    def __init__(self, user_id, email="", connected=True):
        self._user_id = user_id
        self._mailbox_email = email
        self._connected = connected


class FakeOutbound:
    provider_type = "gmail"

    def __init__(self, provider_id):
        self._provider_id = provider_id


class FakeOutboundExecutor:
    def __init__(self, ok=True, error="", external_id="ext-reply-1"):
        self.ok = ok
        self.error = error
        self.external_id = external_id
        self.calls = []

    def execute(self, action_type, params):
        self.calls.append((action_type, params))
        if not self.ok:
            return {"ok": False, "error": self.error}
        return {
            "ok": True,
            "send_result": {
                "id": self.external_id,
                "external_message_id": self.external_id,
                "thread_id": params.get("thread_id", ""),
                "status": "sent",
                "error": "",
            },
        }


@pytest.fixture(autouse=True)
def _clean_registries():
    comm_registry._instances.clear()
    outbound_registry._instances.clear()
    yield
    comm_registry._instances.clear()
    outbound_registry._instances.clear()


def _register_provider(provider_id: str = PROVIDER) -> str:
    comm_registry.register_instance(provider_id, FakeComm("owner-1", email=OWNER_EMAIL))
    outbound_registry.register_instance(provider_id, FakeOutbound(provider_id))
    return provider_id


def _make_conversation() -> tuple:
    """Create a conversation from a sent email; returns (convo, thread_id)."""
    external_thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    convo = create_conversation_from_send(
        provider_id=PROVIDER,
        provider_type="gmail",
        external_thread_id=external_thread_id,
        external_message_id=f"outbound_{uuid.uuid4().hex[:12]}",
        subject="Quick question about Loqi",
        from_email=OWNER_EMAIL,
        from_name="Faisal",
        to_email=CONTACT_EMAIL,
        to_name="Jordan Parker",
        body="Hi Jordan, would Loqi be a fit?",
        campaign_id="cmp-1",
        workflow_id="wf-1",
        lead_id="lead-1",
        owner_id="test-owner",
    )
    return convo, external_thread_id


def _send_reply(conversation_id: str, body: str) -> dict:
    return asyncio.run(
        main_module.send_conversation_reply_route(
            SESSION,
            conversation_id,
            main_module.SendConversationReplyRequest(body=body),
            _auth_request(),
        )
    )


class TestSendReplyEndpoint:
    def test_A_sends_reply_records_message_and_returns_to_sent(self, monkeypatch):
        _register_provider()
        convo, external_thread_id = _make_conversation()
        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
            from_email=CONTACT_EMAIL,
            from_name="Jordan Parker",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="Thanks — we're interested in a call.",
        )
        assert conversation_store.get_conversation(convo.conversation_id).status in {
            ConversationStatus.INTERESTED,
            ConversationStatus.REPLIED,
        }

        fake = FakeOutboundExecutor(external_id=f"sent_{uuid.uuid4().hex[:12]}")
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        result = _send_reply(convo.conversation_id, "Great — let's find a time for a quick call.")

        assert result["ok"] is True
        assert result["status"] == ConversationStatus.SENT.value

        action_type, params = fake.calls[-1]
        assert action_type == "send_reply"
        assert params["thread_id"] == external_thread_id
        assert params["recipient"]["email"] == CONTACT_EMAIL

        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert len(outbound) == 2  # original send + reply
        assert outbound[-1].body == "Great — let's find a time for a quick call."

        timeline_types = {e.event_type for e in conversation_store.get_timeline(convo.conversation_id)}
        assert TimelineEventType.EMAIL_SENT in timeline_types

    def test_B_duplicate_send_rejected(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
            from_email=CONTACT_EMAIL,
            from_name="Jordan Parker",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="Interested in a call.",
        )
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        assert _send_reply(convo.conversation_id, "Sounds good!")["ok"] is True

        with pytest.raises(Exception) as exc_info:
            _send_reply(convo.conversation_id, "One more thing...")
        assert getattr(exc_info.value, "status_code", None) == 409
        assert len(fake.calls) == 1  # second attempt never reached the executor

    def test_C_no_provider_returns_503(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
            from_email=CONTACT_EMAIL,
            from_name="Jordan Parker",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="What does this cost?",
        )
        # Drop the provider so resolution fails.
        comm_registry._instances.clear()
        outbound_registry._instances.clear()

        with pytest.raises(Exception) as exc_info:
            _send_reply(convo.conversation_id, "Here's pricing.")
        assert getattr(exc_info.value, "status_code", None) == 503


class TestStateMachine:
    def test_D_replied_to_sent_allowed(self):
        assert state_transition(ConversationStatus.REPLIED, ConversationStatus.SENT) == ConversationStatus.SENT

    def test_D_interested_to_sent_allowed(self):
        assert state_transition(ConversationStatus.INTERESTED, ConversationStatus.SENT) == ConversationStatus.SENT


class TestIngestIntegration:
    def test_E_handle_reply_idempotent_by_external_message_id(self):
        _register_provider()
        convo, _ = _make_conversation()
        external_message_id = f"inbound_{uuid.uuid4().hex[:12]}"
        for _ in range(2):
            handle_reply(
                conversation_id=convo.conversation_id,
                external_message_id=external_message_id,
                from_email=CONTACT_EMAIL,
                from_name="Jordan Parker",
                to_email=OWNER_EMAIL,
                to_name="Faisal",
                subject="Re: Quick question about Loqi",
                body="Interested in a call.",
            )
        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1

    def test_F_create_conversation_maps_thread_in_communication_store(self):
        _register_provider()
        convo, external_thread_id = _make_conversation()
        mapping = communication_store.get_thread_mapping(external_thread_id)
        assert mapping is not None
        assert mapping.conversation_id == convo.conversation_id

    def test_G_real_inbound_routing_feeds_handle_reply(self):
        _register_provider()
        convo, external_thread_id = _make_conversation()
        provider_msg = ProviderMessage(
            provider_id=PROVIDER,
            external_id=f"inbound_{uuid.uuid4().hex[:12]}",
            thread_id=external_thread_id,
            direction=MessageDirection.INCOMING,
            raw_headers={
                "from": f"Jordan Parker <{CONTACT_EMAIL}>",
                "to": f"Faisal <{OWNER_EMAIL}>",
                "subject": "Re: Quick question about Loqi",
                "message-id": f"inbound_{uuid.uuid4().hex[:12]}",
            },
            raw_body="Hey, we're interested — when do you have time to walk us through it?",
            received_at="2026-08-11T09:00:00+00:00",
        )
        _process_provider_message(SimProvider(), provider_msg)

        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1
        assert inbound[0].from_email == CONTACT_EMAIL
        assert inbound[0].classification.get("category") in {
            c.value for c in (ReplyCategory.INTERESTED, ReplyCategory.QUESTION, ReplyCategory.UNKNOWN)
        }
        updated = conversation_store.get_conversation(convo.conversation_id)
        assert updated.status in {
            ConversationStatus.INTERESTED,
            ConversationStatus.REPLIED,
            ConversationStatus.CLOSED_LOST,
        }
