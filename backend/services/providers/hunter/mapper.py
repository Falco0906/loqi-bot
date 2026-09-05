from __future__ import annotations

from typing import Any

from services.providers.models import ProviderContact, ProviderContactRole


class HunterMapper:
    """Maps raw Hunter API responses to normalized domain models."""

    @staticmethod
    def email_finder_to_contact(
        raw: dict[str, Any],
        provider_id: str = "hunter",
    ) -> ProviderContact | None:
        data = raw.get("data", {})
        email = data.get("email", "")
        if not email:
            return None

        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        title = data.get("position", "")
        phone = data.get("phone_number", "")
        linkedin_url = data.get("linkedin_url", "")
        twitter_url = data.get("twitter_url", "")

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
            email=email,
            phone=phone,
            linkedin_url=linkedin_url,
            role=role,
            provider_id=provider_id,
            metadata={
                "twitter_url": twitter_url,
                "sources": data.get("sources", []),
            },
        )

    @staticmethod
    def email_verifier_to_result(
        raw: dict[str, Any],
        provider_id: str = "hunter",
    ) -> dict[str, Any]:
        data = raw.get("data", {})
        return {
            "email": data.get("email", ""),
            "status": data.get("status", "unknown"),
            "result": data.get("result", "unknown"),
            "score": data.get("score", 0),
            "regexp": data.get("regexp", False),
            "gibberish": data.get("gibberish", False),
            "disposable": data.get("disposable", False),
            "webmail": data.get("webmail", False),
            "mx_records": data.get("mx_records", False),
            "smtp_server": data.get("smtp_server", False),
            "smtp_check": data.get("smtp_check", False),
            "accept_all": data.get("accept_all", False),
            "block": data.get("block", False),
            "provider_id": provider_id,
        }
