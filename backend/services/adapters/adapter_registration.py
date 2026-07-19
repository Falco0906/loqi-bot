from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.adapters.exceptions import AdapterRegistrationError

if TYPE_CHECKING:
    from services.adapters.base_adapter import ExecutionAdapter
    from services.adapters.models import AdapterMetadata

_IDENTITY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


@dataclass(frozen=True)
class AdapterIdentity:
    name: str
    version: str

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.name or not isinstance(self.name, str):
            errors.append(f"name must be non-empty string, got {self.name!r}")
        elif not _IDENTITY_NAME_PATTERN.match(self.name):
            errors.append(
                f"name {self.name!r} must match pattern "
                f"{_IDENTITY_NAME_PATTERN.pattern!r}"
            )
        if not self.version or not isinstance(self.version, str):
            errors.append(f"version must be non-empty string, got {self.version!r}")
        if errors:
            raise AdapterRegistrationError(
                f"AdapterIdentity validation failed: {'; '.join(errors)}"
            )

    def __lt__(self, other: AdapterIdentity) -> bool:
        if not isinstance(other, AdapterIdentity):
            return NotImplemented
        return (self.name.lower(), self._version_key()) < (
            other.name.lower(),
            other._version_key(),
        )

    def _version_key(self) -> tuple[int | str, ...]:
        parts = self.version.replace("-", ".").replace("_", ".").split(".")
        result: list[int | str] = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(p)
        return tuple(result)


@dataclass(frozen=True)
class AdapterRegistration:
    identity: AdapterIdentity
    adapter_class: type[Any]
    metadata: Any  # AdapterMetadata
    capability_names: tuple[str, ...] = ()
    credential_descriptor_names: tuple[str, ...] = ()
    priority: int = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.identity, AdapterIdentity):
            errors.append(
                f"identity must be AdapterIdentity, got {type(self.identity).__name__}"
            )
        if not isinstance(self.adapter_class, type):
            errors.append(
                f"adapter_class must be a class, got {type(self.adapter_class).__name__}"
            )
        if not isinstance(self.priority, int):
            errors.append(
                f"priority must be int, got {type(self.priority).__name__}"
            )
        for name in self.capability_names:
            if not isinstance(name, str) or not name:
                errors.append(f"capability_names must contain non-empty strings")
                break
        for name in self.credential_descriptor_names:
            if not isinstance(name, str) or not name:
                errors.append(
                    f"credential_descriptor_names must contain non-empty strings"
                )
                break
        if errors:
            raise AdapterRegistrationError(
                f"AdapterRegistration validation failed: {'; '.join(errors)}"
            )

    @property
    def name(self) -> str:
        return self.identity.name

    @property
    def version(self) -> str:
        return self.identity.version

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "adapter_class": f"{self.adapter_class.__module__}.{self.adapter_class.__qualname__}",
            "metadata": self.metadata.to_dict() if hasattr(self.metadata, "to_dict") else {},
            "capability_names": list(self.capability_names),
            "credential_descriptor_names": list(self.credential_descriptor_names),
            "priority": self.priority,
            "enabled": self.enabled,
        }
