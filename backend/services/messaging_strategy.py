"""Messaging angle selection.

Determines the strongest messaging strategy for a given buyer persona
and company context, with reasoning and rejected alternatives.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


MESSAGING_ANGLES = [
    "Cost reduction", "Revenue growth", "Automation", "Hiring efficiency",
    "Time savings", "Operational efficiency", "Competitive advantage",
    "Customer experience", "Risk reduction", "Developer productivity",
    "Expansion", "AI transformation", "Talent acquisition",
    "Process optimization", "Compliance", "Innovation",
]


@dataclass
class MessagingStrategy:
    primary_angle: str
    secondary_angle: str
    rejected_alternatives: list[str]
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "primary_angle": self.primary_angle,
            "secondary_angle": self.secondary_angle,
            "rejected_alternatives": self.rejected_alternatives,
            "reasoning": self.reasoning,
        }


def select_strategy(
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> MessagingStrategy:
    """Select the best messaging angle based on persona and company context."""
    hints = []
    if buyer_persona:
        hints.append(f"Buyer persona: {json.dumps(buyer_persona, indent=2)}")
    if company_context:
        hints.append(f"Company context: {json.dumps(company_context, indent=2)}")
    if context:
        company = context.get("company", "")
        industry = context.get("industry", "")
        if company:
            hints.append(f"Target company: {company}")
        if industry:
            hints.append(f"Industry: {industry}")
        if context.get("business_summary"):
            hints.append(f"Business summary: {context['business_summary']}")

    if not hints:
        return _default()

    hint_text = "\n".join(hints)
    angles_json = json.dumps(MESSAGING_ANGLES)

    system_text = (
        "You are a B2B messaging strategist. Based on buyer persona and company context, "
        "select the best messaging angle for cold outreach.\n\n"
        f"Available angles: {angles_json}\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "primary_angle": "chosen angle from list",\n'
        '  "secondary_angle": "alternative angle from list",\n'
        '  "rejected_alternatives": ["angle that was considered but rejected", ...],\n'
        '  "reasoning": "2-3 sentence explanation of why this angle fits the buyer and company"\n'
        "}\n\n"
        "Choose based on:\n"
        "- The buyer's role and what they care about (CTO → developer productivity/automation, CEO → revenue/cost, VP Sales → pipeline)\n"
        "- Company maturity (startup → speed/cost, enterprise → efficiency/compliance)\n"
        "- Growth signals (hiring → talent/efficiency, funding → expansion/scaling)\n"
        "- Industry context (specific pain points per vertical)\n"
        "Rejected alternatives must be angles that could seem relevant but are inferior for this specific combination."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default()

    primary = data.get("primary_angle", "")
    if primary not in MESSAGING_ANGLES:
        primary = _closest_angle(primary)

    secondary = data.get("secondary_angle", "")
    if secondary not in MESSAGING_ANGLES:
        secondary = _closest_angle(secondary)

    return MessagingStrategy(
        primary_angle=primary,
        secondary_angle=secondary,
        rejected_alternatives=data.get("rejected_alternatives", []),
        reasoning=data.get("reasoning", ""),
    )


def _closest_angle(name: str) -> str:
    lower = name.lower()
    for angle in MESSAGING_ANGLES:
        if angle.lower() == lower:
            return angle
    for angle in MESSAGING_ANGLES:
        if any(word in lower for word in angle.lower().split()):
            return angle
    return "Automation"


def _default() -> MessagingStrategy:
    return MessagingStrategy(
        primary_angle="Automation",
        secondary_angle="Time savings",
        rejected_alternatives=[],
        reasoning="Insufficient context to determine the optimal angle.",
    )
