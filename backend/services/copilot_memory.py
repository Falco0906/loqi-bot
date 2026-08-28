"""Bounded, durable, workspace-scoped context for Copilot turns.

This module stores only derived conversational context and references to work
that Copilot previously discussed.  It is deliberately not a workspace-state
cache: campaigns, drafts, leads, inbox records, jobs, and preferences remain
authoritative in their existing services and must be re-read before claims or
actions are made.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


logger = logging.getLogger(__name__)

MAX_TURNS = 12
MAX_TURN_CHARS = 800
MAX_HISTORY_ITEMS = 6
MEMORY_MAX_AGE = timedelta(days=30)
UNFINISHED_TASK_MAX_AGE = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clip(value: Any, limit: int = MAX_TURN_CHARS) -> str:
    return str(value or "").strip()[:limit]


def _safe_operation(operation: Any) -> dict[str, str]:
    if not isinstance(operation, dict):
        return {}
    allowed = ("kind", "tool", "job_id", "discovery_id", "campaign_id", "draft_id", "conversation_id", "status")
    return {key: _clip(operation.get(key), 128) for key in allowed if operation.get(key) not in (None, "")}


class CopilotMemoryRepository:
    """Supabase repository for one user/workspace/conversation memory record."""

    table_name = "copilot_memories"

    def __init__(self, client_provider: Callable[[], Any] | None = None) -> None:
        self._client_provider = client_provider

    def _client(self):
        if self._client_provider is not None:
            return self._client_provider()
        from services.supabase import get_supabase_client
        return get_supabase_client()

    async def get(self, *, user_id: str, workspace_id: str, conversation_key: str) -> dict[str, Any] | None:
        client = self._client()
        if client is None:
            return None

        def _read():
            return (
                client.table(self.table_name)
                .select("memory, updated_at")
                .eq("user_id", user_id)
                .eq("workspace_id", workspace_id)
                .eq("conversation_key", conversation_key)
                .limit(1)
                .execute()
            )

        result = await asyncio.to_thread(_read)
        rows = getattr(result, "data", None) or []
        row = rows[0] if rows else None
        if not isinstance(row, dict):
            return None
        memory = row.get("memory")
        if not isinstance(memory, dict):
            raise RuntimeError("Invalid Copilot memory payload")
        return {"memory": memory, "updated_at": row.get("updated_at")}

    async def save(
        self,
        *,
        user_id: str,
        workspace_id: str,
        conversation_key: str,
        memory: dict[str, Any],
    ) -> None:
        client = self._client()
        if client is None:
            raise RuntimeError("Copilot durable memory persistence is unavailable")
        row = {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "conversation_key": conversation_key,
            "memory": memory,
            "updated_at": _utcnow().isoformat(),
        }
        await asyncio.to_thread(
            lambda: client.table(self.table_name).upsert(
                row, on_conflict="user_id,workspace_id,conversation_key"
            ).execute()
        )


class CopilotMemoryService:
    """Maintains bounded derived Copilot context without becoming state authority."""

    def __init__(self, repository: CopilotMemoryRepository | None = None, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._repository = repository or CopilotMemoryRepository()
        self._now = now

    async def retrieve(
        self, *, user_id: str, workspace_id: str, conversation_key: str,
    ) -> dict[str, Any]:
        """Return safe bounded context, or empty context when unavailable/stale.

        Persistence errors intentionally do not fall back to process-local
        memory. Copilot continues without remembered context and must rely on
        canonical current-state reads.
        """
        try:
            record = await self._repository.get(
                user_id=user_id, workspace_id=workspace_id, conversation_key=conversation_key,
            )
        except Exception:
            logger.warning("copilot_memory_read_failed workspace=%s", workspace_id, exc_info=True)
            return {}
        if not record:
            return {}
        updated_at = _parse_time(record.get("updated_at"))
        if updated_at is None or self._now() - updated_at > MEMORY_MAX_AGE:
            return {}
        memory = record.get("memory") or {}
        turns = memory.get("turns") if isinstance(memory.get("turns"), list) else []
        history = memory.get("workspace_history") if isinstance(memory.get("workspace_history"), list) else []
        task = memory.get("unfinished_task") if isinstance(memory.get("unfinished_task"), dict) else None
        if task:
            task_at = _parse_time(task.get("updated_at"))
            if task_at is None or self._now() - task_at > UNFINISHED_TASK_MAX_AGE:
                task = None
        return {
            "conversation_turns": [
                {"role": _clip(turn.get("role"), 16), "text": _clip(turn.get("text"))}
                for turn in turns[-MAX_TURNS:]
                if isinstance(turn, dict) and _clip(turn.get("text"))
            ],
            "workspace_history": [item for item in history[-MAX_HISTORY_ITEMS:] if isinstance(item, dict)],
            "unfinished_task": task,
        }

    async def record_turn(
        self,
        *,
        user_id: str,
        workspace_id: str,
        conversation_key: str,
        user_text: str,
        intent: str = "",
        tool: str = "",
        operation: dict[str, Any] | None = None,
        status: str = "",
    ) -> None:
        """Append a compact user turn and update derived task/history references."""
        if not _clip(user_text) or not user_id or not workspace_id or not conversation_key:
            return
        try:
            existing = await self._repository.get(
                user_id=user_id, workspace_id=workspace_id, conversation_key=conversation_key,
            )
            memory = dict((existing or {}).get("memory") or {})
            turns = memory.get("turns") if isinstance(memory.get("turns"), list) else []
            turns.append({
                "role": "user",
                "text": _clip(user_text),
                "intent": _clip(intent, 64),
                "tool": _clip(tool, 96),
                "at": self._now().isoformat(),
            })
            memory["turns"] = turns[-MAX_TURNS:]

            safe_operation = _safe_operation(operation)
            normalized_status = _clip(status, 48).lower()
            if safe_operation:
                safe_operation["updated_at"] = self._now().isoformat()
                if normalized_status in {"accepted", "queued", "running"}:
                    memory["unfinished_task"] = safe_operation
                elif normalized_status in {"completed", "failed", "cancelled", "declined", "verification_failed"}:
                    memory.pop("unfinished_task", None)
                    history = memory.get("workspace_history") if isinstance(memory.get("workspace_history"), list) else []
                    history.append({**safe_operation, "status": normalized_status})
                    memory["workspace_history"] = history[-MAX_HISTORY_ITEMS:]
            await self._repository.save(
                user_id=user_id, workspace_id=workspace_id,
                conversation_key=conversation_key, memory=memory,
            )
        except Exception:
            logger.warning("copilot_memory_write_failed workspace=%s", workspace_id, exc_info=True)

    async def record_outcome(
        self,
        *,
        user_id: str,
        workspace_id: str,
        conversation_key: str,
        tool: str,
        status: str,
        operation: dict[str, Any] | None = None,
    ) -> None:
        """Record an actual tool outcome without duplicating the user turn."""
        try:
            existing = await self._repository.get(
                user_id=user_id, workspace_id=workspace_id, conversation_key=conversation_key,
            )
            if not existing:
                return
            memory = dict(existing.get("memory") or {})
            safe_operation = _safe_operation(operation) or {"tool": _clip(tool, 96)}
            safe_operation.setdefault("tool", _clip(tool, 96))
            normalized_status = _clip(status, 48).lower()
            safe_operation["updated_at"] = self._now().isoformat()
            if normalized_status in {"accepted", "queued", "running"}:
                memory["unfinished_task"] = safe_operation
            elif normalized_status in {"completed", "failed", "cancelled", "declined", "verification_failed"}:
                memory.pop("unfinished_task", None)
                history = memory.get("workspace_history") if isinstance(memory.get("workspace_history"), list) else []
                history.append({**safe_operation, "status": normalized_status})
                memory["workspace_history"] = history[-MAX_HISTORY_ITEMS:]
            await self._repository.save(
                user_id=user_id, workspace_id=workspace_id,
                conversation_key=conversation_key, memory=memory,
            )
        except Exception:
            logger.warning("copilot_memory_outcome_write_failed workspace=%s", workspace_id, exc_info=True)


def merge_turn_history(memory_context: dict[str, Any], client_history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Prefer server-persisted context and bound untrusted client history."""
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in [
        *(memory_context.get("conversation_turns") or []),
        *(client_history or []),
    ]:
        if not isinstance(source, dict):
            continue
        role = _clip(source.get("role"), 16).lower()
        text = _clip(source.get("text"))
        if role not in {"user", "assistant"} or not text or (role, text) in seen:
            continue
        seen.add((role, text))
        merged.append({"role": role, "text": text})
    return merged[-MAX_TURNS:]
