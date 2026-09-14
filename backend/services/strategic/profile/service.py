"""Use cases for an authenticated user's onboarding-derived strategic profile."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.strategic.profile.generator import StrategicProfileGenerator, get_profile_generator


async def generate_profile_for_user(
    user_id: str,
    *,
    company_description: str,
    ideal_customer: str,
    differentiation: str,
    annual_goal: str,
    biggest_obstacle: str,
    website: str | None,
    onboarding_service: Any,
    generator: StrategicProfileGenerator | None = None,
) -> dict[str, Any]:
    """Generate a profile and best-effort persist it in onboarding wizard data."""
    profile_generator = generator or get_profile_generator()
    profile = await profile_generator.generate_profile(
        company_description=company_description,
        ideal_customer=ideal_customer,
        differentiation=differentiation,
        annual_goal=annual_goal,
        biggest_obstacle=biggest_obstacle,
        website=website,
    )
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        await onboarding_service.save_wizard_data(
            user_id,
            {
                "strategicProfile": profile,
                "strategicProfileGeneratedAt": generated_at,
            },
        )
    except Exception:
        # Existing contract: generation succeeds even if optional wizard persistence fails.
        pass

    return {"profile": profile, "generated_at": generated_at}


async def get_profile_for_user(user_id: str, *, onboarding_service: Any) -> dict[str, Any]:
    """Read the authenticated user's persisted onboarding strategic profile."""
    try:
        wizard_data = await onboarding_service.get_wizard_data(user_id)
    except Exception:
        return {"profile": None, "generated_at": None}

    profile = wizard_data.get("strategicProfile")
    if not isinstance(profile, dict) or not profile:
        return {"profile": None, "generated_at": None}

    generated_at = wizard_data.get("strategicProfileGeneratedAt")
    return {
        "profile": profile,
        "generated_at": generated_at if isinstance(generated_at, str) else None,
    }
