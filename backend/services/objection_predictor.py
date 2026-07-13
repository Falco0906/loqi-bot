"""Objection prediction engine.

Predicts likely objections a recipient would raise,
with likelihood estimation and suggested responses.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


COMMON_OBJECTIONS = [
    "Already using another tool",
    "No budget",
    "No time",
    "Need approval",
    "Too risky",
    "Not relevant",
    "Already solved",
    "No hiring plans",
    "Too early",
    "Need ROI proof",
    "Happy with current solution",
    "Not a priority",
    "Too expensive",
    "Don't see the value",
    "Need to evaluate more",
    "Wrong timing",
    "Need case studies",
]


@dataclass
class ObjectionPrediction:
    objection: str
    likelihood: str
    reason: str
    suggested_response: str

    def to_dict(self) -> dict:
        return {
            "objection": self.objection,
            "likelihood": self.likelihood,
            "reason": self.reason,
            "suggested_response": self.suggested_response,
        }


def predict_objections(
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
    context: dict | None = None,
) -> list[ObjectionPrediction]:
    """Predict the most likely objections for this lead."""
    hints = []
    if buyer_persona:
        hints.append(f"Buyer persona: {json.dumps(buyer_persona, indent=2)}")
    if company_context:
        hints.append(f"Company context: {json.dumps(company_context, indent=2)}")
    if context:
        for key in ("company", "industry", "business_summary", "role", "contact"):
            val = context.get(key)
            if val:
                hints.append(f"{key}: {val}")

    if not hints:
        return []

    hint_text = "\n".join(hints)
    objections_json = json.dumps(COMMON_OBJECTIONS)

    system_text = (
        "You are a B2B sales objection analyst. Based on the buyer persona and company context, "
        "predict the top 3 most likely objections this lead would raise.\n\n"
        f"Available objections: {objections_json}\n\n"
        "Return ONLY valid JSON array with this structure:\n"
        "[\n"
        "  {\n"
        '    "objection": "objection text",\n'
        '    "likelihood": "high|medium|low",\n'
        '    "reason": "why this objection is likely for this specific buyer/company",\n'
        '    "suggested_response": "a short, concrete way to address this in outreach"\n'
        "  }\n"
        "]\n\n"
        "Predictions should be specific to the persona and company maturity. "
        "A startup CEO is unlikely to say 'need approval' but may say 'too early'. "
        "An enterprise CTO is likely to say 'already using another tool' or 'too risky'. "
        "Base likelihood on the persona's authority level, risk tolerance, and company maturity."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
        if not isinstance(data, list):
            data = data.get("objections", [data])
    except (OpenAIError, json.JSONDecodeError):
        return []

    predictions = []
    for item in data[:3]:
        predictions.append(ObjectionPrediction(
            objection=item.get("objection", "Unknown objection"),
            likelihood=item.get("likelihood", "medium"),
            reason=item.get("reason", ""),
            suggested_response=item.get("suggested_response", ""),
        ))

    return predictions
