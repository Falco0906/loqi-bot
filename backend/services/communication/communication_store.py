"""Communication Store — persists provider state, sync cursors, thread mappings.

Separate from Conversation Memory.
Stores:
- Provider records
- Sync cursors
- External thread ↔ conversation ID mappings
- External message IDs (for deduplication)
"""

from datetime import datetime, timezone
from typing import Optional

from services.communication.provider_models import (
    CommunicationProvider,
    SyncCursor,
    ThreadMapping,
    ProviderType,
    ProviderStatus,
)


class CommunicationStore:
    """In-memory store for provider state. Future: swap with DB."""

    def __init__(self) -> None:
        self._providers: dict[str, CommunicationProvider] = {}
        self._cursors: dict[str, SyncCursor] = {}
        self._thread_mappings: dict[str, ThreadMapping] = {}  # external_thread_id -> mapping
        self._by_conversation: dict[str, str] = {}  # conversation_id -> external_thread_id
        self._seen_message_ids: set[str] = set()
        self._user_providers: dict[str, list[str]] = {}
        self._recent_messages: list[dict] = []  # user_id -> [provider_id]

    # ── Provider CRUD ──

    def save_provider(self, provider: CommunicationProvider) -> None:
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
        sc = SyncCursor(provider_id=provider_id, cursor=cursor)
        self._cursors[provider_id] = sc
        return sc

    def get_cursor(self, provider_id: str) -> Optional[SyncCursor]:
        return self._cursors.get(provider_id)

    # ── Thread Mappings ──

    def map_thread(self, external_thread_id: str, conversation_id: str,
                   provider_id: str, subject: str = "") -> ThreadMapping:
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
