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


# ─── PR-4: provider execution hardening ──────────────────────────────────

import random  # noqa: E402
import time as _time  # noqa: E402

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderTimeoutError(Exception):
    """Provider remained unavailable past the retry budget."""


class ProviderPermanentError(Exception):
    """Provider rejected the request in a way retries cannot fix."""

MAX_PROVIDER_RETRIES = 2
PROVIDER_TIMEOUT_SECONDS = 45.0


def classify_provider_error(error: str = "", status: int | None = None) -> str:
    """Classify a provider failure as retryable or permanent."""
    lowered = (error or "").lower()
    if status is not None and status in RETRYABLE_STATUS:
        return "retryable"
    if status is not None and 400 <= status < 500:
        if status == 429:
            return "retryable"
        return "permanent"
    for marker in ("timeout", "timed out", "connection reset", "connection refused",
                   "temporarily unavailable", "bad gateway"):
        if marker in lowered:
            return "retryable"
    for marker in ("unauthorized", "invalid api key", "invalid credentials",
                   "forbidden", "authentication", "not yet implemented", "stub"):
        if marker in lowered:
            return "permanent"
    return "retryable"  # default safe: transient-looking


def search_leads_with_retry(
    provider,
    *,
    icp: dict,
    search_expansion: dict,
    limit: int = 30,
    max_retries: int = MAX_PROVIDER_RETRIES,
    timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
) -> dict:
    """Bounded, idempotent search with retryable-only retries.

    - exponential backoff + jitter; honors Retry-After when the provider
      surfaces one in the error string
    - permanent failures (auth/4xx validation) fail immediately
    - never mutates shared state; same inputs → same request semantics

    Returns the provider's result dict unchanged on success.
    Raises ProviderTimeoutError / ProviderPermanentError otherwise.
    """
    import requests as _requests

    attempt = 0
    last_error = ""
    last_status = None
    while attempt <= max_retries:
        attempt += 1
        try:
            deadline = _time.monotonic() + timeout_seconds
            result = provider.search_leads(icp=icp, search_expansion=search_expansion, limit=limit)
            if result.get("ok"):
                return result
            error = str(result.get("error") or "provider search failed")
            # Stub/unimplemented providers are permanent by definition.
            if "not yet implemented" in error.lower() or "stub" in error.lower():
                raise ProviderPermanentError(error)
            classification = classify_provider_error(error)
            if classification == "permanent":
                raise ProviderPermanentError(error)
            last_error = error
            retry_after = None
            if "retry-after" in error.lower():
                try:
                    retry_after = int("".join(ch for ch in error.split("retry-after")[1] if ch.isdigit())[:4])
                except (ValueError, IndexError):
                    retry_after = None
            if attempt <= max_retries:
                backoff = min(8.0, (2 ** attempt) * 0.5 + random.uniform(0, 0.25))
                _time.sleep(max(backoff, float(retry_after or 0)))
                continue
            raise TimeoutError(last_error)
        except (_requests.Timeout,) as e:
            last_error = f"provider timeout after {timeout_seconds}s"
            if attempt > max_retries:
                raise ProviderTimeoutError(last_error)
            _time.sleep(min(8.0, (2 ** attempt) * 0.5 + random.uniform(0, 0.25)))
        except _requests.RequestException as e:
            msg = str(e)
            cls = classify_provider_error(msg)
            last_error = msg[:200]
            if cls == "permanent":
                raise ProviderPermanentError(msg[:200])
            if attempt > max_retries:
                raise ProviderTimeoutError(msg[:200])
            _time.sleep(min(8.0, (2 ** attempt) * 0.5))
        except (ProviderTimeoutError, ProviderPermanentError):
            raise
        except Exception as e:
            last_error = str(e)[:200]
            if attempt > max_retries:
                raise ProviderTimeoutError(last_error)
            _time.sleep(1.0)
    raise ProviderTimeoutError(last_error or "provider retries exhausted")
