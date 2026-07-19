from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class AdapterMetadata:
    """Immutable description of an adapter's identity and capabilities.

    The runtime inspects metadata to understand what an adapter can do
    without instantiating it or calling any method.
    """

    name: str
    display_name: str
    version: str
    description: str
    author: str = ""
    supported_operations: tuple[str, ...] = ()
    requires_auth: bool = False
    supports_streaming: bool = False
    supports_batch: bool = False
    supports_retry: bool = True
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "supported_operations": list(self.supported_operations),
            "requires_auth": self.requires_auth,
            "supports_streaming": self.supports_streaming,
            "supports_batch": self.supports_batch,
            "supports_retry": self.supports_retry,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdapterMetadata:
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            supported_operations=tuple(data.get("supported_operations", [])),
            requires_auth=data.get("requires_auth", False),
            supports_streaming=data.get("supports_streaming", False),
            supports_batch=data.get("supports_batch", False),
            supports_retry=data.get("supports_retry", True),
            tags=tuple(data.get("tags", [])),
        )


@dataclass(frozen=True)
class UsageInfo:
    """Immutable usage/cost tracking associated with an adapter execution."""

    tokens_in: int = 0
    tokens_out: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    """Structured result returned by every adapter execution.

    Success and failure are both represented through the same model.
    Downstream consumers inspect ``success`` rather than relying on
    exceptions for control flow.
    """

    success: bool
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    usage: UsageInfo = field(default_factory=UsageInfo)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "metadata": self.metadata,
            "warnings": list(self.warnings),
            "usage": {
                "tokens_in": self.usage.tokens_in,
                "tokens_out": self.usage.tokens_out,
                "api_calls": self.usage.api_calls,
                "cost_usd": self.usage.cost_usd,
                "latency_ms": self.usage.latency_ms,
                "extra": dict(self.usage.extra),
            },
            "error": self.error,
        }

    @classmethod
    def success_result(
        cls,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        usage: UsageInfo | None = None,
    ) -> AdapterResult:
        return cls(
            success=True,
            data=data,
            metadata=metadata or {},
            usage=usage or UsageInfo(),
        )

    @classmethod
    def failure_result(
        cls,
        error: str,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> AdapterResult:
        return cls(
            success=False,
            error=error,
            data=data,
            metadata=metadata or {},
            warnings=warnings or [],
        )
