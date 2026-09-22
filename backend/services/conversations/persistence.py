"""Durable persistence backend for the conversation store.

The conversation store only depends on two functions — ``save(snapshot)``
and ``load()``. Production persists one snapshot per conversation in
Supabase; the JSON-file backend remains only for local/test environments with
no configured database. The store and conversation APIs keep their existing
contract.

The snapshot is an explicit JSON document (never pickled): every entity is
serialized through the existing ``to_dict()`` serializers and restored
through ``from_dict()``, so ids, timestamps, statuses, classifications and
all relationships survive the round trip verbatim.

Durability (PR10.8): writes are atomic (tmp file + fsync + ``os.replace``)
with a stale-write guard on the snapshot ``sequence``; malformed state is
preserved to ``<file>.corrupt.<timestamp>`` instead of being silently
replaced. Write failures raise — callers must not treat them as success.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

from services.persistence import json_file
from services.persistence import retry

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

CATEGORY = "conversations"
LOAD_PAGE_SIZE = 100


class DurableConversationPersistenceUnavailable(RuntimeError):
    """The durable Inbox backend could not be read after bounded retry.

    This is deliberately distinct from corrupt snapshot data. Callers must
    not replace durable conversation state with an empty store in this case.
    """


class DurableConversationPersistenceCorrupt(RuntimeError):
    """The durable snapshot is present but does not satisfy its contract."""


def _local_fallback_allowed() -> bool:
    """Container-local Inbox snapshots are never a production fallback."""
    environment = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()
    return environment != "production" or os.getenv("LOQI_ALLOW_LOCAL_CONVERSATION_SNAPSHOTS", "").lower() in {"1", "true", "yes"}


def _read_local_state() -> Tuple[Optional[dict[str, Any]], json_file.JsonFileStatus]:
    data, status = json_file.read_json(STATE_FILE, category=CATEGORY)
    if status is json_file.JsonFileStatus.OK and not isinstance(data, dict):
        logger.warning("persistence_read_invalid_shape category=%s", CATEGORY)
        json_file.preserve_corrupt(STATE_FILE, CATEGORY)
        return None, json_file.JsonFileStatus.CORRUPT
    return data, status


def _default_state_file() -> str:
    # Up three levels from this file: services/conversations -> backend.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".conversations.json")


STATE_FILE = os.getenv("CONVERSATIONS_STATE_FILE", "") or _default_state_file()


def _client():
    """Return the configured production persistence client, if any.

    A missing client is a local-development condition and may use the explicit
    file fallback. Once a client exists, read/write failures are surfaced to
    callers instead of silently falling back to container-local storage.
    """
    from services.platform.supabase import get_supabase_client
    return get_supabase_client()


def _conversation_snapshots(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a store snapshot into independently durable conversation rows."""
    conversations = snapshot.get("conversations") or []
    threads = snapshot.get("threads") or []
    messages = snapshot.get("messages") or []
    timeline = snapshot.get("timeline") or {}
    rows: list[dict[str, Any]] = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(conversation.get("conversation_id") or "")
        if not conversation_id:
            continue
        metadata = conversation.get("metadata") if isinstance(conversation.get("metadata"), dict) else {}
        workspace_id = str(metadata.get("workspace_id") or "").strip()
        if not workspace_id:
            raise RuntimeError(f"Conversation {conversation_id} has no workspace_id")
        payload = {
            "version": SNAPSHOT_VERSION,
            "sequence": int(snapshot.get("sequence") or 0),
            "conversations": [conversation],
            "threads": [t for t in threads if isinstance(t, dict) and t.get("conversation_id") == conversation_id],
            "messages": [m for m in messages if isinstance(m, dict) and m.get("conversation_id") == conversation_id],
            "timeline": {conversation_id: timeline.get(conversation_id) or []},
        }
        rows.append({
            "conversation_id": conversation_id,
            "owner_id": str(conversation.get("owner_id") or ""),
            "workspace_id": workspace_id,
            "expected_version": int(metadata.get("_persistence_version") or 0),
            "snapshot": payload,
        })
    return rows


def _save_supabase(client, snapshot: dict[str, Any]) -> dict[str, int]:
    versions: dict[str, int] = {}
    for row in _conversation_snapshots(snapshot):
        result = client.rpc("persist_conversation_snapshot", {
            "p_conversation_id": row["conversation_id"],
            "p_owner_id": row["owner_id"],
            "p_workspace_id": row["workspace_id"],
            "p_snapshot": row["snapshot"],
            "p_expected_version": row["expected_version"],
        }).execute()
        value = getattr(result, "data", None)
        versions[row["conversation_id"]] = int(value)
    return versions


