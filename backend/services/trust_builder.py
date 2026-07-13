"""Trust builder engine.

Identifies missing credibility elements in a draft and suggests
specific additions that would increase trust for this buyer persona.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


TRUST_ELEMENT_TYPES = [
    "Customer story", "Metric", "Case study", "Industry statistic",
    "Social proof", "Funding reference", "Hiring observation",
    "Mutual connection", "Technology familiarity",
    "Personalized observation", "Award or recognition",
    "Media mention", "Partner reference", "Open source contribution",
]


@dataclass
class TrustSuggestion:
    element_type: str
    suggestion: str
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "element_type": self.element_type,
            "suggestion": self.suggestion,
            "reasoning": self.reasoning,
        }


def suggest_trust_builders(
    draft_text: str,
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> list[TrustSuggestion]:
    """Suggest trust-building elements that are missing from the draft."""
    hints = []
    if buyer_persona:
        hints.append(f"Buyer persona: {json.dumps(buyer_persona, indent=2)}")
    if company_context:
        hints.append(f"Company context: {json.dumps(company_context, indent=2)}")
    if context:
        for key in ("company", "industry", "business_summary", "messaging_angle"):
            val = context.get(key)
            if val:
                hints.append(f"{key}: {val}")

    if not hints:
        return []

    hint_text = "\n".join(hints) + f"\n\nCurrent draft:\n{draft_text[:500]}" if hints else f"Current draft:\n{draft_text[:500]}"
    types_json = json.dumps(TRUST_ELEMENT_TYPES)

    system_text = (
        "You are a B2B credibility analyst. Review the cold outreach draft and "
        "suggest the top 2-3 trust-building elements that are missing.\n\n"
        f"Available types: {types_json}\n\n"
        "Return ONLY valid JSON array with this structure:\n"
        "[\n"
        "  {\n"
        '    "element_type": "type from list",\n'
        '    "suggestion": "specific text or reference to add",\n'
        '    "reasoning": "why this would increase trust for this specific buyer/company"\n'
        "  }\n"
        "]\n\n"
        "Consider:\n"
        "- What type of proof would resonate with this persona (CTO → technical credibility, CEO → business results)\n"
        "- What's missing from the current draft\n"
        "- What signals the company context provides (funding → mention it, hiring → mention team growth)\n"
        "Only suggest elements that are realistic and evidence-based."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
        if not isinstance(data, list):
            data = [data]
    except (OpenAIError, json.JSONDecodeError):
        return []

    return [
        TrustSuggestion(
            element_type=item.get("element_type", "Social proof"),
            suggestion=item.get("suggestion", ""),
            reasoning=item.get("reasoning", ""),
        )
        for item in data[:3]
    ]
