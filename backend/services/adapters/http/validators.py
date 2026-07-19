from __future__ import annotations

from services.adapters.http.exceptions import (
    InvalidContentTypeError,
    InvalidHeaderError,
    InvalidMethodError,
    InvalidTimeoutError,
    InvalidUrlError,
)
from services.adapters.http.models import SUPPORTED_METHODS, HttpRequest

_VALID_URL_SCHEMES = frozenset({"http", "https"})


def validate_url(url: str) -> None:
    """Validate a URL string.

    Rules:
        - Must be a non-empty string.
        - Must start with http:// or https://.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidUrlError(f"URL must be a non-empty string, got {url!r}")
    url = url.strip()
    if "://" not in url:
        raise InvalidUrlError(f"URL must include a scheme (e.g. https://), got {url!r}")
    scheme = url.split("://")[0].lower()
    if scheme not in _VALID_URL_SCHEMES:
        raise InvalidUrlError(
            f"URL scheme must be http or https, got {scheme!r}"
        )


def validate_method(method: str) -> None:
    """Validate an HTTP method string.

    Rules:
        - Must be a non-empty string.
        - Must be one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.
    """
    if not isinstance(method, str) or not method.strip():
        raise InvalidMethodError(
            f"Method must be a non-empty string, got {method!r}"
        )
    if method.upper() not in SUPPORTED_METHODS:
        raise InvalidMethodError(
            f"Unsupported method {method!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_METHODS))}"
        )


def validate_timeout(timeout: float) -> None:
    """Validate a timeout value.

    Rules:
        - Must be a positive number (int or float).
    """
    if not isinstance(timeout, (int, float)):
        raise InvalidTimeoutError(
            f"Timeout must be a number, got {type(timeout).__name__}"
        )
    if timeout <= 0:
        raise InvalidTimeoutError(
            f"Timeout must be positive, got {timeout}"
        )


def validate_headers(headers: dict[str, str] | None) -> None:
    """Validate request headers.

    Rules:
        - If not None, must be a dict.
        - All keys must be non-empty strings.
        - All values must be strings.
    """
    if headers is None:
        return
    if not isinstance(headers, dict):
        raise InvalidHeaderError(
            f"Headers must be a dict, got {type(headers).__name__}"
        )
    seen: set[str] = set()
    for key, value in headers.items():
        if not isinstance(key, str) or not key.strip():
            raise InvalidHeaderError(
                f"Header key must be a non-empty string, got {key!r}"
            )
        if not isinstance(value, str):
            raise InvalidHeaderError(
                f"Header value for {key!r} must be a string, got {type(value).__name__}"
            )
        lower = key.lower()
        if lower in seen:
            raise InvalidHeaderError(
                f"Duplicate header key {key!r} (case-insensitive)"
            )
        seen.add(lower)


def validate_content_type(content_type: str) -> None:
    """Validate a content type string.

    Rules:
        - If non-empty, must not be just whitespace.
    """
    if content_type and not content_type.strip():
        raise InvalidContentTypeError(
            f"Content type must not be empty or whitespace-only"
        )


def validate_request(request: HttpRequest) -> None:
    """Validate an entire HttpRequest, raising on first failure.

    This is a convenience method that runs all validations in order.
    """
    validate_url(request.url)
    validate_method(request.method)
    validate_timeout(request.timeout)
    validate_headers(request.headers)
    validate_content_type(request.content_type)
