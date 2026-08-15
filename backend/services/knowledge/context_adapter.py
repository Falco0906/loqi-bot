"""Knowledge-to-generation context adapter (PR5.1).

This module deliberately does not retrieve Knowledge itself. It delegates to
the canonical ``get_knowledge_context`` service and only adds a bounded,
attributable representation suitable for existing model prompts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from services.knowledge.service import get_knowledge_context

DEFAULT_KNOWLEDGE_LIMIT = 8
MAX_PROMPT_FIELD_LENGTH = 2400


@dataclass(frozen=True)
class KnowledgePromptContext:
    """Retrieved Knowledge plus its query and attribution metadata."""

    query: str = ""
    categories: tuple[str, ...] = ()
    items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def item_ids(self) -> list[str]:
        return [str(item.get("id") or "") for item in self.items if item.get("id")]

    @property
    def source_ids(self) -> list[str]:
        return [str(source.get("id") or "") for source in self.sources if source.get("id")]

    def to_dict(self) -> dict[str, Any]:
        """Return full structured data for observability and tests."""
        return {
            "query": self.query,
            "categories": list(self.categories),
            "items": self.items,
            "sources": self.sources,
            "item_ids": self.item_ids,
            "source_ids": self.source_ids,
        }


async def retrieve_knowledge_context(
    owner_id: str,
    *,
    query: str = "",
    categories: list[str] | None = None,
    limit: int = DEFAULT_KNOWLEDGE_LIMIT,
) -> KnowledgePromptContext:
    """Retrieve Knowledge through the canonical owner-scoped service.

    A retrieval failure is treated as an empty context so existing generation
    remains functional when Knowledge is unavailable or has not been created.
    """
    if not owner_id:
        return KnowledgePromptContext(query=query, categories=tuple(categories or ()))
    try:
        result = await get_knowledge_context(
            owner_id,
            query=query.strip(),
            categories=categories,
            limit=limit,
        )
    except Exception:
        return KnowledgePromptContext(query=query, categories=tuple(categories or ()))

    return KnowledgePromptContext(
        query=query.strip(),
        categories=tuple(categories or ()),
        items=list(result.get("items") or []),
        sources=list(result.get("sources") or []),
    )


def format_knowledge_context(context: KnowledgePromptContext | dict[str, Any] | None) -> str:
    """Render a bounded, clearly delimited prompt block.

    Knowledge is business guidance, not prospect-specific evidence. IDs and
    provenance remain visible so generated output can be traced in tests and
    later observability surfaces. Empty retrieval returns no prompt section.
    """
    normalized = _coerce_context(context)
    if not normalized.items and not normalized.sources:
        return ""

    lines = [
        "=== KNOWLEDGE CONTEXT ===",
        "Use this as user-provided business context and approved messaging guidance.",
        "It is not prospect-specific evidence. Do not turn generic business claims into prospect facts.",
    ]
    if normalized.query:
        lines.append(f"Retrieval query: {normalized.query[:MAX_PROMPT_FIELD_LENGTH]}")

    for item in normalized.items:
        lines.extend([
            "",
            f"[Knowledge item id={item.get('id', '')} category={item.get('category', '')} "
            f"source_type={item.get('source_type', '')} source_id={item.get('source_id', '')}]",
            f"Title: {_clip(item.get('title'))}",
            f"Summary: {_clip(item.get('summary'))}",
            f"Structured content: {_json_clip(item.get('content') or {})}",
            f"Tags: {', '.join(str(tag) for tag in (item.get('tags') or []))}",
            f"Created by: {_clip(item.get('created_by'))}",
            f"Updated at: {_clip(item.get('updated_at'))}",
        ])

    for source in normalized.sources:
        lines.extend([
            "",
            f"[Knowledge source id={source.get('id', '')} source_type={source.get('source_type', '')}]",
            f"Title: {_clip(source.get('title'))}",
            f"Content: {_clip(source.get('content'))}",
            f"Reference: {_clip(source.get('reference'))}",
            f"Metadata: {_json_clip(source.get('metadata') or {})}",
            f"Created by: {_clip(source.get('created_by'))}",
            f"Updated at: {_clip(source.get('updated_at'))}",
        ])

    lines.extend([
        "",
        "Knowledge safety: use only for business understanding, positioning, and guardrails. "
        "Do not invent customers, results, integrations, metrics, testimonials, ROI, or prospect facts.",
        "=== END KNOWLEDGE CONTEXT ===",
    ])
    return "\n".join(lines)


def _coerce_context(context: KnowledgePromptContext | dict[str, Any] | None) -> KnowledgePromptContext:
    if isinstance(context, KnowledgePromptContext):
        return context
    if not isinstance(context, dict):
        return KnowledgePromptContext()
    return KnowledgePromptContext(
        query=str(context.get("query") or ""),
        categories=tuple(str(value) for value in (context.get("categories") or [])),
        items=list(context.get("items") or []),
        sources=list(context.get("sources") or []),
    )


def _clip(value: Any) -> str:
    text = str(value or "")
    if len(text) <= MAX_PROMPT_FIELD_LENGTH:
        return text
    return text[: MAX_PROMPT_FIELD_LENGTH - 3] + "..."


def _json_clip(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return _clip(text)
