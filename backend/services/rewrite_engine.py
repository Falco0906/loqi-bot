"""Strategy-aware rewrite engine.

Executes rewrites that preserve key elements (personalization, pain alignment, CTA)
and produces structured change summaries instead of chat.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


REWRITE_STRATEGIES = {
    "shorten": "Make the message shorter and more concise while preserving personalization, pain point, and CTA.",
    "lengthen": "Expand the message with more detail while keeping the same core message and CTA.",
    "professional": "Make the tone more professional and polished. Remove casual language.",
    "casual": "Make the tone more casual and conversational. Less formal.",
    "hiring": "If relevant, mention that we are hiring or growing the team as a credibility signal.",
    "expansion": "Mention company expansion, growth, or new developments as context.",
    "rewrite_cta": "Rewrite the call to action to be more compelling and specific. Make it a low-friction ask.",
    "mention_funding": "If appropriate, mention recent funding or investment as social proof.",
    "mention_hiring": "If appropriate, mention team growth or hiring activity.",
    "mention_growth": "If appropriate, mention company growth metrics or momentum.",
    "mention_product_launch": "If appropriate, mention a new product or feature launch.",
    "personalize": "Increase the level of personalization. Reference specific details about the recipient.",
    "aggressive": "Make the CTA more direct and time-sensitive.",
    "softer": "Soften the ask. Make the CTA feel like a lower commitment.",
}


CONFIDENCE_LABELS = {
    "high": "High confidence",
    "medium": "Medium confidence",
    "low": "Low confidence",
}


@dataclass
class RewriteResult:
    text: str
    change_summary: list[str]
    confidence: str = "medium"


def _build_context_block(context: dict | None) -> str:
    if not context:
        return ""
    parts = []
    for key, label in [
        ("company", "Target company"),
        ("contact", "Contact name"),
        ("role", "Contact role"),
        ("industry", "Industry"),
        ("campaign_name", "Campaign"),
        ("messaging_angle", "Messaging angle"),
        ("business_summary", "Business summary"),
    ]:
        val = context.get(key)
        if val:
            parts.append(f"{label}: {val}")
    return "\n".join(parts) + "\n\n" if parts else ""


def execute_rewrite(
    text: str,
    strategy: str,
    context: dict | None = None,
    custom_instruction: str | None = None,
) -> RewriteResult:
    """Execute a strategy-aware rewrite.

    Args:
        text: The current draft text.
        strategy: One of REWRITE_STRATEGIES keys, or "custom".
        context: Optional context about the lead/campaign.
        custom_instruction: If strategy is "custom", use this instruction instead.

    Returns:
        RewriteResult with rewritten text, change summary, and confidence.
    """
    context_block = _build_context_block(context)

    if strategy == "custom" and custom_instruction:
        instruction = custom_instruction
    else:
        instruction = REWRITE_STRATEGIES.get(strategy, f"Rewrite: {strategy}")

    system_text = (
        "You are an expert SDR manager and cold email copywriter. "
        "You rewrite outreach messages strategically — preserving what works, "
        "fixing what doesn't, and always keeping personalization, pain alignment, "
        "and CTA intact.\n\n"
        "Preservation rules (do not violate these):\n"
        "- Preserve the buyer name, company, and role — do NOT remove personalization\n"
        "- Preserve the core pain point and value proposition\n"
        "- Preserve or improve the CTA — never remove it or change the fundamental ask type\n"
        "- Preserve company facts and industry context from the original\n"
        "- If a rewrite would weaken personalization, rewrite surrounding language instead\n\n"
        "Rules:\n"
        "- Keep the email a cold outreach message — do not turn it into a newsletter or article\n"
        "- Return ONLY the rewritten message — no explanation, no prefix, no markdown\n"
        "- After the rewritten message, add a separator line '---CHANGES---' followed by a bullet list "
        "of 2-5 concrete, specific changes made. Each bullet should start with a ✓ and describe exactly what changed.\n"
        "- Then add '---CONFIDENCE---' followed by one of: high, medium, or low\n"
        "  - high: instruction was clear, draft had room for improvement\n"
        "  - medium: instruction was somewhat ambiguous or draft was already strong\n"
        "  - low: instruction was vague or would conflict with preservation rules\n\n"
        "Example:\n"
        "New draft text here...\n"
        "---CHANGES---\n"
        "✓ Personalized opening with recipient name and company\n"
        "✓ CTA softened from 'book a demo' to 'quick chat'\n"
        "✓ Removed repetition of value prop in paragraph two\n"
        "✓ Reduced length from 120 to 85 words\n"
        "---CONFIDENCE---\n"
        "high"
    )

    user_text = (
        f"{context_block}"
        f"Instruction: {instruction}\n\n"
        f"Current message:\n\n{text}\n\n"
        "Rewrite the message following the instruction. Return the new text followed by ---CHANGES--- and ---CONFIDENCE---."
    )

    try:
        result = _send_openai_request(system_text, user_text)
    except OpenAIError as e:
        raise OpenAIError(f"Rewrite failed: {e}")

    if not result or not result.strip():
        raise OpenAIError("Rewrite produced empty output")

    confidence = _extract_confidence(result)
    change_summary = _extract_change_summary(result)
    clean_text = _extract_clean_text(result, text)

    return RewriteResult(
        text=clean_text,
        change_summary=change_summary,
        confidence=confidence,
    )


def _extract_change_summary(response: str) -> list[str]:
    """Extract change bullet points from the response."""
    if "---CHANGES---" not in response:
        return ["✓ Rewritten"]
    parts = response.split("---CHANGES---", 1)
    changes_section = parts[1]
    if "---CONFIDENCE---" in changes_section:
        changes_section = changes_section.split("---CONFIDENCE---", 1)[0]
    changes_section = changes_section.strip()
    bullets = re.findall(r'[✓\-*]\s*(.+?)$', changes_section, re.MULTILINE)
    return [b.strip() for b in bullets if b.strip()]


def _extract_confidence(response: str) -> str:
    """Extract rewrite confidence from the response."""
    if "---CONFIDENCE---" in response:
        parts = response.split("---CONFIDENCE---", 1)
        confidence_raw = parts[1].strip().lower()
        if confidence_raw in ("high", "medium", "low"):
            return confidence_raw
    return "medium"


def _extract_clean_text(response: str, original: str) -> str:
    """Extract the clean rewritten text from the response."""
    clean = response
    if "---CHANGES---" in clean:
        clean = clean.split("---CHANGES---", 1)[0]
    if "---CONFIDENCE---" in clean:
        clean = clean.split("---CONFIDENCE---", 1)[0]
    return clean.strip() if clean.strip() else original
