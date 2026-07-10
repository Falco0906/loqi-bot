from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Raised when a provider operation fails."""
    pass


class BaseProvider(ABC):
    """Abstract interface for all lead providers.

    Every provider must implement these four methods.
    No downstream code should ever know which provider produced a lead.

    The canonical lead schema returned by search_leads, get_lead:

        {
            "lead_id": str,              # unique within provider
            "company_id": str,           # source company id (for SyntheticProvider)
            "first_name": str,
            "last_name": str,
            "name": str,                 # "First Last"
            "title": str,
            "department": str,
            "email": str,
            "linkedin_url": str,
            "buying_authority": int,     # 0-100
            "company": str,              # company name
            "company_industry": str,
            "company_sub_industry": str,
            "company_description": str,
            "company_website": str,
            "company_city": str,
            "company_country": str,
            "company_employees": int,
            "company_locations": int,
            "company_founded": int,
            "company_growth_stage": str,
            "company_revenue_band": str,
            "company_technology": dict,
            "pain_points": list[str],
            "buying_signals": list[str],
            "recent_events": list[str],
            "provider": str,             # provider name
        }
    """

    @property
    @abstractmethod
    def capabilities(self) -> dict:
        """Declare what the provider can do.

        Returns a dict with boolean flags:

            supports_email           — can return email addresses
            supports_company_lookup  — get_company() returns rich metadata
            supports_enrichment      — can do on-the-fly lead enrichment
            supports_live_search     — searches external API (vs static dataset)

        The UI and workflow engine can branch on these without knowing
        which concrete provider is plugged in.
        """
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """Verify the provider is operational.

        Returns:
            {"ok": True} or {"ok": False, "error": "reason"}
        """
        pass

    @abstractmethod
    def search_leads(
        self,
        icp: dict,
        search_expansion: dict,
        limit: int = 20,
    ) -> dict:
        """Search for leads matching ICP criteria.

        Args:
            icp: Structured ICP from icp_extractor
                 (buyer_industries, buyer_roles, excluded_roles, keywords, ...)
            search_expansion: Expanded search terms from search_expansion
                 (roles, industries, keywords, search_queries, ...)
            limit: Maximum leads to return

        Returns:
            {
                "ok": bool,
                "provider": str,
                "leads": [canonical_lead, ...],
                "error": str | None,
                "stats": {
                    "total_found": int,
                    "search_time_ms": float,
                }
            }
        """
        pass

    @abstractmethod
    def get_lead(self, lead_id: str) -> dict | None:
        """Retrieve a single lead by ID.

        Returns canonical lead dict, or None if not found.
        """
        pass

    @abstractmethod
    def get_company(self, company_id: str) -> dict | None:
        """Retrieve company metadata by ID.

        Returns:
            Full company dict from the provider's data, or None if not found.
        """
        pass
