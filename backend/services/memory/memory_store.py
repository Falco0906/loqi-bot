from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import uuid4

from services.memory.models import (
    Memory,
    MemorySearch,
    MemorySearchResult,
    MemoryType,
)


class MemoryProvider(ABC):

    @abstractmethod
    async def store(self, memory: Memory) -> str:
        ...

    @abstractmethod
    async def retrieve(self, memory_id: str) -> Memory | None:
        ...

    @abstractmethod
    async def search(self, search: MemorySearch) -> MemorySearchResult:
        ...

    @abstractmethod
    async def update(self, memory_id: str, updates: dict[str, Any]) -> bool:
        ...

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        ...

    @abstractmethod
    async def summarize(
        self, entity_type: str, entity_id: str,
    ) -> dict[str, Any]:
        ...


class InMemoryMemoryProvider(MemoryProvider):
    """Thread-safe in-memory provider. For development/testing only."""

    def __init__(self) -> None:
        self._store: dict[str, Memory] = {}
        self._lock = _Lock()

    async def store(self, memory: Memory) -> str:
        with self._lock:
            if not memory.id:
                memory.id = uuid4().hex[:12]
            self._store[memory.id] = memory
            return memory.id

    async def retrieve(self, memory_id: str) -> Memory | None:
        with self._lock:
            return self._store.get(memory_id)

    async def search(self, search: MemorySearch) -> MemorySearchResult:
        results: list[Memory] = []
        with self._lock:
            for m in self._store.values():
                if not self._matches(m, search):
                    continue
                results.append(m)

        total = len(results)
        start = search.offset
        end = start + search.limit
        results.sort(key=lambda m: m.timestamp, reverse=True)

        return MemorySearchResult(
            memories=results[start:end],
            total=total,
            search=search,
        )

    async def update(self, memory_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            memory = self._store.get(memory_id)
            if not memory:
                return False
            for key, value in updates.items():
                if hasattr(memory, key):
                    setattr(memory, key, value)
            return True

    async def delete(self, memory_id: str) -> bool:
        with self._lock:
            if memory_id not in self._store:
                return False
            del self._store[memory_id]
            return True

    async def summarize(
        self, entity_type: str, entity_id: str,
    ) -> dict[str, Any]:
        search = MemorySearch(
            entity_id=entity_id,
            limit=100,
        )
        result = await self.search(search)
        if not result.memories:
            return {}

        by_type: dict[str, list[Memory]] = {}
        for m in result.memories:
            by_type.setdefault(m.memory_type.value, []).append(m)

        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "total_memories": result.total,
            "memory_types": list(by_type.keys()),
            "latest": result.memories[0].__dict__ if result.memories else None,
            "summary": _build_summary(by_type),
        }

    def _matches(self, memory: Memory, search: MemorySearch) -> bool:
        if search.memory_type and memory.memory_type != search.memory_type:
            return False
        if search.entity_id:
            eid = search.entity_id
            fields = (
                "contact_id", "company_id", "company_name",
                "conversation_id", "opportunity_id", "event_id",
                "email", "name",
            )
            if not any(str(getattr(memory, f, "") or "") == eid for f in fields):
                return False
        if search.source and memory.source != search.source:
            return False
        if search.tags:
            if not all(t in memory.tags for t in search.tags):
                return False
        if search.from_timestamp and memory.timestamp < search.from_timestamp:
            return False
        if search.to_timestamp and memory.timestamp > search.to_timestamp:
            return False
        if search.query:
            q = search.query.lower()
            text = str(memory.__dict__).lower()
            if q not in text:
                return False
        return True


def _build_summary(by_type: dict[str, list[Memory]]) -> str:
    parts = []
    for t, mems in sorted(by_type.items()):
        parts.append(f"{len(mems)} {t} memories")
    return "; ".join(parts) if parts else "No memories found"


class _Lock:
    """Minimal re-entrant lock for the in-memory store."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()

    def __enter__(self) -> _Lock:
        self._lock.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self._lock.release()


_memory_provider: MemoryProvider = InMemoryMemoryProvider()


def get_memory_provider() -> MemoryProvider:
    return _memory_provider


def set_memory_provider(provider: MemoryProvider) -> None:
    global _memory_provider
    _memory_provider = provider


def reset_memory_provider() -> None:
    global _memory_provider
    _memory_provider = InMemoryMemoryProvider()
