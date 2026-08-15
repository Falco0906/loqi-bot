"""Communication Store — persists provider state, sync cursors, thread mappings.

Separate from Conversation Memory.
Stores:
- Provider records
- Sync cursors
- External thread ↔ conversation ID mappings
- External message IDs (for deduplication)

Durability (PR10.8): when ``COMMUNICATION_STATE_FILE`` is configured the
store snapshots cursor/thread-mapping/dedup state to that file with atomic
writes (see ``services.persistence.json_file``), so a container restart
resumes incremental sync from the last cursor instead of re-syncing from
scratch and losing the seen-message set. Without the env var the store
behaves exactly as before (pure in-memory).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from services.communication.provider_models import (
    CommunicationProvider,
    SyncCursor,
    ThreadMapping,
    ProviderType,
    ProviderStatus,
)
from services.persistence import json_file

logger = logging.getLogger(__name__)

CATEGORY = "communication"
SNAPSHOT_VERSION = 1


def _default_state_file() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".communication.json")


STATE_FILE = os.getenv("COMMUNICATION_STATE_FILE", "") or _default_state_file()
PERSISTENCE_ENABLED = bool(os.getenv("COMMUNICATION_STATE_FILE", ""))


class CommunicationStore:
    """Provider state store with optional durable JSON snapshots."""

    def __init__(self, *, enable_persistence: bool | None = None) -> None:
        self._providers: dict[str, CommunicationProvider] = {}
        self._cursors: dict[str, SyncCursor] = {}
        self._thread_mappings: dict[str, ThreadMapping] = {}  # external_thread_id -> mapping
        self._by_conversation: dict[str, str] = {}  # conversation_id -> external_thread_id
        self._seen_message_ids: set[str] = set()
        self._user_providers: dict[str, list[str]] = {}
        self._recent_messages: list[dict] = []  # user_id -> [provider_id]
        self._sequence = 0
        self._lock = threading.RLock()
        if enable_persistence is not None:
            global PERSISTENCE_ENABLED
            PERSISTENCE_ENABLED = enable_persistence

    # ── Durable snapshots ──

    def to_snapshot(self) -> dict:
        """Explicit JSON-safe snapshot of durable state (no credentials)."""
        with self._lock:
            return {
                "version": SNAPSHOT_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "sequence": self._sequence,
                "cursors": {pid: sc.cursor for pid, sc in self._cursors.items()},
                "thread_mappings": [
                    {
                        "provider_id": m.provider_id,
                        "external_thread_id": m.external_thread_id,
                        "conversation_id": m.conversation_id,
                        "subject": m.subject,
                    }
                    for m in self._thread_mappings.values()
                ],
                "seen_message_ids": sorted(self._seen_message_ids),
            }

    def _restore_from_snapshot(self, data: dict) -> None:
        with self._lock:
            try:
                self._sequence = int(data.get("sequence") or 0)
            except (TypeError, ValueError):
                self._sequence = 0
            for pid, cursor in (data.get("cursors") or {}).items():
                self._cursors[pid] = SyncCursor(provider_id=pid, cursor=str(cursor))
            self._thread_mappings.clear()
            self._by_conversation.clear()
            for raw in data.get("thread_mappings") or []:
                mapping = ThreadMapping(
                    provider_id=raw.get("provider_id", ""),
                    external_thread_id=raw.get("external_thread_id", ""),
                    conversation_id=raw.get("conversation_id", ""),
                    subject=raw.get("subject", ""),
                )
                self._thread_mappings[mapping.external_thread_id] = mapping
                self._by_conversation[mapping.conversation_id] = mapping.external_thread_id
            self._seen_message_ids = set(data.get("seen_message_ids") or [])

    def save_state(self) -> None:
        """Persist durable state atomically; no-op when persistence disabled."""
        if not PERSISTENCE_ENABLED:
            return
        try:
            json_file.atomic_write_json(
                STATE_FILE, self.to_snapshot(), sequence_key="sequence", category=CATEGORY,
            )
        except Exception as e:
            logger.error(
                "persistence_write_failed category=communication error_type=%s",
                type(e).__name__, exc_info=True,
            )

    def load_state(self) -> None:
        """Rehydrate durable state from disk; no-op when persistence disabled.

        A corrupt file is preserved (never destroyed); the store then starts
        empty and the next incremental sync falls back to a full sync.
        """
        if not PERSISTENCE_ENABLED:
            return
        data, status = json_file.read_json(STATE_FILE, category=CATEGORY)
        if status is json_file.JsonFileStatus.OK and isinstance(data, dict):
            self._restore_from_snapshot(data)
            logger.info(
                "persistence_rehydration_completed category=communication "
                "cursors=%d mappings=%d seen=%d",
                len(self._cursors), len(self._thread_mappings), len(self._seen_message_ids),
            )
            return
        if status is json_file.JsonFileStatus.CORRUPT:
            logger.warning(
                "persistence_rehydration_degraded category=communication status=%s preserved=yes",
                status.value,
            )
            return
        logger.info("persistence_rehydration_absent category=communication")

    # ── Provider CRUD ──

    def save_provider(self, provider: CommunicationProvider) -> None:
        with self._lock:
            # Idempotent logical account (PR10.8.2 live fix): the Settings API
            # aggregates from this store, so a reconnect must REPLACE any
            # existing provider record for the same (user, provider type)
            # instead of stacking a second "Connected Account".
            for pid in list(self._providers.keys()):
                existing = self._providers[pid]
                if (existing.user_id == provider.user_id
                        and existing.provider_type == provider.provider_type
                        and pid != provider.id):
                    self._providers.pop(pid, None)
                    pids = self._user_providers.get(existing.user_id, [])
                    if pid in pids:
                        pids.remove(pid)
            self._providers[provider.id] = provider
            if provider.user_id not in self._user_providers:
                self._user_providers[provider.user_id] = []
            if provider.id not in self._user_providers[provider.user_id]:
                self._user_providers[provider.user_id].append(provider.id)
            provider.updated_at = datetime.now(timezone.utc).isoformat()

    def get_provider(self, provider_id: str) -> Optional[CommunicationProvider]:
        return self._providers.get(provider_id)

    def get_user_providers(self, user_id: str) -> list[CommunicationProvider]:
        pids = self._user_providers.get(user_id, [])
        return [self._providers[pid] for pid in pids if pid in self._providers]

    def list_providers(self) -> list[CommunicationProvider]:
        return list(self._providers.values())

    def remove_provider(self, provider_id: str) -> bool:
        with self._lock:
            provider = self._providers.pop(provider_id, None)
            if provider:
                pids = self._user_providers.get(provider.user_id, [])
                if provider_id in pids:
                    pids.remove(provider_id)
                return True
            return False

    def update_provider_status(self, provider_id: str, status: ProviderStatus) -> bool:
        provider = self.get_provider(provider_id)
        if not provider:
            return False
        provider.status = status
        provider.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def update_provider_sync(self, provider_id: str, cursor: str) -> bool:
        provider = self.get_provider(provider_id)
        if not provider:
            return False
        provider.sync_cursor = cursor
        provider.last_sync = datetime.now(timezone.utc).isoformat()
        provider.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    # ── Sync Cursors ──

    def save_cursor(self, provider_id: str, cursor: str) -> SyncCursor:
        with self._lock:
            self._sequence += 1
            sc = SyncCursor(provider_id=provider_id, cursor=cursor)
            self._cursors[provider_id] = sc
            return sc

    def get_cursor(self, provider_id: str) -> Optional[SyncCursor]:
        return self._cursors.get(provider_id)

    # ── Thread Mappings ──

    def map_thread(self, external_thread_id: str, conversation_id: str,
                   provider_id: str, subject: str = "") -> ThreadMapping:
        with self._lock:
            existing = self._thread_mappings.get(external_thread_id)
            if existing and existing.conversation_id == conversation_id:
                return existing
            self._sequence += 1
            mapping = ThreadMapping(
                provider_id=provider_id,
                external_thread_id=external_thread_id,
                conversation_id=conversation_id,
                subject=subject,
            )
            self._thread_mappings[external_thread_id] = mapping
            self._by_conversation[conversation_id] = external_thread_id
            return mapping

    def get_thread_mapping(self, external_thread_id: str) -> Optional[ThreadMapping]:
        return self._thread_mappings.get(external_thread_id)

    def get_thread_by_conversation(self, conversation_id: str) -> Optional[ThreadMapping]:
        ext_id = self._by_conversation.get(conversation_id)
        if not ext_id:
            return None
        return self._thread_mappings.get(ext_id)

    def get_all_threads(self) -> list[ThreadMapping]:
        return list(self._thread_mappings.values())

    # ── Deduplication ──

    def mark_message_seen(self, external_id: str) -> None:
        with self._lock:
            if external_id not in self._seen_message_ids:
                self._sequence += 1
            self._seen_message_ids.add(external_id)

    def is_message_seen(self, external_id: str) -> bool:
        return external_id in self._seen_message_ids

    def message_count(self) -> int:
        return len(self._seen_message_ids)

    def seen_messages(self) -> set[str]:
        return self._seen_message_ids

    # ── Recent Messages (for dev diagnostics) ──

    def add_recent_message(self, subject: str, sender: str, date: str,
                           thread_id: str, message_id: str, history_id: str = "") -> None:
        self._recent_messages.append({
            "subject": subject,
            "sender": sender,
            "date": date,
            "thread_id": thread_id,
            "message_id": message_id,
            "history_id": history_id,
        })
        if len(self._recent_messages) > 50:
            self._recent_messages = self._recent_messages[-50:]

    def get_recent_messages(self, limit: int = 10) -> list[dict]:
        return self._recent_messages[-limit:]


store = CommunicationStore()
