from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from services.organizations.exceptions import (
    CannotInviteExistingMember,
    CannotManageOwner,
    InsufficientRole,
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    LastOwnerCannotBeRemoved,
    LastOwnerCannotLeave,
    MembershipAlreadyExists,
    MembershipNotFound,
    OrganizationNameTaken,
    OrganizationNotFound,
    OrganizationNotActive,
    OrganizationSlugTaken,
)
from services.organizations.models import MembershipRole, MembershipStatus
from services.organizations.resolver import CurrentOrganizationResolver
from services.organizations.schemas import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    ChangeRoleRequest,
    InviteRequest,
    InviteResponse,
    MemberResponse,
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationResponse,
    OrganizationUpdate,
    RemoveMemberRequest,
    TransferOwnershipRequest,
)
from services.organizations.services import InvitationService, MembershipService, OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


HTTP_ERROR_MAP: dict[type[Exception], int] = {
    OrganizationNotFound: 404,
    OrganizationSlugTaken: 409,
    OrganizationNameTaken: 409,
    OrganizationNotActive: 400,
    MembershipNotFound: 404,
    MembershipAlreadyExists: 409,
    InvitationNotFound: 404,
    InvitationExpired: 400,
    InvitationAlreadyAccepted: 400,
    LastOwnerCannotLeave: 400,
    LastOwnerCannotBeRemoved: 400,
    CannotManageOwner: 403,
    CannotInviteExistingMember: 409,
    InsufficientRole: 403,
}


async def _get_current_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _enrich_request(request: Request) -> None:
    request.state.module = "organizations"


def _error_response(exc: Exception) -> JSONResponse:
    status = HTTP_ERROR_MAP.get(type(exc), 500)
    return JSONResponse(status_code=status, content={"detail": exc.message})


# ─── Dependency functions ────────────────────────────────────────────


def _make_org_repositories():
    from services.persistence import REPOSITORY_PROVIDER, RepositoryProvider
    if REPOSITORY_PROVIDER == RepositoryProvider.SUPABASE:
        from services.persistence.repositories import (
            SupabaseInvitationRepository,
            SupabaseMembershipRepository,
            SupabaseOrganizationRepository,
        )
        org_repo = SupabaseOrganizationRepository()
        membership_repo = SupabaseMembershipRepository()
        invitation_repo = SupabaseInvitationRepository()
    else:
        from services.organizations.repositories import (
            InMemoryInvitationRepository,
            InMemoryMembershipRepository,
            InMemoryOrganizationRepository,
        )
        org_repo = InMemoryOrganizationRepository()
        membership_repo = InMemoryMembershipRepository()
        invitation_repo = InMemoryInvitationRepository()
    return org_repo, membership_repo, invitation_repo


def _build_org_deps() -> OrgDeps:
    from services.organizations.resolver import CurrentOrganizationResolver
    from services.organizations.services import InvitationService, MembershipService, OrganizationService
    org_repo, membership_repo, invitation_repo = _make_org_repositories()
    org_service = OrganizationService(org_repo, membership_repo)
    membership_service = MembershipService(membership_repo, org_repo)
    invitation_service = InvitationService(invitation_repo, membership_repo, membership_service)
    resolver = CurrentOrganizationResolver(org_repo, membership_repo)
    return OrgDeps(
        org_service=org_service,
        membership_service=membership_service,
        invitation_service=invitation_service,
        resolver=resolver,
    )


class OrgDeps:
    def __init__(
        self,
        org_service: OrganizationService,
        membership_service: MembershipService,
        invitation_service: InvitationService,
        resolver: CurrentOrganizationResolver,
    ) -> None:
        self.org_service = org_service
        self.membership_service = membership_service
        self.invitation_service = invitation_service
        self.resolver = resolver


_deps_registry: OrgDeps | None = None


def register_deps(deps: OrgDeps) -> None:
    global _deps_registry
    _deps_registry = deps


async def _get_org_service() -> OrganizationService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Organization services not initialized")
    return _deps_registry.org_service


async def _get_membership_service() -> MembershipService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Organization services not initialized")
    return _deps_registry.membership_service


async def _get_invitation_service() -> InvitationService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Organization services not initialized")
    return _deps_registry.invitation_service


async def _get_resolver() -> CurrentOrganizationResolver:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Organization services not initialized")
    return _deps_registry.resolver


