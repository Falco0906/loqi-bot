from __future__ import annotations

import logging

from services.memory.memory_store import get_memory_provider
from services.memory.models import (
    ContactMemory,
    ConversationMemory,
    Memory,
    OutcomeMemory,
    MemoryType,
)
from services.execution.enums import ExecutionEventType
from services.execution.execution_models import ExecutionEvent
from services.planner.planning_models import TaskType

log = logging.getLogger("memory.subscriber")


class MemorySubscriber:
    """EventBus subscriber that stores memories from execution events.

    Listens for TASK_COMPLETED and SESSION_COMPLETED events and
    persists structured memories (conversation, contact, outcome).
    """

    def __init__(self) -> None:
        self._provider = get_memory_provider()

    def handle(self, event: ExecutionEvent) -> None:
        try:
            if event.event_type == ExecutionEventType.TASK_COMPLETED:
                self._handle_task_completed(event)
            elif event.event_type == ExecutionEventType.SESSION_COMPLETED:
                self._handle_session_completed(event)
        except Exception:
            log.exception("MemorySubscriber error (isolated)")

    def _handle_task_completed(self, event: ExecutionEvent) -> None:
        import asyncio
        data = event.data or {}
        task_type = data.get("task_type", "")

        if task_type in ("send_email", "send_message"):
            memory = ConversationMemory(
                source="email",
                confidence=0.7,
                tags=["outbound", task_type],
                metadata={
                    "session_id": event.session_id,
                    "task_id": event.task_id,
                    "recipient": data.get("recipient", ""),
                    "subject": data.get("subject", ""),
                },
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_store(memory))
            except RuntimeError:
                pass

        elif task_type in ("create_contact", "update_contact"):
            memory = ContactMemory(
                source="crm",
                confidence=0.8,
                tags=[task_type, "crm_sync"],
                contact_id=data.get("contact_id", ""),
                email=data.get("email", ""),
                name=data.get("name", ""),
                title=data.get("title", ""),
                metadata={
                    "session_id": event.session_id,
                    "task_id": event.task_id,
                },
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_store(memory))
            except RuntimeError:
                pass

    def _handle_session_completed(self, event: ExecutionEvent) -> None:
        import asyncio
        data = event.data or {}
        memory = OutcomeMemory(
            source="execution",
            confidence=0.9,
            tags=["session_completed"],
            action_type=data.get("strategy_name", "unknown"),
            result=data.get("status", "completed"),
            details=f"Session {event.session_id} completed with {data.get('task_count', 0)} tasks",
            metadata={
                "session_id": event.session_id,
                "task_count": data.get("task_count", 0),
            },
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._safe_store(memory))
        except RuntimeError:
            pass

    async def _safe_store(self, memory: Memory) -> None:
        try:
            await self._provider.store(memory)
            log.debug("Stored memory: %s (%s)", memory.id, memory.memory_type.value)
        except Exception:
            log.exception("Failed to store memory")
