from __future__ import annotations

import time
from typing import Any

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult, HealthMonitor, ProviderStatus
from services.providers.interface import Provider


class ProviderRegistry:
    """Central registry for all production providers.

    Responsibilities:
        - Register and unregister provider instances
        - Discover providers by capability
        - Health check all registered providers
        - Enable/disable providers without removing them
        - Capability lookup for workflow dispatch

    This registry is separate from the legacy lead-provider factory,
    communication registry, and outbound registry.  Those continue
    to work unchanged.  New production providers should use this
    registry.

    The registry is provider-agnostic.  Reasoners and workflows
    discover providers through the registry by capability, never
    by concrete class.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._health_monitor = HealthMonitor()
        self._disabled: set[str] = set()
        self._metadata: dict[str, dict[str, Any]] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, provider: Provider, metadata: dict[str, Any] | None = None) -> None:
        """Register a provider instance.

        If a provider with the same provider_id already exists,
        it is replaced.
        """
        self._providers[provider.provider_id] = provider
        self._disabled.discard(provider.provider_id)
        if metadata:
            self._metadata[provider.provider_id] = metadata

    def unregister(self, provider_id: str) -> None:
        """Unregister and disconnect a provider."""
        provider = self._providers.pop(provider_id, None)
        if provider is not None:
            try:
                provider.disconnect()
            except Exception:
                pass
        self._disabled.discard(provider_id)
        self._metadata.pop(provider_id, None)

    def get(self, provider_id: str) -> Provider | None:
        """Get a registered provider by ID.

        Returns None if the provider is not registered or is disabled.
        """
        provider = self._providers.get(provider_id)
        if provider is None:
            return None
        if provider_id in self._disabled:
            return None
        return provider

    def get_unchecked(self, provider_id: str) -> Provider | None:
        """Get a registered provider regardless of enabled/disabled status."""
        return self._providers.get(provider_id)

    def list_providers(self) -> list[Provider]:
        """List all enabled providers."""
        return [
            p for pid, p in self._providers.items()
            if pid not in self._disabled
        ]

    def list_all(self) -> list[Provider]:
        """List all registered providers (including disabled)."""
        return list(self._providers.values())

    # ── Discovery ─────────────────────────────────────────────────

    def find_by_capability(self, capability: Capability) -> list[Provider]:
        """Find all enabled providers that support a given capability."""
        return [
            p for p in self.list_providers()
            if p.capabilities.has(capability)
        ]

    def find_by_any_capability(self, *capabilities: Capability) -> list[Provider]:
        """Find enabled providers that support any of the given capabilities."""
        return [
            p for p in self.list_providers()
            if p.capabilities.has_any(*capabilities)
        ]

    def find_by_all_capabilities(self, *capabilities: Capability) -> list[Provider]:
        """Find enabled providers that support all of the given capabilities."""
        return [
            p for p in self.list_providers()
            if p.capabilities.has_all(*capabilities)
        ]

    def has_capability(self, provider_id: str, capability: Capability) -> bool:
        """Check if a specific provider has a capability."""
        provider = self.get(provider_id)
        if provider is None:
            return False
        return provider.capabilities.has(capability)

    # ── Enable / Disable ──────────────────────────────────────────

    def enable(self, provider_id: str) -> bool:
        """Re-enable a disabled provider.

        Returns True if the provider was previously disabled.
        """
        if provider_id not in self._providers:
            return False
        was_disabled = provider_id in self._disabled
        self._disabled.discard(provider_id)
        return was_disabled

    def disable(self, provider_id: str) -> bool:
        """Disable a provider without unregistering it.

        Disabled providers are excluded from find_by_capability
        and list_providers, but remain registered.

        Returns True if the provider was previously enabled.
        """
        if provider_id not in self._providers:
            return False
        was_enabled = provider_id not in self._disabled
        self._disabled.add(provider_id)
        return was_enabled

    def is_enabled(self, provider_id: str) -> bool:
        return provider_id in self._providers and provider_id not in self._disabled

    def is_disabled(self, provider_id: str) -> bool:
        return provider_id in self._disabled

    def list_disabled(self) -> list[Provider]:
        return [
            p for pid, p in self._providers.items()
            if pid in self._disabled
        ]

    # ── Health ─────────────────────────────────────────────────────

    def health(self, provider_id: str) -> HealthCheckResult | None:
        """Run a health check on a single provider."""
        provider = self.get_unchecked(provider_id)
        if provider is None:
            return None
        return self._health_monitor.check(provider, provider_id)

    def health_all(self) -> dict[str, HealthCheckResult]:
        """Run health checks on all registered providers.

        Does NOT exclude disabled providers — health checks
        run regardless so the monitor can report degraded status.
        """
        return self._health_monitor.check_all(dict(self._providers))

    def health_status(self, provider_id: str) -> ProviderStatus:
        """Get the latest known health status without running a check."""
        return self._health_monitor.latest_status(provider_id)

    def health_summary(self) -> dict[str, Any]:
        """Get a summary of all provider health statuses."""
        return self._health_monitor.summary()

    def health_consecutive_failures(self, provider_id: str) -> int:
        return self._health_monitor.consecutive_failures(provider_id)

    # ── Metadata ──────────────────────────────────────────────────

    def set_metadata(self, provider_id: str, metadata: dict[str, Any]) -> None:
        self._metadata[provider_id] = metadata

    def get_metadata(self, provider_id: str) -> dict[str, Any]:
        return self._metadata.get(provider_id, {})

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": {
                pid: {
                    **p.to_dict(),
                    "enabled": pid not in self._disabled,
                    "health": self._health_monitor.latest(pid).to_dict()
                    if self._health_monitor.latest(pid) else None,
                    "metadata": self._metadata.get(pid, {}),
                }
                for pid, p in self._providers.items()
            },
            "summary": {
                "total": len(self._providers),
                "enabled": len(self.list_providers()),
                "disabled": len(self._disabled),
                "online": sum(
                    1 for pid in self._providers
                    if self._health_monitor.is_online(pid)
                ),
            },
        }


_GLOBAL_REGISTRY: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Get the global ProviderRegistry singleton.

    All production providers should register here.
    Legacy registries (provider_factory, communication, outbound)
    remain unchanged and continue to work alongside this registry.
    """
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ProviderRegistry()
    return _GLOBAL_REGISTRY
