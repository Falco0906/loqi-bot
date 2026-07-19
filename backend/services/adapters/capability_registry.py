from __future__ import annotations

from typing import Optional

from services.adapters.capabilities import CapabilityDescriptor, CapabilityProvider
from services.adapters.exceptions import CapabilityRegistrationError


class CapabilityRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[tuple[str, str], CapabilityDescriptor] = {}
        self._providers: dict[tuple[str, str], CapabilityProvider] = {}

    # ------------------------------------------------------------------
    # Descriptor management
    # ------------------------------------------------------------------

    def register(self, descriptor: CapabilityDescriptor) -> None:
        key = (descriptor.name, descriptor.version)
        if key in self._descriptors:
            raise CapabilityRegistrationError(
                f"Capability {descriptor.name!r} version {descriptor.version!r} "
                f"is already registered"
            )
        self._descriptors[key] = descriptor

    def unregister(self, name: str, version: str) -> None:
        key = (name, version)
        if key not in self._descriptors:
            raise CapabilityRegistrationError(
                f"Capability {name!r} version {version!r} is not registered"
            )
        del self._descriptors[key]

    def get(self, name: str, version: str) -> Optional[CapabilityDescriptor]:
        return self._descriptors.get((name, version))

    def exists(self, name: str, version: str) -> bool:
        return (name, version) in self._descriptors

    def find_by_name(self, name: str) -> list[CapabilityDescriptor]:
        return [
            d for d in self._descriptors.values()
            if d.name.lower() == name.lower()
        ]

    def find_by_category(self, category: str) -> list[CapabilityDescriptor]:
        return [
            d for d in self._descriptors.values()
            if d.category.lower() == category.lower()
        ]

    def find_by_tag(self, *tags: str) -> list[CapabilityDescriptor]:
        if not tags:
            return self.list_all()
        lower_tags = frozenset(t.lower() for t in tags)
        return [
            d for d in self._descriptors.values()
            if lower_tags.issubset(frozenset(t.lower() for t in d.tags))
        ]

    def search(self, query: str) -> list[CapabilityDescriptor]:
        q = query.strip().lower()
        if not q:
            return []
        return [d for d in self._descriptors.values() if d.matches_query(q)]

    def list_all(self) -> list[CapabilityDescriptor]:
        return list(self._descriptors.values())

    def count(self) -> int:
        return len(self._descriptors)

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def register_provider(self, provider: CapabilityProvider) -> None:
        key = (provider.adapter_name, provider.adapter_version)
        if key in self._providers:
            raise CapabilityRegistrationError(
                f"Provider {provider.adapter_name!r} version "
                f"{provider.adapter_version!r} is already registered"
            )
        self._providers[key] = provider

    def unregister_provider(self, adapter_name: str, adapter_version: str) -> None:
        key = (adapter_name, adapter_version)
        if key not in self._providers:
            raise CapabilityRegistrationError(
                f"Provider {adapter_name!r} version {adapter_version!r} "
                f"is not registered"
            )
        del self._providers[key]

    def find_providers(
        self, capability_name: str
    ) -> list[CapabilityProvider]:
        return [
            p for p in self._providers.values()
            if any(c.lower() == capability_name.lower() for c in p.capability_names)
        ]

    def get_provider(
        self, adapter_name: str, adapter_version: str
    ) -> Optional[CapabilityProvider]:
        return self._providers.get((adapter_name, adapter_version))

    def list_providers(self) -> list[CapabilityProvider]:
        return list(self._providers.values())

    def provider_count(self) -> int:
        return len(self._providers)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._descriptors.clear()
        self._providers.clear()
