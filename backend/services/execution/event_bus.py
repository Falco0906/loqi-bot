"""Event Bus — loosely coupled event pub/sub for the execution engine.

The Event Bus is the only mechanism through which the execution engine
makes its lifecycle observable. The pipeline calls publish() and nothing
else. Subscribers receive events and must not affect execution.

Architectural constraints:
  - Event Bus must not import Scheduler, Dispatcher, or Adapter Registry.
  - Subscribers must not know about the execution pipeline.
  - The execution pipeline must not know who is listening.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from services.execution.execution_models import ExecutionEvent

logger = logging.getLogger(__name__)


class EventSubscriber(Protocol):
    """Protocol for event bus subscribers.

    Implement this protocol to receive ExecutionEvents from the bus.
    Subscriber exceptions are caught and logged — they never propagate
    to the publisher or other subscribers.
    """

    def handle(self, event: ExecutionEvent) -> None:
        ...


class EventBus:
    """Simple in-process event bus with thread-safe publish/subscribe.

    Supports concurrent publishing and subscription using lightweight
    locking. Subscriber failures are isolated — one crashing subscriber
    does not affect other subscribers or the publisher.
    """

    def __init__(self):
        self._subscribers: list[EventSubscriber] = []
        self._lock = threading.Lock()
        self._sequence = 0

    def subscribe(self, subscriber: EventSubscriber) -> None:
        """Register a subscriber for all future events.

        Duplicate subscribers are silently ignored.
        """
        with self._lock:
            if subscriber not in self._subscribers:
                self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        """Unregister a subscriber.

        Silently ignores subscribers that were not registered.
        """
        with self._lock:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass

    def publish(self, event: ExecutionEvent) -> None:
        """Publish an event to all registered subscribers.

        Each subscriber is called in order of registration.
        Exceptions from individual subscribers are caught and logged
        without affecting execution or other subscribers.
        """
        with self._lock:
            self._sequence += 1
            event.sequence = self._sequence
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.handle(event)
            except Exception:
                logger.exception(
                    "Event subscriber %s failed while handling %s (seq=%d)",
                    type(subscriber).__name__,
                    event.event_type.value,
                    event.sequence,
                )

    def clear(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        """Return the number of registered subscribers."""
        with self._lock:
            return len(self._subscribers)
