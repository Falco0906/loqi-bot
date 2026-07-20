from __future__ import annotations

from services.memory.memory_store import get_memory_provider, MemoryProvider
from services.memory.models import (
    Memory,
    MemoryCitation,
    MemoryEvidence,
    MemorySearch,
)


async def explain_decision(
    memory_ids: list[str],
    decision_context: str = "",
    provider: MemoryProvider | None = None,
) -> MemoryCitation:
    if provider is None:
        provider = get_memory_provider()

    evidence: list[MemoryEvidence] = []
    for mid in memory_ids:
        memory = await provider.retrieve(mid)
        if memory is None:
            continue
        evidence.append(MemoryEvidence(
            memory_id=mid,
            memory_type=memory.memory_type,
            summary=_memory_summary(memory),
            relevance_score=memory.confidence,
            excerpt=str(memory.__dict__)[:300],
        ))

    explanation = _build_explanation(evidence, decision_context)
    return MemoryCitation(
        memory_ids=list(evidence),
        evidence=evidence,
        explanation=explanation,
    )


async def audit_plan_influences(
    task_metadata: list[dict],
    provider: MemoryProvider | None = None,
) -> list[dict]:
    """Produce an audit trail of which memories influenced which tasks."""
    if provider is None:
        provider = get_memory_provider()

    audit: list[dict] = []
    for meta in task_metadata:
        memory_ids = meta.get("memory_ids", [])
        if not memory_ids:
            continue
        citations = await explain_decision(memory_ids, provider=provider)
        audit.append({
            "task_id": meta.get("task_id", ""),
            "task_label": meta.get("task_label", ""),
            "citation": {
                "memory_ids": citations.memory_ids,
                "explanation": citations.explanation,
                "evidence_count": len(citations.evidence),
            },
        })
    return audit


def _memory_summary(memory: Memory) -> str:
    mtype = memory.memory_type.value if hasattr(memory.memory_type, "value") else str(memory.memory_type)
    return f"{mtype} from {memory.source} ({memory.timestamp.strftime('%Y-%m-%d') if hasattr(memory.timestamp, 'strftime') else memory.timestamp})"


def _build_explanation(evidence: list[MemoryEvidence], context: str) -> str:
    if not evidence:
        return "No memories influenced this decision."
    categories: dict[str, int] = {}
    for e in evidence:
        cat = e.summary.split(":")[0] if ":" in e.summary else "other"
        categories[cat] = categories.get(cat, 0) + 1
    parts = [f"{k} ({v})" for k, v in sorted(categories.items())]
    base = f"This decision was influenced by {len(evidence)} relevant memories: {'; '.join(parts)}."
    if context:
        base += f" Context: {context}"
    return base
