"""Strategic Intelligence API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.identity.dependencies import AuthContext, get_current_auth
from services.strategic_intelligence import get_profile_generator

router = APIRouter(prefix="/api/v1/strategic-intelligence", tags=["Strategic Intelligence"])


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
    """Generate a strategic profile from onboarding data.

    Requires authentication. The actor identity is derived from the validated
    session; a client-supplied ``user_id`` is never trusted for persistence.
    """
    try:
        generator = get_profile_generator()
        profile = await generator.generate_profile(
            company_description=payload.company_description,
            ideal_customer=payload.ideal_customer,
            differentiation=payload.differentiation,
            annual_goal=payload.annual_goal,
            biggest_obstacle=payload.biggest_obstacle,
            website=payload.website,
        )
        generated_at = datetime.now(timezone.utc).isoformat()

        try:
            from services.onboarding.api import _get_service as get_onboarding_service

            svc = get_onboarding_service()
            await svc.save_wizard_data(
                auth.user_id,
                {
                    "strategicProfile": profile,
                    "strategicProfileGeneratedAt": generated_at,
                },
            )
        except Exception:
            # Persistence is best-effort; generation still succeeds
            pass

        return GenerateProfileResponse(profile=profile, generated_at=generated_at)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to generate profile") from e


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
    """Get the stored strategic profile for the authenticated user."""
    try:
        from services.onboarding.api import _get_service as get_onboarding_service

        svc = get_onboarding_service()
        wizard_data = await svc.get_wizard_data(auth.user_id)
        profile = wizard_data.get("strategicProfile")
        if isinstance(profile, dict) and profile:
            generated_at = wizard_data.get("strategicProfileGeneratedAt")
            return GetProfileResponse(
                profile=profile,
                generated_at=generated_at if isinstance(generated_at, str) else None,
            )
        return GetProfileResponse(profile=None, generated_at=None)
    except Exception:
        return GetProfileResponse(profile=None, generated_at=None)
