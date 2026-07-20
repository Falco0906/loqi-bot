from __future__ import annotations

from services.identity.config import IDENTITY_CONFIG
from services.identity.events import IdentityEvent
from services.identity.exceptions import (
    PasswordPolicyViolationException,
    UserNotFoundException,
)
from services.identity.models import PasswordCredential, User
from services.identity.repositories import (
    PasswordCredentialRepository,
    UserRepository,
)
from services.identity.types import PasswordHash
from services.security.crypto.crypto_service import CryptoService


class PasswordService:

    def __init__(
        self,
        credential_repo: PasswordCredentialRepository,
        user_repo: UserRepository,
        crypto_service: CryptoService,
    ) -> None:
        self._credential_repo = credential_repo
        self._user_repo = user_repo
        self._crypto = crypto_service

    async def set_password(
        self, user_id: str, password: str,
    ) -> tuple[PasswordCredential, IdentityEvent]:
        self._validate_password_policy(password)
        user = await self._user_repo.get(user_id)
        if user is None:
            raise UserNotFoundException(user_id)

        password_hash = self._crypto.hash_password(password)
        credential = PasswordCredential(
            user_id=user_id,
            password_hash=password_hash,
        )
        saved = await self._credential_repo.save(credential)
        event = IdentityEvent.password_set(user_id)
        return saved, event

    async def change_password(
        self, user_id: str, current_password: str, new_password: str,
    ) -> tuple[PasswordCredential, IdentityEvent]:
        self._validate_password_policy(new_password)

        credential = await self._credential_repo.find_by_user_id(user_id)
        if credential is None:
            raise UserNotFoundException(user_id)

        if not self._crypto.verify_password(current_password, PasswordHash(str(credential.password_hash))):
            from services.identity.exceptions import InvalidCredentialsException
            raise InvalidCredentialsException("Current password is incorrect")

        new_hash = self._crypto.hash_password(new_password)
        credential.update_hash(new_hash)
        saved = await self._credential_repo.save(credential)
        event = IdentityEvent.password_changed(user_id)
        return saved, event

    async def verify_password(self, user_id: str, password: str) -> bool:
        credential = await self._credential_repo.find_by_user_id(user_id)
        if credential is None:
            return False
        return self._crypto.verify_password(
            password, PasswordHash(str(credential.password_hash)),
        )

    async def has_password(self, user_id: str) -> bool:
        credential = await self._credential_repo.find_by_user_id(user_id)
        return credential is not None

    def _validate_password_policy(self, password: str) -> None:
        config = IDENTITY_CONFIG.password
        errors: list[str] = []

        if len(password) < config.min_length:
            errors.append(
                f"Password must be at least {config.min_length} characters"
            )

        if config.require_uppercase and not any(c.isupper() for c in password):
            errors.append("Password must contain an uppercase letter")

        if config.require_lowercase and not any(c.islower() for c in password):
            errors.append("Password must contain a lowercase letter")

        if config.require_digit and not any(c.isdigit() for c in password):
            errors.append("Password must contain a digit")

        if config.require_special and not any(
            not c.isalnum() for c in password
        ):
            errors.append("Password must contain a special character")

        if errors:
            raise PasswordPolicyViolationException("; ".join(errors))
