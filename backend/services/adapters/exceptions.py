class AdapterError(Exception):
    """Base exception for all adapter-related failures."""


class ConfigurationError(AdapterError):
    """Raised when an adapter is misconfigured."""


class ValidationError(AdapterError):
    """Raised when input validation fails."""


class AuthenticationError(AdapterError):
    """Raised when authentication credentials are missing or invalid."""


class AuthorizationError(AdapterError):
    """Raised when the authenticated entity lacks permission."""


class PermissionError(AdapterError):
    """Raised when access to a resource is denied."""


class RateLimitError(AdapterError):
    """Raised when an API rate limit is exceeded. Typically retryable."""


class ResourceNotFoundError(AdapterError):
    """Raised when a requested resource does not exist."""


class TransientAdapterError(AdapterError):
    """Temporary failure that may succeed on retry (e.g., network timeout)."""


class FatalAdapterError(AdapterError):
    """Non-recoverable failure that should never be retried."""


class AdapterExecutionError(AdapterError):
    """Unexpected error during adapter execution (e.g., bug, invariant violation)."""


class CapabilityRegistrationError(ValidationError):
    """Raised when capability registration fails (duplicate or invalid)."""


class CredentialNotFoundError(AuthenticationError):
    """Raised when a credential reference cannot be resolved."""


class AdapterRegistrationError(ValidationError):
    """Raised when adapter registration fails."""


class AdapterNotFoundError(ResourceNotFoundError):
    """Raised when an adapter or identity is not registered."""


class AdapterDisabledError(AdapterError):
    """Raised when attempting to create a disabled adapter."""
