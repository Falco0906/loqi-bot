"""Server-side OAuth state (CSRF) protection, durable across instances (SaaS-1.5).

The Gmail web OAuth callback and the legacy Telegram Gmail flow must only
proceed for a state token that a server issued. State tokens are:

- cryptographically random (``secrets.token_urlsafe``)
- single-use (consumed on use, never reusable)
- time-limited (``STATE_TTL_SECONDS``)
- bound to the initiating user/context at issuance
- persisted through the provider-aware OAuthSessionRepository so a callback
  arriving on a different instance (or after a restart) can still be
  validated (migration 023 ``oauth_sessions`` under the SUPABASE provider)

A lost/malformed/expired/reused token fails the callback safely (no fallback
to an unverified identity).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from services.identity.models.oauth_session import OAuthSession

STATE_TTL_SECONDS = 600

# In-memory provider is process-local: a single shared instance so issue and
# consume operate on the same store (mirrors the old dict store). The Supabase
# provider constructs a fresh repo per call (the underlying connection manager
# caches the client), since state lives in the database.
_in_memory_repo = None


def _repo():
    """Provider-aware OAuthSessionRepository (Supabase in production, in-memory
    otherwise), matching the persistence-provider convention used everywhere."""
    from services.persistence.config import get_repository_provider, RepositoryProvider
    if get_repository_provider() == RepositoryProvider.SUPABASE:
        from services.persistence.repositories import SupabaseOAuthSessionRepository
        return SupabaseOAuthSessionRepository()
    global _in_memory_repo
    if _in_memory_repo is None:
        from services.identity.repositories import InMemoryOAuthSessionRepository
        _in_memory_repo = InMemoryOAuthSessionRepository()
    return _in_memory_repo


def reset_store() -> None:
    """Drop the in-memory store (tests / provider switch)."""
    global _in_memory_repo
    _in_memory_repo = None


async def issue_state(user_id: str, context: dict | None = None) -> str:
    """Create a single-use state token bound to ``user_id`` (and optional
    flow context) and persist it durably."""
    repo = _repo()
    token = secrets.token_urlsafe(32)
    session = OAuthSession(
        provider_type="oauth_state",
        state=token,
        user_id=user_id or "",
        context=json.dumps(context) if context else "",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    )
    await repo.save(session)
    return token


async def consume_state(state: str) -> tuple[str | None, dict | None]:
    """Verify + consume a state token.

    Returns ``(user_id, context)`` when the state is valid and unused, else
    ``(None, None)``. The token is marked used regardless, so a replayed
    callback can never re-use it.
    """
    if not state:
        return None, None
    repo = _repo()
    session = await repo.find_by_state(state)
    if session is None:
        return None, None
    if session.is_used or session.is_expired:
        return None, None
    session.mark_used()
    await repo.save(session)
    context = None
    if session.context:
        try:
            context = json.loads(session.context)
        except (ValueError, TypeError):
            context = None
    return (session.user_id or None), context