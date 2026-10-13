"""Offline contracts for the onboarding conversation's saved-answer boundary."""

import pytest

from services.intelligence.ai import OpenAIError
from services.onboarding import conversation
from services.onboarding.repositories import InMemoryLifecycleRepository, InMemoryOnboardingSessionRepository
from services.onboarding.services import LifecycleService, OnboardingService
from services.strategic.profile.generator import StrategicProfileGenerator


class Wizard:
    def __init__(self, data=None, fail_read=False, fail_save=False):
        self.data = dict(data or {})
        self.fail_read = fail_read
        self.fail_save = fail_save
        self.saves = []

    async def get_wizard_data_strict(self, _user_id):
        if self.fail_read:
            raise RuntimeError("storage unavailable")
        return dict(self.data)

    async def save_wizard_data(self, _user_id, update):
        if self.fail_save:
            raise RuntimeError("storage unavailable")
        self.data.update(update)
        self.saves.append(dict(update))


@pytest.mark.asyncio
async def test_turn_saves_answer_before_model_and_advances_deterministically(monkeypatch):
    wizard = Wizard()

    def model(_system, _user):
        assert wizard.data["companyDescription"] == "We help teams plan. https://example.test"
        return '{"acknowledgement":"I understand that you help teams plan.","next_question":"Who makes the decision to buy your planning tool?"}'

    monkeypatch.setattr(conversation, "_send_openai_request", model)
    result = await conversation.answer_turn(
        wizard, "user-1", "companyDescription", "We help teams plan. https://example.test"
    )
    assert result["mode"] == "ai"
    assert result["next_field"] == "idealCustomer"
    assert result["reply"].endswith("Who makes the decision to buy your planning tool?")
    assert wizard.data["website"] == "https://example.test"
    assert len(wizard.saves) == 2

    replay = await conversation.answer_turn(
        wizard, "user-1", "companyDescription", "We help teams plan. https://example.test"
    )
    assert replay == result
    assert len(wizard.saves) == 2


@pytest.mark.asyncio
async def test_provider_failure_is_visible_guided_mode_not_a_fake_ai_reply(monkeypatch):
    wizard = Wizard()

    def fail(_system, _user):
        raise OpenAIError("provider unavailable", kind="provider_timeout")

    monkeypatch.setattr(conversation, "_send_openai_request", fail)
    result = await conversation.answer_turn(wizard, "user-1", "companyDescription", "A planning tool")
    assert result["mode"] == "guided"
    assert "AI reply is unavailable" in result["reply"]
    assert wizard.data["companyDescription"] == "A planning tool"


@pytest.mark.asyncio
async def test_invalid_model_question_falls_back_without_changing_next_field(monkeypatch):
    wizard = Wizard()
    monkeypatch.setattr(conversation, "_send_openai_request", lambda *_: '{"acknowledgement":"Noted.","next_question":""}')
    result = await conversation.answer_turn(wizard, "user-1", "companyDescription", "A planning tool")
    assert result["mode"] == "guided"
    assert result["next_field"] == "idealCustomer"
    assert conversation.QUESTIONS["idealCustomer"] in result["reply"]


@pytest.mark.asyncio
async def test_invalid_order_or_changed_replay_cannot_mutate_answers(monkeypatch):
    wizard = Wizard()
    monkeypatch.setattr(conversation, "_send_openai_request", lambda *_: '{"acknowledgement":"Noted.","next_question":"Who buys it?"}')
    with pytest.raises(ValueError):
        await conversation.answer_turn(wizard, "user-1", "idealCustomer", "Founders")
    await conversation.answer_turn(wizard, "user-1", "companyDescription", "A planning tool")
    with pytest.raises(ValueError):
        await conversation.answer_turn(wizard, "user-1", "companyDescription", "A different answer")
    assert wizard.data["companyDescription"] == "A planning tool"


