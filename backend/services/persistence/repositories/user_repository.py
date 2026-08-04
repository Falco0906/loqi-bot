from __future__ import annotations

from services.identity.models import User
from services.persistence.base_repository import SupabaseRepository


class SupabaseUserRepository(SupabaseRepository[User]):

    @property
    def _table_name(self) -> str:
        return "identity_users"

    @classmethod
    def _entity_type(cls) -> type[User]:
        return User
