"""HTTP routes for the Mission Control domain."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services.identity import dependencies as identity_dependencies
from services.mission_control.briefing import get_service

router = APIRouter(tags=["Mission Control"])

@router.get("/api/web/session/{session_token}/mission-control")
async def mission_control_summary(
    session_token: str,
    request: Request,
    onboarding_user_id: str = "",
):
    """Return the authenticated user's current Mission Control summary."""
    del onboarding_user_id
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return await get_service().get_summary(
        owner_id=owner_id,
        session_token=session_token,
    )

@router.get("/api/web/session/{session_token}/briefing")
async def briefing_endpoint(
    session_token: str,
    request: Request,
    onboarding_user_id: str = "",
):
    """Return the authenticated user's current grounded briefing."""
    del onboarding_user_id
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return await get_service().get_workspace_briefing(
        owner_id=owner_id,
        session_token=session_token,
        user_timezone=request.headers.get("x-timezone"),
    )
