import os
import time

from .base_enricher import BaseEnricher

_ENRICHER_CACHE: dict[str, BaseEnricher] = {}
_LAST_LOG: float = 0


def _log(message: str) -> None:
    print(f"[enrichment_factory] {message}")


def get_enricher() -> BaseEnricher:
    """Return the configured enricher singleton.

    Provider is selected through the ENRICHMENT_PROVIDER environment variable.
    Supported values: synthetic, apollo

    Raises ValueError for unknown providers.
    """
    name = os.getenv("ENRICHMENT_PROVIDER", "synthetic").strip().lower()

    if name in _ENRICHER_CACHE:
        return _ENRICHER_CACHE[name]

    global _LAST_LOG
    now = time.time()
    if now - _LAST_LOG > 5.0:
        _log(f"Initializing enricher: {name}")
        _LAST_LOG = now

    if name == "synthetic":
        from .synthetic_enricher import SyntheticEnricher
        enricher: BaseEnricher = SyntheticEnricher()
    elif name == "apollo":
        from .apollo_enricher import ApolloEnricher
        enricher = ApolloEnricher()
    else:
        raise ValueError(
            f"Unknown ENRICHMENT_PROVIDER: '{name}'. "
            f"Supported values: synthetic, apollo"
        )

    _ENRICHER_CACHE[name] = enricher
    return enricher


def get_enricher_capabilities() -> dict:
    """Return capabilities of the current enricher."""
    return get_enricher().capabilities
