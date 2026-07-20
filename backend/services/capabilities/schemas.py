from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CapabilityDefinitionResponse(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    default_enabled: bool
    beta: bool
    created_at: datetime


class CapabilitiesListResponse(BaseModel):
    capabilities: list[CapabilityDefinitionResponse]


class OrganizationCapabilityResponse(BaseModel):
    organization_id: str
    capability_slug: str
    enabled: bool
    activated_at: datetime | None = None
    activated_by: str = ""


class OrganizationCapabilitiesListResponse(BaseModel):
    capabilities: list[OrganizationCapabilityResponse]


class EnableCapabilityResponse(BaseModel):
    organization_id: str
    capability_slug: str
    enabled: bool
    activated_at: datetime | None = None


class DisableCapabilityResponse(BaseModel):
    organization_id: str
    capability_slug: str
    enabled: bool


class CapabilityUsageResponse(BaseModel):
    organization_id: str
    capability_slug: str
    requests: int = 0
    executions: int = 0
    storage_bytes: int = 0
    api_calls: int = 0
    last_reset: datetime | None = None
    updated_at: datetime
