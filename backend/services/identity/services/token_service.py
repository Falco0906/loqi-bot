from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from services.identity.config import IDENTITY_CONFIG
from services.identity.exceptions import (
    InvalidCredentialsException,
    RefreshTokenExpiredException,
    RefreshTokenRevokedException,
    SessionRevokedException,
)
from services.identity.models import RefreshToken, Session
from services.identity.repositories import (
    RefreshTokenRepository,
    SessionRepository,
)
from services.security.crypto.crypto_service import CryptoService


def _is_unique_violation(exc: Exception) -> bool:
    """True when ``exc`` is a PostgREST unique-constraint violation (SQLSTATE
    23505 / duplicate key). Supabase exposes ``code`` and ``message`` on the
    APIError; string matching covers wrapped errors."""
    text = str(exc).lower()
    code = getattr(exc, "code", None)
    return code in ("23505", "PGRST301") or "duplicate key" in text or "duplicate" in text


class TokenService:

    def __init__(
        self,
        refresh_token_repo: RefreshTokenRepository,
        session_repo: SessionRepository,
        crypto_service: CryptoService,
    ) -> None:
        self._refresh_token_repo = refresh_token_repo
        self._session_repo = session_repo
        self._crypto = crypto_service

    async def create_refresh_token(
        self, session_id: str, family: str | None = None,
    ) -> tuple[RefreshToken, str]:
        raw_token = self._crypto.random_token(
            IDENTITY_CONFIG.tokens.refresh_token_bytes,
        )
        token_hash = self._crypto.hash_token(raw_token)
        token_family = family or str(uuid4())
        now = datetime.now(timezone.utc)

        refresh_token = RefreshToken(
            session_id=session_id,
            token_hash=token_hash,
            family=token_family,
            sequence=1,
            expires_at=now + timedelta(
                seconds=IDENTITY_CONFIG.tokens.refresh_token_ttl_seconds,
            ),
        )
        saved = await self._refresh_token_repo.save(refresh_token)
        return saved, raw_token

    async def rotate_refresh_token(
        self, current_raw_token: str,
    ) -> tuple[RefreshToken, str]:
        token_hash = self._crypto.hash_token(current_raw_token)

        current_token = await self._find_by_hash(str(token_hash))
        if current_token is None:
            raise InvalidCredentialsException("Invalid refresh token")

        if current_token.is_revoked:
            await self._refresh_token_repo.revoke_family(current_token.family)
            session = await self._session_repo.get(current_token.session_id)
            if session is not None:
                session.revoke()
                await self._session_repo.save(session)
            raise RefreshTokenRevokedException(
                "Refresh token has been revoked. Possible token theft detected. "
                "Session and family have been revoked.",
            )

        if current_token.is_expired:
            raise RefreshTokenExpiredException("Refresh token has expired")

        session = await self._session_repo.get(current_token.session_id)
        if session is None or session.is_revoked:
            current_token.revoke()
            await self._refresh_token_repo.save(current_token)
            raise SessionRevokedException("Session is no longer active")

        current_token.revoke()
        await self._refresh_token_repo.save(current_token)

        # Concurrent-rotation guard (replay race): if another ACTIVE token in
        # this family already exists after the presented token was revoked, a
        # second refresh with the same token is racing us. Treat it as theft —
        # revoke the family and the session. For the Supabase provider the
        # refresh_tokens_family_active_uidx unique index (migration 022)
        # enforces this at the database; this check is defense in depth and
        # the deterministic path for the in-memory provider.
        siblings = await self._refresh_token_repo.find_by_family(current_token.family)
        if any(rt.is_active for rt in siblings if rt.id != current_token.id):
            await self._revoke_family_and_session(current_token.family, current_token.session_id)
            raise RefreshTokenRevokedException(
                "Concurrent refresh detected. Possible token theft. "
                "Session and family have been revoked.",
            )

        now = datetime.now(timezone.utc)
        raw_token = self._crypto.random_token(
            IDENTITY_CONFIG.tokens.refresh_token_bytes,
        )
        new_token = RefreshToken(
            session_id=current_token.session_id,
            token_hash=self._crypto.hash_token(raw_token),
            family=current_token.family,
            sequence=current_token.sequence + 1,
            expires_at=now + timedelta(
                seconds=IDENTITY_CONFIG.tokens.refresh_token_ttl_seconds,
            ),
        )
        try:
            saved = await self._refresh_token_repo.save(new_token)
        except Exception as exc:  # noqa: BLE001
            # The family-active unique index rejected the insert because a
            # concurrent rotation already minted an active token in this
            # family. That is a replay race — revoke the family and session.
            if _is_unique_violation(exc):
                await self._revoke_family_and_session(
                    current_token.family, current_token.session_id,
                )
                raise RefreshTokenRevokedException(
                    "Concurrent refresh detected. Possible token theft. "
                    "Session and family have been revoked.",
                ) from exc
            raise

        session.touch()
        await self._session_repo.save(session)

        return saved, raw_token

    async def _revoke_family_and_session(self, family: str, session_id: str) -> None:
        await self._refresh_token_repo.revoke_family(family)
        session = await self._session_repo.get(session_id)
        if session is not None:
            session.revoke()
            await self._session_repo.save(session)

    async def revoke_all_for_session(self, session_id: str) -> int:
        return await self._refresh_token_repo.revoke_all_for_session(session_id)

    async def revoke_family(self, family: str) -> int:
        return await self._refresh_token_repo.revoke_family(family)

    async def revoke_all_for_user(
        self, user_id: str, session_ids: list[str],
    ) -> int:
        return await self._refresh_token_repo.revoke_all_for_user(user_id, session_ids)

    async def _find_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self._refresh_token_repo.find_by_hash(token_hash)
