from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from services.adapters.exceptions import CapabilityRegistrationError

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_VERSION_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class CapabilityCategory:
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    SEARCH = "search"
    FILES = "files"
    CRM = "crm"
    WEB = "web"
    AI = "ai"
    SYSTEM = "system"


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise CapabilityRegistrationError(
                f"Parameter name must be a non-empty string, got {self.name!r}"
            )
        if not isinstance(self.type, str) or not self.type.strip():
            raise CapabilityRegistrationError(
                f"Parameter type must be a non-empty string, got {self.type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParameterSpec:
        return cls(
            name=data["name"],
            type=data["type"],
            description=data.get("description", ""),
            required=data.get("required", True),
            default=data.get("default"),
        )


@dataclass(frozen=True)
class ReturnSpec:
    type: str = "object"
    description: str = ""
    fields: tuple[ParameterSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.type:
            raise CapabilityRegistrationError(
                f"Return type must be a non-empty string, got {self.type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "description": self.description,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReturnSpec:
        fields_data = data.get("fields", [])
        return cls(
            type=data.get("type", "object"),
            description=data.get("description", ""),
            fields=tuple(ParameterSpec.from_dict(f) for f in fields_data),
        )


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    display_name: str
    description: str
    category: str
    version: str
    parameters: tuple[ParameterSpec, ...] = ()
    returns: ReturnSpec = field(default_factory=ReturnSpec)
    requires_auth: bool = False
    supports_streaming: bool = False
    supports_batch: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.name or not isinstance(self.name, str):
            errors.append(f"name must be a non-empty string, got {self.name!r}")
        elif not _NAME_PATTERN.match(self.name):
            errors.append(
                f"name {self.name!r} must match pattern {_NAME_PATTERN.pattern!r}"
            )
        if not self.display_name or not isinstance(self.display_name, str):
            errors.append(
                f"display_name must be a non-empty string, got {self.display_name!r}"
            )
        if not self.description or not isinstance(self.description, str):
            errors.append(
                f"description must be a non-empty string, got {self.description!r}"
            )
        if not self.category or not isinstance(self.category, str):
            errors.append(
                f"category must be a non-empty string, got {self.category!r}"
            )
        if not self.version or not isinstance(self.version, str):
            errors.append(
                f"version must be a non-empty string, got {self.version!r}"
            )
        elif not _VERSION_PATTERN.match(self.version):
            errors.append(
                f"version {self.version!r} must match pattern {_VERSION_PATTERN.pattern!r}"
            )

        seen_params: set[str] = set()
        for p in self.parameters:
            if p.name in seen_params:
                errors.append(f"duplicate parameter name {p.name!r}")
            seen_params.add(p.name)

        if errors:
            raise CapabilityRegistrationError(
                f"CapabilityDescriptor validation failed: {'; '.join(errors)}"
            )

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.version}"

    def matches_query(self, query: str) -> bool:
        q = query.lower()
        return (
            q in self.name.lower()
            or q in self.display_name.lower()
            or q in self.description.lower()
            or any(q in t.lower() for t in self.tags)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "parameters": [p.to_dict() for p in self.parameters],
            "returns": self.returns.to_dict(),
            "requires_auth": self.requires_auth,
            "supports_streaming": self.supports_streaming,
            "supports_batch": self.supports_batch,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityDescriptor:
        params_data = data.get("parameters", [])
        returns_data = data.get("returns", {})
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            category=data.get("category", ""),
            version=data.get("version", "1.0.0"),
            parameters=tuple(ParameterSpec.from_dict(p) for p in params_data),
            returns=ReturnSpec.from_dict(returns_data) if returns_data else ReturnSpec(),
            requires_auth=data.get("requires_auth", False),
            supports_streaming=data.get("supports_streaming", False),
            supports_batch=data.get("supports_batch", False),
            tags=tuple(data.get("tags", [])),
        )


@dataclass(frozen=True)
class CapabilityProvider:
    adapter_name: str
    adapter_version: str
    capability_names: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.adapter_name or not isinstance(self.adapter_name, str):
            errors.append(
                f"adapter_name must be a non-empty string, got {self.adapter_name!r}"
            )
        if not self.adapter_version or not isinstance(self.adapter_version, str):
            errors.append(
                f"adapter_version must be a non-empty string, got {self.adapter_version!r}"
            )
        if errors:
            raise CapabilityRegistrationError(
                f"CapabilityProvider validation failed: {'; '.join(errors)}"
            )
