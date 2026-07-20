from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from services.identity.models import (
    PasswordResetRequest,
    RefreshToken,
    VerificationToken,
)
from services.identity.repositories.base import InMemoryRepository, Repository


# ─── VerificationTokenRepository ───────────────────────────────────────

class VerificationTokenRepository(Repository[VerificationToken], ABC):

    @abstractmethod
    async def find_valid_by_target_and_purpose(
        self, target: str, purpose: str,
    ) -> VerificationToken | None:
        ...

    @abstractmethod
    async def find_by_target(self, target: str) -> List[VerificationToken]:
        ...

    @abstractmethod
    async def invalidate_all_for_target(self, target: str) -> int:
        ...

    @abstractmethod
    async def find_by_hash(self, token_hash: str) -> VerificationToken | None:
        ...


class InMemoryVerificationTokenRepository(
    InMemoryRepository[VerificationToken], VerificationTokenRepository
):

    async def find_valid_by_target_and_purpose(
        self, target: str, purpose: str,
    ) -> VerificationToken | None:
        for t in self._all():
            if t.target == target and t.purpose.value == purpose and t.is_valid:
                return t
        return None

    async def find_by_target(self, target: str) -> list[VerificationToken]:
        return [t for t in self._all() if t.target == target]

    async def find_by_hash(self, token_hash: str) -> VerificationToken | None:
        for t in self._all():
            if str(t.token_hash) == token_hash:
                return t
        return None

    async def invalidate_all_for_target(self, target: str) -> int:
        count = 0
        for t in self._all():
            if t.target == target and not t.is_used:
                t.mark_used()
                count += 1
        return count


# ─── RefreshTokenRepository ────────────────────────────────────────────

class RefreshTokenRepository(Repository[RefreshToken], ABC):

    @abstractmethod
    async def find_active_by_session_id(self, session_id: str) -> RefreshToken | None:
        ...

    @abstractmethod
    async def find_by_family(self, family: str) -> List[RefreshToken]:
        ...

    @abstractmethod
    async def revoke_all_for_session(self, session_id: str) -> int:
        ...

    @abstractmethod
    async def revoke_all_for_user(self, user_id: str, session_ids: list[str]) -> int:
        ...

    @abstractmethod
    async def revoke_family(self, family: str) -> int:
        ...

    @abstractmethod
    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        ...


class InMemoryRefreshTokenRepository(
    InMemoryRepository[RefreshToken], RefreshTokenRepository
):

    async def find_active_by_session_id(self, session_id: str) -> RefreshToken | None:
        for rt in self._all():
            if rt.session_id == session_id and rt.is_active:
                return rt
        return None

    async def find_by_family(self, family: str) -> list[RefreshToken]:
        return [rt for rt in self._all() if rt.family == family]

    async def revoke_all_for_session(self, session_id: str) -> int:
        count = 0
        for rt in self._all():
            if rt.session_id == session_id and not rt.is_revoked:
                rt.revoke()
                count += 1
        return count

    async def revoke_all_for_user(self, user_id: str, session_ids: list[str]) -> int:
        session_set = set(session_ids)
        count = 0
        for rt in self._all():
            if rt.session_id in session_set and not rt.is_revoked:
                rt.revoke()
                count += 1
        return count

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        for rt in self._all():
            if str(rt.token_hash) == token_hash:
                return rt
        return None

    async def revoke_family(self, family: str) -> int:
        count = 0
        for rt in self._all():
            if rt.family == family and not rt.is_revoked:
                rt.revoke()
                count += 1
        return count


# ─── PasswordResetRepository ───────────────────────────────────────────

class PasswordResetRepository(Repository[PasswordResetRequest], ABC):

    @abstractmethod
    async def find_valid_by_user_id(self, user_id: str) -> PasswordResetRequest | None:
        ...

    @abstractmethod
    async def invalidate_all_for_user(self, user_id: str) -> int:
        ...


class InMemoryPasswordResetRepository(
    InMemoryRepository[PasswordResetRequest], PasswordResetRepository
):

    async def find_valid_by_user_id(self, user_id: str) -> PasswordResetRequest | None:
        for pr in self._all():
            if pr.user_id == user_id and pr.is_valid:
                return pr
        return None

    async def invalidate_all_for_user(self, user_id: str) -> int:
        count = 0
        for pr in self._all():
            if pr.user_id == user_id and not pr.is_used:
                pr.mark_used()
                count += 1
        return count
