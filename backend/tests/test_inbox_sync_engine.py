"""PR8 — background inbox sync and follow-up readiness tests."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.communication import provider_registry
from services.communication.inbox_sync_engine import InboxSyncEngine, maintain_follow_up_readiness
from services.communication.provider_models import ProviderType, SyncResult
from services.conversations.conversation_models import Conversation, ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import handle_reply
from services.conversations.timeline import TimelineEventType


class FakeProvider:
    provider_type = ProviderType.GMAIL

    def __init__(self, provider_id: str, user_id: str = "user-1"):
        self._provider_id = provider_id
        self._user_id = user_id
        self._connected = True

    @property
    def provider_id(self):
        return self._provider_id


@pytest.fixture(autouse=True)
def _clean_registry():
    provider_registry._instances.clear()
    yield
    provider_registry._instances.clear()


def _old_conversation(status=ConversationStatus.SENT):
    conversation = Conversation(status=status, campaign_id="campaign-1", lead_id="lead-1")
    conversation.last_activity_at = datetime.now(timezone.utc) - timedelta(days=4)
    conversation_store.create_conversation(conversation)
    return conversation


class TestInboxSyncEngine:
    def test_start_stop_without_providers_is_healthy(self):
        engine = InboxSyncEngine(interval_seconds=3600)
        asyncio.run(engine.start())
        assert engine._task is not None
        asyncio.run(engine.stop())
        assert engine._task is None

    def test_provider_failures_are_isolated(self, monkeypatch):
        provider_registry.register_instance("bad", FakeProvider("bad"))
        provider_registry.register_instance("good", FakeProvider("good"))
        calls = []

        def fake_sync(provider):
            calls.append(provider.provider_id)
            if provider.provider_id == "bad":
                raise RuntimeError("provider unavailable")
            return SyncResult(provider_id=provider.provider_id, messages_synced=2, cursor="cursor-2")

        monkeypatch.setattr("services.communication.inbox_sync_engine.sync_all", fake_sync)
        result = asyncio.run(InboxSyncEngine(interval_seconds=3600).sync_once())

        assert calls == ["bad", "good"]
        assert result["providers"] == 2

    def test_webhook_trigger_uses_same_sync_path(self, monkeypatch):
        provider_registry.register_instance("gmail-1", FakeProvider("gmail-1"))
        calls = []

        def fake_sync(provider):
            calls.append(provider.provider_id)
            return SyncResult(provider_id=provider.provider_id, cursor="cursor")

        monkeypatch.setattr("services.communication.inbox_sync_engine.sync_all", fake_sync)
        asyncio.run(InboxSyncEngine(interval_seconds=3600).sync_once(["gmail-1"]))
        assert calls == ["gmail-1"]


class TestFollowUpReadiness:
    def test_due_outbound_conversation_becomes_ready_without_sending(self):
        conversation = _old_conversation()
        before_messages = conversation_store.get_messages_for_conversation(conversation.conversation_id)

        assert maintain_follow_up_readiness() == 1
        updated = conversation_store.get_conversation(conversation.conversation_id)
        events = conversation_store.get_timeline(conversation.conversation_id)

        assert updated.status == ConversationStatus.FOLLOW_UP_READY
        assert sum(event.event_type == TimelineEventType.FOLLOW_UP_READY for event in events) == 1
        assert conversation_store.get_messages_for_conversation(conversation.conversation_id) == before_messages

    def test_readiness_is_idempotent_and_follow_up_sent_stays_sent(self):
        ready = _old_conversation()
        assert maintain_follow_up_readiness() == 1
        assert maintain_follow_up_readiness() == 0
        assert sum(
            event.event_type == TimelineEventType.FOLLOW_UP_READY
            for event in conversation_store.get_timeline(ready.conversation_id)
        ) == 1

        sent = _old_conversation(ConversationStatus.FOLLOW_UP_SENT)
        assert maintain_follow_up_readiness() == 0
        assert conversation_store.get_conversation(sent.conversation_id).status == ConversationStatus.FOLLOW_UP_SENT

    def test_pending_follow_up_promotes_once(self):
        conversation = _old_conversation(ConversationStatus.FOLLOW_UP_PENDING)
        assert maintain_follow_up_readiness() == 1
        assert conversation_store.get_conversation(conversation.conversation_id).status == ConversationStatus.FOLLOW_UP_READY
        assert maintain_follow_up_readiness() == 0

    def test_duplicate_inbound_after_store_reload_does_not_duplicate_message(self):
        conversation = _old_conversation()
        handle_reply(
            conversation_id=conversation.conversation_id,
            external_message_id="gmail-message-1",
            from_email="lead@example.com",
            from_name="Lead",
            to_email="owner@example.com",
            to_name="Owner",
            subject="Re: question",
            body="Interested.",
        )
        conversation_store.reload()
        handle_reply(
            conversation_id=conversation.conversation_id,
            external_message_id="gmail-message-1",
            from_email="lead@example.com",
            from_name="Lead",
            to_email="owner@example.com",
            to_name="Owner",
            subject="Re: question",
            body="Interested.",
        )
        inbound = [
            message for message in conversation_store.get_messages_for_conversation(conversation.conversation_id)
            if message.direction == "inbound"
        ]
        assert len(inbound) == 1

    def test_unknown_inbound_does_not_create_orphan_state(self):
        assert handle_reply(
            conversation_id="missing-conversation",
            external_message_id="gmail-message-missing",
            from_email="lead@example.com",
            from_name="Lead",
            to_email="owner@example.com",
            to_name="Owner",
            subject="Re: unknown",
            body="Hello",
        ) is None
        assert conversation_store.get_conversation("missing-conversation") is None
        assert conversation_store.get_messages_for_conversation("missing-conversation") == []
