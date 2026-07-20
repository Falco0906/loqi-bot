from __future__ import annotations

from abc import ABC

from services.identity.models import User
from services.identity.repositories.base import InMemoryRepository, Repository


class UserRepository(Repository[User], ABC):
    pass


class InMemoryUserRepository(InMemoryRepository[User], UserRepository):
    pass
