from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult
from services.memory.memory_store import get_memory_provider
from services.memory.models import (
    Memory,
    AccountMemory,
    ContactMemory,
    ConversationMemory,
    MeetingMemory,
    OpportunityMemory,
    DecisionMemory,
    PreferenceMemory,
    OutcomeMemory,
    MemorySearch,
    MemorySearchResult,
    MemoryType,
)

MEMORY_METADATA = AdapterMetadata(
    name="memory",
    display_name="Memory Adapter",
    version="1.0.0",
    description="Organizational memory adapter — store, retrieve, search, "
    "update, delete, and summarize structured memories "
    "across contacts, accounts, conversations, meetings, "
    "opportunities, decisions, preferences, and outcomes.",
    author="Loqi",
    supported_operations=(
        "store_memory",
        "retrieve_memory",
        "search_memory",
        "update_memory",
        "delete_memory",
        "summarize_memory",
    ),
    requires_auth=False,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("memory", "knowledge", "organizational", "learning"),
)

MEMORY_TYPE_MAP: dict[str, type[Memory]] = {
    "account": AccountMemory,
    "contact": ContactMemory,
    "conversation": ConversationMemory,
    "meeting": MeetingMemory,
    "opportunity": OpportunityMemory,
    "decision": DecisionMemory,
    "preference": PreferenceMemory,
    "outcome": OutcomeMemory,
}

ACTION_METHOD_MAP: dict[str, str] = {
    "store_memory": "store_memory",
    "retrieve_memory": "retrieve_memory",
    "search_memory": "search_memory",
    "update_memory": "update_memory",
    "delete_memory": "delete_memory",
    "summarize_memory": "summarize_memory",
}


class MemoryAdapter(ExecutionAdapter):

    @property
    def metadata(self) -> AdapterMetadata:
        return MEMORY_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        action = context.action
        method_name = ACTION_METHOD_MAP.get(action)
        if not method_name:
            return AdapterResult.failure_result(
                error=f"Unknown memory action: {action}",
                metadata={"action": action},
            )

        method = getattr(self, method_name, None)
        if not method:
            return AdapterResult.failure_result(
                error=f"No handler for memory action: {action}",
                metadata={"action": action},
            )

        try:
            result = await method(context.params)
            return AdapterResult.success_result(
                data=result,
                metadata={"action": action},
            )
        except Exception as e:
            return AdapterResult.failure_result(
                error=str(e),
                metadata={"action": action, "error_type": type(e).__name__},
            )

    async def store_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        memory = _build_memory(params)
        memory_id = await provider.store(memory)
        return {"ok": True, "memory_id": memory_id, "memory_type": memory.memory_type.value}

    async def retrieve_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        memory_id = params.get("memory_id", "")
        memory = await provider.retrieve(memory_id)
        if not memory:
            return {"ok": False, "error": "Memory not found"}
        return {"ok": True, "memory": _memory_to_dict(memory)}

    async def search_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        search = MemorySearch(
            query=params.get("query", ""),
            memory_type=_parse_memory_type(params.get("memory_type", "")),
            tags=params.get("tags", []),
            entity_id=params.get("entity_id", ""),
            source=params.get("source", ""),
            limit=params.get("limit", 10),
            offset=params.get("offset", 0),
        )
        result = await provider.search(search)
        return {
            "ok": True,
            "memories": [_memory_to_dict(m) for m in result.memories],
            "total": result.total,
        }

    async def update_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        memory_id = params.get("memory_id", "")
        updates = params.get("updates", {})
        if not memory_id:
            return {"ok": False, "error": "memory_id is required"}
        success = await provider.update(memory_id, updates)
        return {"ok": success, "memory_id": memory_id}

    async def delete_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        memory_id = params.get("memory_id", "")
        if not memory_id:
            return {"ok": False, "error": "memory_id is required"}
        success = await provider.delete(memory_id)
        return {"ok": success, "memory_id": memory_id}

    async def summarize_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_memory_provider()
        entity_type = params.get("entity_type", "")
        entity_id = params.get("entity_id", "")
        if not entity_type or not entity_id:
            return {"ok": False, "error": "entity_type and entity_id are required"}
        summary = await provider.summarize(entity_type, entity_id)
        return {"ok": True, "summary": summary}


def _build_memory(params: dict[str, Any]) -> Memory:
    memory_type_str = params.get("memory_type", "contact")
    cls = MEMORY_TYPE_MAP.get(memory_type_str)
    if not cls:
        cls = Memory
    kwargs = {k: v for k, v in params.items() if k != "memory_type"}
    return cls(**kwargs)


def _parse_memory_type(value: str) -> MemoryType | None:
    if not value:
        return None
    try:
        return MemoryType(value)
    except ValueError:
        return None


def _memory_to_dict(memory: Memory) -> dict[str, Any]:
    data = memory.__dict__.copy()
    data["memory_type"] = memory.memory_type.value
    data["timestamp"] = memory.timestamp.isoformat() if hasattr(memory.timestamp, "isoformat") else str(memory.timestamp)
    data.pop("memory_type", None)  # already set
    data["_type"] = memory.memory_type.value
    return data
