from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from services.identity.models import Invitation, InvitationStatus
from services.identity.repositories.base import InMemoryRepository, Repository


class InvitationRepository(Repository[Invitation], ABC):

    @abstractmethod
    async def find_by_email_and_org(
        self, email: str, organization_id: str,
    ) -> Invitation | None:
        ...

    @abstractmethod
    async def find_pending_by_email(self, email: str) -> List[Invitation]:
        ...

    @abstractmethod
    async def find_by_org_id(self, organization_id: str) -> List[Invitation]:
        ...

    @abstractmethod
    async def expire_old_invitations(self) -> int:
        ...

    @abstractmethod
    async def find_by_email(self, email: str) -> List[Invitation]:
        ...


class InMemoryInvitationRepository(InMemoryRepository[Invitation], InvitationRepository):

    async def find_by_email_and_org(
        self, email: str, organization_id: str,
    ) -> Invitation | None:
        for inv in self._all():
            if str(inv.invitee_email) == email and inv.organization_id == organization_id:
                return inv
        return None

    async def find_pending_by_email(self, email: str) -> list[Invitation]:
        return [
            inv for inv in self._all()
            if str(inv.invitee_email) == email and inv.is_pending
        ]

    async def find_by_org_id(self, organization_id: str) -> list[Invitation]:
        return [inv for inv in self._all() if inv.organization_id == organization_id]

    async def expire_old_invitations(self) -> int:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        count = 0
        for inv in self._all():
            if inv.status == InvitationStatus.PENDING and inv.expires_at < now:
                inv.status = InvitationStatus.EXPIRED
                count += 1
        return count

    async def find_by_email(self, email: str) -> list[Invitation]:
        return [
            inv for inv in self._all()
            if str(inv.invitee_email) == email
        ]
