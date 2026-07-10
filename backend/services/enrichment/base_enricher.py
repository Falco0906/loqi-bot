from abc import ABC, abstractmethod


class EnricherError(Exception):
    """Raised when an enrichment operation fails."""
    pass


class BaseEnricher(ABC):
    """Abstract interface for all company enrichers.

    Every enricher transforms a raw lead + company data into structured
    business intelligence before draft generation.

    The canonical enrichment schema:

        {
            "company_summary": str,
            "recommended_pitch_angle": str,
            "business_pain_summary": str,
            "technology_summary": str,
            "growth_summary": str,
            "decision_context": str,
            "buying_signal_summary": str,
            "recent_events_summary": str,
            "qualification_reason": str,
            "confidence_score": int,          # 0-100
            "provider": str,                   # enricher name
        }
    """

    @property
    @abstractmethod
    def capabilities(self) -> dict:
        """Declare what the enricher can do."""
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """Verify the enricher is operational.

        Returns:
            {"ok": True} or {"ok": False, "error": "reason"}
        """
        pass

    @abstractmethod
    def enrich_company(self, company: dict) -> dict:
        """Enrich a raw company dict.

        Returns the canonical enrichment schema.
        """
        pass

    @abstractmethod
    def enrich_lead(self, lead: dict) -> dict:
        """Enrich a single lead.

        Returns the canonical enrichment schema.
        """
        pass
