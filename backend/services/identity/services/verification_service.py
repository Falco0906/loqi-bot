from __future__ import annotations

from datetime import datetime, timezone, timedelta

from services.identity.config import IDENTITY_CONFIG
from services.identity.events import IdentityEvent
from services.identity.exceptions import (
    EmailNotVerifiedException,
    InvalidVerificationTokenException,
    VerificationTokenExpiredException,
)
from services.identity.models import (
    EmailIdentity,
    VerificationToken,
    VerificationTokenPurpose,
)
from services.identity.repositories import (
    EmailIdentityRepository,
    VerificationTokenRepository,
)
from services.security.crypto.crypto_service import CryptoService


class VerificationService:

    def __init__(
        self,
        verification_token_repo: VerificationTokenRepository,
        email_identity_repo: EmailIdentityRepository,
        crypto_service: CryptoService,
    ) -> None:
        self._token_repo = verification_token_repo
        self._email_repo = email_identity_repo
        self._crypto = crypto_service

    async def create_verification_token(
        self, target: str, purpose: VerificationTokenPurpose = VerificationTokenPurpose.VERIFY_EMAIL,
    ) -> tuple[VerificationToken, str]:
        raw_token = self._crypto.random_token(
            IDENTITY_CONFIG.tokens.verification_token_bytes,
        )
        token_hash = self._crypto.hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=IDENTITY_CONFIG.tokens.verification_token_ttl_seconds,
        )

        token = VerificationToken(
            purpose=purpose,
            target=target,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        saved = await self._token_repo.save(token)
        return saved, raw_token

    async def verify_email(self, target: str, raw_token: str) -> tuple[EmailIdentity, IdentityEvent]:
        token_hash = self._crypto.hash_token(raw_token)
        token = await self._token_repo.find_valid_by_target_and_purpose(
            target, VerificationTokenPurpose.VERIFY_EMAIL.value,
        )

        if token is None:
            raise InvalidVerificationTokenException("No valid verification token found")

        if str(token.token_hash) != str(token_hash):
            raise InvalidVerificationTokenException("Token does not match")

        if token.is_expired:
            raise VerificationTokenExpiredException()

        token.mark_used()
        await self._token_repo.save(token)

        email_identity = await self._email_repo.find_by_email(target)
        if email_identity is None:
            raise EmailNotVerifiedException(f"No email identity found for {target}")

        email_identity.verify()
        await self._email_repo.save(email_identity)

        event = IdentityEvent.email_verified(email_identity.user_id, target)
        return email_identity, event

    async def validate_token(
        self, target: str, raw_token: str, purpose: str,
    ) -> VerificationToken:
        token_hash = self._crypto.hash_token(raw_token)
        token = await self._token_repo.find_valid_by_target_and_purpose(target, purpose)

        if token is None:
            raise InvalidVerificationTokenException("No valid token found")

        if str(token.token_hash) != str(token_hash):
            raise InvalidVerificationTokenException("Token does not match")

        if token.is_expired:
            raise VerificationTokenExpiredException()

        return token

    async def consume_token(self, token: VerificationToken) -> None:
        token.mark_used()
        await self._token_repo.save(token)
