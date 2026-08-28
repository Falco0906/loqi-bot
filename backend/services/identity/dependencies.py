"""Canonical authentication dependency for the Loqi identity boundary.

SaaS-1: every protected route resolves the authenticated caller through this
single dependency. Routes must never trust client-supplied ``user_id`` /
``organization_id`` values derived from auth; deriving identity happens here,
from the ``Authorization: Bearer <access token>`` header only.

The access token is the opaque identity session id (15-minute TTL). Validation
delegates to the existing ``AuthService`` / ``SessionService`` path so there is
one canonical implementation for both authentication and session validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from services.identity.models import Session

log = logging.getLogger(__name__)
_BRIDGE_TTL = 60
_bridge_verified: dict[str, float] = {}
_BINDING_TTL = 10
_binding_local: dict[str, tuple[float, object | None]] = {}


def web_session_token(request: Request | None) -> str:
    """Return a legacy web-session bearer from Authorization only."""
    if request is None:
        return ""
    try:
        authorization = request.headers.get("authorization", "")
    except Exception:
        return ""
    scheme, _, token = str(authorization).partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else ""


async def ensure_legacy_user_bridge(user_id: str) -> None:
    user_id = str(user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    now = time.monotonic()
    if _bridge_verified.get(user_id, 0) > now:
        return
    if len(_bridge_verified) > 2048:
        _bridge_verified.clear()
    display_name = ""
    try:
        from services.identity.api import get_auth_user_service
        user = await get_auth_user_service().get_user(user_id)
        display_name = str(user.display_name or "")
    except Exception as error:  # the bridge can use a safe fallback name
        log.warning(
            "legacy_user_bridge_identity_lookup_failed user_id=%s error_type=%s",
            user_id,
            type(error).__name__,
        )
    from services.supabase import ensure_legacy_user_bridge
    row = await asyncio.to_thread(ensure_legacy_user_bridge, user_id, display_name)
    if row is None or str(row.get("id") or "") != user_id:
        raise HTTPException(status_code=503, detail="Authenticated user provisioning is temporarily unavailable")
    _bridge_verified[user_id] = now + _BRIDGE_TTL


async def cached_web_session_identity(token: str) -> dict | None:
    from services.session_cache import SessionIdentity, session_cache
    cached = await session_cache.get_identity(token)
    if cached is not None:
        return cached
    try:
        from services.conversation_store import get_web_session
        from services.supabase import has_connected_account

        def _read_identity() -> dict | None:
            user = get_web_session(token)
            if user is None:
                return None
            user_id = str(user.get("id") or "")
            if not user_id:
                return None
            return {
                "user_id": user_id,
                "display_name": str(user.get("username") or ""),
                "gmail_connected": bool(has_connected_account(user_id)),
            }

        identity = await asyncio.to_thread(_read_identity)
    except Exception as error:
        log.warning("session_identity_lookup_failed error_type=%s", type(error).__name__)
        return None
    if identity and identity.get("user_id"):
        await session_cache.set_identity(token, SessionIdentity(user_id=str(identity["user_id"]), display_name=str(identity.get("display_name") or ""), gmail_connected=bool(identity.get("gmail_connected"))))
    return identity


async def web_session_binding(token: str):
    from services import redis_client
    from services.session_cache import _token_hash
    key = redis_client.k_session_binding(_token_hash(token))
    now = time.monotonic()
    if len(_binding_local) > 2048:
        _binding_local.clear()
    local = _binding_local.get(key)
    if local is not None:
        expires_at, value = local
        if expires_at > now:
            return value
        _binding_local.pop(key, None)
    client = await redis_client.get_client()
    if client is not None:
        try:
            raw = await asyncio.wait_for(client.get(key), redis_client.OPERATION_TIMEOUT)
            if raw is not None:
                binding = (json.loads(raw) or {}).get("b")
                _binding_local[key] = (now + _BINDING_TTL, binding)
                return binding
        except Exception as error:
            log.debug("binding_cache_read_failed error_type=%s", type(error).__name__)
            client = None
    from services.web_session_binding import find_binding
    binding = await find_binding(token)
    if client is not None:
        try:
            value = binding.__dict__ if binding else None
            await asyncio.wait_for(client.set(key, json.dumps({"b": value}), ex=_BINDING_TTL), redis_client.OPERATION_TIMEOUT)
        except Exception as error:
            log.debug("binding_cache_write_failed error_type=%s", type(error).__name__)
    _binding_local[key] = (now + _BINDING_TTL, binding)
    return binding


async def resolve_web_session(request: Request) -> tuple[str, str]:
    """Resolve identity or bound legacy web-session bearer, failing closed."""
    token = web_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from services.identity.api import get_authenticated_user_id
        user_id = await get_authenticated_user_id(request)
    except HTTPException:
        user_id = ""
    if user_id:
        await ensure_legacy_user_bridge(user_id)
        return str(user_id), token
    identity = await cached_web_session_identity(token)
    if not identity or not identity.get("user_id"):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    binding = await web_session_binding(token)
    if binding:
        binding_user = getattr(binding, "canonical_user_id", "") or binding.get("canonical_user_id", "")
        binding_session = getattr(binding, "canonical_session_id", "") or binding.get("canonical_session_id", "")
        from services.identity.api import _get_service
        try:
            await _get_service()._session_svc.touch_session(binding_session)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
        await ensure_legacy_user_bridge(binding_user)
        return binding_user, token
    user_id = str(identity["user_id"])
    await ensure_legacy_user_bridge(user_id)
    return user_id, token


async def authenticated_user_id(request: Request, session_token: str = "") -> str:
    """Resolve the authenticated durable user for a legacy web route.

    ``session_token`` is intentionally ignored: legacy route path tokens are
    placeholders, never credentials. Keeping the argument preserves route
    call signatures while the Authorization bearer remains the only authority.
    """
    user_id, _ = await resolve_web_session(request)
    return user_id


@dataclass(frozen=True)
class AuthContext:
    """Typed, authenticated caller context exposed to protected routes."""

    user_id: str
    session_id: str
    organization_id: str

    @classmethod
    def from_session(cls, session: Session) -> "AuthContext":
        return cls(
            user_id=session.user_id,
            session_id=session.id,
            organization_id=session.organization_id,
        )


def _bearer_token(request: Request) -> str:
    """Extract the bearer token from the Authorization header.

    Raises 401 for missing or malformed credentials. Accepts only a single
    ``Bearer`` token; never reads tokens from URLs, cookies, or query params.
    """
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="Authentication required")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Malformed authorization header")
    return token.strip()


async def get_current_auth(request: Request) -> AuthContext:
    """Resolve the authenticated caller from the request (FastAPI dependency).

    Rejects:
    - missing credentials (no Authorization header)
    - malformed credentials (non-Bearer scheme / empty token)
    - expired sessions (access token past its 15-minute TTL)
    - revoked / invalid sessions

    Returns a typed ``AuthContext`` bound to the authenticated user.
    """
    token = _bearer_token(request)
    from services.identity.api import _get_service

    try:
        session = await _get_service().validate_access_token(token)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — identity exceptions normalize to 401
        raise HTTPException(
            status_code=401, detail="Invalid or expired session",
        ) from exc
    return AuthContext.from_session(session)


async def get_current_user_id(request: Request) -> str:
    """Dependency returning just the authenticated ``user_id``."""
    return (await get_current_auth(request)).user_id
