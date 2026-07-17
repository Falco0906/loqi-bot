"""Draft Store — stores drafts, approval state, version history.

No provider logic.
Supports create, update, approve, reject, delete, archive.
"""
from datetime import datetime, timezone
from typing import Optional

from services.outbound.outbound_models import (
    DraftMessage,
    DraftVersion,
    ApprovalState,
    DraftStatus,
    DraftListResult,
)
from services.outbound.outbound_events import emit_event, OutboundEventType


class DraftStore:
    def __init__(self) -> None:
        self._drafts: dict[str, DraftMessage] = {}
        self._versions: dict[str, list[DraftVersion]] = {}
        self._by_conversation: dict[str, list[str]] = {}
        self._by_workflow: dict[str, list[str]] = {}
        self._by_provider: dict[str, list[str]] = {}

    def create(self, draft: DraftMessage) -> DraftMessage:
        draft.created_at = datetime.now(timezone.utc).isoformat()
        draft.updated_at = draft.created_at
        draft.version = 1
        self._drafts[draft.id] = draft
        self._index_draft(draft)
        self._save_version(draft)
        emit_event(OutboundEventType.DRAFT_CREATED, draft.provider_id,
                   f"Draft {draft.id} created: {draft.subject[:60]}",
                   {"draft_id": draft.id, "conversation_id": draft.conversation_id})
        return draft

    def get(self, draft_id: str) -> Optional[DraftMessage]:
        return self._drafts.get(draft_id)

    def update(self, draft: DraftMessage) -> Optional[DraftMessage]:
        existing = self._drafts.get(draft.id)
        if not existing:
            return None
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        draft.version = existing.version + 1
        draft.created_at = existing.created_at
        self._drafts[draft.id] = draft
        self._save_version(draft)
        emit_event(OutboundEventType.DRAFT_UPDATED, draft.provider_id,
                   f"Draft {draft.id} updated (v{draft.version})",
                   {"draft_id": draft.id, "version": draft.version})
        return draft

    def delete(self, draft_id: str) -> bool:
        draft = self._drafts.pop(draft_id, None)
        if not draft:
            return False
        self._deindex_draft(draft)
        self._versions.pop(draft_id, None)
        emit_event(OutboundEventType.DRAFT_DELETED, draft.provider_id,
                   f"Draft {draft_id} deleted",
                   {"draft_id": draft_id})
        return True

    def approve(self, draft_id: str, auto: bool = False) -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        if auto:
            draft.approval_state = ApprovalState.AUTO_APPROVED
            draft.status = DraftStatus.AUTO_APPROVED
            emit_event(OutboundEventType.DRAFT_AUTO_APPROVED, draft.provider_id,
                       f"Draft {draft_id} auto-approved",
                       {"draft_id": draft_id})
        else:
            draft.approval_state = ApprovalState.APPROVED
            draft.status = DraftStatus.APPROVED
            emit_event(OutboundEventType.DRAFT_APPROVED, draft.provider_id,
                       f"Draft {draft_id} approved",
                       {"draft_id": draft_id})
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        return draft

    def reject(self, draft_id: str) -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        draft.approval_state = ApprovalState.REJECTED
        draft.status = DraftStatus.REJECTED
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        emit_event(OutboundEventType.DRAFT_REJECTED, draft.provider_id,
                   f"Draft {draft_id} rejected",
                   {"draft_id": draft_id})
        return draft

    def mark_sent(self, draft_id: str) -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        draft.status = DraftStatus.SENT
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        return draft

    def mark_sending(self, draft_id: str) -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        draft.status = DraftStatus.SENDING
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        emit_event(OutboundEventType.DRAFT_SENDING, draft.provider_id,
                   f"Draft {draft_id} sending",
                   {"draft_id": draft_id})
        return draft

    def mark_failed(self, draft_id: str, error: str = "") -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        draft.status = DraftStatus.FAILED
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        emit_event(OutboundEventType.DRAFT_FAILED, draft.provider_id,
                   f"Draft {draft_id} failed: {error[:100]}",
                   {"draft_id": draft_id, "error": error})
        return draft

    def mark_cancelled(self, draft_id: str) -> Optional[DraftMessage]:
        draft = self._drafts.get(draft_id)
        if not draft:
            return None
        draft.status = DraftStatus.CANCELLED
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        emit_event(OutboundEventType.DRAFT_CANCELLED, draft.provider_id,
                   f"Draft {draft_id} cancelled",
                   {"draft_id": draft_id})
        return draft

    def archive(self, draft_id: str) -> bool:
        draft = self._drafts.get(draft_id)
        if not draft:
            return False
        draft.status = DraftStatus.ARCHIVED
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def list_by_provider(self, provider_id: str) -> DraftListResult:
        draft_ids = self._by_provider.get(provider_id, [])
        drafts = [self._drafts[did] for did in draft_ids if did in self._drafts]
        return DraftListResult(drafts=drafts, total=len(drafts))

    def list_by_conversation(self, conversation_id: str) -> DraftListResult:
        draft_ids = self._by_conversation.get(conversation_id, [])
        drafts = [self._drafts[did] for did in draft_ids if did in self._drafts]
        return DraftListResult(drafts=drafts, total=len(drafts))

    def list_by_workflow(self, workflow_id: str) -> DraftListResult:
        draft_ids = self._by_workflow.get(workflow_id, [])
        drafts = [self._drafts[did] for did in draft_ids if did in self._drafts]
        return DraftListResult(drafts=drafts, total=len(drafts))

    def list_all(self) -> DraftListResult:
        drafts = list(self._drafts.values())
        return DraftListResult(drafts=drafts, total=len(drafts))

    def get_versions(self, draft_id: str) -> list[DraftVersion]:
        return self._versions.get(draft_id, [])

    def _save_version(self, draft: DraftMessage) -> None:
        if draft.id not in self._versions:
            self._versions[draft.id] = []
        self._versions[draft.id].append(DraftVersion(
            draft_id=draft.id,
            version=draft.version,
            subject=draft.subject,
            body=draft.body,
            editor=draft.last_editor,
            change_summary=f"v{draft.version}: {draft.subject[:60]}",
        ))

    def _index_draft(self, draft: DraftMessage) -> None:
        if draft.conversation_id:
            self._by_conversation.setdefault(draft.conversation_id, []).append(draft.id)
        if draft.workflow_id:
            self._by_workflow.setdefault(draft.workflow_id, []).append(draft.id)
        self._by_provider.setdefault(draft.provider_id, []).append(draft.id)

    def _deindex_draft(self, draft: DraftMessage) -> None:
        for idx_map in [self._by_conversation, self._by_workflow, self._by_provider]:
            for key in list(idx_map.keys()):
                idx_map[key] = [did for did in idx_map[key] if did != draft.id]
                if not idx_map[key]:
                    del idx_map[key]

    def count(self) -> int:
        return len(self._drafts)

    def clear(self) -> None:
        self._drafts.clear()
        self._versions.clear()
        self._by_conversation.clear()
        self._by_workflow.clear()
        self._by_provider.clear()


draft_store = DraftStore()
