"""R23-C-5b durable legacy-memory persistence characterization."""

from __future__ import annotations

import pytest

from services.conversation_models import ConversationMemory
from services.conversations.conversation_models import Conversation
from services.conversations import intelligence_memory


class _ConversationStore:
    def __init__(self, conversation):
        self.conversation = conversation

    def get_conversation(self, conversation_id):
        return self.conversation if conversation_id == self.conversation.conversation_id else None


@pytest.fixture
def canonical_conversation(monkeypatch, tmp_path):
    conversation = Conversation(
        conversation_id="00000000-0000-4000-8000-000000000901",
        owner_id="owner-1",
        metadata={"workspace_id": "workspace-1"},
    )
    monkeypatch.setattr(intelligence_memory, "conversation_store", _ConversationStore(conversation))
    monkeypatch.setattr(intelligence_memory, "get_supabase_client", lambda: None)
    monkeypatch.setattr(intelligence_memory, "STATE_FILE", str(tmp_path / "intelligence-memory.json"))
    return conversation


def _memory(conversation_id: str, summary: str = "first"):
    return ConversationMemory(conversation_id=conversation_id, summary=summary)


def test_persisted_memory_round_trips_for_authorized_canonical_conversation(canonical_conversation):
    record = intelligence_memory.persist_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
        memory=_memory(canonical_conversation.conversation_id),
        source_message_id="gmail-message-1",
        expected_version=0,
    )

    loaded = intelligence_memory.load_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
    )

    assert record.version == 1
    assert loaded is not None
    assert loaded.memory.model_dump(mode="json") == record.memory.model_dump(mode="json")
    assert loaded.source_message_ids == ("gmail-message-1",)


def test_replaying_source_message_is_idempotent(canonical_conversation):
    first = intelligence_memory.persist_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
        memory=_memory(canonical_conversation.conversation_id, "first"),
        source_message_id="gmail-message-1",
        expected_version=0,
    )
    replay = intelligence_memory.persist_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
        memory=_memory(canonical_conversation.conversation_id, "must-not-overwrite"),
        source_message_id="gmail-message-1",
        expected_version=0,
    )

    assert replay.version == first.version == 1
    assert replay.memory.summary == "first"


def test_stale_version_cannot_overwrite_newer_memory(canonical_conversation):
    first = intelligence_memory.persist_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
        memory=_memory(canonical_conversation.conversation_id, "first"),
        source_message_id="gmail-message-1",
        expected_version=0,
    )
    intelligence_memory.persist_legacy_memory(
        conversation_id=canonical_conversation.conversation_id,
        owner_id="owner-1",
        workspace_id="workspace-1",
        memory=_memory(canonical_conversation.conversation_id, "second"),
        source_message_id="gmail-message-2",
        expected_version=first.version,
    )

    with pytest.raises(intelligence_memory.ConversationMemoryVersionConflict):
        intelligence_memory.persist_legacy_memory(
            conversation_id=canonical_conversation.conversation_id,
            owner_id="owner-1",
            workspace_id="workspace-1",
            memory=_memory(canonical_conversation.conversation_id, "stale"),
            source_message_id="gmail-message-3",
            expected_version=first.version,
        )


def test_foreign_owner_cannot_read_or_write_memory(canonical_conversation):
    with pytest.raises(intelligence_memory.ConversationMemoryAccessError):
        intelligence_memory.load_legacy_memory(
            conversation_id=canonical_conversation.conversation_id,
            owner_id="owner-2",
            workspace_id="workspace-1",
        )

    with pytest.raises(intelligence_memory.ConversationMemoryAccessError):
        intelligence_memory.persist_legacy_memory(
            conversation_id=canonical_conversation.conversation_id,
            owner_id="owner-2",
            workspace_id="workspace-1",
            memory=_memory(canonical_conversation.conversation_id),
            source_message_id="gmail-message-1",
            expected_version=0,
        )


def test_noncanonical_id_cannot_create_durable_memory(canonical_conversation):
    with pytest.raises(intelligence_memory.ConversationMemoryAccessError):
        intelligence_memory.persist_legacy_memory(
            conversation_id="analysis-only-id",
            owner_id="owner-1",
            workspace_id="workspace-1",
            memory=_memory("analysis-only-id"),
            source_message_id="analysis-message-1",
            expected_version=0,
        )
