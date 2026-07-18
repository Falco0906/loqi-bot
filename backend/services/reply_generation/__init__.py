"""Reply Generation Engine.

Consumes Conversation Intelligence + Reasoning Results → produces reply drafts.
Provider-independent. Prompt construction is isolated from providers.
"""

from .generation_models import (
    GenerationStyle, GenerationTemplate, ValidationSeverity,
    GenerationContext, ReplyDraft, ReplyVariant,
    GenerationMetadata, GenerationResult, ValidationIssue,
    PROMPT_BUILDER_VERSION, TEMPLATE_LIBRARY_VERSION,
    STYLE_ENGINE_VERSION, CONTEXT_BUILDER_VERSION,
    PIPELINE_VERSION,
)
from .provider_base import LLMProvider, ProviderResponse
from .provider_registry import register_provider, get_provider, list_providers, get_default_provider, validate_all
from .generation_pipeline import GenerationPipeline
from .validation import validate_draft
from .style_engine import get_style_instructions, list_styles
from .template_library import register_template, select_template, get_template_instructions

__all__ = [
    "GenerationStyle", "GenerationTemplate", "ValidationSeverity",
    "GenerationContext", "ReplyDraft", "ReplyVariant",
    "GenerationMetadata", "GenerationResult", "ValidationIssue",
    "PROMPT_BUILDER_VERSION", "TEMPLATE_LIBRARY_VERSION",
    "STYLE_ENGINE_VERSION", "CONTEXT_BUILDER_VERSION", "PIPELINE_VERSION",
    "LLMProvider", "ProviderResponse",
    "register_provider", "get_provider", "list_providers",
    "get_default_provider", "validate_all",
    "GenerationPipeline",
    "validate_draft",
    "get_style_instructions", "list_styles",
    "register_template", "select_template", "get_template_instructions",
]
