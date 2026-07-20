from __future__ import annotations

from services.identity.contracts import IdentityProvider, ProviderType


class IdentityProviderRegistryError(Exception):
    pass


class IdentityProviderRegistry:

    def __init__(self) -> None:
        self._providers: dict[ProviderType, IdentityProvider] = {}

    def register(self, provider: IdentityProvider) -> None:
        pt = provider.provider_type
        if pt in self._providers:
            raise IdentityProviderRegistryError(
                f"Provider already registered: {pt.value}",
            )
        self._providers[pt] = provider

    def get(self, provider_type: ProviderType | str) -> IdentityProvider:
        if isinstance(provider_type, str):
            provider_type = ProviderType(provider_type)
        provider = self._providers.get(provider_type)
        if provider is None:
            raise IdentityProviderRegistryError(
                f"No provider registered for: {provider_type.value}",
            )
        return provider

    def list(self) -> list[IdentityProvider]:
        return list(self._providers.values())


_registry = IdentityProviderRegistry()


def get_provider_registry() -> IdentityProviderRegistry:
    return _registry


def reset_provider_registry() -> None:
    _registry._providers.clear()
