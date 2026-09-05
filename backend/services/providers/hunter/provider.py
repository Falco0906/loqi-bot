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
from services.providers.hunter.mapper import HunterMapper

logger = logging.getLogger(__name__)

HUNTER_API_BASE = "https://api.hunter.io/v2"


class HunterProvider(Provider):
    """Hunter provider — email discovery and email verification.

    Uses Hunter's REST API with an API key (no OAuth).
    Reads HUNTER_API_KEY from environment.
    """

    def __init__(
        self,
        api_key: str = "",
        provider_id: str = "hunter",
    ) -> None:
        self._api_key = api_key or os.environ.get("HUNTER_API_KEY", "")
        self._provider_id = provider_id
        self._connected = False
        self._mapper = HunterMapper()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return "Hunter"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.EMAIL_DISCOVERY,
            Capability.EMAIL_VERIFICATION,
        )

    def connect(self) -> None:
        if not self._api_key:
            raise ProviderSetupError(
                "Hunter: no API key configured. "
                "Set HUNTER_API_KEY in your environment."
            )
        self._connected = True
        logger.info("HunterProvider ready")

    def disconnect(self) -> None:
        self._connected = False
        logger.info("HunterProvider disconnected")

    def health(self) -> HealthCheckResult:
        if not self._connected or not self._api_key:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                status="offline", error="Not connected or no API key",
            )
        try:
            start = time.time()
            resp = requests.get(
                f"{HUNTER_API_BASE}/email-verifier",
                params={"email": "test@example.com", "api_key": self._api_key},
                timeout=5,
            )
            elapsed = (time.time() - start) * 1000
            if resp.status_code == 200:
                return HealthCheckResult(
                    ok=True, provider_id=self._provider_id,
                    latency_ms=elapsed,
                )
            if resp.status_code == 401:
                return HealthCheckResult(
                    ok=False, provider_id=self._provider_id,
                    latency_ms=elapsed, error="Invalid API key",
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

    # ── Email Discovery ───────────────────────────────────────────

    def email_find(
        self,
        domain: str,
        first_name: str = "",
        last_name: str = "",
        company: str = "",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "domain": domain,
            "api_key": self._api_key,
        }
        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if company and not domain:
            params["company"] = company

        resp = requests.get(
            f"{HUNTER_API_BASE}/email-finder",
            params=params,
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        raw = resp.json()
        events: list[dict[str, Any]] = []

        data = raw.get("data", {})
        email = data.get("email", "")
        if email:
            contact = self._mapper.email_finder_to_contact(raw, self._provider_id)
            if contact:
                data_dict = contact.to_dict()
                data_dict["domain"] = domain
                data_dict["score"] = data.get("score", 0)
                events.append(self._build_event("EMAIL_FOUND", data_dict))

        return events

    def domain_search(
        self,
        domain: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "domain": domain,
            "api_key": self._api_key,
            "limit": limit,
        }

        resp = requests.get(
            f"{HUNTER_API_BASE}/domain-search",
            params=params,
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        raw = resp.json()
        data = raw.get("data", {})
        emails = data.get("emails", [])
        events: list[dict[str, Any]] = []

        for email_data in emails:
            contact = ProviderContact(
                first_name=email_data.get("first_name", ""),
                last_name=email_data.get("last_name", ""),
                title=email_data.get("position", ""),
                email=email_data.get("value", ""),
                phone=email_data.get("phone_number", ""),
                linkedin_url=email_data.get("linkedin_url", ""),
                provider_id=self._provider_id,
            )
            data_dict = contact.to_dict()
            data_dict["domain"] = domain
            data_dict["type"] = email_data.get("type", "unknown")
            data_dict["sources"] = email_data.get("sources", [])
            events.append(self._build_event("EMAIL_FOUND", data_dict))

        return events

    # ── Email Verification ────────────────────────────────────────

    def email_verify(self, email: str) -> dict[str, Any] | None:
        resp = requests.get(
            f"{HUNTER_API_BASE}/email-verifier",
            params={"email": email, "api_key": self._api_key},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        raw = resp.json()
        result = self._mapper.email_verifier_to_result(raw, self._provider_id)
        return self._build_event("EMAIL_VERIFIED", result)

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "hunter",
            "data": data,
        }
