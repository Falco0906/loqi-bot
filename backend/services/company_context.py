"""Company context analysis.

Analyzes a company's maturity, growth signals, market position,
and potential pain areas from available intelligence data.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from services.ai import _send_openai_request, OpenAIError


COMPANY_MATURITIES = ["Startup", "Scale-up", "Enterprise", "Agency", "SMB"]


@dataclass
class CompanyContext:
    maturity: str
    growth_signals: list[str]
    technology_stack: list[str]
    business_model: str
    competitive_position: str
    potential_pain_areas: list[str]
    decision_urgency: str
    revenue_stage: str
    employee_count_range: str
    recent_developments: list[str]

    def to_dict(self) -> dict:
        return {
            "maturity": self.maturity,
            "growth_signals": self.growth_signals,
            "technology_stack": self.technology_stack,
            "business_model": self.business_model,
            "competitive_position": self.competitive_position,
            "potential_pain_areas": self.potential_pain_areas,
            "decision_urgency": self.decision_urgency,
            "revenue_stage": self.revenue_stage,
            "employee_count_range": self.employee_count_range,
            "recent_developments": self.recent_developments,
        }


def analyze_company(context: dict | None = None) -> CompanyContext:
    """Analyze company intelligence and produce a structured CompanyContext."""
    if not context:
        return _default()

    company = context.get("company", "")
    industry = context.get("industry", "")
    business_summary = context.get("business_summary", "")
    company_intel = context.get("company_intelligence", {})
    lead = context.get("lead", {})

    hints = []
    if company:
        hints.append(f"Company: {company}")
    if industry:
        hints.append(f"Industry: {industry}")
    if business_summary:
        hints.append(f"Business summary: {business_summary}")
    if company_intel:
        ci = company_intel
        if ci.get("company_summary"):
            hints.append(f"Company summary: {ci['company_summary']}")
        if ci.get("business_pain"):
            hints.append(f"Business pain: {ci['business_pain']}")
        if ci.get("growth"):
            hints.append(f"Growth: {ci['growth']}")
    if lead:
        lc = lead.get("company", "")
        if lc and lc != company:
            hints.append(f"Lead company: {lc}")

    if not hints:
        return _default()

    hint_text = "\n".join(hints)

    system_text = (
        "You are a B2B sales intelligence analyst. Analyze company information "
        "and return structured JSON about the company's context.\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "maturity": "Startup|Scale-up|Enterprise|Agency|SMB",\n'
        '  "growth_signals": ["hiring", "funding", "expansion", "product_launch", ...],\n'
        '  "technology_stack": ["technology observed or inferred"],\n'
        '  "business_model": "B2B SaaS|Agency|E-commerce|Enterprise|...",\n'
        '  "competitive_position": "market leader|challenger|niche|emerging|...",\n'
        '  "potential_pain_areas": ["pain area 1", "pain area 2", ...],\n'
        '  "decision_urgency": "immediate|short-term|medium-term|long-term|unknown",\n'
        '  "revenue_stage": "pre-revenue|seed|growth|scale|enterprise|unknown",\n'
        '  "employee_count_range": "1-10|11-50|51-200|201-1000|1000+|unknown",\n'
        '  "recent_developments": ["development 1", "development 2", ...]\n'
        "}\n"
        "Base maturity on employee count, funding stage, and market presence. "
        "Growth signals should only include signals that have evidence. "
        "Potential pain areas should be inferred from industry and business model. "
        "Decision urgency should reflect typical purchase cycles for the industry."
    )

    try:
        result = _send_openai_request(system_text, hint_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError):
        return _default()

    maturity = data.get("maturity", "unknown")
    if maturity not in COMPANY_MATURITIES:
        maturity = "unknown"

    return CompanyContext(
        maturity=maturity,
        growth_signals=data.get("growth_signals", []),
        technology_stack=data.get("technology_stack", []),
        business_model=data.get("business_model", "unknown"),
        competitive_position=data.get("competitive_position", "unknown"),
        potential_pain_areas=data.get("potential_pain_areas", []),
        decision_urgency=data.get("decision_urgency", "unknown"),
        revenue_stage=data.get("revenue_stage", "unknown"),
        employee_count_range=data.get("employee_count_range", "unknown"),
        recent_developments=data.get("recent_developments", []),
    )


def _default() -> CompanyContext:
    return CompanyContext(
        maturity="unknown",
        growth_signals=[],
        technology_stack=[],
        business_model="unknown",
        competitive_position="unknown",
        potential_pain_areas=[],
        decision_urgency="unknown",
        revenue_stage="unknown",
        employee_count_range="unknown",
        recent_developments=[],
    )
