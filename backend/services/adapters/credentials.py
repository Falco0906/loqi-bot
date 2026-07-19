from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from services.adapters.exceptions import ValidationError

_FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_DESCRIPTOR_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


class CredentialType:
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"
    JWT = "jwt"
    CUSTOM = "custom"


def mask_value(value: str, show_first: int = 4, mask_char: str = "*") -> str:
    if not value:
        return ""
    if len(value) <= show_first:
        return mask_char * max(len(value), 8)
    return value[:show_first] + mask_char * (len(value) - show_first)


def mask_sensitive_values(
    values: dict[str, str],
    sensitive_fields: set[str],
    show_first: int = 4,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, val in values.items():
        if key in sensitive_fields and val:
            result[key] = mask_value(val, show_first=show_first)
        else:
            result[key] = val
    return result


@dataclass(frozen=True)
class CredentialField:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    sensitive: bool = True

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValidationError(
                f"CredentialField name must be a non-empty string, got {self.name!r}"
            )
        if not _FIELD_NAME_PATTERN.match(self.name):
            raise ValidationError(
                f"CredentialField name {self.name!r} must match "
                f"pattern {_FIELD_NAME_PATTERN.pattern!r}"
            )
        if not self.type or not isinstance(self.type, str):
            raise ValidationError(
                f"CredentialField type must be a non-empty string, got {self.type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "sensitive": self.sensitive,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialField:
        return cls(
            name=data["name"],
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", True),
            sensitive=data.get("sensitive", True),
        )


@dataclass(frozen=True)
class CredentialDescriptor:
    name: str
    display_name: str
    description: str
    auth_type: str
    required_fields: tuple[CredentialField, ...] = ()
    optional_fields: tuple[CredentialField, ...] = ()
    supports_refresh: bool = False
    supports_expiry: bool = False
    version: str = "1.0.0"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.name or not isinstance(self.name, str):
            errors.append(f"name must be non-empty, got {self.name!r}")
        elif not _DESCRIPTOR_NAME_PATTERN.match(self.name):
            errors.append(
                f"name {self.name!r} must match pattern "
                f"{_DESCRIPTOR_NAME_PATTERN.pattern!r}"
            )
        if not self.display_name or not isinstance(self.display_name, str):
            errors.append(
                f"display_name must be non-empty, got {self.display_name!r}"
            )
        if not self.description or not isinstance(self.description, str):
            errors.append(
                f"description must be non-empty, got {self.description!r}"
            )
        if not self.auth_type or not isinstance(self.auth_type, str):
            errors.append(
                f"auth_type must be non-empty, got {self.auth_type!r}"
            )

        seen: set[str] = set()
        for field in self.required_fields:
            if field.name in seen:
                errors.append(f"duplicate field name {field.name!r}")
            seen.add(field.name)
        for field in self.optional_fields:
            if field.name in seen:
                errors.append(f"duplicate field name {field.name!r}")
            seen.add(field.name)

        if errors:
            raise ValidationError(
                f"CredentialDescriptor validation failed: {'; '.join(errors)}"
            )

    @property
    def all_fields(self) -> list[CredentialField]:
        return [*self.required_fields, *self.optional_fields]

    @property
    def sensitive_field_names(self) -> set[str]:
        return {f.name for f in self.all_fields if f.sensitive}

    @property
    def required_field_names(self) -> set[str]:
        return {f.name for f in self.required_fields}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "auth_type": self.auth_type,
            "required_fields": [f.to_dict() for f in self.required_fields],
            "optional_fields": [f.to_dict() for f in self.optional_fields],
            "supports_refresh": self.supports_refresh,
            "supports_expiry": self.supports_expiry,
            "version": self.version,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialDescriptor:
        required = data.get("required_fields", [])
        optional = data.get("optional_fields", [])
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            auth_type=data.get("auth_type", ""),
            required_fields=tuple(CredentialField.from_dict(f) for f in required),
            optional_fields=tuple(CredentialField.from_dict(f) for f in optional),
            supports_refresh=data.get("supports_refresh", False),
            supports_expiry=data.get("supports_expiry", False),
            version=data.get("version", "1.0.0"),
            tags=tuple(data.get("tags", [])),
        )


@dataclass(frozen=True)
class CredentialReference:
    credential_id: str
    descriptor_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.credential_id or not isinstance(self.credential_id, str):
            raise ValidationError(
                f"credential_id must be non-empty, got {self.credential_id!r}"
            )
        if not self.descriptor_name or not isinstance(self.descriptor_name, str):
            raise ValidationError(
                f"descriptor_name must be non-empty, got {self.descriptor_name!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "descriptor_name": self.descriptor_name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialReference:
        return cls(
            credential_id=data["credential_id"],
            descriptor_name=data["descriptor_name"],
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class CredentialInstance:
    credential_id: str
    descriptor_name: str
    values: dict[str, str]
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.credential_id or not isinstance(self.credential_id, str):
            raise ValidationError(
                f"credential_id must be non-empty, got {self.credential_id!r}"
            )
        if not self.descriptor_name or not isinstance(self.descriptor_name, str):
            raise ValidationError(
                f"descriptor_name must be non-empty, got {self.descriptor_name!r}"
            )
        if not isinstance(self.values, dict):
            raise ValidationError("values must be a dict")

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(self.expires_at.tzinfo) > self.expires_at

    def mask_sensitive(self, descriptor: CredentialDescriptor) -> CredentialInstance:
        sensitive = descriptor.sensitive_field_names
        masked_vals = mask_sensitive_values(self.values, sensitive)
        return CredentialInstance(
            credential_id=self.credential_id,
            descriptor_name=self.descriptor_name,
            values=masked_vals,
            expires_at=self.expires_at,
            created_at=self.created_at,
            metadata=dict(self.metadata),
        )

    def to_safe_dict(self, descriptor: CredentialDescriptor) -> dict[str, Any]:
        safe = self.mask_sensitive(descriptor)
        return {
            "credential_id": safe.credential_id,
            "descriptor_name": safe.descriptor_name,
            "values": dict(safe.values),
            "expires_at": safe.expires_at.isoformat() if safe.expires_at else None,
            "created_at": safe.created_at.isoformat() if safe.created_at else None,
            "metadata": dict(safe.metadata),
        }

    def __repr__(self) -> str:
        return (
            f"CredentialInstance(credential_id={self.credential_id!r}, "
            f"descriptor_name={self.descriptor_name!r}, "
            f"values={{...}}, "
            f"expires_at={self.expires_at!r})"
        )

    def __str__(self) -> str:
        return (
            f"CredentialInstance({self.credential_id}, "
            f"{self.descriptor_name}, "
            f"{len(self.values)} fields)"
        )
