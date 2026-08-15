"""PR8.1 — lead-scoped inbound filtering tests."""

from __future__ import annotations

import os
import sys
import uuid

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.communication.communication_store import store as communication_store
from services.communication.gmail_sync import _process_provider_message
from services.communication.inbound_filter import normalize_email
from services.communication.provider_models import MessageDirection, ProviderMessage
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply


class FakeProvider:
    provider_type = "gmail"

    def __init__(self, provider_id: str, user_id: str):
        self._provider_id = provider_id
        self._user_id = user_id
        self._connected = True

    @property
    def provider_id(self) -> str:
        return self._provider_id


@pytest.fixture(autouse=True)
def _clean_state():
    communication_store._thread_mappings.clear()
    communication_store._by_conversation.clear()
    yield
    communication_store._thread_mappings.clear()
    communication_store._by_conversation.clear()


def _provider_message(provider_id: str, thread_id: str, sender: str) -> ProviderMessage:
    return ProviderMessage(
        provider_id=provider_id,
        external_id=f"gmail-{uuid.uuid4().hex[:12]}",
        thread_id=thread_id,
        direction=MessageDirection.INCOMING,
        raw_headers={
            "from": sender,
            "to": "owner@loqi.com",
            "subject": "Re: Outreach",
            "message-id": f"gmail-{uuid.uuid4().hex[:12]}",
        },
        raw_body="Hello from the inbox.",
        received_at="2026-08-12T10:00:00+00:00",
    )


class TestInboundFilter:
    def test_unrelated_message_is_ignored_and_no_state_created(self):
        provider = FakeProvider("prov-1", "user-1")
        message = _provider_message(provider.provider_id, "thread-unrelated", "stranger@elsewhere.com")

        assert _process_provider_message(provider, message) is None
        assert conversation_store.get_conversation("thread-unrelated") is None
        assert communication_store.get_thread_mapping("thread-unrelated") is None
        assert conversation_store.get_messages_for_conversation("thread-unrelated") == []

    def test_unknown_sender_is_ignored(self):
        provider = FakeProvider("prov-1", "user-1")
        message = _provider_message(provider.provider_id, "thread-unknown", "nobody@unknown.io")
        assert _process_provider_message(provider, message) is None

    def test_existing_thread_mapping_resolves_existing_conversation(self):
        provider = FakeProvider("prov-1", "user-1")
        convo = create_conversation_from_send(
            provider_id=provider.provider_id,
            provider_type="gmail",
            external_thread_id="thread-known",
            external_message_id="out-1",
            subject="Outreach",
            from_email="owner@loqi.com",
            from_name="Owner",
            to_email="lead@acme.com",
            to_name="Lead",
            body="Hello",
            campaign_id="campaign-1",
            workflow_id="campaign-1",
            lead_id="lead-1",
        )
        message = _provider_message(provider.provider_id, "thread-known", "Lead <lead@acme.com>")

        result = _process_provider_message(provider, message)
        inbound = [
            m for m in conversation_store.get_messages_for_conversation(convo.conversation_id)
            if m.direction == "inbound"
        ]
        assert result == convo.conversation_id
        assert len(inbound) == 1

    def test_reply_to_known_outbound_message_resolves_existing_conversation(self):
        provider = FakeProvider("prov-2", "user-1")
        convo = create_conversation_from_send(
            provider_id=provider.provider_id,
            provider_type="gmail",
            external_thread_id="thread-reply",
            external_message_id="out-2",
            subject="Outreach",
            from_email="owner@loqi.com",
            from_name="Owner",
            to_email="lead@acme.com",
            to_name="Lead",
            body="Hello",
            campaign_id="campaign-1",
            workflow_id="campaign-1",
            lead_id="lead-1",
        )
        message = _provider_message(provider.provider_id, "thread-reply", "Lead <lead@acme.com>")
        assert _process_provider_message(provider, message) == convo.conversation_id

    def test_known_lead_email_with_existing_conversation_resolves(self, monkeypatch):
        provider = FakeProvider("prov-3", "user-1")
        convo = create_conversation_from_send(
            provider_id=provider.provider_id,
            provider_type="gmail",
            external_thread_id="thread-new",
            external_message_id="out-3",
            subject="Outreach",
            from_email="owner@loqi.com",
            from_name="Owner",
            to_email="lead@acme.com",
            to_name="Lead",
            body="Hello",
            campaign_id="campaign-1",
            workflow_id="campaign-1",
            lead_id="lead-1",
        )
        # Remove the thread mapping to force the lead-identity resolution path.
        communication_store._thread_mappings.pop("thread-new", None)
        communication_store._by_conversation.pop(convo.conversation_id, None)

        class FakeWorkspaceLead:
            lead_id = "lead-1"

        class FakeRepo:
            async def list_by_email(self, workspace_id, email):
                return [FakeWorkspaceLead()]

        monkeypatch.setattr("services.workspace_state._async_workspace", lambda user_id: "ws-1")
        monkeypatch.setattr(
            "services.persistence.launch.repositories.WorkspaceLeadRepository",
            lambda: FakeRepo(),
        )

        message = _provider_message(provider.provider_id, "thread-new", "Lead <LEAD@acme.com>")
        assert _process_provider_message(provider, message) == convo.conversation_id

    def test_email_normalization_is_case_insensitive(self):
        assert normalize_email("Lead <LEAD@Acme.COM>") == "lead@acme.com"
        assert normalize_email("lead@acme.com") == "lead@acme.com"
        assert normalize_email('"Quoted" <lead@acme.com>') == "lead@acme.com"

    def test_duplicate_inbound_remains_deduplicated(self):
        provider = FakeProvider("prov-4", "user-1")
        convo = create_conversation_from_send(
            provider_id=provider.provider_id,
            provider_type="gmail",
            external_thread_id="thread-dupe",
            external_message_id="out-4",
            subject="Outreach",
            from_email="owner@loqi.com",
            from_name="Owner",
            to_email="lead@acme.com",
            to_name="Lead",
            body="Hello",
            campaign_id="campaign-1",
            workflow_id="campaign-1",
            lead_id="lead-1",
        )
        message = _provider_message(provider.provider_id, "thread-dupe", "Lead <lead@acme.com>")
        assert _process_provider_message(provider, message) == convo.conversation_id
        assert _process_provider_message(provider, message) is None
        inbound = [
            m for m in conversation_store.get_messages_for_conversation(convo.conversation_id)
            if m.direction == "inbound"
        ]
        assert len(inbound) == 1

    def test_unrelated_message_does_not_affect_cursor_progression(self):
        provider = FakeProvider("prov-5", "user-1")
        message = _provider_message(provider.provider_id, "thread-x", "stranger@elsewhere.com")
        assert _process_provider_message(provider, message) is None
        assert communication_store.get_thread_mapping("thread-x") is None
        assert conversation_store.get_conversation("thread-x") is None

    def test_unrelated_message_cannot_create_follow_up_ready(self):
        from services.communication.inbox_sync_engine import maintain_follow_up_readiness

        provider = FakeProvider("prov-6", "user-1")
        message = _provider_message(provider.provider_id, "thread-y", "stranger@elsewhere.com")
        assert _process_provider_message(provider, message) is None
        assert maintain_follow_up_readiness() == 0
        assert conversation_store.get_conversation("thread-y") is None
