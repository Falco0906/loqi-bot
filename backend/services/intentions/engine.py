from __future__ import annotations

from typing import Any

from services.intentions.helpers import (
    build_intention,
    deduplicate,
    filter_expired,
    create_ignore_intention,
)
from services.intentions.models import Intention
from services.intentions.policies import evaluate_policies, PolicyResult
from services.intentions.priority import order_intentions, compute_priority
from services.intentions.queue import IntentionQueue
from services.intentions.lifecycle import expire


class IntentionEngine:
    """Transforms workspace state + signals + reasoning into intentions.

    Input:
        WorkspaceState — current world model projection
        Signals       — structured signals describing reality
        Reasoning     — outputs of reasoners (priorities, attention, scores)
        Delta         — what changed since last_viewed_at

    Output:
        List[Intention] — priority-ordered, deduplicated, evidence-backed

    The engine is purely deterministic.  No LLM calls.

    Flow:
        1. Collect evidence from signals + reasoning + delta
        2. Apply policies → PolicyResult[]
        3. Build Intention objects from matched policies
        4. Deduplicate (same reason_code + related entity)
        5. Merge evidence from duplicates
        6. Assign final priorities (considering blocking, urgency, health)
        7. Filter expired intentions
        8. Order by priority (highest first)
        9. Return stable ordering
    """

    def __init__(self, queue: IntentionQueue | None = None) -> None:
        self._queue = queue or IntentionQueue()

    @property
    def queue(self) -> IntentionQueue:
        return self._queue

    def evaluate(
        self,
        workspace_id: str,
        workspace_state: dict[str, Any] | None = None,
        signals: dict[str, Any] | None = None,
        reasoning: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> list[Intention]:
        signals = signals or {}
        reasoning = reasoning or {}
        delta = delta or {}

        combined = self._merge_signals(signals, delta)

        policy_results = evaluate_policies(combined, reasoning)

        if not policy_results:
            return [create_ignore_intention(workspace_id)]

        intentions = self._build_intentions(workspace_id, policy_results, combined)

        intentions = self._apply_priority_boost(intentions, combined)

        intentions = deduplicate(intentions)

        intentions = filter_expired(intentions)

        intentions = order_intentions(intentions)

        return intentions

    def evaluate_and_enqueue(
        self,
        workspace_id: str,
        workspace_state: dict[str, Any] | None = None,
        signals: dict[str, Any] | None = None,
        reasoning: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> list[Intention]:
        """Evaluate and immediately enqueue the resulting intentions."""
        intentions = self.evaluate(
            workspace_id=workspace_id,
            workspace_state=workspace_state,
            signals=signals,
            reasoning=reasoning,
            delta=delta,
        )
        self._queue.enqueue_all(intentions)
        return self._queue.get_active()

    def _merge_signals(
        self,
        signals: dict[str, Any],
        delta: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge signals and delta into a single evidence dict.

        Delta values override signal values where they overlap.
        """
        merged = dict(signals)
        for k, v in delta.items():
            if isinstance(v, (int, float, str, bool)):
                merged[k] = v
        return merged

    def _build_intentions(
        self,
        workspace_id: str,
        policy_results: list[PolicyResult],
        signals: dict[str, Any],
    ) -> list[Intention]:
        """Convert PolicyResults into Intention objects."""
        intentions: list[Intention] = []
        for pr in policy_results:
            intention = build_intention(
                workspace_id=workspace_id,
                policy_result=pr,
                evidence_signals=signals,
            )
            intentions.append(intention)
        return intentions

    def _apply_priority_boost(
        self,
        intentions: list[Intention],
        signals: dict[str, Any],
    ) -> list[Intention]:
        """Re-evaluate priority considering cross-cutting signals."""
        for intention in intentions:
            boosted = compute_priority(
                signals=signals,
                policy_priority=intention.priority,
                confidence=intention.confidence,
                blocking=intention.blocking,
            )
            intention.priority = boosted
        return intentions

    def expire_stale(self, max_age_hours: float = 24) -> list[Intention]:
        """Expire old intentions from the queue."""
        return self._queue.expire_old(max_age_hours=max_age_hours)
