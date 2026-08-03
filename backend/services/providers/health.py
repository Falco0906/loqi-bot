from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class ProviderStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    ok: bool
    provider_id: str
    checked_at: str = ""
    status: ProviderStatus = ProviderStatus.UNKNOWN
    latency_ms: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()
        if isinstance(self.status, str):
            try:
                self.status = ProviderStatus(self.status)
            except ValueError:
                self.status = ProviderStatus.UNKNOWN
        if self.ok and self.status == ProviderStatus.UNKNOWN:
            self.status = ProviderStatus.ONLINE
        elif not self.ok and self.status == ProviderStatus.UNKNOWN:
            self.status = ProviderStatus.ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider_id": self.provider_id,
            "checked_at": self.checked_at,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "details": self.details,
        }


class HealthCheckable(Protocol):
    def health(self) -> HealthCheckResult:
        ...


class HealthMonitor:
    """Tracks provider health over time.

    Maintains the latest health result per provider and
    tracks consecutive failures for degradation detection.
    """

    def __init__(self) -> None:
        self._latest: dict[str, HealthCheckResult] = {}
        self._failures: dict[str, int] = {}
        self._consecutive_failures: dict[str, int] = {}

    def record(self, result: HealthCheckResult) -> HealthCheckResult:
        self._latest[result.provider_id] = result
        if not result.ok:
            self._consecutive_failures[result.provider_id] = (
                self._consecutive_failures.get(result.provider_id, 0) + 1
            )
        else:
            self._consecutive_failures[result.provider_id] = 0
        return result

    def latest(self, provider_id: str) -> HealthCheckResult | None:
        return self._latest.get(provider_id)

    def latest_status(self, provider_id: str) -> ProviderStatus:
        result = self._latest.get(provider_id)
        if result is None:
            return ProviderStatus.UNKNOWN
        return result.status

    def is_online(self, provider_id: str) -> bool:
        result = self._latest.get(provider_id)
        if result is None:
            return False
        return result.ok

    def consecutive_failures(self, provider_id: str) -> int:
        return self._consecutive_failures.get(provider_id, 0)

    def summary(self) -> dict[str, Any]:
        return {
            pid: r.to_dict()
            for pid, r in self._latest.items()
        }

    def all_ok(self) -> bool:
        return all(r.ok for r in self._latest.values()) if self._latest else True

    def _execute_health(self, provider: HealthCheckable) -> HealthCheckResult:
        start = time.time()
        try:
            result = provider.health()
            elapsed = (time.time() - start) * 1000
            if isinstance(result, dict):
                ok = result.get("ok", False)
                return HealthCheckResult(
                    ok=ok,
                    provider_id=result.get("provider_id", ""),
                    latency_ms=elapsed,
                    error=result.get("error"),
                    details={k: v for k, v in result.items() if k not in ("ok", "provider_id", "error")},
                )
            if isinstance(result, HealthCheckResult):
                result.latency_ms = elapsed
                return result
            return HealthCheckResult(
                ok=False,
                provider_id="",
                latency_ms=elapsed,
                error="health() returned unexpected type",
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return HealthCheckResult(
                ok=False,
                provider_id="",
                latency_ms=elapsed,
                error=str(e),
            )

    def check(self, provider: HealthCheckable, provider_id: str) -> HealthCheckResult:
        result = self._execute_health(provider)
        result.provider_id = provider_id
        return self.record(result)

    def check_all(self, providers: dict[str, HealthCheckable]) -> dict[str, HealthCheckResult]:
        results: dict[str, HealthCheckResult] = {}
        for pid, provider in providers.items():
            results[pid] = self.check(provider, pid)
        return results
