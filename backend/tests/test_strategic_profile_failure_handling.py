"""Offline failure contracts for the authenticated strategic-profile route."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.intelligence.ai import OpenAIError
from services.strategic.profile import api


def _payload():
    return api.GenerateProfileRequest(
        company_description="A planning tool",
        ideal_customer="Founders",
        differentiation="Faster setup",
        annual_goal="Grow",
        biggest_obstacle="Awareness",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", [
    ("invalid_output", 502), ("provider_timeout", 504),
    ("credentials", 503), ("rate_limit", 503),
])
async def test_known_ai_failure_is_actionable_without_exposing_provider_details(monkeypatch, kind, status):
    async def fail(*_args, **_kwargs):
        raise OpenAIError("provider-secret-response", kind=kind)

    monkeypatch.setattr(api.profile_service, "generate_profile_for_user", fail)
    with pytest.raises(HTTPException) as exc:
        await api.generate_strategic_profile(_payload(), SimpleNamespace(user_id="user-1"))
    assert exc.value.status_code == status
    assert "answers are saved" in exc.value.detail
    assert "provider-secret-response" not in exc.value.detail


@pytest.mark.asyncio
async def test_unexpected_failure_is_not_presented_as_success(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise RuntimeError("internal-secret")

    monkeypatch.setattr(api.profile_service, "generate_profile_for_user", fail)
    with pytest.raises(HTTPException) as exc:
        await api.generate_strategic_profile(_payload(), SimpleNamespace(user_id="user-1"))
    assert exc.value.status_code == 500
    assert "internal-secret" not in exc.value.detail
