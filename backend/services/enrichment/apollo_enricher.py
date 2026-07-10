from .base_enricher import BaseEnricher


def _log(message: str) -> None:
    print(f"[apollo_enricher] {message}")


class ApolloEnricher(BaseEnricher):
    """Apollo.io enricher.

    NOT YET IMPLEMENTED.
    Set ENRICHMENT_PROVIDER=apollo in your .env to test the wiring.
    """

    @property
    def capabilities(self) -> dict:
        return {
            "supports_company_enrichment": True,
            "supports_lead_enrichment": True,
            "uses_ai": False,
        }

    def __init__(self) -> None:
        _log("ApolloEnricher loaded (stub)")

    def health_check(self) -> dict:
        return {
            "ok": False,
            "error": "ApolloEnricher is a stub — not yet implemented",
        }

    def enrich_company(self, company: dict) -> dict:
        return {
            "ok": False,
            "provider": "apollo",
            "error": "ApolloEnricher is a stub — implement to use Apollo enrichment",
        }

    def enrich_lead(self, lead: dict) -> dict:
        return {
            "ok": False,
            "provider": "apollo",
            "error": "ApolloEnricher is a stub — implement to use Apollo enrichment",
        }