def _load_supabase(client) -> tuple[Optional[dict[str, Any]], json_file.JsonFileStatus]:
    """Load every durable snapshot through bounded, deterministic pages."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        try:
            result = (
                client.table("conversation_snapshots")
                .select("snapshot, owner_id, workspace_id, version")
                .order("conversation_id")
                .range(start, start + LOAD_PAGE_SIZE - 1)
                .execute()
            )
        except Exception as error:
            logger.error(
                "persistence_read_page_failed category=%s start=%d error_type=%s",
                CATEGORY,
                start,
                type(error).__name__,
            )
            raise
        page = getattr(result, "data", None) or []
        if not isinstance(page, list):
            raise DurableConversationPersistenceCorrupt("Invalid durable conversation page")
        rows.extend(page)
        if len(page) < LOAD_PAGE_SIZE:
            break
        start += LOAD_PAGE_SIZE
    if not rows:
        return None, json_file.JsonFileStatus.ABSENT
    combined: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "sequence": 0,
        "conversations": [],
        "threads": [],
        "messages": [],
        "timeline": {},
    }
    for row in rows:
        if not isinstance(row, dict):
            raise DurableConversationPersistenceCorrupt("Invalid durable conversation row")
        payload = row.get("snapshot")
        if not isinstance(payload, dict):
            raise DurableConversationPersistenceCorrupt("Invalid durable conversation snapshot")
        combined["sequence"] = max(combined["sequence"], int(payload.get("sequence") or 0))
        conversations = payload.get("conversations") or []
        for conversation in conversations:
            if not isinstance(conversation, dict):
                raise DurableConversationPersistenceCorrupt("Invalid durable conversation row")
            if str(conversation.get("owner_id") or "") != str(row.get("owner_id") or ""):
                raise DurableConversationPersistenceCorrupt("Conversation owner mismatch")
            metadata = conversation.setdefault("metadata", {})
            if not isinstance(metadata, dict):
                raise DurableConversationPersistenceCorrupt("Invalid durable conversation metadata")
            metadata["workspace_id"] = str(row.get("workspace_id") or "")
            metadata["_persistence_version"] = int(row.get("version") or 0)
        combined["conversations"].extend(conversations)
        combined["threads"].extend(payload.get("threads") or [])
        combined["messages"].extend(payload.get("messages") or [])
        combined["timeline"].update(payload.get("timeline") or {})
    return combined, json_file.JsonFileStatus.OK


def delete_conversation(conversation_id: str) -> None:
    """Remove one durable conversation snapshot after an explicit deletion."""
    if not conversation_id:
        return
    client = _client()
    if client is not None:
        client.table("conversation_snapshots").delete().eq("conversation_id", conversation_id).execute()
        return
    # The local fallback is rewritten by the caller's subsequent store save.


def save(snapshot: dict[str, Any]) -> dict[str, int]:
    """Atomically persist the store snapshot (tmp file + fsync + rename).

    Raises on failure; the previous on-disk snapshot is left intact. A
    snapshot older than the one already on disk is skipped (stale guard).
    """
    client = _client()
    if client is not None:
        try:
            return _save_supabase(client, snapshot)
        except Exception:
            if not _local_fallback_allowed():
                raise
            logger.warning("conversation_supabase_save_unavailable_using_development_fallback", exc_info=True)
            json_file.atomic_write_json(STATE_FILE, snapshot, sequence_key="sequence", category=CATEGORY)
            return {}
    if not _local_fallback_allowed():
        raise RuntimeError("Durable conversation persistence is unavailable; local fallback is disabled")
    json_file.atomic_write_json(STATE_FILE, snapshot, sequence_key="sequence", category=CATEGORY)
    return {}


def load() -> Optional[dict[str, Any]]:
    """Load the last persisted snapshot, or None when absent/corrupt.

    A corrupt file is preserved (never destroyed) and the store is left
    empty — the caller may then rehydrate a fresh snapshot on next save.
    """
    data, status = json_file.read_json(STATE_FILE, category=CATEGORY)
    if status is json_file.JsonFileStatus.OK:
        if isinstance(data, dict):
            return data
        logger.warning("persistence_read_invalid_shape category=%s", CATEGORY)
        json_file.preserve_corrupt(STATE_FILE, CATEGORY)
        return None
    if status is json_file.JsonFileStatus.CORRUPT:
        return None
    return None


def load_state() -> Tuple[Optional[dict[str, Any]], json_file.JsonFileStatus]:
    """Return ``(data, status)`` for accurate corruption handling by callers."""
    client = _client()
    if client is not None:
        try:
            return retry.retry_sync(
                lambda: _load_supabase(client),
                category=CATEGORY,
            )
        except DurableConversationPersistenceCorrupt as error:
            logger.error("persistence_read_corrupt category=%s error_type=%s", CATEGORY, type(error).__name__)
            return None, json_file.JsonFileStatus.CORRUPT
        except Exception as error:
            logger.error(
                "persistence_read_unavailable category=%s retryable=%s error_type=%s",
                CATEGORY,
                retry.classify_retryable(error),
                type(error).__name__,
            )
            raise DurableConversationPersistenceUnavailable(
                "Durable conversation persistence is unavailable"
            ) from error
    if not _local_fallback_allowed():
        logger.error("persistence_read_temporarily_unavailable category=%s error=durable_backend_unavailable", CATEGORY)
        raise DurableConversationPersistenceUnavailable(
            "Durable conversation persistence is unavailable"
        )
    return _read_local_state()
