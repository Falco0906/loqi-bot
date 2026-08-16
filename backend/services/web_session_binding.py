"""Web-session → canonical identity binding (SaaS-1.6).

When the web-session bootstrap is invoked with a valid canonical access token,
the issued web-session token is durably bound to the canonical user + session.
`main._resolve_session_context` then resolves bound web-sessions through the
canonical identity model:

- the actor is the canonical user (one authoritative identity),
- the web-session is authorized only while the canonical session remains
  valid (not revoked / not expired) — revoking the canonical session via
  logout / password change / password reset invalidates the bound
  web-session.

Provider-aware (Supabase in production so the binding survives restarts and
multi-instance callbacks; in-memory otherwise), matching the persistence
convention used across the identity layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class WebSessionBinding:
    id: str = field(default_factory=lambda: str(uuid4()))
    session_key: str = ""
    canonical_user_id: str = ""
    canonical_session_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_in_memory: dict[str, WebSessionBinding] = {}


def _repo():
    from services.persistence.config import get_repository_provider, RepositoryProvider
    if get_repository_provider() == RepositoryProvider.SUPABASE:
        return _SupabaseBindingStore()
    return _InMemoryBindingStore()


class _InMemoryBindingStore:
    async def save(self, binding: WebSessionBinding) -> WebSessionBinding:
        _in_memory[binding.session_key] = binding
        return binding

    async def find_by_session_key(self, session_key: str) -> WebSessionBinding | None:
        return _in_memory.get(session_key)

    async def delete(self, session_key: str) -> bool:
        return _in_memory.pop(session_key, None) is not None


class _SupabaseBindingStore:
    _table = "web_session_bindings"

    async def save(self, binding: WebSessionBinding) -> WebSessionBinding:
        from services.supabase import get_supabase_client
        client = get_supabase_client()
        if client is None:
            return binding
        await asyncio.to_thread(
            lambda: client.table(self._table).insert({
                "id": binding.id,
                "session_key": binding.session_key,
                "canonical_user_id": binding.canonical_user_id,
                "canonical_session_id": binding.canonical_session_id,
                "created_at": binding.created_at.isoformat(),
            }).execute()
        )
        return binding

    async def find_by_session_key(self, session_key: str) -> WebSessionBinding | None:
        from services.supabase import get_supabase_client
        client = get_supabase_client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table)
            .select("*")
            .eq("session_key", session_key)
            .limit(1)
            .execute()
        )
        data = getattr(result, "data", None) or []
        if not data:
            return None
        row = data[0]
        return WebSessionBinding(
            id=str(row.get("id", "")),
            session_key=str(row.get("session_key", "")),
            canonical_user_id=str(row.get("canonical_user_id", "")),
            canonical_session_id=str(row.get("canonical_session_id", "")),
            created_at=row.get("created_at"),
        )


async def bind_web_session(
    session_key: str,
    canonical_user_id: str,
    canonical_session_id: str,
) -> WebSessionBinding:
    """Record the canonical binding for an authenticated web-session token."""
    repo = _repo()
    binding = WebSessionBinding(
        session_key=session_key,
        canonical_user_id=canonical_user_id,
        canonical_session_id=canonical_session_id,
    )
    return await repo.save(binding)


async def find_binding(session_key: str) -> WebSessionBinding | None:
    """Return the canonical binding for a web-session token, if any."""
    if not session_key:
        return None
    return await _repo().find_by_session_key(session_key)


def reset_store() -> None:
    """Drop the in-memory store (tests)."""
    _in_memory.clear()