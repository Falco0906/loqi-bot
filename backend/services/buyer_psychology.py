"""Buyer persona analysis.

Analyzes a lead's role, seniority, and context to produce
a structured BuyerPersona with goals, fears, motivations, etc.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


PERSONA_ROLES = [
    "CEO", "CTO", "VP Engineering", "Head of Sales", "Marketing Director",
    "HR", "Operations", "Founder", "Product Manager", "Finance",
    "VP Product", "Head of Growth", "Engineering Manager", "Sales Director",
    "Head of People", "Chief Revenue Officer", "Chief Marketing Officer",
]


@dataclass
class BuyerPersona:
    role: str
    seniority: str
    primary_goals: list[str]
    primary_fears: list[str]
    decision_criteria: list[str]
    buying_motivations: list[str]
    likely_objections: list[str]
    communication_preferences: list[str]
    preferred_cta_style: str
    risk_tolerance: str
    time_sensitivity: str
    authority_level: str

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "seniority": self.seniority,
            "primary_goals": self.primary_goals,
            "primary_fears": self.primary_fears,
            "decision_criteria": self.decision_criteria,
            "buying_motivations": self.buying_motivations,
            "likely_objections": self.likely_objections,
            "communication_preferences": self.communication_preferences,
            "preferred_cta_style": self.preferred_cta_style,
            "risk_tolerance": self.risk_tolerance,
            "time_sensitivity": self.time_sensitivity,
            "authority_level": self.authority_level,
        }


def analyze_buyer(context: dict | None = None) -> BuyerPersona:
    """Analyze lead context and produce a structured BuyerPersona."""
    if not context:
        return _default()

    lead = context.get("lead", {})
    contact = context.get("contact", "") or lead.get("name", "")
    role = context.get("role", "") or lead.get("title", "")
    company = context.get("company", "") or lead.get("company", "")
    industry = context.get("industry", "")

    hints = []
    if role:
        hints.append(f"Role/Title: {role}")
    if company:
        hints.append(f"Company: {company}")
    if industry:
        hints.append(f"Industry: {industry}")
    if contact:
        hints.append(f"Contact: {contact}")

    if not hints:
        return _default()

    hint_text = "\n".join(hints)

    system_text = (
        "You are a B2B buyer psychology analyst. Based on the role and context, "
        "infer the buyer persona and return structured JSON.\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "role": "CEO|CTO|VP Engineering|...",\n'
        '  "seniority": "C-level|VP|Director|Manager|IC|founder",\n'
        '  "primary_goals": ["goal 1", "goal 2", "goal 3"],\n'
        '  "primary_fears": ["fear 1", "fear 2"],\n'
        '  "decision_criteria": ["criterion 1", "criterion 2", "criterion 3"],\n'
        '  "buying_motivations": ["motivation 1", "motivation 2"],\n'
        '  "likely_objections": ["objection 1", "objection 2"],\n'
        '  "communication_preferences": ["preference 1", "preference 2"],\n'
        '  "preferred_cta_style": "direct|consultative|low-friction|value-first|referral|educational",\n'
        '  "risk_tolerance": "low|medium|high",\n'
        '  "time_sensitivity": "low|medium|high",\n'
        '  "authority_level": "budget_owner|influencer|evaluator|champion|end_user"\n'
        "}\n\n"
        "Base the persona on known patterns for this role and industry. "
        "A CTO cares about technical fit, scalability, and engineering productivity. "
        "A CEO cares about revenue, growth, and strategic advantage. "
        "A VP Sales cares about pipeline, conversion, and team efficiency. "
        "An HR leader cares about culture, retention, and process. "
        "A founder cares about speed, cost, and product-market fit."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default()

    return BuyerPersona(
        role=data.get("role", "unknown"),
        seniority=data.get("seniority", "unknown"),
        primary_goals=data.get("primary_goals", []),
        primary_fears=data.get("primary_fears", []),
        decision_criteria=data.get("decision_criteria", []),
        buying_motivations=data.get("buying_motivations", []),
        likely_objections=data.get("likely_objections", []),
        communication_preferences=data.get("communication_preferences", []),
        preferred_cta_style=data.get("preferred_cta_style", "consultative"),
        risk_tolerance=data.get("risk_tolerance", "medium"),
        time_sensitivity=data.get("time_sensitivity", "medium"),
        authority_level=data.get("authority_level", "influencer"),
    )


def _default() -> BuyerPersona:
    return BuyerPersona(
        role="unknown",
        seniority="unknown",
        primary_goals=[],
        primary_fears=[],
        decision_criteria=[],
        buying_motivations=[],
        likely_objections=[],
        communication_preferences=[],
        preferred_cta_style="consultative",
        risk_tolerance="medium",
        time_sensitivity="medium",
        authority_level="influencer",
    )
