from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from services.identity.contracts import IdentityContext
from services.identity.events import IdentityEvent
from services.identity.exceptions import UserNotFoundException
from services.identity.models import EmailIdentity, User
from services.identity.repositories import (
    EmailIdentityRepository,
    UserRepository,
)


class UserService:

    def __init__(
        self,
        user_repo: UserRepository,
        email_identity_repo: EmailIdentityRepository,
    ) -> None:
        self._user_repo = user_repo
        self._email_identity_repo = email_identity_repo

    async def create_user(
        self, display_name: str, email: str, locale: str = "en",
    ) -> tuple[User, EmailIdentity, IdentityEvent]:
        user = User(
            id=str(uuid4()),
            display_name=display_name,
            locale=locale,
        )
        saved = await self._user_repo.save(user)

        email_identity = EmailIdentity(
            user_id=saved.id,
            email=email,
            is_verified=False,
            is_primary=True,
        )
        saved_email = await self._email_identity_repo.save(email_identity)

        event = IdentityEvent.user_created(saved.id, email)
        return saved, saved_email, event

    async def get_user(self, user_id: str) -> User:
        user = await self._user_repo.get(user_id)
        if user is None:
            raise UserNotFoundException(user_id)
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        email_identity = await self._email_identity_repo.find_by_email(email)
        if email_identity is None:
            return None
        return await self._user_repo.get(email_identity.user_id)

    async def update_user(self, user_id: str, display_name: str | None = None) -> User:
        user = await self.get_user(user_id)
        if display_name is not None:
            user.display_name = display_name
        user.updated_at = datetime.now(timezone.utc)
        return await self._user_repo.save(user)

    async def soft_delete_user(self, user_id: str) -> None:
        user = await self.get_user(user_id)
        user.soft_delete()
        await self._user_repo.save(user)

    async def get_identity_context(
        self, user_id: str, org_id: str, session_id: str,
    ) -> IdentityContext:
        user = await self.get_user(user_id)
        return IdentityContext(
            user_id=user.id,
            org_id=org_id,
            session_id=session_id,
        )
