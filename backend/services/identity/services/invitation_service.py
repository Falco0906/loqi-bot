from __future__ import annotations

from datetime import datetime, timezone, timedelta

from services.identity.config import IDENTITY_CONFIG
from services.identity.events import IdentityEvent
from services.identity.exceptions import (
    InvitationExpiredException,
    InvitationNotFoundException,
    OrganizationNotFoundException,
    UserNotFoundException,
)
from services.identity.models import Invitation, InvitationStatus
from services.identity.repositories import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from services.security.crypto.crypto_service import CryptoService


class InvitationService:

    def __init__(
        self,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        org_repo: OrganizationRepository,
        user_repo: UserRepository,
        crypto_service: CryptoService,
    ) -> None:
        self._invitation_repo = invitation_repo
        self._membership_repo = membership_repo
        self._org_repo = org_repo
        self._user_repo = user_repo
        self._crypto = crypto_service

    async def create_invitation(
        self, organization_id: str, invited_by: str, invitee_email: str,
        role: str = "member",
    ) -> tuple[Invitation, IdentityEvent]:
        org = await self._org_repo.get(organization_id)
        if org is None:
            raise OrganizationNotFoundException(organization_id)

        inviter = await self._user_repo.get(invited_by)
        if inviter is None:
            raise UserNotFoundException(invited_by)

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=IDENTITY_CONFIG.tokens.invitation_ttl_seconds,
        )

        invitation = Invitation(
            organization_id=organization_id,
            invited_by_user_id=invited_by,
            invitee_email=invitee_email,
            role=role,
            expires_at=expires_at,
        )
        saved = await self._invitation_repo.save(invitation)
        event = IdentityEvent.member_invited(organization_id, invited_by, invitee_email)
        return saved, event

    async def accept_invitation(self, invitation_id: str, user_id: str) -> Invitation:
        invitation = await self._invitation_repo.get(invitation_id)
        if invitation is None:
            raise InvitationNotFoundException()

        if invitation.is_expired:
            invitation.status = InvitationStatus.EXPIRED
            await self._invitation_repo.save(invitation)
            raise InvitationExpiredException()

        user = await self._user_repo.get(user_id)
        if user is None:
            raise UserNotFoundException(user_id)

        invitation.accept()
        await self._invitation_repo.save(invitation)

        from services.identity.exceptions import MembershipAlreadyExistsException
        from services.identity.models import Membership

        existing = await self._membership_repo.find_by_user_and_org(
            user_id, invitation.organization_id,
        )
        if existing is not None:
            if existing.is_active:
                raise MembershipAlreadyExistsException(user_id, invitation.organization_id)
            existing.role = invitation.role
            existing.invited_by = invitation.invited_by_user_id
            existing.activate()  # reactivate pending/removed/left -> active
            return await self._membership_repo.save(existing)

        membership = Membership(
            user_id=user_id,
            organization_id=invitation.organization_id,
            role=invitation.role,
            invited_by=invitation.invited_by_user_id,
        )
        membership.activate()
        await self._membership_repo.save(membership)

        return invitation

    async def revoke_invitation(self, invitation_id: str) -> Invitation:
        invitation = await self._invitation_repo.get(invitation_id)
        if invitation is None:
            raise InvitationNotFoundException()
        invitation.revoke()
        return await self._invitation_repo.save(invitation)

    async def get_invitation(self, invitation_id: str) -> Invitation:
        invitation = await self._invitation_repo.get(invitation_id)
        if invitation is None:
            raise InvitationNotFoundException()
        return invitation

    async def list_invitations(self, organization_id: str) -> list[Invitation]:
        return await self._invitation_repo.find_by_org_id(organization_id)
