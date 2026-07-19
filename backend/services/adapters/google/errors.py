from __future__ import annotations

import json
from typing import Any

from services.adapters.http.exceptions import HttpError


class GoogleApiError(HttpError):
    """Base exception for all Google API adapter failures."""


class GoogleAuthenticationError(GoogleApiError):
    """Raised when OAuth2 credentials are missing, expired, or invalid."""


class GooglePermissionError(GoogleApiError):
    """Raised when the authenticated user lacks access to the resource."""


class GoogleResourceNotFoundError(GoogleApiError):
    """Raised when a requested Google resource does not exist."""


class GoogleConflictError(GoogleApiError):
    """Raised when a request conflicts with the current state (409)."""


class GoogleQuotaExceededError(GoogleApiError):
    """Raised when the API quota is exhausted (429)."""


class GoogleRateLimitError(GoogleApiError):
    """Raised when rate-limited by the Google API."""


class GoogleValidationError(GoogleApiError):
    """Raised when a request parameter is invalid (400)."""


class GoogleApiErrorInfo:
    """Structured information parsed from a Google API error response.

    The Google API returns errors in this format:
    .. code-block:: json
        {
            "error": {
                "code": 400,
                "message": "Bad Request",
                "status": "INVALID_ARGUMENT",
                "errors": [{
                    "domain": "global",
                    "reason": "invalid",
                    "message": "Invalid value"
                }]
            }
        }
    """

    def __init__(
        self,
        code: int = 0,
        message: str = "",
        status: str = "",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.errors = errors or []

    def to_exception(self) -> GoogleApiError:
        if self.status in ("UNAUTHENTICATED",) or self.code == 401:
            return GoogleAuthenticationError(self.message)
        if self.status in ("PERMISSION_DENIED",) or self.code == 403:
            return GooglePermissionError(self.message)
        if self.status in ("NOT_FOUND",) or self.code == 404:
            return GoogleResourceNotFoundError(self.message)
        if self.status in ("CONFLICT", "ALREADY_EXISTS") or self.code == 409:
            return GoogleConflictError(self.message)
        if self.status in ("RATE_LIMIT_EXCEEDED",):
            return GoogleRateLimitError(self.message)
        if self.status in ("RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED") or self.code == 429:
            return GoogleQuotaExceededError(self.message)
        if self.code == 400 or self.status in (
            "INVALID_ARGUMENT", "FAILED_PRECONDITION", "INVALID_REQUEST",
        ):
            return GoogleValidationError(self.message)
        return GoogleApiError(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "errors": list(self.errors),
        }


def parse_google_error_body(body: str) -> GoogleApiErrorInfo | None:
    """Parse a Google API JSON error response body.

    Returns None if the body cannot be parsed or does not contain
    a valid Google error payload.
    """
    if not body:
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    error_data = data.get("error")
    if not isinstance(error_data, dict):
        return None
    return GoogleApiErrorInfo(
        code=error_data.get("code", 0),
        message=error_data.get("message", ""),
        status=error_data.get("status", ""),
        errors=error_data.get("errors", []),
    )


def classify_google_status_code(status_code: int) -> type[GoogleApiError]:
    """Map an HTTP status code to a GoogleApiError subclass."""
    mapping: dict[int, type[GoogleApiError]] = {
        400: GoogleValidationError,
        401: GoogleAuthenticationError,
        403: GooglePermissionError,
        404: GoogleResourceNotFoundError,
        409: GoogleConflictError,
        429: GoogleQuotaExceededError,
    }
    return mapping.get(status_code, GoogleApiError)
