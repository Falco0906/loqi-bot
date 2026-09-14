"""Characterization tests for onboarding-derived strategic profile use cases."""

from __future__ import annotations

import asyncio

from services.strategic.profile import service


class _Generator:
    def __init__(self, profile: dict):
        self.profile = profile
        self.calls: list[dict] = []

    async def generate_profile(self, **kwargs):
        self.calls.append(kwargs)
        return self.profile


class _Onboarding:
    def __init__(self, wizard_data: dict | None = None, *, fail_save: bool = False, fail_read: bool = False):
        self.wizard_data = wizard_data or {}
        self.fail_save = fail_save
        self.fail_read = fail_read
        self.saved: list[tuple[str, dict]] = []

    async def save_wizard_data(self, user_id: str, data: dict):
        if self.fail_save:
            raise RuntimeError("persistence unavailable")
        self.saved.append((user_id, data))

    async def get_wizard_data(self, _user_id: str):
        if self.fail_read:
            raise RuntimeError("persistence unavailable")
        return self.wizard_data


def test_generate_profile_preserves_envelope_and_best_effort_persistence():
    generator = _Generator({"COMPANY_SUMMARY": "Acme"})
    onboarding = _Onboarding()

    result = asyncio.run(service.generate_profile_for_user(
        "user-1",
        company_description="Widgets",
        ideal_customer="Operators",
        differentiation="Fast",
        annual_goal="Grow",
        biggest_obstacle="Awareness",
        website="https://acme.example",
        onboarding_service=onboarding,
        generator=generator,
    ))

    assert set(result) == {"profile", "generated_at"}
    assert result["profile"] == {"COMPANY_SUMMARY": "Acme"}
    assert generator.calls == [{
        "company_description": "Widgets",
        "ideal_customer": "Operators",
        "differentiation": "Fast",
        "annual_goal": "Grow",
        "biggest_obstacle": "Awareness",
        "website": "https://acme.example",
    }]
    assert onboarding.saved == [("user-1", {
        "strategicProfile": result["profile"],
        "strategicProfileGeneratedAt": result["generated_at"],
    })]


def test_generate_profile_keeps_result_when_wizard_persistence_fails():
    result = asyncio.run(service.generate_profile_for_user(
        "user-1",
        company_description="Widgets",
        ideal_customer="Operators",
        differentiation="Fast",
        annual_goal="Grow",
        biggest_obstacle="Awareness",
        website=None,
        onboarding_service=_Onboarding(fail_save=True),
        generator=_Generator({"COMPANY_SUMMARY": "Acme"}),
    ))

    assert result["profile"] == {"COMPANY_SUMMARY": "Acme"}
    assert isinstance(result["generated_at"], str)


def test_get_profile_preserves_empty_and_read_failure_envelopes():
    profile = asyncio.run(service.get_profile_for_user(
        "user-1",
        onboarding_service=_Onboarding({
            "strategicProfile": {"COMPANY_SUMMARY": "Acme"},
            "strategicProfileGeneratedAt": "2026-01-01T00:00:00+00:00",
        }),
    ))
    assert profile == {
        "profile": {"COMPANY_SUMMARY": "Acme"},
        "generated_at": "2026-01-01T00:00:00+00:00",
    }

    assert asyncio.run(service.get_profile_for_user(
        "user-1", onboarding_service=_Onboarding(),
    )) == {"profile": None, "generated_at": None}
    assert asyncio.run(service.get_profile_for_user(
        "user-1", onboarding_service=_Onboarding(fail_read=True),
    )) == {"profile": None, "generated_at": None}
