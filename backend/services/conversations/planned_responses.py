"""Retained future legacy-conversation response capabilities.

These helpers are intentionally unused today. They support a planned
onboarding question-skipping and workflow next-step-suggestion feature, so
they are not legacy dead code and must not be removed without a product check.
"""
from __future__ import annotations

from typing import Optional

import services.intelligence.ai as ai_service
from services.conversations.legacy_responses import _extract_single_message_fields


def should_skip_question(
    user_message: str,
    session_context: dict,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if the user already provided sufficient info to skip questions.
    Returns (should_skip, service, target).
    """
    service, target, signals = _extract_single_message_fields(user_message)

    existing_service = session_context.get("service")
    existing_target = session_context.get("target")

    combined_message = "combined_message" in signals

    if combined_message and service and target:
        return True, service, target

    if service and not existing_service and not existing_target:
        if len(user_message.split()) > 3:
            return True, service, None

    return False, None, None


def suggest_next_action(
    stage: str,
    context: dict,
) -> str:
    """
    AI-guided suggestion for the next action.
    """
    system = (
        "You suggest ONE immediate next action for a B2B sales assistant.\n"
        "Be direct, concise, and actionable.\n"
        "Return only the action text, no explanation.\n"
        "Examples:\n"
        "- 'Draft outreach for [name]'\n"
        "- 'Send the email'\n"
        "- 'Find restaurant operators in [area]'\n"
        "- 'Refine the message'\n"
        "- 'Look for more leads'\n"
    )

    user_text = f"Stage: {stage}\nContext: {context}"

    result = ai_service.try_send_openai_request(system, user_text, timeout=15)

    if result and len(result) > 0 and len(result) < 100:
        return result.strip()

    return _suggest_fallback_action(stage, context)


def _suggest_fallback_action(stage: str, context: dict) -> str:
    """Fallback action suggestions based on stage."""
    suggestions = {
        "need_service": "Ask what they sell",
        "need_target": "Ask who they want to reach",
        "leads_ready": "Let them pick a lead",
        "draft_ready": "Ask if they want to send or refine",
        "refining": "Apply their feedback",
        "sending": "Send the email",
        "complete": "Offer to find more leads",
    }
    return suggestions.get(stage, "Continue the conversation")
