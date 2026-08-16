from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from services.capabilities.exceptions import (
    CapabilityAlreadyDisabled,
    CapabilityAlreadyEnabled,
    CapabilityException,
    CapabilityNotRegistered,
    DuplicateCapabilityRegistration,
)
from services.capabilities.schemas import (
    CapabilitiesListResponse,
    CapabilityDefinitionResponse,
    CapabilityUsageResponse,
    DisableCapabilityResponse,
    EnableCapabilityResponse,
    OrganizationCapabilitiesListResponse,
    OrganizationCapabilityResponse,
)
from services.capabilities.services import CapabilityService
from services.identity.dependencies import get_current_user_id
from services.organizations.models import MembershipRole, MembershipStatus

router = APIRouter(prefix="/api/v1", tags=["Capabilities"])


HTTP_ERROR_MAP: dict[type[Exception], int] = {
    CapabilityNotRegistered: 404,
    CapabilityAlreadyEnabled: 409,
    CapabilityAlreadyDisabled: 409,
    DuplicateCapabilityRegistration: 409,
}


# ─── Dependency Resolution ───────────────────────────────────────────


class CapabilityDeps:
    def __init__(
        self,
        capability_service: CapabilityService,
    ) -> None:
        self.capability_service = capability_service


_deps_registry: CapabilityDeps | None = None


def register_deps(deps: CapabilityDeps) -> None:
    global _deps_registry
    _deps_registry = deps


async def _get_capability_service() -> CapabilityService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Capability services not initialized")
    return _deps_registry.capability_service


# ─── Organization-boundary authorization (SaaS-1.4) ─────────────────


async def _get_org_membership_service():
    """Reuse the organization platform's membership service (canonical actor
    resolution + org membership)."""
    from services.organizations.api import _get_membership_service
    return await _get_membership_service()


async def _get_actor_membership(
    organization_id: str,
    membership_service,
    current_user: str,
):
    from services.organizations.exceptions import MembershipNotFound
    try:
        return await membership_service.get_user_membership(current_user, organization_id)
    except MembershipNotFound:
        # 404 hides whether the organization exists (BOLA enumeration guard).
        raise HTTPException(status_code=404, detail="Organization not found") from None


async def _require_org_member(
    organization_id: str = Path(...),
    membership_service=Depends(_get_org_membership_service),
    current_user: str = Depends(get_current_user_id),
):
    await _get_actor_membership(organization_id, membership_service, current_user)


async def _require_org_admin(
    organization_id: str = Path(...),
    membership_service=Depends(_get_org_membership_service),
    current_user: str = Depends(get_current_user_id),
):
    membership = await _get_actor_membership(organization_id, membership_service, current_user)
    if (
        membership.status != MembershipStatus.ACTIVE
        or membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
    ):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


# ─── Helpers ─────────────────────────────────────────────────────────


def _capability_to_response(c) -> CapabilityDefinitionResponse:
    return CapabilityDefinitionResponse(
        slug=c.slug,
        name=c.name,
        category=c.category,
        description=c.description,
        default_enabled=c.default_enabled,
        beta=c.beta,
        created_at=c.created_at,
    )


def _org_capability_to_response(oc) -> OrganizationCapabilityResponse:
    return OrganizationCapabilityResponse(
        organization_id=oc.organization_id,
        capability_slug=oc.capability_slug,
        enabled=oc.enabled,
        activated_at=oc.activated_at,
        activated_by=oc.activated_by,
    )


def _usage_to_response(u) -> CapabilityUsageResponse:
    return CapabilityUsageResponse(
        organization_id=u.organization_id,
        capability_slug=u.capability_slug,
        requests=u.requests,
        executions=u.executions,
        storage_bytes=u.storage_bytes,
        api_calls=u.api_calls,
        last_reset=u.last_reset,
        updated_at=u.updated_at,
    )


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("/capabilities", response_model=CapabilitiesListResponse)
async def list_capabilities(
    capability_service: CapabilityService = Depends(_get_capability_service),
):
    capabilities = await capability_service.list_capabilities()
    return CapabilitiesListResponse(
        capabilities=[_capability_to_response(c) for c in capabilities]
    )


@router.get(
    "/organizations/{organization_id}/capabilities",
    response_model=OrganizationCapabilitiesListResponse,
)
async def list_organization_capabilities(
    organization_id: str = Path(...),
    capability_service: CapabilityService = Depends(_get_capability_service),
    _boundary: None = Depends(_require_org_member),
):
    org_caps = await capability_service.get_organization_capabilities(organization_id)
    return OrganizationCapabilitiesListResponse(
        capabilities=[_org_capability_to_response(oc) for oc in org_caps]
    )


@router.post(
    "/organizations/{organization_id}/capabilities/{slug}/enable",
    response_model=EnableCapabilityResponse,
)
async def enable_organization_capability(
    organization_id: str = Path(...),
    slug: str = Path(...),
    capability_service: CapabilityService = Depends(_get_capability_service),
    current_user: str = Depends(get_current_user_id),
    _boundary: None = Depends(_require_org_admin),
):
    try:
        org_cap = await capability_service.enable_capability(
            organization_id, slug, activated_by=current_user,
        )
    except CapabilityException as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return EnableCapabilityResponse(
        organization_id=org_cap.organization_id,
        capability_slug=org_cap.capability_slug,
        enabled=org_cap.enabled,
        activated_at=org_cap.activated_at,
    )


@router.post(
    "/organizations/{organization_id}/capabilities/{slug}/disable",
    response_model=DisableCapabilityResponse,
)
async def disable_organization_capability(
    organization_id: str = Path(...),
    slug: str = Path(...),
    capability_service: CapabilityService = Depends(_get_capability_service),
    current_user: str = Depends(get_current_user_id),
    _boundary: None = Depends(_require_org_admin),
):
    try:
        org_cap = await capability_service.disable_capability(organization_id, slug)
    except CapabilityException as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return DisableCapabilityResponse(
        organization_id=org_cap.organization_id,
        capability_slug=org_cap.capability_slug,
        enabled=org_cap.enabled,
    )


@router.get(
    "/organizations/{organization_id}/capabilities/{slug}/usage",
    response_model=CapabilityUsageResponse,
)
async def get_capability_usage(
    organization_id: str = Path(...),
    slug: str = Path(...),
    capability_service: CapabilityService = Depends(_get_capability_service),
    _boundary: None = Depends(_require_org_member),
):
    try:
        usage = await capability_service.get_usage(organization_id, slug)
    except CapabilityException as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return _usage_to_response(usage)
