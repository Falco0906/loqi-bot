"""Strategy comparison engine.

Compares two messaging approaches and produces a structured comparison
with expected strengths, weaknesses, confidence, and recommendation.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


@dataclass
class StrategyComparison:
    current_strengths: list[str]
    current_weaknesses: list[str]
    alternative_strengths: list[str]
    alternative_weaknesses: list[str]
    confidence: str
    recommendation: str
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "current_strengths": self.current_strengths,
            "current_weaknesses": self.current_weaknesses,
            "alternative_strengths": self.alternative_strengths,
            "alternative_weaknesses": self.alternative_weaknesses,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
        }


def compare_strategies(
    current_angle: str,
    alternative_angle: str,
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> StrategyComparison:
    """Compare two messaging angles for a given lead.

    Args:
        current_angle: The current messaging angle being used.
        alternative_angle: An alternative messaging angle to compare.
        buyer_persona: Structured buyer persona data.
        company_context: Structured company context data.
        context: Raw context dict.

    Returns:
        StrategyComparison with structured evaluation.
    """
    hints = []
    hints.append(f"Current angle: {current_angle}")
    hints.append(f"Alternative angle: {alternative_angle}")
    if buyer_persona:
        hints.append(f"Buyer persona: {json.dumps(buyer_persona, indent=2)}")
    if company_context:
        hints.append(f"Company context: {json.dumps(company_context, indent=2)}")
    if context:
        for key in ("company", "industry", "role", "contact", "business_summary"):
            val = context.get(key)
            if val:
                hints.append(f"{key}: {val}")

    hint_text = "\n".join(hints)

    system_text = (
        "You are a B2B messaging strategist. Compare two messaging angles for a specific "
        "buyer persona and company context, and recommend which to use.\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "current_strengths": ["strength 1", "strength 2", ...],\n'
        '  "current_weaknesses": ["weakness 1", "weakness 2", ...],\n'
        '  "alternative_strengths": ["strength 1", "strength 2", ...],\n'
        '  "alternative_weaknesses": ["weakness 1", "weakness 2", ...],\n'
        '  "confidence": "high|medium|low",\n'
        '  "recommendation": "current|alternative|hybrid",\n'
        '  "reasoning": "3-4 sentence explanation of the comparison and recommendation"\n'
        "}\n\n"
        "Evaluate based on:\n"
        "- How well each angle aligns with the buyer's primary goals and fears\n"
        "- How relevant each angle is to the company's maturity and pain areas\n"
        "- Which angle would generate a stronger response\n"
        "- Any risks or downsides to each approach\n"
        "The recommendation should be 'current' if the current angle is clearly superior, "
        "'alternative' if switching would be better, or 'hybrid' if combining both would work."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default(current_angle, alternative_angle)

    return StrategyComparison(
        current_strengths=data.get("current_strengths", []),
        current_weaknesses=data.get("current_weaknesses", []),
        alternative_strengths=data.get("alternative_strengths", []),
        alternative_weaknesses=data.get("alternative_weaknesses", []),
        confidence=data.get("confidence", "medium"),
        recommendation=data.get("recommendation", "current"),
        reasoning=data.get("reasoning", ""),
    )


def _default(current: str, alternative: str) -> StrategyComparison:
    return StrategyComparison(
        current_strengths=[],
        current_weaknesses=[],
        alternative_strengths=[],
        alternative_weaknesses=[],
        confidence="medium",
        recommendation="current",
        reasoning=f"Insufficient context to compare {current} vs {alternative}.",
    )