@pytest.mark.asyncio
async def test_final_answer_completes_questions_without_generating_profile(monkeypatch):
    wizard = Wizard({field: "Saved" for field in conversation.FIELDS[:-1]})
    monkeypatch.setattr(conversation, "_send_openai_request", lambda *_: '{"acknowledgement":"Thank you for sharing that.","next_question":""}')
    result = await conversation.answer_turn(wizard, "user-1", "biggestObstacle", "Awareness")
    assert result["complete"] is True
    assert result["next_field"] is None
    assert wizard.data["biggestObstacle"] == "Awareness"
    assert "strategicProfile" not in wizard.data


@pytest.mark.asyncio
async def test_storage_failures_are_not_reported_as_saved(monkeypatch):
    monkeypatch.setattr(conversation, "_send_openai_request", lambda *_: '{"acknowledgement":"Noted.","next_question":"Who buys it?"}')
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await conversation.answer_turn(Wizard(fail_read=True), "user-1", "companyDescription", "Answer")
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await conversation.answer_turn(Wizard(fail_save=True), "user-1", "companyDescription", "Answer")


def test_incomplete_strategic_profile_is_not_silently_filled_with_fake_facts():
    with pytest.raises(OpenAIError):
        StrategicProfileGenerator()._parse_profile_json('{"COMPANY_SUMMARY":"A tool"}')


def test_optional_profile_sections_can_be_absent_without_inventing_facts():
    profile = StrategicProfileGenerator()._parse_profile_json(
        '{"COMPANY_SUMMARY":"A planning tool",'
        '"ICP":"Founders","DIFFERENTIATION":"Faster setup",'
        '"PRIMARY_OBJECTIVE":"Grow","CURRENT_CONSTRAINTS":"Awareness"}'
    )
    assert profile["COMPANY_SUMMARY"] == "A planning tool"
    assert profile["INDUSTRY"] == "Unknown"
    assert profile["BUYER_PERSONAS"] == []
    assert profile["CONFIDENCE_LEVELS"] == {}


def test_profile_uses_strict_json_schema_for_all_expected_fields():
    schema = StrategicProfileGenerator.RESPONSE_FORMAT
    assert schema["type"] == "json_schema" and schema["strict"] is True
    contract = schema["schema"]
    assert set(contract["required"]) == set(contract["properties"])
    assert contract["additionalProperties"] is False
    for field in ("COMPANY_SUMMARY", "ICP", "DIFFERENTIATION", "PRIMARY_OBJECTIVE", "CURRENT_CONSTRAINTS"):
        assert contract["properties"][field] == {"type": "string"}


@pytest.mark.asyncio
async def test_profile_generation_requests_structured_output(monkeypatch):
    from services.strategic.profile import generator as module

    captured = []

    def model(_system, _user, response_format):
        captured.append(response_format)
        return ('{"COMPANY_SUMMARY":"A planning tool","ICP":"Founders",'
                '"DIFFERENTIATION":"Faster setup","PRIMARY_OBJECTIVE":"Grow",'
                '"CURRENT_CONSTRAINTS":"Awareness"}')

    monkeypatch.setattr(module, "_send_openai_request", model)
    profile = await StrategicProfileGenerator().generate_profile(
        "A planning tool", "Founders", "Faster setup", "Grow", "Awareness",
    )
    assert captured == [StrategicProfileGenerator.RESPONSE_FORMAT]
    assert profile["COMPANY_SUMMARY"] == "A planning tool"


@pytest.mark.asyncio
async def test_provider_failure_cannot_become_a_generated_strategic_profile(monkeypatch):
    from services.strategic.profile import generator as module

    def fail(_system, _user, _response_format):
        raise OpenAIError("provider unavailable", kind="provider_timeout")

    monkeypatch.setattr(module, "_send_openai_request", fail)
    with pytest.raises(OpenAIError):
        await StrategicProfileGenerator().generate_profile(
            "A planning tool", "Founders", "Faster setup", "Grow", "Awareness",
        )


@pytest.mark.asyncio
async def test_progress_read_failure_does_not_look_like_a_new_user():
    class FailingUsers:
        async def get_user(self, _user_id):
            raise RuntimeError("storage unavailable")

    service = OnboardingService(
        LifecycleService(InMemoryLifecycleRepository()),
        InMemoryOnboardingSessionRepository(),
        user_service=FailingUsers(),
    )
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await service.get_wizard_data("user-1")
