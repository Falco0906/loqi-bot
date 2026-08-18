"""Knowledge service (PR5 — Knowledge Foundation).

User-owned, workspace-scoped canonical Knowledge:

- ``KnowledgeItem``   — structured facts per category (company / icp /
                        messaging / sales_offer) with provenance.
- ``KnowledgeSource`` — source material (notes or references to stored
                        files) that future agents can retrieve.

Everything is durable: items/sources live in Supabase tables
(``knowledge_items`` / ``knowledge_sources``) via the LaunchRepository
layer. All reads/writes are scoped by ``workspace_id`` derived from the
authenticated owner — never from client input.

``get_knowledge_context`` is the deterministic, bounded retrieval interface
future PRs will use to feed Discovery / Strategy / Drafts / Replies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from services.persistence.launch import (
    AuditLogRepository,
    KnowledgeCategory,
    KnowledgeItem,
    KnowledgeItemRepository,
    KnowledgeItemSourceType,
    KnowledgeSource,
    KnowledgeSourceRepository,
    KnowledgeSourceType,
)

# ─── Limits ─────────────────────────────────────────────────────────────

MAX_TITLE_LENGTH = 160
MAX_SUMMARY_LENGTH = 4000
MAX_CONTENT_BYTES = 65536
MAX_TAGS = 20
MAX_TAG_LENGTH = 60
MAX_SOURCE_TITLE_LENGTH = 160
MAX_SOURCE_CONTENT_BYTES = 65536
MAX_SOURCE_REFERENCE_LENGTH = 500
DEFAULT_CONTEXT_LIMIT = 8
MAX_CONTEXT_LIMIT = 20


class KnowledgeValidationError(ValueError):
    """Raised on invalid Knowledge payloads (title size, category, etc.)."""


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def item_to_dict(item: KnowledgeItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "category": item.category,
        "title": item.title,
        "summary": item.summary,
        "content": dict(item.content or {}),
        "tags": list(item.tags or []),
        "source_type": item.source_type,
        "source_id": item.source_id,
        "created_by": item.created_by,
        "created_at": _utc_iso(item.created_at),
        "updated_at": _utc_iso(item.updated_at),
    }


def source_to_dict(source: KnowledgeSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "workspace_id": source.workspace_id,
        "title": source.title,
        "source_type": source.source_type,
        "content": source.content,
        "reference": source.reference,
        "metadata": dict(source.metadata or {}),
        "created_by": source.created_by,
        "created_at": _utc_iso(source.created_at),
        "updated_at": _utc_iso(source.updated_at),
    }


def _validate_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        raise KnowledgeValidationError(
            f"tags must be a list of at most {MAX_TAGS} strings")
    cleaned: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise KnowledgeValidationError("tags must be strings")
        tag = tag.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise KnowledgeValidationError(
                f"each tag must be at most {MAX_TAG_LENGTH} characters")
        cleaned.append(tag)
    return cleaned


def _validate_content_size(content: Any) -> dict[str, Any]:
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise KnowledgeValidationError("content must be a JSON object")
    try:
        size = len(json.dumps(content, default=str))
    except (TypeError, ValueError) as error:
        raise KnowledgeValidationError(f"content is not JSON-serializable: {error}")
    if size > MAX_CONTENT_BYTES:
        raise KnowledgeValidationError(
            f"content exceeds the {MAX_CONTENT_BYTES}-byte limit")
    return content


class KnowledgeService:
    """CRUD + retrieval for user Knowledge. All methods are workspace-scoped."""

    def __init__(self) -> None:
        self._items = KnowledgeItemRepository()
        self._sources = KnowledgeSourceRepository()
        self._audit = AuditLogRepository()

    # ─── item validation ─────────────────────────────────────────────

    def validate_item_fields(
        self,
        *,
        category: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> None:
        if category is not None:
            if category not in {c.value for c in KnowledgeCategory}:
                raise KnowledgeValidationError(
                    f"category must be one of: "
                    f"{', '.join(c.value for c in KnowledgeCategory)}")
        if title is not None:
            title = (title or "").strip()
            if not title:
                raise KnowledgeValidationError("title is required")
            if len(title) > MAX_TITLE_LENGTH:
                raise KnowledgeValidationError(
                    f"title must be at most {MAX_TITLE_LENGTH} characters")
        if summary is not None and len(summary) > MAX_SUMMARY_LENGTH:
            raise KnowledgeValidationError(
                f"summary must be at most {MAX_SUMMARY_LENGTH} characters")
        if content is not None:
            _validate_content_size(content)
        if tags is not None:
            _validate_tags(tags)
        if source_type is not None:
            if source_type not in {s.value for s in KnowledgeItemSourceType}:
                raise KnowledgeValidationError(
                    "source_type must be one of: user_input, uploaded_document, "
                    "imported_source, system_generated")
        if source_id is not None and len(source_id) > MAX_SOURCE_REFERENCE_LENGTH:
            raise KnowledgeValidationError(
                f"source_id must be at most {MAX_SOURCE_REFERENCE_LENGTH} characters")

    # ─── items ────────────────────────────────────────────────────────

    async def list_items(
        self,
        workspace_id: str,
        category: str | None = None,
        q: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if category:
            self.validate_item_fields(category=category)
        items = await self._items.list_for_workspace(workspace_id, category=category)
        results = [
            item_to_dict(i) for i in items
            if i.deleted_at is None
        ]
        query = (q or "").strip().lower()
        if query:
            results = [r for r in results if _matches_query(r, query)]
        return results[:limit]

    async def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any] | None:
        item = await self._items.get_for_workspace(item_id, workspace_id)
        if item is None or item.deleted_at is not None:
            return None
        return item_to_dict(item)

    async def create_item(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        category: str,
        title: str,
        summary: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        source_type: str = "user_input",
        source_id: str = "",
    ) -> dict[str, Any]:
        self.validate_item_fields(
            category=category, title=title, summary=summary,
            content=content, tags=tags, source_type=source_type, source_id=source_id,
        )
        item = KnowledgeItem(
            workspace_id=workspace_id,
            category=category,
            title=(title or "").strip(),
            summary=(summary or "").strip(),
            content=_validate_content_size(content),
            tags=_validate_tags(tags),
            source_type=source_type,
            source_id=(source_id or "").strip(),
            created_by=owner_id,
        )
        await self._items.save(item)
        await self._audit_record(owner_id, workspace_id, "knowledge_item.create",
                                 item.id, after=item_to_dict(item))
        return item_to_dict(item)

    async def update_item(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        item_id: str,
        title: str | None = None,
        summary: str | None = None,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any] | None:
        item = await self._items.get_for_workspace(item_id, workspace_id)
        if item is None or item.deleted_at is not None:
            return None
        self.validate_item_fields(
            title=title, summary=summary, content=content,
            tags=tags, source_type=source_type, source_id=source_id,
        )
        before = item_to_dict(item)
        if title is not None:
            item.title = (title or "").strip()
        if summary is not None:
            item.summary = (summary or "").strip()
        if content is not None:
            item.content = _validate_content_size(content)
        if tags is not None:
            item.tags = _validate_tags(tags)
        if source_type is not None:
            item.source_type = source_type
        if source_id is not None:
            item.source_id = (source_id or "").strip()
        item.updated_at = datetime.now(timezone.utc)
        await self._items.save(item)
        after = item_to_dict(item)
        await self._audit_record(owner_id, workspace_id, "knowledge_item.update",
                                 item.id, before=before, after=after)
        return after

    async def archive_item(self, owner_id: str, workspace_id: str, item_id: str) -> dict[str, Any] | None:
        item = await self._items.get_for_workspace(item_id, workspace_id)
        if item is None or item.deleted_at is not None:
            return None
        before = item_to_dict(item)
        item.deleted_at = datetime.now(timezone.utc)
        item.updated_at = item.deleted_at
        await self._items.save(item)
        await self._audit_record(owner_id, workspace_id, "knowledge_item.archive",
                                 item.id, before=before)
        return item_to_dict(item)

    # ─── sources ──────────────────────────────────────────────────────

    def validate_source_fields(
        self,
        *,
        title: str | None = None,
        source_type: str | None = None,
        content: str | None = None,
        reference: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if title is not None:
            title = (title or "").strip()
            if not title:
                raise KnowledgeValidationError("title is required")
            if len(title) > MAX_SOURCE_TITLE_LENGTH:
                raise KnowledgeValidationError(
                    f"title must be at most {MAX_SOURCE_TITLE_LENGTH} characters")
        if source_type is not None:
            if source_type not in {s.value for s in KnowledgeSourceType}:
                raise KnowledgeValidationError(
                    "source_type must be one of: user_input, uploaded_document, "
                    "imported_source, system_generated")
        if content is not None and len(content) > MAX_SOURCE_CONTENT_BYTES:
            raise KnowledgeValidationError(
                f"content exceeds the {MAX_SOURCE_CONTENT_BYTES}-byte limit")
        if reference is not None and len(reference) > MAX_SOURCE_REFERENCE_LENGTH:
            raise KnowledgeValidationError(
                f"reference must be at most {MAX_SOURCE_REFERENCE_LENGTH} characters")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise KnowledgeValidationError("metadata must be a JSON object")
            try:
                size = len(json.dumps(metadata, default=str))
            except (TypeError, ValueError) as error:
                raise KnowledgeValidationError(
                    f"metadata is not JSON-serializable: {error}")
            if size > MAX_CONTENT_BYTES:
                raise KnowledgeValidationError(
                    f"metadata exceeds the {MAX_CONTENT_BYTES}-byte limit")

    async def list_sources(
        self, workspace_id: str, q: str | None = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        sources = await self._sources.list_for_workspace(workspace_id)
        results = [
            source_to_dict(s) for s in sources
            if s.deleted_at is None
        ]
        query = (q or "").strip().lower()
        if query:
            results = [r for r in results if _matches_source_query(r, query)]
        return results[:limit]

    async def get_source(self, workspace_id: str, source_id: str) -> dict[str, Any] | None:
        source = await self._sources.get_for_workspace(source_id, workspace_id)
        if source is None or source.deleted_at is not None:
            return None
        return source_to_dict(source)

    async def create_source(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        title: str,
        source_type: str = "user_input",
        content: str = "",
        reference: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.validate_source_fields(
            title=title, source_type=source_type, content=content,
            reference=reference, metadata=metadata,
        )
        source = KnowledgeSource(
            workspace_id=workspace_id,
            title=(title or "").strip(),
            source_type=source_type,
            content=(content or "").strip(),
            reference=(reference or "").strip(),
            metadata=dict(metadata or {}),
            created_by=owner_id,
        )
        await self._sources.save(source)
        await self._audit_record(owner_id, workspace_id, "knowledge_source.create",
                                 source.id, after=source_to_dict(source))
        return source_to_dict(source)

    async def update_source(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        source_id: str,
        title: str | None = None,
        source_type: str | None = None,
        content: str | None = None,
        reference: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        source = await self._sources.get_for_workspace(source_id, workspace_id)
        if source is None or source.deleted_at is not None:
            return None
        self.validate_source_fields(
            title=title, source_type=source_type, content=content,
            reference=reference, metadata=metadata,
        )
        before = source_to_dict(source)
        if title is not None:
            source.title = (title or "").strip()
        if source_type is not None:
            source.source_type = source_type
        if content is not None:
            source.content = (content or "").strip()
        if reference is not None:
            source.reference = (reference or "").strip()
        if metadata is not None:
            source.metadata = dict(metadata)
        source.updated_at = datetime.now(timezone.utc)
        await self._sources.save(source)
        after = source_to_dict(source)
        await self._audit_record(owner_id, workspace_id, "knowledge_source.update",
                                 source.id, before=before, after=after)
        return after

    async def archive_source(self, owner_id: str, workspace_id: str, source_id: str) -> dict[str, Any] | None:
        source = await self._sources.get_for_workspace(source_id, workspace_id)
        if source is None or source.deleted_at is not None:
            return None
        before = source_to_dict(source)
        source.deleted_at = datetime.now(timezone.utc)
        source.updated_at = source.deleted_at
        await self._sources.save(source)
        await self._audit_record(owner_id, workspace_id, "knowledge_source.archive",
                                 source.id, before=before)
        return source_to_dict(source)

    # ─── retrieval / context ──────────────────────────────────────────

    async def get_knowledge_context(
        self,
        owner_id: str,
        *,
        query: str | None = None,
        categories: list[str] | None = None,
        limit: int = DEFAULT_CONTEXT_LIMIT,
    ) -> dict[str, Any]:
        """Deterministic, bounded, owner-scoped retrieval for future agents.

        Returns structured, attributable entries: every item/source keeps its
        id, category/type and provenance so AI insights can be traced back.
        """
        if not owner_id:
            return {"items": [], "sources": [], "owner_id": "", "limit": limit}
        workspace_id = await self._resolve_workspace(owner_id)
        if not workspace_id:
            return {"items": [], "sources": [], "owner_id": owner_id, "limit": limit}

        bounded = max(1, min(int(limit), MAX_CONTEXT_LIMIT))
        categories = list(categories or [])
        if categories:
            for cat in categories:
                self.validate_item_fields(category=cat)

        items = await self._items.list_for_workspace(workspace_id)
        item_dicts = [
            item_to_dict(i) for i in items
            if i.deleted_at is None
            and (not categories or i.category in categories)
        ]
        sources = await self._sources.list_for_workspace(workspace_id)
        source_dicts = [
            source_to_dict(s) for s in sources if s.deleted_at is None
        ]

        query_norm = (query or "").strip().lower()
        if query_norm:
            item_dicts = [r for r in item_dicts if _matches_query(r, query_norm)]
            source_dicts = [r for r in source_dicts if _matches_source_query(r, query_norm)]

        return {
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "limit": bounded,
            "items": item_dicts[:bounded],
            "sources": source_dicts[:bounded],
        }

    # ─── helpers ──────────────────────────────────────────────────────

    async def _resolve_workspace(self, owner_id: str) -> str | None:
        from services.workspace_state import _async_workspace
        return await _async_workspace(owner_id)

    async def _audit_record(
        self,
        owner_id: str,
        workspace_id: str,
        action: str,
        entity_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self._audit.record(
                workspace_id=workspace_id,
                user_id=owner_id,
                action=action,
                entity_type="knowledge",
                entity_id=entity_id,
                before=before,
                after=after,
                metadata={"domain": "knowledge"},
            )
        except Exception:  # audit must never block the primary write
            pass


def _matches_query(item: dict[str, Any], query: str) -> bool:
    haystack = " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        " ".join(str(t) for t in (item.get("tags") or [])),
    ]).lower()
    if query in haystack:
        return True
    content = item.get("content") or {}
    for value in content.values():
        if isinstance(value, str) and query in value.lower():
            return True
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and query in entry.lower():
                    return True
    return False


def _matches_source_query(source: dict[str, Any], query: str) -> bool:
    haystack = " ".join([
        str(source.get("title") or ""),
        str(source.get("content") or ""),
        str(source.get("reference") or ""),
    ]).lower()
    return query in haystack


async def get_knowledge_context(
    owner_id: str,
    query: str | None = None,
    categories: list[str] | None = None,
    limit: int = DEFAULT_CONTEXT_LIMIT,
) -> dict[str, Any]:
    """Public retrieval seam for future agents.

    A fresh service resolves the current persistence connection and workspace
    scope for each call; no process-local Knowledge cache is authoritative.
    """
    return await KnowledgeService().get_knowledge_context(
        owner_id,
        query=query,
        categories=categories,
        limit=limit,
    )
