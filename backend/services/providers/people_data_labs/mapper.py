from __future__ import annotations

from typing import Any

from services.providers.models import (
    ProviderCompany,
    ProviderContact,
    ProviderContactRole,
    ProviderLead,
    GrowthStage,
)


class PDLMapper:
    """Maps raw People Data Labs API responses to normalized domain models.

    PDL person schema → ProviderContact + ProviderLead
    PDL company schema → ProviderCompany
    """

    @staticmethod
    def person_to_contact(
        raw: dict[str, Any],
        provider_id: str = "people_data_labs",
    ) -> ProviderContact:
        name_data = raw.get("name", {}) or {}
        first_name = name_data.get("first", "")
        last_name = name_data.get("last", "")
        title = raw.get("job_title", raw.get("employment", {}).get("title", ""))
        email = PDLMapper._pick_email(raw.get("email_addresses", []))
        phone = PDLMapper._pick_phone(raw.get("phone_numbers", []))

        linkedin_url = ""
        for profile in raw.get("profiles", []):
            url = profile.get("url", "")
            if "linkedin.com" in url:
                linkedin_url = url
                break

        role = ProviderContactRole.UNKNOWN
        raw_role = (title or "").lower()
        if any(kw in raw_role for kw in ("ceo", "cto", "cfo", "cmo", "coo", "cio", "founder", "owner", "president", "vp", "vice president", "director", "head", "chief")):
            role = ProviderContactRole.DECISION_MAKER
        elif any(kw in raw_role for kw in ("manager", "lead", "senior")):
            role = ProviderContactRole.INFLUENCER

        return ProviderContact(
            first_name=first_name,
            last_name=last_name,
            title=title,
            email=email,
            linkedin_url=linkedin_url,
            phone=phone,
            role=role,
            provider_id=provider_id,
            external_id=raw.get("id", ""),
            metadata={"pdl_likelihood": raw.get("likelihood", 0)},
        )

    @staticmethod
    def person_to_company(
        raw: dict[str, Any],
        provider_id: str = "people_data_labs",
    ) -> ProviderCompany:
        emp = raw.get("employment", {}) or {}

        industry_name = ""
        industries = raw.get("industry", [])
        if isinstance(industries, list) and industries:
            industry_name = industries[0]
        elif isinstance(industries, str):
            industry_name = industries

        return ProviderCompany(
            name=emp.get("company", ""),
            industry=industry_name,
            description=emp.get("company_description", ""),
            website=emp.get("company_website", ""),
            employees=emp.get("company_size", 0) or 0,
            linkedin_url=emp.get("company_linkedin_url", ""),
            provider_id=provider_id,
        )

    @staticmethod
    def person_to_lead(
        raw: dict[str, Any],
        provider_id: str = "people_data_labs",
    ) -> ProviderLead:
        contact = PDLMapper.person_to_contact(raw, provider_id)
        company = PDLMapper.person_to_company(raw, provider_id)
        return ProviderLead(
            contact=contact,
            company=company,
            score=raw.get("likelihood", 0) / 10.0,
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )

    @staticmethod
    def company_to_company(
        raw: dict[str, Any],
        provider_id: str = "people_data_labs",
    ) -> ProviderCompany:
        growth_stage = PDLMapper._map_growth_stage(raw.get("growth_stage", ""))

        return ProviderCompany(
            name=raw.get("name", ""),
            industry=raw.get("industry", ""),
            sub_industry=raw.get("sub_industry", ""),
            description=raw.get("summary", raw.get("description", "")),
            website=raw.get("website", ""),
            city=raw.get("location", {}).get("locality", ""),
            country=raw.get("location", {}).get("country", ""),
            employees=raw.get("size", raw.get("employee_count", 0)) or 0,
            founded=raw.get("founded", 0) or 0,
            growth_stage=growth_stage,
            revenue_band=raw.get("revenue", {}).get("amount", ""),
            technologies=raw.get("technologies", []),
            linkedin_url=raw.get("linkedin_url", ""),
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )

    @staticmethod
    def _pick_email(email_addresses: list[dict[str, Any]]) -> str:
        for addr in email_addresses:
            if addr.get("type") in ("work", "personal"):
                return addr.get("address", "")
        if email_addresses:
            return email_addresses[0].get("address", "")
        return ""

    @staticmethod
    def _pick_phone(phone_numbers: list[dict[str, Any]]) -> str:
        for num in phone_numbers:
            if num.get("type") in ("work", "mobile"):
                return num.get("number", "")
        if phone_numbers:
            return phone_numbers[0].get("number", "")
        return ""

    @staticmethod
    def _map_growth_stage(stage: str) -> str:
        if not stage:
            return ""
        stage_lower = stage.lower()
        mapping = {
            "startup": "startup",
            "early stage": "startup",
            "series a": "series_a",
            "series b": "series_b",
            "series c": "series_c",
            "public": "public",
            "bootstrapped": "bootstrapped",
        }
        for k, v in mapping.items():
            if k in stage_lower:
                return v
        return ""
