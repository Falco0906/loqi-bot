from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.exceptions import (
    AdapterDisabledError,
    AdapterNotFoundError,
)

if TYPE_CHECKING:
    from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration


class AdapterFactory:
    """Creates adapter instances lazily.

    The factory never caches instances and never executes adapters.
    Every call to ``create``, ``create_latest``, or
    ``create_for_capability`` returns a fresh instance.
    """

    def __init__(
        self,
        get_registration: Callable[[AdapterIdentity], Optional[AdapterRegistration]],
        find_registrations: Callable[[str], list[AdapterRegistration]],
    ) -> None:
        self._get_registration = get_registration
        self._find_registrations = find_registrations

    def create(self, identity: AdapterIdentity) -> ExecutionAdapter:
        """Create an adapter instance for the given identity."""
        reg = self._get_registration(identity)
        if reg is None:
            raise AdapterNotFoundError(
                f"Adapter {identity.name!r} version {identity.version!r} "
                f"is not registered"
            )
        if not reg.enabled:
            raise AdapterDisabledError(
                f"Adapter {identity.name!r} version {identity.version!r} "
                f"is disabled"
            )
        return reg.adapter_class()

    def create_latest(self, name: str) -> ExecutionAdapter:
        """Create an adapter instance for the latest version of *name*."""
        registrations = self._find_registrations(name)
        enabled = [r for r in registrations if r.enabled]
        if not enabled:
            raise AdapterNotFoundError(
                f"No enabled adapter found for {name!r}"
            )
        selected = enabled[0]
        for r in enabled[1:]:
            if r.identity._version_key() > selected.identity._version_key():
                selected = r
        return selected.adapter_class()

    def create_for_capability(
        self,
        capability_name: str,
        providers: list[AdapterRegistration],
    ) -> ExecutionAdapter:
        """Create an adapter instance by selecting from *providers*.

        The caller is responsible for providing the candidate list
        (usually via ``AdapterRegistry.select_provider``).
        """
        if not providers:
            raise AdapterNotFoundError(
                f"No provider found for capability {capability_name!r}"
            )
        return providers[0].adapter_class()
