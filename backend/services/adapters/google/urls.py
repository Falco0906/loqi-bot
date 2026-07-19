from __future__ import annotations

from services.adapters.google.services import GoogleServiceDescriptor, GoogleServiceRegistry

_DEFAULT_REGISTRY: GoogleServiceRegistry | None = None


def _get_registry() -> GoogleServiceRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = GoogleServiceRegistry.with_defaults()
    return _DEFAULT_REGISTRY


def build_google_url(
    service: str,
    resource: str,
    version: str = "",
    registry: GoogleServiceRegistry | None = None,
) -> str:
    """Build a Google API URL for a service, version, and resource path.

    Args:
        service: The service name (e.g. ``"gmail"``, ``"drive"``).
        resource: The resource path (e.g. ``"users/me/messages"``).
        version: API version override (default: service's default_version).
        registry: Optional service registry (default: global registry).

    Returns:
        The full Google API URL.
    """
    reg = registry or _get_registry()
    descriptor = reg.require(service)
    return descriptor.build_url(version=version, resource=resource)


def register_google_service(
    descriptor: GoogleServiceDescriptor,
    registry: GoogleServiceRegistry | None = None,
) -> None:
    """Register a custom Google service descriptor."""
    reg = registry or _get_registry()
    reg.register(descriptor)


# -- Convenience helpers for well-known Google services --
# Each returns the resource path suitable for passing as the
# ``resource`` argument to ``GoogleApiAdapter.execute()``.

def gmail(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    """Build params for a Gmail API call.

    Example::

        adapter.execute(context_for_params(gmail("users/me/messages")))
    """
    reg = service_registry or _get_registry()
    desc = reg.require("gmail")
    return {"service": "gmail", "resource": resource, "version": desc.default_version}


def calendar(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("calendar")
    return {"service": "calendar", "resource": resource, "version": desc.default_version}


def drive(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("drive")
    return {"service": "drive", "resource": resource, "version": desc.default_version}


def docs(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("docs")
    return {"service": "docs", "resource": resource, "version": desc.default_version}


def sheets(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("sheets")
    return {"service": "sheets", "resource": resource, "version": desc.default_version}


def people(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("people")
    return {"service": "people", "resource": resource, "version": desc.default_version}


def tasks(resource: str, service_registry: GoogleServiceRegistry | None = None) -> dict[str, str]:
    reg = service_registry or _get_registry()
    desc = reg.require("tasks")
    return {"service": "tasks", "resource": resource, "version": desc.default_version}


_ALL_HELPERS = {
    "gmail": gmail,
    "calendar": calendar,
    "drive": drive,
    "docs": docs,
    "sheets": sheets,
    "people": people,
    "tasks": tasks,
}
