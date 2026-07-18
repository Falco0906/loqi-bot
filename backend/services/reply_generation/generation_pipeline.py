from __future__ import annotations
import logging
import time
from typing import Optional

from services.reply_generation.generation_models import (
    GenerationStyle, GenerationContext, GenerationResult,
    ReplyDraft, ReplyVariant, GenerationMetadata, ValidationIssue,
    ValidationSeverity, PIPELINE_VERSION,
)
from services.reply_generation.generation_context import build_context
from services.reply_generation.prompt_builder import build_system_prompt, build_user_prompt
from services.reply_generation.provider_registry import get_provider, get_default_provider
from services.reply_generation.validation import validate_draft
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import ReasoningResult


logger = logging.getLogger(__name__)


class GenerationPipeline:
    """Full-stack reply generation pipeline.

    Lifecycle:
        Generation Requested
        → Context Built
        → Template Selected
        → Style Applied
        → Prompt Built
        → Provider Selected
        → Generation Started
        → Generation Completed
        → Validation Completed
        → Generation Returned

    The pipeline does not reason. It does not decide. It generates.
    """

    def __init__(self, provider_name: Optional[str] = None):
        self._provider_name = provider_name

    def _get_provider(self):
        if self._provider_name:
            provider = get_provider(self._provider_name)
            if provider:
                return provider
        return get_default_provider()

    def generate(
        self,
        intelligence: ConversationIntelligence,
        reasoning: ReasoningResult,
        styles: Optional[list[GenerationStyle]] = None,
        variant_count: int = 1,
        latest_messages: Optional[list[str]] = None,
    ) -> GenerationResult:
        """Generate reply drafts for the given intelligence + reasoning."""
        timing: dict[str, int] = {"start": int(time.perf_counter() * 1000)}

        if not styles:
            styles = [GenerationStyle.PROFESSIONAL]

        provider = self._get_provider()
        if not provider:
            return GenerationResult(
                conversation_id=intelligence.conversation_id,
                validation_results=[
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="no_provider",
                        message="No LLM provider available. Configure OPENAI_API_KEY or another provider.",
                    )
                ],
                timing={"error": "no_provider"},
            )

        result = GenerationResult(conversation_id=intelligence.conversation_id)
        template_used = ""

        for style_idx, style in enumerate(styles):
            t_context = int(time.perf_counter() * 1000)
            context = build_context(intelligence, reasoning, style, latest_messages)
            template_used = select_template_name(context)
            context.template_name = template_used
            timing[f"context_built_{style.value}"] = int(time.perf_counter() * 1000) - t_context

            t_prompt = int(time.perf_counter() * 1000)
            system_prompt = build_system_prompt(context)
            user_prompt = build_user_prompt(context)
            timing[f"prompt_built_{style.value}"] = int(time.perf_counter() * 1000) - t_prompt

            t_gen_start = int(time.perf_counter() * 1000)
            prompt_preview = user_prompt[:200].replace("\n", " ") if user_prompt else ""

            drafts: list[ReplyDraft] = []
            temperatures = [0.5, 0.6, 0.8, 0.9]

            for i in range(variant_count):
                temp = temperatures[i] if i < len(temperatures) else 0.7
                variant_instructions = _variant_instruction(i, variant_count)

                variant_system = system_prompt
                if variant_instructions:
                    variant_system = f"{variant_system}\n\nVariation: {variant_instructions}"

                try:
                    response = provider.generate(
                        system_prompt=variant_system,
                        user_prompt=user_prompt,
                        temperature=temp,
                    )
                    raw = response.text
                except Exception as e:
                    logger.error("Generation failed for style=%s variant=%d: %s", style.value, i, e)
                    raw = ""

                draft = ReplyDraft(content=raw.strip(), style=style, variant_index=i)
                validation_issues = validate_draft(draft)
                result.validation_results.extend(validation_issues)
                drafts.append(draft)

            timing[f"generation_{style.value}"] = int(time.perf_counter() * 1000) - t_gen_start

            t_validate = int(time.perf_counter() * 1000)
            timing[f"validation_{style.value}"] = int(time.perf_counter() * 1000) - t_validate

            result.variants.append(ReplyVariant(drafts=drafts, style=style))

            result.metadata = GenerationMetadata(
                provider=provider.provider_name,
                model=response.model if hasattr(response, 'model') and response.model else provider.default_model,
                token_usage=response.token_usage if hasattr(response, 'token_usage') else {},
                template_used=template_used,
                style_used=style.value,
                reasoning_version=getattr(reasoning, 'pipeline_version', '1'),
                prompt_preview=prompt_preview,
            )

        timing["total"] = int(time.perf_counter() * 1000) - timing.pop("start")
        result.timing = timing

        return result


def select_template_name(context: GenerationContext) -> str:
    """Determine template name from context without importing template library."""
    goal = context.primary_goal.lower()
    if "pricing" in goal or "budget" in goal:
        return "pricing_response"
    if "demo" in goal:
        return "demo_confirmation"
    if "meeting" in goal or "schedule" in goal:
        return "meeting_scheduling"
    if "objection" in goal or "overcome" in goal:
        return "objection_handling"
    if "question" in goal or "technical" in goal or "information" in context.decision_type:
        return "technical_question" if context.buying_signals else "clarification"
    if "engage" in goal or "follow" in goal:
        return "re_engagement"
    if "confirm" in goal or "interest" in goal:
        return "thank_you"
    if context.decision_type in ("wait", "continue_nurturing"):
        return "follow_up"
    return "general_reply"


def _variant_instruction(index: int, total: int) -> str:
    """Generate a variation instruction for a specific variant index.
    
    Each variant gets structurally different instructions so drafts
    differ in more than just temperature.
    """
    if total <= 1:
        return ""

    variations = [
        "Write a concise version — 2-3 sentences maximum. Lead with the key point.",
        "Write a question-driven version. Start with a relevant question, then provide context.",
        "Write a value-first version. Open with the key benefit, then offer a next step.",
        "Write a story-driven version. Use a brief anecdote or example to illustrate the point.",
    ]
    return variations[index % len(variations)]
