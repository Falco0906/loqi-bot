"""Style engine — modifies generation instructions based on selected style.

Each style provides tone, structure, and language instructions.
Styles modify prompts — they contain no business logic.
"""

from __future__ import annotations
from services.reply_generation.generation_models import GenerationStyle


STYLE_INSTRUCTIONS: dict[GenerationStyle, str] = {
    GenerationStyle.PROFESSIONAL: (
        "Tone: Professional and polished.\n"
        "Language: Clear, formal, respectful.\n"
        "Structure: Greeting, main message, clear call to action.\n"
        "Avoid: Slang, overly casual phrases, emojis."
    ),
    GenerationStyle.FRIENDLY: (
        "Tone: Warm and approachable.\n"
        "Language: Conversational, natural, human.\n"
        "Structure: Friendly opening, helpful message, soft next step.\n"
        "Avoid: Stiff corporate language, excessive formality."
    ),
    GenerationStyle.EXECUTIVE: (
        "Tone: Direct and strategic.\n"
        "Language: Concise, high-level, business-focused.\n"
        "Structure: Bottom-line upfront, key points, strategic ask.\n"
        "Avoid: Over-explaining, technical detail, casual language."
    ),
    GenerationStyle.TECHNICAL: (
        "Tone: Precise and informative.\n"
        "Language: Technical but accessible, specific.\n"
        "Structure: Context, technical detail, next technical step.\n"
        "Avoid: Vague claims, marketing language, oversimplification."
    ),
    GenerationStyle.CONSULTATIVE: (
        "Tone: Advisory and insightful.\n"
        "Language: Thoughtful, value-oriented.\n"
        "Structure: Insight, relevance to their situation, recommendation, next step.\n"
        "Avoid: Hard sell, generic statements, pressure."
    ),
    GenerationStyle.SHORT: (
        "Tone: Brief and efficient.\n"
        "Language: Minimal, direct, scannable.\n"
        "Structure: 1-2 sentences max, single point, simple next step.\n"
        "Avoid: Long paragraphs, multiple topics, pleasantries."
    ),
    GenerationStyle.DETAILED: (
        "Tone: Thorough and comprehensive.\n"
        "Language: Complete sentences, full context.\n"
        "Structure: Full context, detailed explanation, supporting points, clear next step.\n"
        "Avoid: Missing context, skipping steps, assumptions."
    ),
    GenerationStyle.PERSUASIVE: (
        "Tone: Confident and compelling.\n"
        "Language: Strong, benefit-driven.\n"
        "Structure: Hook, value proposition, proof points, call to action.\n"
        "Avoid: Aggressive pressure, exaggerated claims, dismissing concerns."
    ),
    GenerationStyle.NEUTRAL: (
        "Tone: Balanced and objective.\n"
        "Language: Factual, measured.\n"
        "Structure: Neutral opening, balanced information, open next step.\n"
        "Avoid: Overly positive or negative framing, pushing, assumptions."
    ),
}


def get_style_instructions(style: GenerationStyle) -> str:
    """Get instructions for the given style."""
    return STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS[GenerationStyle.PROFESSIONAL])


def list_styles() -> list[dict]:
    """List all available styles with descriptions."""
    descriptions = {
        GenerationStyle.PROFESSIONAL: "Polished and formal",
        GenerationStyle.FRIENDLY: "Warm and conversational",
        GenerationStyle.EXECUTIVE: "Direct and strategic",
        GenerationStyle.TECHNICAL: "Precise and detailed",
        GenerationStyle.CONSULTATIVE: "Advisory and insightful",
        GenerationStyle.SHORT: "Brief and scannable",
        GenerationStyle.DETAILED: "Thorough and comprehensive",
        GenerationStyle.PERSUASIVE: "Confident and compelling",
        GenerationStyle.NEUTRAL: "Balanced and objective",
    }
    return [
        {"id": s.value, "name": s.value.title(), "description": descriptions[s]}
        for s in GenerationStyle
    ]
