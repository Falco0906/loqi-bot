from __future__ import annotations

from typing import Optional

from services.adapters.credentials import CredentialDescriptor
from services.adapters.exceptions import ValidationError


class CredentialRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, CredentialDescriptor] = {}

    # ------------------------------------------------------------------
    # Descriptor management
    # ------------------------------------------------------------------

    def register(self, descriptor: CredentialDescriptor) -> None:
        if descriptor.name in self._descriptors:
            raise ValidationError(
                f"Credential descriptor {descriptor.name!r} is already registered"
            )
        self._descriptors[descriptor.name] = descriptor

    def unregister(self, name: str) -> None:
        if name not in self._descriptors:
            raise ValidationError(
                f"Credential descriptor {name!r} is not registered"
            )
        del self._descriptors[name]

    def get(self, name: str) -> Optional[CredentialDescriptor]:
        return self._descriptors.get(name)

    def exists(self, name: str) -> bool:
        return name in self._descriptors

    def find_by_auth_type(self, auth_type: str) -> list[CredentialDescriptor]:
        return [
            d for d in self._descriptors.values()
            if d.auth_type.lower() == auth_type.lower()
        ]

    def find_by_tag(self, *tags: str) -> list[CredentialDescriptor]:
        if not tags:
            return self.list_all()
        lower_tags = frozenset(t.lower() for t in tags)
        return [
            d for d in self._descriptors.values()
            if lower_tags.issubset(frozenset(t.lower() for t in d.tags))
        ]

    def list_all(self) -> list[CredentialDescriptor]:
        return list(self._descriptors.values())

    def count(self) -> int:
        return len(self._descriptors)

    def clear(self) -> None:
        self._descriptors.clear()
