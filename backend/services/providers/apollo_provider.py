from .base_provider import BaseProvider


def _log(message: str) -> None:
    print(f"[apollo_provider] {message}")


class ApolloProvider(BaseProvider):
    """Apollo.io lead provider.

    NOT YET IMPLEMENTED.
    Set LEAD_PROVIDER=apollo in your .env to test the wiring.
    """

    def __init__(self) -> None:
        _log("ApolloProvider loaded (stub)")

    @property
    def capabilities(self) -> dict:
        return {
            "supports_email": True,
            "supports_company_lookup": True,
            "supports_enrichment": True,
            "supports_live_search": True,
        }

    def health_check(self) -> dict:
        return {
            "ok": False,
            "error": "ApolloProvider is a stub — not yet implemented",
        }

    def search_leads(
        self,
        icp: dict,
        search_expansion: dict,
        limit: int = 20,
    ) -> dict:
        return {
            "ok": False,
            "provider": "apollo",
            "leads": [],
            "error": "ApolloProvider is a stub — implement ApolloProvider to use Apollo.io",
            "stats": {
                "total_found": 0,
                "returned": 0,
                "search_time_ms": 0.0,
            },
        }

    def get_lead(self, lead_id: str) -> dict | None:
        return None

    def get_company(self, company_id: str) -> dict | None:
        return None
