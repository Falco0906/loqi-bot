from __future__ import annotations

import re
from typing import Any

from services.providers.models import ProviderContact, ProviderCompany, ProviderContactRole


class LinkedInMapper:
    """Maps LinkedIn URL patterns and metadata to normalized domain models.

    No scraping. No policy bypass. Only parses public URL patterns
    and structured metadata that users explicitly provide.
    """

    PROFILE_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)/?"
    )
    COMPANY_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?linkedin\.com/company/([a-zA-Z0-9_-]+)/?"
    )

    @staticmethod
    def parse_profile_url(url: str) -> str:
        match = LinkedInMapper.PROFILE_PATTERN.search(url)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def parse_company_url(url: str) -> str:
        match = LinkedInMapper.COMPANY_PATTERN.search(url)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def is_valid_profile_url(url: str) -> bool:
        return bool(LinkedInMapper.PROFILE_PATTERN.search(url))

    @staticmethod
    def is_valid_company_url(url: str) -> bool:
        return bool(LinkedInMapper.COMPANY_PATTERN.search(url))

    @staticmethod
    def url_to_profile(
        url: str,
        provider_id: str = "linkedin",
    ) -> ProviderContact | None:
        username = LinkedInMapper.parse_profile_url(url)
        if not username:
            return None
        return ProviderContact(
            first_name="",
            last_name="",
            title="",
            email="",
            linkedin_url=url,
            provider_id=provider_id,
            external_id=username,
            metadata={"profile_username": username},
        )

    @staticmethod
    def url_to_company(
        url: str,
        provider_id: str = "linkedin",
    ) -> ProviderCompany | None:
        slug = LinkedInMapper.parse_company_url(url)
        if not slug:
            return None
        return ProviderCompany(
            name="",
            linkedin_url=url,
            provider_id=provider_id,
            external_id=slug,
            metadata={"company_slug": slug},
        )

    @staticmethod
    def build_profile_url(username: str) -> str:
        return f"https://www.linkedin.com/in/{username}/"

    @staticmethod
    def build_company_url(slug: str) -> str:
        return f"https://www.linkedin.com/company/{slug}/"

    @staticmethod
    def to_contact(raw: dict[str, Any], provider_id: str = "linkedin") -> ProviderContact:
        linkedin_url = raw.get("linkedin_url", "")
        username = LinkedInMapper.parse_profile_url(linkedin_url)
        if not username and raw.get("username"):
            linkedin_url = LinkedInMapper.build_profile_url(raw["username"])
            username = raw["username"]

        first_name = raw.get("first_name", raw.get("firstName", ""))
        last_name = raw.get("last_name", raw.get("lastName", ""))
        title = raw.get("headline", raw.get("position", raw.get("title", "")))

        role = ProviderContactRole.UNKNOWN
        if title:
            title_lower = title.lower()
            if any(kw in title_lower for kw in ("ceo", "cto", "cfo", "cmo", "coo", "cio", "founder", "owner", "president", "vp", "vice president", "director", "head", "chief")):
                role = ProviderContactRole.DECISION_MAKER
            elif any(kw in title_lower for kw in ("manager", "lead", "senior")):
                role = ProviderContactRole.INFLUENCER

        return ProviderContact(
            first_name=first_name,
            last_name=last_name,
            title=title,
            email=raw.get("email", ""),
            linkedin_url=linkedin_url,
            role=role,
            provider_id=provider_id,
            external_id=username or "",
            metadata={k: v for k, v in raw.items() if k not in (
                "first_name", "last_name", "firstName", "lastName",
                "headline", "position", "title", "email",
                "linkedin_url", "username",
            )},
        )

    @staticmethod
    def to_company(raw: dict[str, Any], provider_id: str = "linkedin") -> ProviderCompany:
        linkedin_url = raw.get("linkedin_url", "")
        slug = LinkedInMapper.parse_company_url(linkedin_url)
        if not slug and raw.get("slug"):
            linkedin_url = LinkedInMapper.build_company_url(raw["slug"])
            slug = raw["slug"]

        return ProviderCompany(
            name=raw.get("name", ""),
            industry=raw.get("industry", ""),
            description=raw.get("description", ""),
            website=raw.get("website", ""),
            employees=raw.get("employees", raw.get("employee_count", 0)) or 0,
            linkedin_url=linkedin_url,
            provider_id=provider_id,
            external_id=slug or "",
            metadata={k: v for k, v in raw.items() if k not in (
                "name", "industry", "description", "website",
                "employees", "employee_count", "linkedin_url", "slug",
            )},
        )
