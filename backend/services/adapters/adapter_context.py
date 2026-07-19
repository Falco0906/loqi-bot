from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Optional


@dataclass(frozen=True)
class AdapterContext:
    """Immutable execution context provided to every adapter invocation.

    The context carries everything an adapter needs to perform its work:
    identity information, credentials, operational parameters, and
    diagnostic tools.  Adapters must never mutate the context.
    """

    execution_session_id: str
    execution_task_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    user_context: dict[str, Any] = field(default_factory=dict)
    logger: Optional[Logger] = None
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        execution_session_id: str,
        execution_task_id: str,
        action: str,
        params: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        user_context: dict[str, Any] | None = None,
        logger: Logger | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> AdapterContext:
        return cls(
            execution_session_id=execution_session_id,
            execution_task_id=execution_task_id,
            action=action,
            params=params or {},
            credentials=credentials or {},
            config=config or {},
            user_context=user_context or {},
            logger=logger,
            runtime_metadata=runtime_metadata or {},
        )
