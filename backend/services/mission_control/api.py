"""Mission Control API endpoint handlers.

These are thin wrappers that can be registered as route handlers in main.py.
They avoid circular imports by accepting all data as parameters.
"""
from __future__ import annotations

from services.mission_control.briefing import get_service


async def handle_get_briefing(
    session_token: str,
    campaigns: list[dict],
    drafts: list[dict],
    total_leads: int = 0,
    db_user_id: str | None = None,
):
    """Handler for GET /api/web/session/{session_token}/briefing.

    Call this from main.py with the resolved campaign_store, draft_store, etc.
    """
    service = get_service()
    return service.get_briefing(
        session_token=session_token,
        campaigns=campaigns,
        drafts=drafts,
        total_leads=total_leads,
        user_id=session_token,
        db_user_id=db_user_id,
    )
