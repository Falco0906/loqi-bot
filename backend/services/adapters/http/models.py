from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from services.adapters.http.exceptions import DeserializationError, InvalidUrlError

SUPPORTED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class HttpRequest:
    """Immutable HTTP request model."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: Any = None
    timeout: float = 30.0
    content_type: str = ""
    accept: str = ""

    def __post_init__(self) -> None:
        _validate_method(self.method)
        _validate_url(self.url)
        _validate_timeout(self.timeout)


@dataclass(frozen=True)
class HttpResponse:
    """Immutable HTTP response model."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed: float = 0.0
    content_type: str = ""

    @property
    def success(self) -> bool:
        return self.status_code < 400

    @property
    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DeserializationError(
                f"Failed to parse response body as JSON: {exc}",
            ) from exc

    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    def is_server_error(self) -> bool:
        return 500 <= self.status_code < 600

    def __repr__(self) -> str:
        return (
            f"HttpResponse(status_code={self.status_code}, "
            f"content_type={self.content_type!r}, "
            f"body={len(self.body)} bytes)"
        )


def _validate_method(method: str) -> None:
    from services.adapters.http.exceptions import InvalidMethodError

    if not isinstance(method, str) or not method:
        raise InvalidMethodError(f"Method must be a non-empty string, got {method!r}")
    if method.upper() not in SUPPORTED_METHODS:
        raise InvalidMethodError(
            f"Unsupported method {method!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_METHODS))}"
        )


def _validate_url(url: str) -> None:
    if not isinstance(url, str) or not url:
        raise InvalidUrlError(f"URL must be a non-empty string, got {url!r}")
    if not url.startswith(("http://", "https://")):
        raise InvalidUrlError(
            f"URL must start with http:// or https://, got {url!r}"
        )


def _validate_timeout(timeout: float) -> None:
    from services.adapters.http.exceptions import InvalidTimeoutError

    if not isinstance(timeout, (int, float)):
        raise InvalidTimeoutError(
            f"Timeout must be a positive number, got {timeout!r}"
        )
    if timeout <= 0:
        raise InvalidTimeoutError(
            f"Timeout must be positive, got {timeout}"
        )
