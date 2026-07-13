"""Messaging framework selector.

Recommends which messaging framework (PAS, AIDA, BAB, etc.)
to use for a given buyer persona and company context.
Framework implementations are pluggable for future phases.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from services.ai import _send_openai_request, OpenAIError


FRAMEWORKS = {
    "PAS": "Problem-Agitate-Solve: identify a problem, agitate the pain, present the solution",
    "AIDA": "Attention-Interest-Desire-Action: grab attention, build interest, create desire, call to action",
    "BAB": "Before-After-Bridge: describe the current state, paint the desired future, show how to get there",
    "Jobs-to-be-Done": "Focus on the progress the customer wants to make in a specific circumstance",
    "SPIN": "Situation-Problem-Implication-Need-payoff: explore situation, uncover problem, imply consequences, show value",
    "Consultative": "Ask insightful questions, demonstrate expertise, propose tailored solution",
    "Founder-to-Founder": "Direct peer-level communication between founders, short and candid",
    "Executive Brief": "Concise, data-driven, focused on strategic outcomes and business impact",
    "Problem-Agitate-Solve": "Alternative PAS naming",
}


FRAMEWORK_HOOKS: list[Callable[[dict, dict], dict | None]] = []


def register_framework_hook(hook: Callable[[dict, dict], dict | None]) -> None:
    """Register a custom framework evaluator for future phases."""
    FRAMEWORK_HOOKS.append(hook)


@dataclass
class FrameworkRecommendation:
    framework: str
    reasoning: str
    alternatives: list[str]

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "reasoning": self.reasoning,
            "alternatives": self.alternatives,
        }


def select_framework(
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> FrameworkRecommendation:
    """Select the best messaging framework for this lead."""
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
    frameworks_text = "\n".join(f"- {k}: {v}" for k, v in FRAMEWORKS.items())

    system_text = (
        "You are a B2B messaging architect. Based on buyer persona and company context, "
        "recommend the best messaging framework for cold outreach.\n\n"
        f"Available frameworks:\n{frameworks_text}\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "framework": "chosen framework key",\n'
        '  "reasoning": "2-3 sentence explanation of why this framework fits",\n'
        '  "alternatives": ["alternative 1", "alternative 2"]\n'
        "}\n\n"
        "Choose based on:\n"
        "- Persona (executives → Executive Brief or PAS, technical → BAB or Consultative, founder → Founder-to-Founder)\n"
        "- Company maturity (startup → direct/founder, enterprise → structured/SPIN)\n"
        "- Industry (complex B2B → SPIN/Consultative, simple product → AIDA)\n"
        "- Relationship stage (cold → PAS/BAB, warm → Consultative/SPIN)\n"
        "Alternatives should be frameworks that could also work well."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default()

    framework = data.get("framework", "PAS")
    if framework not in FRAMEWORKS:
        normalized = framework.replace("-", " ").lower().strip()
        for k in FRAMEWORKS:
            if k.replace("-", " ").lower() == normalized or normalized in k.lower():
                framework = k
                break
        else:
            framework = "PAS"

    return FrameworkRecommendation(
        framework=framework,
        reasoning=data.get("reasoning", ""),
        alternatives=data.get("alternatives", []),
    )


def _default() -> FrameworkRecommendation:
    return FrameworkRecommendation(
        framework="PAS",
        reasoning="Insufficient context to determine optimal framework.",
        alternatives=[],
    )