# ─── Organiation CRUD ────────────────────────────────────────────────


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    body: OrganizationCreate,
    request: Request,
    org_service: OrganizationService = Depends(_get_org_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        org = await org_service.create_organization(
            name=body.name,
            created_by=current_user,
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
        )
    except (OrganizationSlugTaken, OrganizationNameTaken) as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    return _org_to_response(org)


@router.get("", response_model=OrganizationListResponse)
async def list_organizations(
    request: Request,
    org_service: OrganizationService = Depends(_get_org_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    orgs = await org_service.list_user_organizations(current_user)
    return OrganizationListResponse(
        organizations=[_org_to_response(org) for org in orgs]
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: str = Path(...),
    request: Request = None,
    org_service: OrganizationService = Depends(_get_org_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        org = await org_service.get_organization(organization_id)
    except OrganizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return _org_to_response(org)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    body: OrganizationUpdate,
    organization_id: str = Path(...),
    request: Request = None,
    org_service: OrganizationService = Depends(_get_org_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        update_kwargs = body.model_dump(exclude_none=True)
        org = await org_service.update_organization(
            organization_id=organization_id,
            updated_by=current_user,
            **update_kwargs,
        )
    except (OrganizationNotFound, OrganizationSlugTaken, OrganizationNameTaken) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return _org_to_response(org)


@router.delete("/{organization_id}", status_code=204)
async def delete_organization(
    organization_id: str = Path(...),
    request: Request = None,
    org_service: OrganizationService = Depends(_get_org_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        await org_service.soft_delete_organization(organization_id, current_user)
    except OrganizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


# ─── Members ─────────────────────────────────────────────────────────


@router.get("/{organization_id}/members", response_model=list[MemberResponse])
async def list_members(
    organization_id: str = Path(...),
    status: MembershipStatus | None = Query(None),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    members = await membership_service.get_memberships(organization_id, status=status)
    return [_member_to_response(m) for m in members]


@router.get("/{organization_id}/members/me", response_model=MemberResponse)
async def get_my_membership(
    organization_id: str = Path(...),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        membership = await membership_service.get_user_membership(current_user, organization_id)
    except MembershipNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return _member_to_response(membership)


@router.post("/{organization_id}/members/role", status_code=200)
async def change_role(
    body: ChangeRoleRequest,
    organization_id: str = Path(...),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        membership = await membership_service.change_role(
            organization_id=organization_id,
            target_user_id=body.target_user_id,
            new_role=body.role,
            changed_by=current_user,
        )
    except (MembershipNotFound, CannotManageOwner) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return _member_to_response(membership)


@router.post("/{organization_id}/transfer-ownership", status_code=200)
async def transfer_ownership(
    body: TransferOwnershipRequest,
    organization_id: str = Path(...),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        await membership_service.transfer_ownership(
            organization_id=organization_id,
            current_owner_id=current_user,
            new_owner_id=body.new_owner_id,
        )
    except (InsufficientRole, MembershipNotFound) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return {"message": "Ownership transferred"}


@router.post("/{organization_id}/leave", status_code=200)
async def leave_organization(
    organization_id: str = Path(...),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        await membership_service.leave_organization(current_user, organization_id)
    except (MembershipNotFound, LastOwnerCannotLeave) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return {"message": "Left organization"}


@router.post("/{organization_id}/remove-member", status_code=200)
async def remove_member(
    body: RemoveMemberRequest,
    organization_id: str = Path(...),
    request: Request = None,
    membership_service: MembershipService = Depends(_get_membership_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        await membership_service.remove_member(organization_id, body.user_id, current_user)
    except (MembershipNotFound, LastOwnerCannotBeRemoved) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return {"message": "Member removed"}


# ─── Invitations ─────────────────────────────────────────────────────


@router.post("/{organization_id}/invitations", response_model=InviteResponse, status_code=201)
async def invite_member(
    body: InviteRequest,
    organization_id: str = Path(...),
    request: Request = None,
    invitation_service: InvitationService = Depends(_get_invitation_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        invitation = await invitation_service.invite(
            organization_id=organization_id,
            email=body.email,
            role=body.role,
            created_by=current_user,
        )
    except (OrganizationNotActive, OrganizationNotFound) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return _invitation_to_response(invitation)


@router.get("/{organization_id}/invitations", response_model=list[InviteResponse])
async def list_invitations(
    organization_id: str = Path(...),
    request: Request = None,
    invitation_service: InvitationService = Depends(_get_invitation_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    invitations = await invitation_service.get_organization_invitations(organization_id)
    return [_invitation_to_response(i) for i in invitations]


@router.post("/invitations/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request = None,
    invitation_service: InvitationService = Depends(_get_invitation_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        membership = await invitation_service.accept_invitation(body.token, current_user)
    except (InvitationNotFound, InvitationExpired, InvitationAlreadyAccepted) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return AcceptInvitationResponse(
        organization_id=membership.organization_id,
        role=membership.role.value,
        membership_id=membership.id,
    )


@router.post("/invitations/{invitation_id}/revoke", status_code=200)
async def revoke_invitation(
    invitation_id: str = Path(...),
    request: Request = None,
    invitation_service: InvitationService = Depends(_get_invitation_service),
    current_user: str = Depends(_get_current_user),
):
    _enrich_request(request)
    try:
        await invitation_service.revoke_invitation(invitation_id, current_user)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return {"message": "Invitation revoked"}


# ─── Helpers ─────────────────────────────────────────────────────────


def _org_to_response(org: object) -> OrganizationResponse:
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        display_name=org.display_name,
        description=org.description,
        avatar_url=org.avatar_url,
        status=org.status.value if hasattr(org.status, "value") else org.status,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
        metadata=org.metadata,
    )


def _member_to_response(m: object) -> MemberResponse:
    return MemberResponse(
        id=m.id,
        user_id=m.user_id,
        organization_id=m.organization_id,
        role=m.role.value if hasattr(m.role, "value") else m.role,
        status=m.status.value if hasattr(m.status, "value") else m.status,
        joined_at=m.joined_at,
        invited_by=m.invited_by,
    )


def _invitation_to_response(i: object) -> InviteResponse:
    return InviteResponse(
        id=i.id,
        organization_id=i.organization_id,
        email=i.email,
        role=i.role.value if hasattr(i.role, "value") else i.role,
        token=i.token,
        status=i.status.value if hasattr(i.status, "value") else i.status,
        expires_at=i.expires_at,
        created_by=i.created_by,
        created_at=i.created_at,
    )


# ─── deprecated context provision ──────────────────────────────────
# Service dependency injection is handled by register_deps() and
# _get_org_service / _get_membership_service / _get_invitation_service
# defined at the top of this module.
