from .base_enricher import BaseEnricher


def _log(message: str) -> None:
    print(f"[synthetic_enricher] {message}")


def _has_value(val) -> bool:
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return bool(val)
    return bool(val)


def _confidence_from_lead(lead: dict) -> int:
    """Estimate confidence score (0-100) based on data completeness.

    Handles both canonical lead keys (company_description) and
    raw company keys (description) interchangeably.
    """
    fields = [
        _has_value(lead.get("company_description") or lead.get("description")),
        _has_value(lead.get("pain_points")),
        _has_value(lead.get("buying_signals")),
        _has_value(lead.get("recent_events")),
        _has_value(lead.get("company_technology") or lead.get("technology")),
        _has_value(lead.get("company_growth_stage") or lead.get("growth_stage")),
        _has_value(lead.get("company_revenue_band") or lead.get("revenue_band")),
        _has_value(lead.get("company_employees") or lead.get("employees")),
        _has_value(lead.get("company_founded") or lead.get("founded")),
        _has_value(lead.get("title")),
    ]
    filled = sum(fields)
    base = int((filled / len(fields)) * 80) + 10
    return min(base + 5, 100)


def _truncate(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


class SyntheticEnricher(BaseEnricher):
    """Enricher backed by existing synthetic company data.

    Reads fields already present in the canonical lead schema —
    company_description, pain_points, buying_signals, technology_stack,
    growth_stage, etc. — and builds structured intelligence from them.
    No external API calls.
    """

    @property
    def capabilities(self) -> dict:
        return {
            "supports_company_enrichment": True,
            "supports_lead_enrichment": True,
            "uses_ai": False,
        }

    def health_check(self) -> dict:
        return {"ok": True, "provider": "synthetic"}

    def enrich_company(self, company: dict) -> dict:
        name = (company.get("name") or "Unknown Company").strip()
        industry = (company.get("industry") or "").strip()
        sub_industry = (company.get("sub_industry") or "").strip()
        description = (company.get("description") or "").strip()
        employees = company.get("employees", 0) or 0
        locations = company.get("locations", 0) or 0
        founded = company.get("founded", 0) or 0
        growth_stage = (company.get("growth_stage") or "").strip()
        revenue_band = (company.get("revenue_band") or "").strip()
        technology = company.get("technology") or {}
        pain_points = company.get("pain_points") or []
        buying_signals = company.get("buying_signals") or []
        recent_events = company.get("recent_events") or []

        industry_label = f"{industry}" + (f" ({sub_industry})" if sub_industry else "")
        tech_summary = ", ".join(technology.get("tools", [])) if isinstance(technology, dict) else str(technology)

        summary_parts = [f"{name} is a {industry_label}"]
        if description:
            summary_parts.append(f". {_truncate(description, 300)}")
        if employees:
            summary_parts.append(f" It employs approximately {employees} people")
        if locations:
            summary_parts.append(f" across {locations} location{'s' if locations != 1 else ''}")
        company_summary = "".join(summary_parts) + "."

        growth_parts = []
        if growth_stage:
            growth_parts.append(f"Growth stage: {growth_stage}")
        if revenue_band:
            growth_parts.append(f"Revenue: {revenue_band}")
        if employees:
            growth_parts.append(f"Team size: {employees}" + (f" (founded {founded})" if founded else ""))
        growth_summary = " | ".join(growth_parts) if growth_parts else "Limited growth data available."

        return {
            "company_summary": company_summary,
            "recommended_pitch_angle": self._recommend_pitch(name, industry, pain_points, buying_signals),
            "business_pain_summary": self._pain_summary(pain_points, description),
            "technology_summary": tech_summary if tech_summary else "No technology data available.",
            "growth_summary": growth_summary,
            "decision_context": "No specific decision context — enrich a lead for per-role context.",
            "buying_signal_summary": self._signal_summary(buying_signals),
            "recent_events_summary": self._events_summary(recent_events),
            "qualification_reason": "Company-level enrichment — use enrich_lead for per-lead qualification context.",
            "confidence_score": _confidence_from_lead(company),
            "provider": "synthetic",
        }

    def enrich_lead(self, lead: dict) -> dict:
        name = (lead.get("company") or "Unknown Company").strip()
        industry = (lead.get("company_industry") or "").strip()
        sub_industry = (lead.get("company_sub_industry") or "").strip()
        description = (lead.get("company_description") or "").strip()
        employees = lead.get("company_employees", 0) or 0
        locations = lead.get("company_locations", 0) or 0
        founded = lead.get("company_founded", 0) or 0
        growth_stage = (lead.get("company_growth_stage") or "").strip()
        revenue_band = (lead.get("company_revenue_band") or "").strip()
        technology = lead.get("company_technology") or {}
        pain_points = lead.get("pain_points") or []
        buying_signals = lead.get("buying_signals") or []
        recent_events = lead.get("recent_events") or []
        title = (lead.get("title") or "").strip()
        role_summary = f"Decision maker role: {title}" if title else ""

        industry_label = f"{industry}" + (f" ({sub_industry})" if sub_industry else "")
        tech_summary = ", ".join(technology.get("tools", [])) if isinstance(technology, dict) else str(technology)

        summary_parts = [f"{name} is a {industry_label}"]
        if description:
            summary_parts.append(f". {_truncate(description, 300)}")
        if employees:
            summary_parts.append(f" It employs approximately {employees} people")
        if locations:
            summary_parts.append(f" across {locations} location{'s' if locations != 1 else ''}")
        company_summary = "".join(summary_parts) + "."

        growth_parts = []
        if growth_stage:
            growth_parts.append(f"Growth stage: {growth_stage}")
        if revenue_band:
            growth_parts.append(f"Revenue: {revenue_band}")
        if employees:
            growth_parts.append(f"Team size: {employees}" + (f" (founded {founded})" if founded else ""))
        growth_summary = " | ".join(growth_parts) if growth_parts else "Limited growth data available."

        return {
            "company_summary": company_summary,
            "recommended_pitch_angle": self._recommend_pitch(name, industry, pain_points, buying_signals),
            "business_pain_summary": self._pain_summary(pain_points, description),
            "technology_summary": tech_summary if tech_summary else "No technology data available.",
            "growth_summary": growth_summary,
            "decision_context": role_summary,
            "buying_signal_summary": self._signal_summary(buying_signals),
            "recent_events_summary": self._events_summary(recent_events),
            "qualification_reason": self._qualification_reason(title, industry, pain_points),
            "confidence_score": _confidence_from_lead(lead),
            "provider": "synthetic",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _recommend_pitch(self, company: str, industry: str, pain_points: list, buying_signals: list) -> str:
        """Recommend what angle the AI should lead with."""
        if pain_points:
            top = pain_points[0]
            return f"Lead with how your solution addresses '{top}', which directly relates to {company}'s current challenges in the {industry or 'industry'} space."
        if buying_signals:
            signal = buying_signals[0]
            return f"Reference '{signal}' as a timely reason to connect with {company}."
        return f"Position your solution as a way to help {company} modernize operations in {industry or 'their industry'}."

    def _pain_summary(self, pain_points: list, description: str) -> str:
        if pain_points:
            bullets = "\n".join(f"  - {p}" for p in pain_points)
            desc_note = ""
            if description:
                desc_note = f" Context: {_truncate(description, 200)}"
            return f"Key pain points identified:\n{bullets}\n{desc_note}".strip()
        return "No specific pain points identified in available data."

    def _signal_summary(self, buying_signals: list) -> str:
        if buying_signals:
            bullets = "\n".join(f"  - {s}" for s in buying_signals)
            return f"Active buying signals detected:\n{bullets}"
        return "No buying signals detected in available data."

    def _events_summary(self, recent_events: list) -> str:
        if recent_events:
            bullets = "\n".join(f"  - {e}" for e in recent_events)
            return f"Recent notable events:\n{bullets}"
        return "No recent events in available data."

    def _qualification_reason(self, title: str, industry: str, pain_points: list) -> str:
        reasons = []
        if title:
            reasons.append(f"decision maker holds '{title}' role")
        if industry:
            reasons.append(f"operates in {industry}")
        if pain_points:
            reasons.append(f"faces relevant challenges ({pain_points[0]})")
        if not reasons:
            return "Qualified based on available firmographic data."
        return "Qualified because the " + ", ".join(reasons) + "."
