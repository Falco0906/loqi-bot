from __future__ import annotations

from datetime import datetime, timezone, timedelta

from services.identity.config import IDENTITY_CONFIG
from services.identity.events import IdentityEvent
from services.identity.exceptions import (
    SessionLimitExceededException,
    SessionNotFoundException,
    SessionRevokedException,
)
from services.identity.models import RefreshToken, Session
from services.identity.repositories import (
    RefreshTokenRepository,
    SessionRepository,
)


class SessionService:

    def __init__(
        self,
        session_repo: SessionRepository,
        refresh_token_repo: RefreshTokenRepository,
    ) -> None:
        self._session_repo = session_repo
        self._refresh_token_repo = refresh_token_repo

    async def create_session(
        self,
        user_id: str,
        organization_id: str,
        provider_type: str = "",
        device_info: str = "",
        ip_address: str = "",
        user_agent: str = "",
        session_ttl: int | None = None,
    ) -> tuple[Session, IdentityEvent]:
        active_count = await self._session_repo.count_active_by_user_id(user_id)
        if active_count >= IDENTITY_CONFIG.sessions.max_active_sessions_per_user:
            raise SessionLimitExceededException(
                IDENTITY_CONFIG.sessions.max_active_sessions_per_user,
            )

        ttl = session_ttl or IDENTITY_CONFIG.tokens.session_ttl_seconds
        now = datetime.now(timezone.utc)
        session = Session(
            user_id=user_id,
            organization_id=organization_id,
            provider_type=provider_type,
            device_info=device_info,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=now + timedelta(seconds=ttl),
        )
        saved = await self._session_repo.save(session)
        event = IdentityEvent.session_created(saved.id, user_id)
        return saved, event

    async def get_session(self, session_id: str) -> Session:
        session = await self._session_repo.get(session_id)
        if session is None:
            raise SessionNotFoundException(session_id)
        return session

    async def validate_session(self, session_id: str) -> Session:
        session = await self.get_session(session_id)
        if session.is_revoked:
            raise SessionRevokedException()
        if session.is_expired:
            session.revoke()
            await self._session_repo.save(session)
            raise SessionRevokedException("Session has expired")
        return session

    async def touch_session(self, session_id: str) -> Session:
        session = await self.validate_session(session_id)
        session.touch()

        if IDENTITY_CONFIG.sessions.extend_on_activity:
            session.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=IDENTITY_CONFIG.tokens.session_ttl_seconds,
            )

        return await self._session_repo.save(session)

    async def revoke_session(self, session_id: str) -> tuple[Session, IdentityEvent]:
        session = await self.get_session(session_id)
        session.revoke()
        await self._session_repo.save(session)
        await self._refresh_token_repo.revoke_all_for_session(session_id)
        event = IdentityEvent.session_revoked(session_id, session.user_id)
        return session, event

    async def revoke_all_user_sessions(
        self, user_id: str,
    ) -> tuple[int, IdentityEvent]:
        revoked = await self._session_repo.revoke_all_for_user(user_id)
        sessions = await self._session_repo.find_by_user_id(user_id)
        session_ids = [s.id for s in sessions if s.is_revoked]
        await self._refresh_token_repo.revoke_all_for_user(user_id, session_ids)
        event = IdentityEvent.session_revoked("all", user_id)
        return revoked, event

    async def list_active_sessions(self, user_id: str) -> list[Session]:
        return await self._session_repo.find_active_by_user_id(user_id)

    async def count_active_sessions(self, user_id: str) -> int:
        return await self._session_repo.count_active_by_user_id(user_id)
