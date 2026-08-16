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

from dataclasses import dataclass

from fastapi import HTTPException, Request

from services.identity.models import Session


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