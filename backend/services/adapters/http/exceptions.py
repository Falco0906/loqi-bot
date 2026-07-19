from services.adapters.exceptions import AdapterError, TransientAdapterError, ValidationError


class HttpError(AdapterError):
    """Base exception for all HTTP adapter failures."""


class InvalidUrlError(ValidationError, HttpError):
    """Raised when a URL fails validation."""


class InvalidMethodError(ValidationError, HttpError):
    """Raised when an HTTP method is unsupported."""


class InvalidTimeoutError(ValidationError, HttpError):
    """Raised when a timeout value is invalid."""


class InvalidHeaderError(ValidationError, HttpError):
    """Raised when request headers are invalid."""


class InvalidContentTypeError(ValidationError, HttpError):
    """Raised when a content type is unsupported."""


class RequestTimeoutError(TransientAdapterError, HttpError):
    """Raised when a request exceeds the timeout."""


class ConnectionError(TransientAdapterError, HttpError):
    """Raised when a connection cannot be established."""


class DnsError(TransientAdapterError, HttpError):
    """Raised when a DNS lookup fails."""


class SerializationError(ValidationError, HttpError):
    """Raised when request body serialization fails."""


class DeserializationError(HttpError):
    """Raised when response body deserialization fails."""


class HttpStatusError(HttpError):
    """Raised for HTTP error status codes (4xx or 5xx).

    Carries the status code and response body for inspection.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        super().__init__(message)
