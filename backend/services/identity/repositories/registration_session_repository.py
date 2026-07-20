from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from services.identity.models import RegistrationSession, RegistrationSessionStatus
from services.identity.repositories.base import InMemoryRepository, Repository


class RegistrationSessionRepository(Repository[RegistrationSession], ABC):

    @abstractmethod
    async def find_pending_by_email(self, email: str) -> List[RegistrationSession]:
        ...

    @abstractmethod
    async def expire_stale(self) -> int:
        ...


class InMemoryRegistrationSessionRepository(
    InMemoryRepository[RegistrationSession], RegistrationSessionRepository,
):

    async def find_pending_by_email(self, email: str) -> list[RegistrationSession]:
        return [
            rs for rs in self._all()
            if rs.email == email and rs.status == RegistrationSessionStatus.PENDING
        ]

    async def expire_stale(self) -> int:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        count = 0
        for rs in self._all():
            if rs.status == RegistrationSessionStatus.PENDING and rs.is_expired:
                rs.status = RegistrationSessionStatus.EXPIRED
                count += 1
        return count
