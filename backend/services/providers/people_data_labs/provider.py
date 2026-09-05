from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult
from services.providers.interface import Provider, ProviderSetupError
from services.providers.people_data_labs.mapper import PDLMapper

logger = logging.getLogger(__name__)

PDL_API_BASE = "https://api.peopledatalabs.com/v5"


class PeopleDataLabsProvider(Provider):
    """People Data Labs provider — person enrichment and company enrichment.

    Uses PDL's REST API with an API key (no OAuth).
    Reads PEOPLE_DATA_LABS_API_KEY from environment.
    """

    def __init__(
        self,
        api_key: str = "",
        provider_id: str = "people_data_labs",
    ) -> None:
        self._api_key = api_key or os.environ.get("PEOPLE_DATA_LABS_API_KEY", "")
        self._provider_id = provider_id
        self._connected = False
        self._mapper = PDLMapper()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return "People Data Labs"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.LEAD_ENRICHMENT,
            Capability.COMPANY_ENRICHMENT,
        )

    def connect(self) -> None:
        if not self._api_key:
            raise ProviderSetupError(
                "People Data Labs: no API key configured. "
                "Set PEOPLE_DATA_LABS_API_KEY in your environment."
            )
        self._connected = True
        logger.info("PeopleDataLabsProvider ready")

    def disconnect(self) -> None:
        self._connected = False
        logger.info("PeopleDataLabsProvider disconnected")

    def health(self) -> HealthCheckResult:
        if not self._connected or not self._api_key:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                status="offline", error="Not connected or no API key",
            )
        try:
            start = time.time()
            resp = requests.get(
                f"{PDL_API_BASE}/person/enrich",
                params={"email": "test@example.com"},
                headers=self._headers(),
                timeout=5,
            )
            elapsed = (time.time() - start) * 1000
            if resp.status_code == 200:
                return HealthCheckResult(
                    ok=True, provider_id=self._provider_id,
                    latency_ms=elapsed,
                )
            if resp.status_code == 402:
                return HealthCheckResult(
                    ok=True, provider_id=self._provider_id,
                    latency_ms=elapsed,
                    status="degraded",
                    error="API quota exhausted",
                )
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                latency_ms=elapsed,
                error=f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                error=str(e),
            )

    # ── Person Enrichment ─────────────────────────────────────────

    def enrich_person_by_email(self, email: str) -> dict[str, Any] | None:
        return self._person_enrich({"email": email})

    def enrich_person_by_linkedin(self, linkedin_url: str) -> dict[str, Any] | None:
        return self._person_enrich({"profile": linkedin_url})

    def enrich_person_by_name_company(
        self,
        first_name: str,
        last_name: str,
        company_name: str,
    ) -> dict[str, Any] | None:
        return self._person_enrich({
            "first_name": first_name,
            "last_name": last_name,
            "company": company_name,
        })

    def enrich_person(
        self,
        email: str = "",
        linkedin_url: str = "",
        first_name: str = "",
        last_name: str = "",
        company_name: str = "",
    ) -> dict[str, Any] | None:
        params: dict[str, str] = {}
        if email:
            params["email"] = email
        elif linkedin_url:
            params["profile"] = linkedin_url
        else:
            if first_name:
                params["first_name"] = first_name
            if last_name:
                params["last_name"] = last_name
            if company_name:
                params["company"] = company_name
        if not params:
            return None
        return self._person_enrich(params)

    def _person_enrich(self, params: dict[str, str]) -> dict[str, Any] | None:
        resp = requests.get(
            f"{PDL_API_BASE}/person/enrich",
            params=params,
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()
        if not raw.get("data", {}).get("full_name"):
            return None
        data = raw["data"]
        lead = self._mapper.person_to_lead(data, self._provider_id)
        return self._build_event("LEAD_ENRICHED", lead.to_dict())

    # ── Company Enrichment ────────────────────────────────────────

    def enrich_company_by_domain(self, domain: str) -> dict[str, Any] | None:
        return self._company_enrich({"domain": domain})

    def enrich_company_by_name(self, name: str) -> dict[str, Any] | None:
        return self._company_enrich({"name": name})

    def _company_enrich(self, params: dict[str, str]) -> dict[str, Any] | None:
        resp = requests.get(
            f"{PDL_API_BASE}/company/enrich",
            params=params,
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()
        data = raw.get("data", {})
        if not data.get("name"):
            return None
        company = self._mapper.company_to_company(data, self._provider_id)
        return self._build_event("COMPANY_ENRICHED", company.to_dict())

    # ── Bulk / Search ────────────────────────────────────────────

    def search_persons(
        self,
        sql: str = "",
        size: int = 10,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"size": size}
        if sql:
            payload["sql"] = sql

        resp = requests.post(
            f"{PDL_API_BASE}/person/search",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        results = resp.json().get("data", [])
        events = []
        for item in results:
            lead = self._mapper.person_to_lead(item, self._provider_id)
            events.append(self._build_event("LEAD_DISCOVERED", lead.to_dict()))
        return events

    def search_companies(
        self,
        sql: str = "",
        size: int = 10,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"size": size}
        if sql:
            payload["sql"] = sql

        resp = requests.post(
            f"{PDL_API_BASE}/company/search",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        results = resp.json().get("data", [])
        events = []
        for item in results:
            company = self._mapper.company_to_company(item, self._provider_id)
            events.append(self._build_event("COMPANY_ENRICHED", company.to_dict()))
        return events

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "people_data_labs",
            "data": data,
        }
