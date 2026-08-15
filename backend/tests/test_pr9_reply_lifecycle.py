"""PR9 — final core reply/follow-up lifecycle regression tests.

Covers the human-in-the-loop reply loop end-to-end:
inbound → classified → recommended → human edit → approved/send → persisted →
same conversation/thread → duplicate protection → follow-up reset → restart.
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

from services.communication import provider_registry as comm_registry
from services.outbound import outbound_registry
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply
from services.conversations.state_machine import transition as state_transition
from services.conversations.timeline import TimelineEventType

import main as main_module  # noqa: E402


SESSION = "session-pr9"

def _auth_request(token="session-pr9"):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request


PROVIDER = "prov-pr9"
CONTACT_EMAIL = "cheryl.werner@harvestkitchenrestaurants.com"
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
    def __init__(self, external_id="ext-reply-1"):
        self.external_id = external_id
        self.calls = []

    def execute(self, action_type, params):
        self.calls.append((action_type, params))
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
        to_name="Cheryl Werner",
        body="Hi Cheryl, would Loqi be a fit?",
        campaign_id="cmp-1",
        workflow_id="wf-1",
        lead_id="lead-1",
        owner_id="test-owner",
    )
    return convo, external_thread_id


def _inbound_reply(conversation_id: str, body: str = "We're interested — what does it cost?") -> None:
    handle_reply(
        conversation_id=conversation_id,
        external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
        from_email=CONTACT_EMAIL,
        from_name="Cheryl Werner",
        to_email=OWNER_EMAIL,
        to_name="Faisal",
        subject="Re: Quick question about Loqi",
        body=body,
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
class TestReplyLifecycle:
    def test_edited_reply_text_is_what_is_sent_and_persisted(self, monkeypatch):
        _register_provider()
        convo, external_thread_id = _make_conversation()
        _inbound_reply(convo.conversation_id)

        fake = FakeOutboundExecutor(external_id=f"sent_{uuid.uuid4().hex[:12]}")
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        edited = "Thanks for the interest! Here is our pricing — a quick call would help. Edited by human."
        result = _send_reply(convo.conversation_id, edited)

        assert result["ok"] is True
        assert result["conversation_id"] == convo.conversation_id
        assert result["status"] == ConversationStatus.SENT.value

        action_type, params = fake.calls[-1]
        assert action_type == "send_reply"
        assert params["body"] == edited
        assert params["thread_id"] == external_thread_id
        assert params["recipient"]["email"] == CONTACT_EMAIL

        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert outbound[-1].body == edited
        assert outbound[-1].conversation_id == convo.conversation_id
        assert outbound[-1].thread_id == conversation_store.get_threads_for_conversation(convo.conversation_id)[0].thread_id

        events = conversation_store.get_timeline(convo.conversation_id)
        assert any(e.event_type == TimelineEventType.EMAIL_SENT for e in events)

    def test_duplicate_reply_send_rejected_409(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _inbound_reply(convo.conversation_id)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        assert _send_reply(convo.conversation_id, "Sounds good.")["ok"] is True

        with pytest.raises(Exception) as exc_info:
            _send_reply(convo.conversation_id, "One more thing...")
        assert getattr(exc_info.value, "status_code", None) == 409
        assert len(fake.calls) == 1

    def test_refresh_and_restart_do_not_duplicate(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        inbound_id = f"inbound_{uuid.uuid4().hex[:12]}"
        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=inbound_id,
            from_email=CONTACT_EMAIL,
            from_name="Cheryl Werner",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="Interested — pricing?",
        )

        # Reload (refresh/restart equivalent) preserves messages + thread mapping.
        conversation_store.reload()
        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1
        assert conversation_store.find_by_external_thread(convo.external_thread_id) is not None

        # Re-ingesting the same inbound message after restart must not duplicate.
        handle_reply(
            conversation_id=convo.conversation_id,
            external_message_id=inbound_id,
            from_email=CONTACT_EMAIL,
            from_name="Cheryl Werner",
            to_email=OWNER_EMAIL,
            to_name="Faisal",
            subject="Re: Quick question about Loqi",
            body="Interested — pricing?",
        )
        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1


class TestFollowUpInteraction:
    def test_real_reply_resets_follow_up_readiness(self):
        _register_provider()
        convo, _ = _make_conversation()
        convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_PENDING)
        convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_READY)
        conversation_store.update_conversation(convo)

        _inbound_reply(convo.conversation_id, "Yes, let's talk next week.")
        updated = conversation_store.get_conversation(convo.conversation_id)
        assert updated.status != ConversationStatus.FOLLOW_UP_READY
        assert updated.status in {
            ConversationStatus.REPLIED,
            ConversationStatus.INTERESTED,
        }

        from services.communication.inbox_sync_engine import maintain_follow_up_readiness
        assert maintain_follow_up_readiness() == 0
        assert conversation_store.get_conversation(convo.conversation_id).status == updated.status

    def test_terminal_conversation_does_not_become_actionable(self):
        _register_provider()
        convo, _ = _make_conversation()
        convo.status = state_transition(convo.status, ConversationStatus.CLOSED_LOST)
        conversation_store.update_conversation(convo)

        from services.communication.inbox_sync_engine import maintain_follow_up_readiness
        assert maintain_follow_up_readiness() == 0
        assert conversation_store.get_conversation(convo.conversation_id).status == ConversationStatus.CLOSED_LOST

    def test_sent_reply_returns_conversation_to_awaiting_response(self, monkeypatch):
        _register_provider()
        convo, _ = _make_conversation()
        _inbound_reply(convo.conversation_id)
        monkeypatch.setattr(main_module, "outbound_executor", FakeOutboundExecutor())
        _send_reply(convo.conversation_id, "Here is the pricing breakdown.")

        assert conversation_store.get_conversation(convo.conversation_id).status == ConversationStatus.SENT


class TestConversationReplyTestRecipient:
    def _send_with_test_recipient(self, conversation_id: str, body: str, test_recipient: str = "") -> dict:
        return asyncio.run(
            main_module.send_conversation_reply_route(
                SESSION, conversation_id,
                main_module.SendConversationReplyRequest(
                    body=body,
                    test_recipient=test_recipient,
                    test_recipient_name="Test Recipient" if test_recipient else "",
                ),
                _auth_request(),
            )
        )

    def test_reply_with_test_recipient_uses_test_envelope_and_preserves_identity(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        _register_provider()
        convo, external_thread_id = _make_conversation()
        _inbound_reply(convo.conversation_id)
        fake = FakeOutboundExecutor(external_id=f"sent_{uuid.uuid4().hex[:12]}")
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        edited = "EDITED TEST REPLY - Hi Cheryl,"
        result = self._send_with_test_recipient(convo.conversation_id, edited, "tofu9262@gmail.com")

        assert result["ok"] is True
        assert result["conversation_id"] == convo.conversation_id

        action_type, params = fake.calls[-1]
        assert action_type == "send_reply"
        assert params["body"] == edited
        assert params["recipient"]["email"] == "tofu9262@gmail.com"
        assert params["thread_id"] == external_thread_id

        # Persisted conversation message keeps the real lead identity.
        messages = conversation_store.get_messages_for_conversation(convo.conversation_id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert outbound[-1].body == edited
        assert outbound[-1].to_email == CONTACT_EMAIL

    def test_reply_without_override_uses_real_recipient(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "false")
        _register_provider()
        convo, external_thread_id = _make_conversation()
        _inbound_reply(convo.conversation_id)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        self._send_with_test_recipient(convo.conversation_id, "Normal reply.", "")

        params = fake.calls[-1][1]
        assert params["recipient"]["email"] == CONTACT_EMAIL
        assert params["thread_id"] == external_thread_id

    def test_reply_override_rejected_when_disabled(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "false")
        _register_provider()
        convo, _ = _make_conversation()
        _inbound_reply(convo.conversation_id)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        with pytest.raises(Exception) as exc_info:
            self._send_with_test_recipient(convo.conversation_id, "Hi", "tofu9262@gmail.com")
        assert getattr(exc_info.value, "status_code", None) == 403
        assert fake.calls == []

    def test_duplicate_protection_remains_intact_with_override(self, monkeypatch):
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        _register_provider()
        convo, _ = _make_conversation()
        _inbound_reply(convo.conversation_id)
        fake = FakeOutboundExecutor()
        monkeypatch.setattr(main_module, "outbound_executor", fake)

        assert self._send_with_test_recipient(convo.conversation_id, "First.", "tofu9262@gmail.com")["ok"] is True
        with pytest.raises(Exception) as exc_info:
            self._send_with_test_recipient(convo.conversation_id, "Second.", "tofu9262@gmail.com")
        assert getattr(exc_info.value, "status_code", None) == 409
        assert len(fake.calls) == 1
