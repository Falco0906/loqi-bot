"""CTA strategy engine.

Recommends the optimal CTA type based on buyer persona,
company context, and relationship stage.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


CTA_TYPES = [
    "15-minute call", "Quick question", "Resource share", "Demo",
    "Audit", "Loom video", "Reply with yes/no", "Referral",
    "Warm introduction", "Discussion", "Brief call", "Coffee meeting",
    "Content preview", "Question for advice",
]


@dataclass
class CTARecommendation:
    cta_type: str
    reasoning: str
    alternative: str

    def to_dict(self) -> dict:
        return {
            "cta_type": self.cta_type,
            "reasoning": self.reasoning,
            "alternative": self.alternative,
        }


def recommend_cta(
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> CTARecommendation:
    """Recommend the best CTA type for this lead."""
    hints = []
    if buyer_persona:
        hints.append(f"Buyer persona: {json.dumps(buyer_persona, indent=2)}")
    if company_context:
        hints.append(f"Company context: {json.dumps(company_context, indent=2)}")
    if context:
        for key in ("company", "industry", "role", "contact"):
            val = context.get(key)
            if val:
                hints.append(f"{key}: {val}")

    if not hints:
        return _default()

    hint_text = "\n".join(hints)
    types_json = json.dumps(CTA_TYPES)

    system_text = (
        "You are a B2B CTA strategist. Based on buyer persona and company context, "
        "recommend the optimal call-to-action type for cold outreach.\n\n"
        f"Available types: {types_json}\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "cta_type": "chosen type from list",\n'
        '  "reasoning": "2-3 sentence explanation of why this CTA type fits",\n'
        '  "alternative": "a different CTA type as backup"\n'
        "}\n\n"
        "Choose based on:\n"
        "- Persona (CEO → brief strategic discussion, CTO → technical resource or audit, VP Sales → quick question)\n"
        "- Seniority (C-level → low-friction asks, IC → more specific/value-forward)\n"
        "- Company maturity (startup → direct call, enterprise → softer ask like resource share)\n"
        "- Risk tolerance (low → educational/resource, high → direct meeting request)\n"
        "- Authority level (budget owner → direct, influencer → educational/value-first)"
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default()

    return CTARecommendation(
        cta_type=data.get("cta_type", "Quick question"),
        reasoning=data.get("reasoning", ""),
        alternative=data.get("alternative", "Brief call"),
    )


def _default() -> CTARecommendation:
    return CTARecommendation(
        cta_type="Quick question",
        reasoning="Insufficient context to determine optimal CTA.",
        alternative="Brief call",
    )
