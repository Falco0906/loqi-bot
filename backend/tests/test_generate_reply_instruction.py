"""PR4.3B — generate-reply instruction (refine) path.

Covers:
  A. Route threads an optional ``instruction`` into the generation pipeline.
  B. Route behavior is unchanged when ``instruction`` is absent (None passed).
  C. The pipeline embeds the instruction in the system prompt (highest
     priority) so it conditions the generated reply.
  D. No instruction -> no refinement text in the system prompt.
"""
import asyncio
import os
import sys
import uuid
from unittest.mock import MagicMock

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.reasoning.reasoning_models import (
    DecisionPriority,
    DecisionType,
    GoalSelection,
    GoalType,
    PriorityAssessment,
    ReasoningDecision,
    ReasoningResult,
    RiskAssessment,
    RiskLevel,
)
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send, handle_reply

import main as main_module  # noqa: E402
def _auth_request(token="session-x"):
    request = MagicMock()
    request.headers.get = lambda k, d="": f"Bearer {token}" if k == "authorization" else d
    return request



PROVIDER = "prov-instruction"
CONTACT_EMAIL = "jordan@bella-vista.com"
OWNER_EMAIL = "faisal@loqi.com"


class FakeReply:
    def __init__(self, content):
        self.text = content


class FakeProvider:
    provider_name = "fake"
    default_model = "fake-model"

    def __init__(self):
        self.captured_prompts = []

    def generate(self, system_prompt, user_prompt, temperature):
        self.captured_prompts.append(system_prompt)
        return FakeReply(f"Draft at temperature {temperature}")


class FakeGenerationPipeline:
    calls = []

    @classmethod
    def reset(cls):
        cls.calls = []

    def __init__(self):
        pass

    def generate(self, **kwargs):
        FakeGenerationPipeline.calls.append(kwargs)
        return SimpleNamespace(to_dict=lambda: {"instruction": kwargs.get("instruction")})


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def to_dict(self):
        return self.__dict__


@pytest.fixture(autouse=True)
def _clean_registries():
    FakeGenerationPipeline.reset()
    yield
    FakeGenerationPipeline.reset()


def _make_conversation_with_reply() -> str:
    external_thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    convo = create_conversation_from_send(
        provider_id=PROVIDER,
        provider_type="gmail",
        external_thread_id=external_thread_id,
        external_message_id=f"outbound_{uuid.uuid4().hex[:12]}",
        subject="Quick question about Loqi",
        from_email=OWNER_EMAIL,
        from_name="Faisal",
        to_email=CONTACT_EMAIL,
        to_name="Jordan Parker",
        body="Hi Jordan, would Loqi be a fit?",
        campaign_id="cmp-1",
        workflow_id="wf-1",
        lead_id="lead-1",
        owner_id="test-owner",
    )
    handle_reply(
        conversation_id=convo.conversation_id,
        external_message_id=f"inbound_{uuid.uuid4().hex[:12]}",
        from_email=CONTACT_EMAIL,
        from_name="Jordan Parker",
        to_email=OWNER_EMAIL,
        to_name="Faisal",
        subject="Re: Quick question about Loqi",
        body="We're interested — could you share pricing and a rough timeline?",
    )
    return convo.conversation_id


def _sample_intelligence() -> ConversationIntelligence:
    return ConversationIntelligence(conversation_id="c-1")


def _sample_reasoning() -> ReasoningResult:
    return ReasoningResult(
        conversation_id="c-1",
        decision=ReasoningDecision(type=DecisionType.REPLY),
        goal=GoalSelection(primary=GoalType.PROVIDE_PRICING),
        priority=PriorityAssessment(level=DecisionPriority.HIGH),
        risk=RiskAssessment(level=RiskLevel.LOW),
    )


class TestGenerateReplyInstructionRoute:
    def test_A_route_threads_instruction(self, monkeypatch):
        monkeypatch.setattr(
            "services.reply_generation.generation_pipeline.GenerationPipeline",
            FakeGenerationPipeline,
        )
        cid = _make_conversation_with_reply()
        result = asyncio.run(
            main_module.generate_reply_route(
                "session-x",
                cid,
                {"styles": ["professional"], "variant_count": 1, "instruction": "make it shorter"},
                _auth_request(),
            )
        )
        assert result["ok"] is True
        calls = FakeGenerationPipeline.calls
        assert calls, "pipeline was never invoked"
        assert calls[-1]["instruction"] == "make it shorter"
        assert calls[-1]["styles"] and calls[-1]["styles"][0].value == "professional"

    def test_B_route_preserves_behavior_without_instruction(self, monkeypatch):
        monkeypatch.setattr(
            "services.reply_generation.generation_pipeline.GenerationPipeline",
            FakeGenerationPipeline,
        )
        cid = _make_conversation_with_reply()
        result = asyncio.run(
            main_module.generate_reply_route(
                "session-x",
                cid,
                {"styles": ["professional"], "variant_count": 1},
                _auth_request(),
            )
        )
        assert result["ok"] is True
        calls = FakeGenerationPipeline.calls
        assert calls[-1]["instruction"] is None


class TestGenerationPipelineInstruction:
    def _run(self, instruction):
        from services.reply_generation.generation_pipeline import GenerationPipeline

        fake = FakeProvider()
        pipeline = GenerationPipeline()
        monkeypatch_provider(pipeline, fake)
        pipeline.generate(
            intelligence=_sample_intelligence(),
            reasoning=_sample_reasoning(),
            styles=None,
            variant_count=1,
            instruction=instruction,
        )
        return fake.captured_prompts

    def test_C_instruction_embedded_in_system_prompt(self):
        prompts = self._run("make it shorter and less salesy")
        assert prompts
        assert "User Refinement Instruction" in prompts[0]
        assert "make it shorter and less salesy" in prompts[0]

    def test_D_no_instruction_no_refinement_block(self):
        prompts = self._run(None)
        assert prompts
        assert "User Refinement Instruction" not in prompts[0]


def monkeypatch_provider(pipeline, fake_provider):
    import services.reply_generation.generation_pipeline as gp

    gp.get_default_provider = lambda: fake_provider
