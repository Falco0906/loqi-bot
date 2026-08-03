from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.intentions.models import (
    Intention,
    IntentionType,
    LifecycleStatus,
    Evidence,
    ReasonCode,
    PriorityLevel,
    intention_id,
)
from services.intentions.policies import PolicyResult
from services.intentions.priority import order_intentions


def build_intention(
    workspace_id: str,
    policy_result: PolicyResult,
    related_campaign: str = "",
    related_lead: str = "",
    related_provider: str = "",
    evidence_signals: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Intention:
    """Build an Intention from a PolicyResult and contextual identifiers.

    This is the primary factory used by the IntentionEngine to convert
    policy evaluations into concrete intentions.
    """
    now = datetime.now(timezone.utc).isoformat()
    iid = intention_id(workspace_id, policy_result.reason_code)

    ev = Evidence(
        reason_code=policy_result.reason_code,
        confidence=policy_result.confidence,
        source=policy_result.name if hasattr(policy_result, 'name') else "policy",
        detail=policy_result.detail,
        signals=evidence_signals or {},
    )

    return Intention(
        id=iid,
        workspace_id=workspace_id,
        type=policy_result.intention_type,
        priority=policy_result.priority,
        confidence=policy_result.confidence,
        status=LifecycleStatus.CREATED,
        reason_code=policy_result.reason_code,
        blocking=policy_result.blocking,
        created_at=now,
        updated_at=now,
        related_campaign=related_campaign,
        related_lead=related_lead,
        related_provider=related_provider,
        metadata=metadata or {},
        evidence=[ev],
    )


def deduplicate(intentions: list[Intention]) -> list[Intention]:
    """Remove duplicate intentions by reason_code + related_campaign/lead.

    When two intentions share the same reason_code and the same
    related entity, the higher-priority one wins.
    """
    seen: dict[str, Intention] = {}
    for i in intentions:
        key = _dedup_key(i)
        existing = seen.get(key)
        if existing is None:
            seen[key] = i
        else:
            winner = i if _priority_score(i) > _priority_score(existing) else existing
            seen[key] = _merge_evidence(winner, [existing, i])
    return order_intentions(list(seen.values()))


def _dedup_key(intention: Intention) -> str:
    parts = [intention.reason_code.value, intention.workspace_id]
    if intention.related_campaign:
        parts.append(f"campaign:{intention.related_campaign}")
    if intention.related_lead:
        parts.append(f"lead:{intention.related_lead}")
    if intention.related_provider:
        parts.append(f"provider:{intention.related_provider}")
    return "::".join(parts)


def _priority_score(intention: Intention) -> float:
    """Reuse the priority module's scoring for dedup ordering."""
    from services.intentions.priority import order_intentions
    ranked = order_intentions([intention])
    # Use a simple numeric proxy
    type_weights = {
        "ask_user": 100, "escalate": 90, "follow_up": 70,
        "recommend_action": 60, "auto_handle": 50, "notify": 40,
        "wait": 20, "ignore": 0,
    }
    base = type_weights.get(intention.type.value, 40)
    confidence_bonus = intention.confidence * 50
    blocking_bonus = 80 if intention.blocking else 0
    return base + confidence_bonus + blocking_bonus


def _merge_evidence(primary: Intention, duplicates: list[Intention]) -> Intention:
    """Merge evidence lists from duplicate intentions into the primary.

    Avoids duplicate evidence entries (by reason_code).
    """
    seen_codes: set[str] = {e.reason_code.value for e in primary.evidence}
    for dup in duplicates:
        if dup is primary:
            continue
        for ev in dup.evidence:
            if ev.reason_code.value not in seen_codes:
                primary.evidence.append(ev)
                seen_codes.add(ev.reason_code.value)
    return primary


def filter_expired(intentions: list[Intention]) -> list[Intention]:
    """Remove intentions whose expires_at has passed."""
    now = datetime.now(timezone.utc)
    return [
        i for i in intentions
        if not i.expires_at or _parse_iso(i.expires_at, now) > now
    ]


def _parse_iso(iso_str: str, now: datetime) -> datetime:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return now


def create_ignore_intention(
    workspace_id: str,
    reason: str = "No actionable signals detected",
) -> Intention:
    """Create a low-priority IGNORE intention as a no-op placeholder."""
    now = datetime.now(timezone.utc).isoformat()
    return Intention(
        id=intention_id(workspace_id, ReasonCode.LOW_CONFIDENCE, "ignore"),
        workspace_id=workspace_id,
        type=IntentionType.IGNORE,
        priority=PriorityLevel.LOW,
        confidence=0.0,
        status=LifecycleStatus.CREATED,
        reason_code=ReasonCode.LOW_CONFIDENCE,
        blocking=False,
        created_at=now,
        updated_at=now,
        evidence=[
            Evidence(
                reason_code=ReasonCode.LOW_CONFIDENCE,
                confidence=0.0,
                source="helpers",
                detail=reason,
            )
        ],
    )
