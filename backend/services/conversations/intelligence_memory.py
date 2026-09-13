"""Durable, authorized storage for the legacy conversation-memory projection.

This is deliberately separate from Inbox snapshots: intelligence updates have
their own idempotency and compare-and-swap lifecycle. The active legacy
``services.conversation_memory`` store is not cut over here; C5c migrates its
callers after this boundary is proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any

from services.conversation_models import ConversationMemory
from services.conversations.conversation_store import (
    conversation_in_workspace,
    conversation_owned_by,
    conversation_store,
)
from services.persistence import json_file
from services.platform.supabase import get_supabase_client


_CATEGORY = "conversation_intelligence_memories"
_MAX_SOURCE_MESSAGE_IDS = 200


def _default_state_file() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".conversation_intelligence_memories.json")


STATE_FILE = (
    os.getenv("CONVERSATION_INTELLIGENCE_MEMORY_STATE_FILE", "")
    or _default_state_file()
)


class ConversationMemoryAccessError(Exception):
    """The requested canonical Inbox conversation is unavailable to the caller."""


class ConversationMemoryVersionConflict(Exception):
    """A newer durable memory write won the compare-and-swap race."""


@dataclass(frozen=True)
class LegacyConversationMemoryRecord:
    conversation_id: str
    owner_id: str
    workspace_id: str
    memory: ConversationMemory
    source_message_ids: tuple[str, ...]
    version: int
    updated_at: str


def _authorized_conversation(*, conversation_id: str, owner_id: str, workspace_id: str):
    conversation = conversation_store.get_conversation(conversation_id)
    if (
        conversation is None
        or not conversation_owned_by(conversation, owner_id)
        or not conversation_in_workspace(conversation, workspace_id)
    ):
        raise ConversationMemoryAccessError("Conversation is unavailable")
    return conversation


def _record_from_row(row: dict[str, Any]) -> LegacyConversationMemoryRecord:
    memory_payload = row.get("memory") if isinstance(row.get("memory"), dict) else {}
    source_ids = row.get("processed_source_message_ids") or row.get("source_message_ids") or []
    return LegacyConversationMemoryRecord(
        conversation_id=str(row.get("conversation_id") or ""),
        owner_id=str(row.get("owner_id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        memory=ConversationMemory.model_validate(memory_payload),
        source_message_ids=tuple(str(item) for item in source_ids if str(item)),
        version=int(row.get("version") or 0),
        updated_at=str(row.get("updated_at") or ""),
    )


def _load_local_rows() -> dict[str, dict[str, Any]]:
    data, status = json_file.read_json(STATE_FILE, category=_CATEGORY)
    if status is json_file.JsonFileStatus.ABSENT:
        return {}
    if status is not json_file.JsonFileStatus.OK or not isinstance(data, dict):
        raise RuntimeError("Conversation intelligence memory persistence is unreadable")
    rows = data.get("records") or {}
    if not isinstance(rows, dict):
        raise RuntimeError("Conversation intelligence memory persistence has invalid records")
    return rows


def _save_local_rows(rows: dict[str, dict[str, Any]]) -> None:
    current, status = json_file.read_json(STATE_FILE, category=_CATEGORY)
    if status is json_file.JsonFileStatus.OK and isinstance(current, dict):
        sequence = int(current.get("sequence") or 0) + 1
    elif status is json_file.JsonFileStatus.ABSENT:
        sequence = 1
    else:
        raise RuntimeError("Conversation intelligence memory persistence is unreadable")
    json_file.atomic_write_json(
        STATE_FILE,
        {"sequence": sequence, "records": rows},
        sequence_key="sequence",
        category=_CATEGORY,
    )


def load_legacy_memory(
    *, conversation_id: str, owner_id: str, workspace_id: str,
) -> LegacyConversationMemoryRecord | None:
    """Load a legacy-compatible memory only after canonical scope validation."""
    _authorized_conversation(
        conversation_id=conversation_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    client = get_supabase_client()
    if client is not None:
        result = client.table("conversation_intelligence_memories").select(
            "conversation_id, owner_id, workspace_id, memory, processed_source_message_ids, version, updated_at"
        ).eq("conversation_id", conversation_id).eq("owner_id", owner_id).eq(
            "workspace_id", workspace_id
        ).limit(1).execute()
        rows = getattr(result, "data", None) or []
        return _record_from_row(rows[0]) if rows else None
    row = _load_local_rows().get(conversation_id)
    if row is None:
        return None
    if str(row.get("owner_id") or "") != str(owner_id) or str(row.get("workspace_id") or "") != str(workspace_id):
        raise ConversationMemoryAccessError("Conversation is unavailable")
    return _record_from_row(row)


def persist_legacy_memory(
    *,
    conversation_id: str,
    owner_id: str,
    workspace_id: str,
    memory: ConversationMemory,
    source_message_id: str,
    expected_version: int,
) -> LegacyConversationMemoryRecord:
    """Persist one canonical memory update with source-message idempotency."""
    _authorized_conversation(
        conversation_id=conversation_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    if not source_message_id:
        raise ValueError("source_message_id is required")
    if memory.conversation_id != conversation_id:
        raise ValueError("memory conversation_id must match canonical conversation_id")

    client = get_supabase_client()
    if client is not None:
        try:
            result = client.rpc("persist_conversation_intelligence_memory", {
                "p_conversation_id": conversation_id,
                "p_owner_id": owner_id,
                "p_workspace_id": workspace_id,
                "p_memory": memory.model_dump(mode="json"),
                "p_source_message_id": source_message_id,
                "p_expected_version": expected_version,
            }).execute()
        except Exception as error:
            raise ConversationMemoryVersionConflict from error
        version = int(getattr(result, "data", 0) or 0)
        current = load_legacy_memory(
            conversation_id=conversation_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
        )
        if current is None or current.version != version:
            raise RuntimeError("Conversation intelligence memory write could not be verified")
        return current

    rows = _load_local_rows()
    existing = rows.get(conversation_id)
    if existing is not None:
        if str(existing.get("owner_id") or "") != str(owner_id) or str(existing.get("workspace_id") or "") != str(workspace_id):
            raise ConversationMemoryAccessError("Conversation is unavailable")
        source_ids = [str(item) for item in existing.get("source_message_ids") or []]
        if source_message_id in source_ids:
            return _record_from_row(existing)
        if int(existing.get("version") or 0) != expected_version:
            raise ConversationMemoryVersionConflict("Conversation intelligence memory version conflict")
    elif expected_version != 0:
        raise ConversationMemoryVersionConflict("Conversation intelligence memory version conflict")
    else:
        source_ids = []

    source_ids = (source_ids + [source_message_id])[-_MAX_SOURCE_MESSAGE_IDS:]
    row = {
        "conversation_id": conversation_id,
        "owner_id": owner_id,
        "workspace_id": workspace_id,
        "memory": memory.model_dump(mode="json"),
        "source_message_ids": source_ids,
        "version": (int(existing.get("version") or 0) if existing else 0) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    rows[conversation_id] = row
    _save_local_rows(rows)
    return _record_from_row(row)
