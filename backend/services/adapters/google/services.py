from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.adapters.google.errors import GoogleApiError


@dataclass(frozen=True)
class GoogleServiceDescriptor:
    """Immutable metadata describing a Google REST API service.

    Each Google service (Gmail, Calendar, Drive, etc.) has a
    descriptor that defines its base URL, default API version,
    OAuth scopes, and supported features.
    """

    name: str
    base_url: str
    default_version: str
    scopes: tuple[str, ...] = ()
    supports_pagination: bool = True
    supports_batch: bool = False

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.name or not isinstance(self.name, str):
            errors.append(f"name must be a non-empty string, got {self.name!r}")
        if not self.base_url or not isinstance(self.base_url, str):
            errors.append(f"base_url must be a non-empty string, got {self.base_url!r}")
        if not self.default_version or not isinstance(self.default_version, str):
            errors.append(
                f"default_version must be a non-empty string, "
                f"got {self.default_version!r}"
            )
        if errors:
            raise GoogleApiError(
                f"GoogleServiceDescriptor validation failed: {'; '.join(errors)}"
            )

    def build_url(self, version: str = "", resource: str = "") -> str:
        """Build a full Google API URL for this service.

        Pattern: ``{base_url}/{name}/{version}/{resource}``

        Example for gmail/v1/users/me/messages::

            https://gmail.googleapis.com/gmail/v1/users/me/messages
        """
        v = version or self.default_version
        parts = [self.base_url.rstrip("/"), self.name, v]
        if resource:
            parts.append(resource.lstrip("/"))
        return "/".join(parts)


DEFAULT_GOOGLE_SERVICES: list[GoogleServiceDescriptor] = [
    GoogleServiceDescriptor(
        name="gmail",
        base_url="https://gmail.googleapis.com",
        default_version="v1",
        scopes=("https://www.googleapis.com/auth/gmail.modify",),
    ),
    GoogleServiceDescriptor(
        name="calendar",
        base_url="https://www.googleapis.com",
        default_version="v3",
        scopes=("https://www.googleapis.com/auth/calendar",),
    ),
    GoogleServiceDescriptor(
        name="drive",
        base_url="https://www.googleapis.com",
        default_version="v3",
        scopes=("https://www.googleapis.com/auth/drive",),
    ),
    GoogleServiceDescriptor(
        name="docs",
        base_url="https://docs.googleapis.com",
        default_version="v1",
        scopes=("https://www.googleapis.com/auth/documents",),
    ),
    GoogleServiceDescriptor(
        name="sheets",
        base_url="https://sheets.googleapis.com",
        default_version="v4",
        scopes=("https://www.googleapis.com/auth/spreadsheets",),
    ),
    GoogleServiceDescriptor(
        name="people",
        base_url="https://people.googleapis.com",
        default_version="v1",
        scopes=("https://www.googleapis.com/auth/contacts",),
    ),
    GoogleServiceDescriptor(
        name="tasks",
        base_url="https://tasks.googleapis.com",
        default_version="v1",
        scopes=("https://www.googleapis.com/auth/tasks",),
    ),
]


class GoogleServiceRegistry:
    """Registry of Google service descriptors.

    Services are looked up by name.  The registry is pre-populated
    with default Google services but can be extended at runtime.
    """

    def __init__(self) -> None:
        self._services: dict[str, GoogleServiceDescriptor] = {}

    def register(self, descriptor: GoogleServiceDescriptor) -> None:
        if descriptor.name in self._services:
            raise GoogleApiError(
                f"Google service {descriptor.name!r} is already registered"
            )
        self._services[descriptor.name] = descriptor

    def get(self, name: str) -> GoogleServiceDescriptor | None:
        return self._services.get(name)

    def require(self, name: str) -> GoogleServiceDescriptor:
        descriptor = self.get(name)
        if descriptor is None:
            raise GoogleApiError(
                f"Unknown Google service {name!r}. "
                f"Registered: {', '.join(sorted(self._services))}"
            )
        return descriptor

    def list_services(self) -> list[GoogleServiceDescriptor]:
        return list(self._services.values())

    def unregister(self, name: str) -> None:
        if name not in self._services:
            raise GoogleApiError(
                f"Google service {name!r} is not registered"
            )
        del self._services[name]

    def clear(self) -> None:
        self._services.clear()

    def count(self) -> int:
        return len(self._services)

    @classmethod
    def with_defaults(cls) -> GoogleServiceRegistry:
        registry = cls()
        for svc in DEFAULT_GOOGLE_SERVICES:
            registry._services[svc.name] = svc
        return registry
