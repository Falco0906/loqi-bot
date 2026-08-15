"""Optional workspace context for Discovery and qualification.

This adapter composes the existing Knowledge retrieval and Strategic Update
services. It does not introduce a second retrieval system or persistence layer.
"""

from __future__ import annotations

import json
from typing import Any

from services.knowledge.context_adapter import retrieve_knowledge_context


async def retrieve_discovery_context(owner_id: str, query: str = "") -> dict[str, Any]:
    """Return bounded, owner-scoped context; failures degrade to empty context."""
    empty = {
        "query": query,
        "knowledge": {"items": [], "sources": [], "item_ids": [], "source_ids": []},
        "knowledge_icp": {},
        "strategic_observations": [],
        "provenance": {"query": query, "knowledge_item_ids": [], "knowledge_source_ids": [], "strategic_update_ids": []},
    }
    if not owner_id:
        return empty

    try:
        knowledge = await retrieve_knowledge_context(
            owner_id,
            query=query,
            categories=["company", "icp", "messaging"],
            limit=8,
        )
        knowledge_dict = knowledge.to_dict()
    except Exception:
        knowledge_dict = empty["knowledge"]

    strategic: list[dict[str, Any]] = []
    try:
        from services.strategic.service import StrategicIntelligenceService
        strategic = (await StrategicIntelligenceService().list_updates(owner_id))[:6]
    except Exception:
        strategic = []

    provenance = {
        "query": query,
        "knowledge_item_ids": list(knowledge_dict.get("item_ids") or []),
        "knowledge_source_ids": list(knowledge_dict.get("source_ids") or []),
        "strategic_update_ids": [str(item.get("id")) for item in strategic if item.get("id")],
    }
    return {
        "query": query,
        "knowledge": knowledge_dict,
        "knowledge_icp": _knowledge_icp(knowledge_dict.get("items") or []),
        "strategic_observations": [
            {
                "id": item.get("id"),
                "update_type": item.get("update_type"),
                "title": item.get("title"),
                "observation": item.get("observation"),
                "interpretation": item.get("interpretation"),
                "evidence_ids": [ref.get("signal_id") for ref in (item.get("evidence") or []) if ref.get("signal_id")],
            }
            for item in strategic
        ],
        "provenance": provenance,
    }


def format_discovery_context(context: dict[str, Any] | None) -> str:
    """Build a compact prompt-safe block for existing ICP extraction."""
    if not isinstance(context, dict):
        return ""
    knowledge = context.get("knowledge") or {}
    items = knowledge.get("items") or []
    observations = context.get("strategic_observations") or []
    if not items and not observations:
        return ""
    lines = [
        "WORKSPACE CONTEXT (optional guidance; not prospect evidence):",
        "Use this to interpret the user's ICP and exclusions. Do not make it a hard rule and do not treat strategic observations as facts about a specific prospect.",
    ]
    for item in items[:8]:
        lines.append(
            f"- Knowledge {item.get('id', '')} [{item.get('category', '')}]: "
            f"{item.get('title', '')} — {item.get('summary', '')}; "
            f"structured={_compact_json(item.get('content') or {})}; "
            f"source_type={item.get('source_type', '')} source_id={item.get('source_id', '')}"
        )
    for observation in observations[:6]:
        lines.append(
            f"- Strategic Update {observation.get('id', '')}: "
            f"{observation.get('observation', '')} "
            f"(observation only; evidence={','.join(observation.get('evidence_ids') or [])})"
        )
    return "\n".join(lines)


def _knowledge_icp(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "buyer_industries": [],
        "buyer_roles": [],
        "company_types": [],
        "pain_points": [],
        "excluded_roles": [],
        "keywords": [],
    }
    aliases = {
        "industries": "buyer_industries",
        "target_industries": "buyer_industries",
        "roles": "buyer_roles",
        "target_roles": "buyer_roles",
        "personas": "buyer_roles",
        "company_sizes": "company_types",
        "company_types": "company_types",
        "pain_points": "pain_points",
        "buying_signals": "keywords",
        "exclusions": "excluded_roles",
        "excluded_roles": "excluded_roles",
        "technologies": "keywords",
    }
    for item in items:
        if item.get("category") != "icp":
            continue
        content = item.get("content") or {}
        for key, output_key in aliases.items():
            value = content.get(key)
            values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
            result[output_key].extend(str(entry).strip() for entry in values if str(entry).strip())
    for key, values in result.items():
        result[key] = _dedupe(values)[:10]
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.lower().split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, default=str, separators=(",", ":"))[:1200]
    except Exception:
        return str(value)[:1200]
