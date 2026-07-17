"""In-memory conversation store.

Stores conversations, threads, messages, and timeline events.
Provides indexed lookups by provider, campaign, workflow, and status.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from services.conversations.conversation_models import (
    Conversation,
    ConversationThread,
    ConversationMessage,
    ConversationStatus,
)
from services.conversations.timeline import TimelineEvent, TimelineEventType, build_timeline_event
from services.conversations.state_machine import transition

logger = logging.getLogger(__name__)


class ConversationStore:
    def __init__(self):
        self._conversations: dict[str, Conversation] = {}
        self._threads: dict[str, ConversationThread] = {}
        self._messages: dict[str, ConversationMessage] = {}
        self._timeline: dict[str, list[TimelineEvent]] = {}
        self._by_provider: dict[str, set[str]] = {}
        self._by_campaign: dict[str, set[str]] = {}
        self._by_workflow: dict[str, set[str]] = {}
        self._by_status: dict[ConversationStatus, set[str]] = {}
        self._by_external_thread: dict[str, str] = {}

    # ── Conversation CRUD ──

    def create_conversation(self, conversation: Conversation) -> Conversation:
        cid = conversation.conversation_id
        self._conversations[cid] = conversation
        self._add_index(conversation)
        self._add_timeline_event(build_timeline_event(
            conversation_id=cid,
            event_type=TimelineEventType.CAMPAIGN_CREATED,
            title="Conversation created",
            description=f"Conversation {cid[:12]} initialized",
            metadata={"status": conversation.status.value},
        ))
        logger.info("[conversations] Created conversation %s", cid[:12])
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)

    def update_conversation(self, conversation: Conversation) -> Conversation:
        cid = conversation.conversation_id
        old = self._conversations.get(cid)
        if old:
            if old.status != conversation.status:
                old_status = old.status
                new_status = transition(old.status, conversation.status)
                if new_status != old_status:
                    self._remove_status_index(cid, old_status)
                    self._add_status_index(cid, new_status)
                    self._add_timeline_event(build_timeline_event(
                        conversation_id=cid,
                        event_type=TimelineEventType.STATUS_CHANGED,
                        title=f"Status: {old_status.value} → {new_status.value}",
                        metadata={"from": old_status.value, "to": new_status.value},
                    ))
            self._conversations[cid] = conversation
            conversation.updated_at = datetime.now(timezone.utc)
        else:
            self._conversations[cid] = conversation
            self._add_index(conversation)
        return conversation

    def list_conversations(
        self,
        provider_id: str = "",
        campaign_id: str = "",
        workflow_id: str = "",
        status: Optional[ConversationStatus] = None,
        limit: int = 50,
    ) -> list[Conversation]:
        ids: set[str] = set()
        if provider_id:
            ids |= self._by_provider.get(provider_id, set())
        if campaign_id:
            ids |= self._by_campaign.get(campaign_id, set())
        if workflow_id:
            ids |= self._by_workflow.get(workflow_id, set())
        if status:
            ids |= self._by_status.get(status, set())
        if not ids:
            ids = set(self._conversations.keys())
        result = [self._conversations[cid] for cid in ids if cid in self._conversations]
        result.sort(key=lambda c: c.last_activity_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return result[:limit]

    def delete_conversation(self, conversation_id: str) -> bool:
        convo = self._conversations.pop(conversation_id, None)
        if not convo:
            return False
        self._remove_index(convo)
        self._timeline.pop(conversation_id, None)
        thread_ids = [tid for tid, t in self._threads.items() if t.conversation_id == conversation_id]
        for tid in thread_ids:
            self._threads.pop(tid, None)
        msg_ids = [mid for mid, m in self._messages.items() if m.conversation_id == conversation_id]
        for mid in msg_ids:
            self._messages.pop(mid, None)
        return True

    # ── Thread CRUD ──

    def add_thread(self, thread: ConversationThread) -> ConversationThread:
        self._threads[thread.thread_id] = thread
        return thread

    def get_thread(self, thread_id: str) -> Optional[ConversationThread]:
        return self._threads.get(thread_id)

    def get_threads_for_conversation(self, conversation_id: str) -> list[ConversationThread]:
        return [t for t in self._threads.values() if t.conversation_id == conversation_id]

    # ── Message CRUD ──

    def add_message(self, message: ConversationMessage) -> ConversationMessage:
        self._messages[message.message_id] = message
        convo = self._conversations.get(message.conversation_id)
        if convo:
            convo.message_count += 1
            convo.last_activity_at = message.sent_at or datetime.now(timezone.utc)
        return message

    def get_message(self, message_id: str) -> Optional[ConversationMessage]:
        return self._messages.get(message_id)

    def get_messages_for_conversation(
        self, conversation_id: str, limit: int = 100
    ) -> list[ConversationMessage]:
        msgs = [m for m in self._messages.values() if m.conversation_id == conversation_id]
        msgs.sort(key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc))
        return msgs[-limit:]

    def get_messages_for_thread(self, thread_id: str, limit: int = 100) -> list[ConversationMessage]:
        msgs = [m for m in self._messages.values() if m.thread_id == thread_id]
        msgs.sort(key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc))
        return msgs[-limit:]

    # ── Timeline ──

    def add_timeline_event(self, event: TimelineEvent) -> TimelineEvent:
        cid = event.conversation_id
        if cid not in self._timeline:
            self._timeline[cid] = []
        self._timeline[cid].append(event)
        self._timeline[cid].sort(key=lambda e: e.timestamp)
        return event

    def get_timeline(self, conversation_id: str) -> list[TimelineEvent]:
        return self._timeline.get(conversation_id, [])

    # ── Lookup Helpers ──

    def find_by_external_thread(self, external_thread_id: str) -> Optional[Conversation]:
        cid = self._by_external_thread.get(external_thread_id)
        if cid:
            return self._conversations.get(cid)
        return None

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for convo in self._conversations.values():
            s = convo.status.value
            counts[s] = counts.get(s, 0) + 1
        return counts

    # ── Internal Index Management ──

    def _add_index(self, conversation: Conversation) -> None:
        cid = conversation.conversation_id
        if conversation.provider_id:
            self._by_provider.setdefault(conversation.provider_id, set()).add(cid)
        if conversation.campaign_id:
            self._by_campaign.setdefault(conversation.campaign_id, set()).add(cid)
        if conversation.workflow_id:
            self._by_workflow.setdefault(conversation.workflow_id, set()).add(cid)
        self._add_status_index(cid, conversation.status)
        if conversation.external_thread_id:
            self._by_external_thread[conversation.external_thread_id] = cid

    def _remove_index(self, conversation: Conversation) -> None:
        cid = conversation.conversation_id
        self._by_provider.get(conversation.provider_id, set()).discard(cid)
        self._by_campaign.get(conversation.campaign_id, set()).discard(cid)
        self._by_workflow.get(conversation.workflow_id, set()).discard(cid)
        self._remove_status_index(cid, conversation.status)
        if conversation.external_thread_id:
            self._by_external_thread.pop(conversation.external_thread_id, None)

    def _add_status_index(self, cid: str, status: ConversationStatus) -> None:
        self._by_status.setdefault(status, set()).add(cid)

    def _remove_status_index(self, cid: str, status: ConversationStatus) -> None:
        self._by_status.get(status, set()).discard(cid)

    def _add_timeline_event(self, event: TimelineEvent) -> None:
        cid = event.conversation_id
        if cid not in self._timeline:
            self._timeline[cid] = []
        self._timeline[cid].append(event)


conversation_store = ConversationStore()
