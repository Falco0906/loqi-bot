from __future__ import annotations

from typing import Any, Optional

from services.adapters.adapter_factory import AdapterFactory
from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
from services.adapters.exceptions import (
    AdapterNotFoundError,
    AdapterRegistrationError,
)


class AdapterRegistry:
    """Unified registry linking adapter classes to capabilities and credentials.

    The registry stores registration metadata only — no adapter instances,
    no runtime state.  It optionally integrates with a ``CapabilityRegistry``
    and ``CredentialRegistry`` for cross-referencing.
    """

    def __init__(self, capability_registry: Any = None, credential_registry: Any = None) -> None:
        self._registrations: dict[AdapterIdentity, AdapterRegistration] = {}
        self._order: list[AdapterIdentity] = []
        self._capability_registry = capability_registry
        self._credential_registry = credential_registry
        self._factory = AdapterFactory(
            get_registration=self._get_registration,
            find_registrations=self.find_by_name,
        )

    # ------------------------------------------------------------------
    # Registration management
    # ------------------------------------------------------------------

    def register(self, registration: AdapterRegistration) -> None:
        errors: list[str] = []
        if registration.identity in self._registrations:
            raise AdapterRegistrationError(
                f"Adapter {registration.name!r} version {registration.version!r} "
                f"is already registered"
            )

        if self._capability_registry is not None:
            for cap_name in registration.capability_names:
                if not self._capability_registry.exists(
                    cap_name, registration.identity.version
                ) and not self._capability_registry.find_by_name(cap_name):
                    errors.append(
                        f"capability {cap_name!r} is not registered in "
                        f"the capability registry"
                    )

        if self._credential_registry is not None:
            for cred_name in registration.credential_descriptor_names:
                if not self._credential_registry.exists(cred_name):
                    errors.append(
                        f"credential descriptor {cred_name!r} is not "
                        f"registered in the credential registry"
                    )

        if errors:
            raise AdapterRegistrationError(
                f"Cannot register {registration.name!r}: {'; '.join(errors)}"
            )

        self._registrations[registration.identity] = registration
        self._order.append(registration.identity)

    def unregister(self, identity: AdapterIdentity) -> None:
        if identity not in self._registrations:
            raise AdapterNotFoundError(
                f"Adapter {identity.name!r} version {identity.version!r} "
                f"is not registered"
            )
        del self._registrations[identity]
        self._order.remove(identity)

    def get(self, identity: AdapterIdentity) -> Optional[AdapterRegistration]:
        return self._registrations.get(identity)

    def exists(self, identity: AdapterIdentity) -> bool:
        return identity in self._registrations

    # ------------------------------------------------------------------
    # Lookup queries
    # ------------------------------------------------------------------

    def find_by_name(self, name: str) -> list[AdapterRegistration]:
        return [
            r for r in self._registrations.values()
            if r.name.lower() == name.lower()
        ]

    def find_by_version(self, name: str, version: str) -> Optional[AdapterRegistration]:
        identity = AdapterIdentity(name=name, version=version)
        return self._registrations.get(identity)

    def find_by_capability(self, capability_name: str) -> list[AdapterRegistration]:
        q = capability_name.lower()
        return [
            r for r in self._registrations.values()
            if any(c.lower() == q for c in r.capability_names)
        ]

    def find_enabled(self) -> list[AdapterRegistration]:
        return [r for r in self._registrations.values() if r.enabled]

    def find_disabled(self) -> list[AdapterRegistration]:
        return [r for r in self._registrations.values() if not r.enabled]

    def search(self, query: str) -> list[AdapterRegistration]:
        q = query.strip().lower()
        if not q:
            return []
        results: list[AdapterRegistration] = []
        for r in self._registrations.values():
            if q in r.name.lower():
                results.append(r)
                continue
            meta = r.metadata
            if hasattr(meta, "display_name") and q in meta.display_name.lower():
                results.append(r)
                continue
            if hasattr(meta, "description") and q in meta.description.lower():
                results.append(r)
                continue
            if hasattr(meta, "tags") and any(q in t.lower() for t in meta.tags):
                results.append(r)
                continue
        return results

    def list_all(self) -> list[AdapterRegistration]:
        return list(self._registrations.values())

    def count(self) -> int:
        return len(self._registrations)

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def find_providers(self, capability_name: str) -> list[AdapterRegistration]:
        """Find all enabled adapters that provide *capability_name*.

        If a ``CapabilityRegistry`` was provided at construction time,
        the registry consults it for ``CapabilityProvider`` records and
        cross-references them against registered adapters.
        """
        if self._capability_registry is not None:
            providers = self._capability_registry.find_providers(capability_name)
            results: list[AdapterRegistration] = []
            for p in providers:
                identity = AdapterIdentity(
                    name=p.adapter_name, version=p.adapter_version
                )
                reg = self._registrations.get(identity)
                if reg is not None and reg.enabled:
                    results.append(reg)
            return results

        return [
            r for r in self._registrations.values()
            if r.enabled and any(
                c.lower() == capability_name.lower() for c in r.capability_names
            )
        ]

    def select_provider(
        self, capability_name: str
    ) -> Optional[AdapterRegistration]:
        """Select the best provider for *capability_name*.

        Selection is deterministic:
          1. Priority descending
          2. Version descending (semver-aware)
          3. Registration order ascending
        """
        candidates = self.find_providers(capability_name)
        return self._select_best(candidates)

    def highest_priority_provider(
        self, capability_name: str
    ) -> Optional[AdapterRegistration]:
        candidates = self.find_providers(capability_name)
        if not candidates:
            return None
        max_priority = max(r.priority for r in candidates)
        tied = [r for r in candidates if r.priority == max_priority]
        return self._select_best(tied)

    def _select_best(
        self, candidates: list[AdapterRegistration]
    ) -> Optional[AdapterRegistration]:
        if not candidates:
            return None

        def sort_key(r: AdapterRegistration) -> tuple:
            priority_key = -r.priority
            version_parts = r.identity._version_key()
            version_key: list[int | str] = []
            for p in version_parts:
                if isinstance(p, int):
                    version_key.append(-p)
                else:
                    version_key.append(p)
            try:
                order_key = self._order.index(r.identity)
            except ValueError:
                order_key = len(self._order)
            return (priority_key, tuple(version_key), order_key)

        sorted_candidates = sorted(candidates, key=sort_key)
        return sorted_candidates[0]

    # ------------------------------------------------------------------
    # Factory access
    # ------------------------------------------------------------------

    @property
    def factory(self) -> AdapterFactory:
        return self._factory

    def create_adapter(self, identity: AdapterIdentity) -> Any:
        """Convenience: look up and create an adapter in one call."""
        return self._factory.create(identity)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        issues: list[str] = []
        for reg in self._registrations.values():
            if not hasattr(reg.adapter_class, "metadata") or not callable(
                getattr(reg.adapter_class, "execute", None)
            ):
                issues.append(
                    f"{reg.name}@{reg.version}: adapter_class does not appear "
                    f"to be a valid ExecutionAdapter subclass"
                )

            if self._capability_registry is not None:
                for cap_name in reg.capability_names:
                    if not self._capability_registry.find_by_name(cap_name):
                        issues.append(
                            f"{reg.name}@{reg.version}: capability "
                            f"{cap_name!r} not found in capability registry"
                        )

            if self._credential_registry is not None:
                for cred_name in reg.credential_descriptor_names:
                    if not self._credential_registry.exists(cred_name):
                        issues.append(
                            f"{reg.name}@{reg.version}: credential descriptor "
                            f"{cred_name!r} not found in credential registry"
                        )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_registration(
        self, identity: AdapterIdentity
    ) -> Optional[AdapterRegistration]:
        return self._registrations.get(identity)

    def clear(self) -> None:
        self._registrations.clear()
        self._order.clear()
