"""Logging subscriber — writes ExecutionEngine lifecycle events
to Python's logging module.

Implements the ``EventSubscriber`` protocol so it can be registered
with any ``EventBus`` instance.  Exceptions are isolated by the
EventBus — this subscriber never propagates failures.
"""

from __future__ import annotations

import logging

from services.execution.execution_models import ExecutionEvent

logger = logging.getLogger(__name__)


class LoggingSubscriber:
    """Subscribes to an EventBus and logs all execution lifecycle events.

    Each event is logged at ``INFO`` level with a structured message
    that includes the event type, session ID, task ID, and event data.

    Usage::

        bus.subscribe(LoggingSubscriber())
    """

    def handle(self, event: ExecutionEvent) -> None:
        logger.info(
            "[exec] %s | session=%s task=%s | data=%s",
            event.event_type.value,
            event.session_id,
            event.task_id,
            event.data,
        )
