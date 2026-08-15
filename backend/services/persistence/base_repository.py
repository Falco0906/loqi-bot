from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

T = TypeVar("T")



class SupabaseRepository(ABC, Generic[T]):

    def __init__(self) -> None:
        from services.persistence.database import get_connection_manager
        self._connection = get_connection_manager()

    @property
    @abstractmethod
    def _table_name(self) -> str:
        ...

    def _to_row(self, entity: T) -> dict[str, Any]:
        return _serialize(entity)

    def _from_row(self, row: dict[str, Any]) -> T:
        return _deserialize(self._entity_type(), row)

    @classmethod
    @abstractmethod
    def _entity_type(cls) -> type[T]:
        ...

    def _client(self):
        return self._connection.get_client()

    def _first(self, result) -> dict[str, Any] | None:
        data = getattr(result, "data", None) or []
        return data[0] if data else None

    def _retry(self, factory, category: str = ""):
        """Bounded retry for idempotent-safe persistence operations."""
        from services.persistence.retry import retry_async
        return retry_async(factory, category=category or self._table_name)

    async def save(self, entity: T) -> T:
        import asyncio
        client = self._client()
        if client is None:
            return entity
        row = self._to_row(entity)
        row_id = row.get("id", "")

        async def _perform() -> None:
            existing = self._first(await asyncio.to_thread(
                lambda: client.table(self._table_name)
                .select("id")
                .eq("id", row_id)
                .limit(1)
                .execute(),
            ))
            if existing:
                if hasattr(entity, "updated_at"):
                    row["updated_at"] = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    lambda: client.table(self._table_name)
                    .update(row)
                    .eq("id", row_id)
                    .execute(),
                )
            else:
                if hasattr(entity, "created_at"):
                    row["created_at"] = row.get("created_at") or datetime.now(timezone.utc).isoformat()
                if hasattr(entity, "updated_at"):
                    row["updated_at"] = row.get("updated_at") or datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    lambda: client.table(self._table_name)
                    .insert(row)
                    .execute(),
                )

        await self._retry(_perform)
        return entity

    async def get(self, entity_id: str) -> T | None:
        import asyncio
        client = self._client()
        if client is None:
            return None

        async def _perform() -> T | None:
            result = await asyncio.to_thread(
                lambda: client.table(self._table_name)
                .select("*")
                .eq("id", entity_id)
                .limit(1)
                .execute(),
            )
            row = self._first(result)
            if row is None:
                return None
            return self._from_row(row)

        return await self._retry(_perform)

    async def delete(self, entity_id: str) -> bool:
        import asyncio
        client = self._client()
        if client is None:
            return False

        async def _perform() -> bool:
            result = await asyncio.to_thread(
                lambda: client.table(self._table_name)
                .delete()
                .eq("id", entity_id)
                .execute(),
            )
            return len(getattr(result, "data", None) or []) > 0

        return await self._retry(_perform)


def _serialize(entity: Any) -> dict[str, Any]:
    from dataclasses import fields, is_dataclass
    if not is_dataclass(entity):
        return {}
    row: dict[str, Any] = {}
    for f in fields(entity):
        val = getattr(entity, f.name)
        if val is None:
            row[f.name] = None
        elif hasattr(val, "isoformat"):
            row[f.name] = val.isoformat()
        elif hasattr(val, "value"):
            row[f.name] = val.value
        elif isinstance(val, str):
            row[f.name] = val
        else:
            row[f.name] = str(val)
    return row


_TYPE_HINTS_CACHE: dict[type, dict[str, type]] = {}


def _get_type_hints(cls: type) -> dict[str, type]:
    from typing import get_type_hints
    if cls not in _TYPE_HINTS_CACHE:
        _TYPE_HINTS_CACHE[cls] = get_type_hints(cls)
    return _TYPE_HINTS_CACHE[cls]


def _resolve_type(ftype: object) -> type:
    from typing import get_origin, get_args
    origin = get_origin(ftype)
    args = get_args(ftype) if origin else ()
    if origin is not None:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _resolve_type(non_none[0])
        return _resolve_type(args[0]) if args else object
    if isinstance(ftype, type):
        return ftype
    return object


def _deserialize(cls: type[T], row: dict[str, Any]) -> T:
    from dataclasses import fields, is_dataclass
    from datetime import timezone as tz

    if not is_dataclass(cls):
        return cls(**row)

    hints = _get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in row:
            continue
        val = row[f.name]
        if val is None:
            kwargs[f.name] = None
            continue

        ftype = _resolve_type(hints.get(f.name, object))

        if ftype is datetime and isinstance(val, str):
            normalized = val[:-1] + "+00:00" if val.endswith("Z") else val
            kwargs[f.name] = datetime.fromisoformat(normalized)
        elif ftype is datetime and isinstance(val, datetime):
            kwargs[f.name] = val
        elif issubclass(ftype, str) and isinstance(val, str):
            kwargs[f.name] = val
        elif issubclass(ftype, Enum):
            kwargs[f.name] = ftype(val)
        elif isinstance(val, str):
            kwargs[f.name] = val
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


from enum import Enum
