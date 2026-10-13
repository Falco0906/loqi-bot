"""HTTP adapters for onboarding-derived strategic profile operations."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.intelligence.ai import OpenAIError
from services.identity.dependencies import AuthContext, get_current_auth
from services.onboarding.api import get_onboarding_service
from services.strategic.profile import service as profile_service


router = APIRouter(prefix="/api/v1/strategic-intelligence", tags=["Strategic Intelligence"])
log = logging.getLogger(__name__)


class GenerateProfileRequest(BaseModel):
    """Request to generate a strategic profile."""

    company_description: str
    ideal_customer: str
    differentiation: str
    annual_goal: str
    biggest_obstacle: str
    website: str | None = None
    user_id: str | None = None


class GenerateProfileResponse(BaseModel):
    """Response containing the generated strategic profile."""

    profile: dict[str, Any]
    generated_at: str


class GetProfileResponse(BaseModel):
    """Response containing the stored strategic profile."""

    profile: dict[str, Any] | None
    generated_at: str | None


@router.post(
    "/generate",
    response_model=GenerateProfileResponse,
    summary="Generate strategic profile from onboarding data",
    description=(
        "Generate a structured strategic organization profile from onboarding "
        "conversation data using LLM. When user_id is provided, also persists "
        "the profile into onboarding wizard_data."
    ),
)
async def generate_strategic_profile(
    payload: GenerateProfileRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> GenerateProfileResponse:
    """Generate a profile for the authenticated actor only."""
    try:
        result = await profile_service.generate_profile_for_user(
            auth.user_id,
            company_description=payload.company_description,
            ideal_customer=payload.ideal_customer,
            differentiation=payload.differentiation,
            annual_goal=payload.annual_goal,
            biggest_obstacle=payload.biggest_obstacle,
            website=payload.website,
            onboarding_service=get_onboarding_service(),
        )
        return GenerateProfileResponse(**result)
    except OpenAIError as error:
        # Provider details can contain sensitive content. Log only the failure
        # category and return a stable, actionable message to the client.
        log.warning("strategic_profile_generation_failed kind=%s", error.kind)
        status = {
            "credentials": 503,
            "rate_limit": 503,
            "connection": 503,
            "provider_timeout": 504,
            "invalid_output": 502,
        }.get(error.kind, 502)
        detail = (
            "The AI profile service is unavailable. Your answers are saved; retry or continue without a profile."
            if status == 503 else
            "Profile generation timed out. Your answers are saved; retry or continue without a profile."
            if status == 504 else
            "The AI did not return a usable profile. Your answers are saved; retry or continue without a profile."
        )
        raise HTTPException(status_code=status, detail=detail) from error
    except Exception as error:
        log.error("strategic_profile_generation_failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=500, detail="Profile generation failed. Your answers are saved; you can continue without a profile.") from error


@router.get(
    "/profile/{user_id}",
    response_model=GetProfileResponse,
    summary="Get stored strategic profile",
    description="Retrieve the authenticated caller's stored strategic profile "
    "if it exists. Identity is derived from the session; the path user_id is "
    "ignored for actor identity.",
)
async def get_strategic_profile(
    user_id: str,
    auth: AuthContext = Depends(get_current_auth),
) -> GetProfileResponse:
    """Read the authenticated actor's profile; preserve the legacy empty result."""
    del user_id
    try:
        result = await profile_service.get_profile_for_user(
            auth.user_id,
            onboarding_service=get_onboarding_service(),
        )
        return GetProfileResponse(**result)
    except Exception:
        return GetProfileResponse(profile=None, generated_at=None)
