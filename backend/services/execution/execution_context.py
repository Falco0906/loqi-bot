"""Execution context — built once at session initialization.

The ExecutionContext is passed (read-only) to every adapter invocation.
Adapters may read workspace config but never modify it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExecutionContext:
    """Immutable context provided to adapters during task execution.

    Built once at session initialization and passed read-only to every
    adapter invocation.

    Attributes:
        session_id: The executing session's ID.
        channel: The channel identifier (telegram, web, ...).
        workspace_snapshot: Frozen workspace state at session start.
        policies: Execution policies from workspace config.
        idempotency_store: Placeholder for future IdempotencyStore.
    """

    session_id: str
    channel: str = ""
    workspace_snapshot: dict = field(default_factory=dict)
    policies: dict = field(default_factory=dict)
    idempotency_store: Optional[Any] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "workspace_snapshot": self.workspace_snapshot,
            "policies": self.policies,
        }