from services.adapters.adapter_factory import AdapterFactory
from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
from services.adapters.adapter_registry import AdapterRegistry
from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.adapter_context import AdapterContext
from services.adapters.exceptions import (
    AdapterDisabledError,
    AdapterError,
    AdapterExecutionError,
    AdapterNotFoundError,
    AdapterRegistrationError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    FatalAdapterError,
    PermissionError,
    RateLimitError,
    ResourceNotFoundError,
    TransientAdapterError,
    ValidationError,
)
from services.adapters.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityProvider,
    ParameterSpec,
    ReturnSpec,
)
from services.adapters.capability_registry import CapabilityRegistry
from services.adapters.credential_registry import CredentialRegistry
from services.adapters.credential_resolver import CredentialResolver
from services.adapters.credentials import (
    CredentialDescriptor,
    CredentialField,
    CredentialInstance,
    CredentialReference,
    CredentialType,
    mask_sensitive_values,
    mask_value,
)
from services.adapters.exceptions import (
    CapabilityRegistrationError,
    CredentialNotFoundError,
)
from services.adapters.protocols import (
    CapabilityReporter,
    HealthCheckable,
    Validator,
)

__all__ = [
    "AdapterContext",
    "AdapterDisabledError",
    "AdapterError",
    "AdapterExecutionError",
    "AdapterFactory",
    "AdapterIdentity",
    "AdapterMetadata",
    "AdapterNotFoundError",
    "AdapterRegistration",
    "AdapterRegistrationError",
    "AdapterRegistry",
    "AdapterResult",
    "AuthenticationError",
    "AuthorizationError",
    "CapabilityCategory",
    "CapabilityDescriptor",
    "CapabilityProvider",
    "CapabilityRegistrationError",
    "CapabilityRegistry",
    "CapabilityReporter",
    "ConfigurationError",
    "CredentialDescriptor",
    "CredentialField",
    "CredentialInstance",
    "CredentialNotFoundError",
    "CredentialReference",
    "CredentialRegistry",
    "CredentialResolver",
    "CredentialType",
    "ExecutionAdapter",
    "FatalAdapterError",
    "HealthCheckable",
    "mask_sensitive_values",
    "mask_value",
    "ParameterSpec",
    "PermissionError",
    "RateLimitError",
    "ResourceNotFoundError",
    "ReturnSpec",
    "TransientAdapterError",
    "UsageInfo",
    "ValidationError",
    "Validator",
]
