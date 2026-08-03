from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult
from services.providers.interface import Provider, ProviderSetupError
from services.providers.linkedin.mapper import LinkedInMapper

logger = logging.getLogger(__name__)


class LinkedInProvider(Provider):
    """LinkedIn provider — profile metadata, company information, URL parsing.

    Does NOT scrape LinkedIn.
    Does NOT bypass LinkedIn policies.
    Does NOT require an API key.

    This provider:
        - Parses and validates LinkedIn profile/company URLs
        - Stores structured profile data that users explicitly provide
        - Publishes normalized PROFILE_FOUND / COMPANY_INFO_FOUND events

    For actual profile data enrichment, use PeopleDataLabsProvider which
    has a LinkedIn data partnership.

    If you need LinkedIn API access, implement a separate OAuth provider
    using LinkedIn's official Marketing Developer Platform API.
    """

    def __init__(
        self,
        provider_id: str = "linkedin",
    ) -> None:
        self._provider_id = provider_id
        self._connected = False
        self._mapper = LinkedInMapper()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return "LinkedIn"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.PROFILE_LOOKUP,
            Capability.COMPANY_LOOKUP,
        )

    def connect(self) -> None:
        self._connected = True
        logger.info("LinkedInProvider ready")

    def disconnect(self) -> None:
        self._connected = False
        logger.info("LinkedInProvider disconnected")

    def health(self) -> HealthCheckResult:
        return HealthCheckResult(
            ok=True,
            provider_id=self._provider_id,
            status="online",
            details={"note": "No external API — URL parsing and metadata only"},
        )

    # ── Profile Lookup ────────────────────────────────────────────

    def lookup_profile(self, linkedin_url: str) -> dict[str, Any] | None:
        if not self._mapper.is_valid_profile_url(linkedin_url):
            return None
        username = self._mapper.parse_profile_url(linkedin_url)
        if not username:
            return None

        return self._build_event("PROFILE_FOUND", {
            "linkedin_url": linkedin_url,
            "username": username,
            "provider_id": self._provider_id,
        })

    def lookup_company(self, linkedin_url: str) -> dict[str, Any] | None:
        if not self._mapper.is_valid_company_url(linkedin_url):
            return None
        slug = self._mapper.parse_company_url(linkedin_url)
        if not slug:
            return None

        return self._build_event("COMPANY_INFO_FOUND", {
            "linkedin_url": linkedin_url,
            "slug": slug,
            "provider_id": self._provider_id,
        })

    def validate_url(self, url: str) -> dict[str, Any]:
        is_profile = self._mapper.is_valid_profile_url(url)
        is_company = self._mapper.is_valid_company_url(url)

        result: dict[str, Any] = {
            "url": url,
            "valid": is_profile or is_company,
            "type": "profile" if is_profile else ("company" if is_company else "unknown"),
        }

        if is_profile:
            result["username"] = self._mapper.parse_profile_url(url)
        elif is_company:
            result["slug"] = self._mapper.parse_company_url(url)

        return result

    # ── Structured Profile Data (user-provided) ───────────────────

    def publish_profile(
        self,
        linkedin_url: str,
        first_name: str = "",
        last_name: str = "",
        headline: str = "",
        email: str = "",
    ) -> dict[str, Any] | None:
        if not self._mapper.is_valid_profile_url(linkedin_url):
            return None

        contact = self._mapper.to_contact({
            "linkedin_url": linkedin_url,
            "first_name": first_name,
            "last_name": last_name,
            "headline": headline,
            "email": email,
        }, self._provider_id)

        return self._build_event("PROFILE_FOUND", contact.to_dict())

    def publish_company(
        self,
        linkedin_url: str,
        name: str = "",
        industry: str = "",
        website: str = "",
        employees: int = 0,
    ) -> dict[str, Any] | None:
        if not self._mapper.is_valid_company_url(linkedin_url):
            return None

        company = self._mapper.to_company({
            "linkedin_url": linkedin_url,
            "name": name,
            "industry": industry,
            "website": website,
            "employee_count": employees,
        }, self._provider_id)

        return self._build_event("COMPANY_INFO_FOUND", company.to_dict())

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "linkedin",
            "data": data,
        }
