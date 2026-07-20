from __future__ import annotations


class CapabilityException(Exception):
    def __init__(self, message: str = "A capability error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class CapabilityNotFound(CapabilityException):
    def __init__(self, slug: str = "") -> None:
        msg = f"Capability not found: {slug}" if slug else "Capability not found"
        super().__init__(msg)
        self.slug = slug


class CapabilityNotRegistered(CapabilityException):
    def __init__(self, slug: str = "") -> None:
        msg = f"Capability not registered: {slug}" if slug else "Capability not registered"
        super().__init__(msg)
        self.slug = slug


class CapabilityAlreadyEnabled(CapabilityException):
    def __init__(self, slug: str = "", organization_id: str = "") -> None:
        msg = f"Capability {slug} is already enabled for organization {organization_id}"
        super().__init__(msg)
        self.slug = slug
        self.organization_id = organization_id


class CapabilityAlreadyDisabled(CapabilityException):
    def __init__(self, slug: str = "", organization_id: str = "") -> None:
        msg = f"Capability {slug} is already disabled for organization {organization_id}"
        super().__init__(msg)
        self.slug = slug
        self.organization_id = organization_id


class DuplicateCapabilityRegistration(CapabilityException):
    def __init__(self, slug: str = "") -> None:
        msg = f"Capability already registered: {slug}" if slug else "Capability already registered"
        super().__init__(msg)
        self.slug = slug
