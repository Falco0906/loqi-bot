"""PR — Draft Lifecycle: conversation follow-up action semantics.

Covers:
  F. A conversation awaiting a follow-up (FOLLOW_UP_READY) sends via the
     follow-up endpoint — never via the reply endpoint — using SEND_REPLY on
     the existing thread, records the outbound message + FOLLOW_UP_SENT
     timeline event, and transitions to FOLLOW_UP_SENT.
  G. FOLLOW_UP_PENDING conversations are also accepted (guard + state
     machine agree).
  H. The reply endpoint does NOT serve follow-up conversations (409) and
     the follow-up endpoint does NOT call the reply path.
  I. Duplicate follow-up sends are rejected once the conversation is
     FOLLOW_UP_SENT (409, executor never called).
  J. The existing reply duplicate guard (409) remains intact.
  K. An inbound reply on a follow-up conversation still routes normally
     (simulator/sync path unchanged).
  L. Empty follow-up body -> 400; missing provider -> 503.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.communication import provider_registry as comm_registry
from services.outbound import outbound_registry
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply
from services.conversations.state_machine import transition as state_transition
from services.conversations.timeline import TimelineEventType

import main as main_module  # noqa: E402
def _auth_request(token="session-flow"):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request



SESSION = "session-followup"
PROVIDER = "prov-conv-followup"
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
    def __init__(self, ok=True, error="", external_id="ext-followup-1"):
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


def _to_follow_up_state(conversation_id: str, ready: bool = True) -> None:
    convo = conversation_store.get_conversation(conversation_id)
    convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_PENDING)
    if ready:
        convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_READY)
    conversation_store.update_conversation(convo)


def _send_follow_up(conversation_id: str, body: str) -> dict:
    return asyncio.run(
        main_module.send_conversation_followup_route(
            SESSION,
            conversation_id,
            main_module.SendConversationReplyRequest(body=body),
            _auth_request(),
        )
    )


def _send_reply(conversation_id: str, body: str) -> dict:
    return asyncio.run(
        main_module.send_conversation_reply_route(
            SESSION,
            conversation_id,
            main_module.SendConversationReplyRequest(body=body),
            _auth_request(),
        )
    )


class TestFollowUpSend:
    def test_F_sends_followup_on_existing_thread(self, monkeypatch):
        _register_provider()
        convo, external_thread_id = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)

        fake = FakeOutboundExecutor(external_id=f"fu_{uuid.uuid4().hex[:12]}")
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        result = _send_follow_up(convo.conversation_id, "Just checking in — any thoughts?")

        assert result["ok"] is True
        assert result["status"] == ConversationStatus.FOLLOW_UP_SENT.value

        action_type, params = fake.calls[-1]
        assert action_type == "send_reply"
        assert params["thread_id"] == external_thread_id
        assert params["subject"].startswith("Re: ")
        assert params["recipient"]["email"] == CONTACT_EMAIL

        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert len(outbound) == 2  # original send + follow-up
        assert outbound[-1].body == "Just checking in — any thoughts?"

        timeline_types = {e.event_type for e in conversation_store.get_timeline(convo.conversation_id)}
        assert TimelineEventType.FOLLOW_UP_SENT in timeline_types
        assert conversation_store.get_conversation(convo.conversation_id).status == ConversationStatus.FOLLOW_UP_SENT

    def test_G_followup_pending_is_accepted(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=False)

        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        result = _send_follow_up(convo.conversation_id, "Bumping this up.")

        assert result["ok"] is True
        assert result["status"] == ConversationStatus.FOLLOW_UP_SENT.value
        assert len(fake.calls) == 1

    def test_H_reply_endpoint_does_not_serve_followup_conversations(self, monkeypatch):
        """A follow-up conversation must go through /follow-up, not /reply."""
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)

        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        with pytest.raises(Exception) as exc_info:
            _send_reply(convo.conversation_id, "Trying to reply instead of follow up.")
        assert getattr(exc_info.value, "status_code", None) == 409
        assert fake.calls == []

    def test_I_duplicate_followup_rejected_409(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)

        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        assert _send_follow_up(convo.conversation_id, "First follow-up.")["ok"] is True

        with pytest.raises(Exception) as exc_info:
            _send_follow_up(convo.conversation_id, "Second follow-up.")
        assert getattr(exc_info.value, "status_code", None) == 409
        assert len(fake.calls) == 1  # duplicate never reached the executor


class TestReplyGuardIntact:
    def test_J_reply_duplicate_guard_still_returns_409(self, monkeypatch):
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
        assert len(fake.calls) == 1

    def test_J2_reply_rejected_after_followup_sent(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        _send_follow_up(convo.conversation_id, "Checking in.")

        with pytest.raises(Exception) as exc_info:
            _send_reply(convo.conversation_id, "Trying to reply now.")
        assert getattr(exc_info.value, "status_code", None) == 409


class TestFollowUpIngest:
    def test_K_inbound_reply_after_followup_routes_normally(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)
        _send_follow_up(convo.conversation_id, "Checking in.")

        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
            from_email=CONTACT_EMAIL,
            from_name="Jordan Parker",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="Yes, let's talk.",
        )

        updated = conversation_store.get_conversation(convo.conversation_id)
        assert updated.status in {
            ConversationStatus.REPLIED,
            ConversationStatus.INTERESTED,
        }
        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1


class TestFollowUpGuards:
    def test_L_empty_body_rejected_400(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)

        with pytest.raises(Exception) as exc_info:
            _send_follow_up(convo.conversation_id, "   ")
        assert getattr(exc_info.value, "status_code", None) == 400

    def test_L2_missing_provider_returns_503(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _to_follow_up_state(convo.conversation_id, ready=True)

        comm_registry._instances.clear()
        outbound_registry._instances.clear()

        with pytest.raises(Exception) as exc_info:
            _send_follow_up(convo.conversation_id, "Still interested?")
        assert getattr(exc_info.value, "status_code", None) == 503

    def test_L3_unknown_conversation_404(self, monkeypatch):
        _register_provider()
        with pytest.raises(Exception) as exc_info:
            _send_follow_up("missing-convo", "Hello?")
        assert getattr(exc_info.value, "status_code", None) == 404
