import os
import time

from .base_provider import BaseProvider

_PROVIDER_CACHE: dict[str, BaseProvider] = {}
_LAST_LOG: float = 0


def _log(message: str) -> None:
    print(f"[provider_factory] {message}")


def get_provider() -> BaseProvider:
    """Return the configured lead provider singleton.

    Provider is selected through the LEAD_PROVIDER environment variable.
    Supported values: synthetic, apollo

    Raises ValueError for unknown providers.
    """
    name = os.getenv("LEAD_PROVIDER", "synthetic").strip().lower()

    if name in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[name]

    global _LAST_LOG
    now = time.time()
    if now - _LAST_LOG > 5.0:
        _log(f"Initializing provider: {name}")
        _LAST_LOG = now

    if name == "synthetic":
        from .synthetic_provider import SyntheticProvider
        provider: BaseProvider = SyntheticProvider()
    elif name == "apollo":
        from .apollo_provider import ApolloProvider
        provider = ApolloProvider()
    else:
        raise ValueError(
            f"Unknown LEAD_PROVIDER: '{name}'. "
            f"Supported values: synthetic, apollo"
        )

    _PROVIDER_CACHE[name] = provider
    return provider


def get_provider_capabilities() -> dict:
    """Return capabilities of the current provider.

    The UI or workflow engine can call this to discover what the
    plugged-in provider supports without importing a concrete class.
    """
    return get_provider().capabilities
