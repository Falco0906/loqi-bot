from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from services.organizations.models import MembershipRole, MembershipStatus


# ─── Organization ────────────────────────────────────────────────────


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=255, pattern=r"^[a-z0-9\-]+$")
    display_name: str | None = Field(None, max_length=255)
    description: str = Field(default="", max_length=2000)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=255, pattern=r"^[a-z0-9\-]+$")
    display_name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=2048)
    metadata: dict[str, Any] | None = None


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    display_name: str
    description: str
    avatar_url: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]


# ─── Membership ──────────────────────────────────────────────────────


class MemberResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    status: str
    joined_at: datetime
    invited_by: str


class ChangeRoleRequest(BaseModel):
    target_user_id: str
    role: MembershipRole


class TransferOwnershipRequest(BaseModel):
    new_owner_id: str


class RemoveMemberRequest(BaseModel):
    user_id: str


# ─── Invitation ──────────────────────────────────────────────────────


class InviteRequest(BaseModel):
    email: str = Field(..., max_length=320)
    role: MembershipRole = MembershipRole.MEMBER


class InviteResponse(BaseModel):
    id: str
    organization_id: str
    email: str
    role: str
    token: str
    status: str
    expires_at: datetime
    created_by: str
    created_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str


class AcceptInvitationResponse(BaseModel):
    organization_id: str
    role: str
    membership_id: str


# ─── Organizations Module ────────────────────────────────────────────


class ModuleFeatures(BaseModel):
    onboarding: bool = True
    members: bool = True
    invitations: bool = True
    billing: bool = False
    capabilities: bool = False
