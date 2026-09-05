from .base_provider import BaseProvider
from .provider_factory import get_provider, get_provider_capabilities
from .synthetic_provider import SyntheticProvider
from .apollo_provider import ApolloProvider

# New provider platform (Phase 9)
from .capabilities import Capability, CapabilitySet
from .health import HealthCheckResult, HealthMonitor, ProviderStatus
from .interface import Provider, ProviderSetupError, ProviderSyncError, ProviderPublishError
from .models import (
    CompanySize,
    ConversationStage,
    EmailDeliveryStatus,
    GrowthStage,
    MeetingStatus,
    ProviderCompany,
    ProviderContact,
    ProviderContactRole,
    ProviderConversation,
    ProviderDocument,
    ProviderEmail,
    ProviderLead,
    ProviderMeeting,
    ProviderMessage,
)
from .oauth import (
    InMemoryTokenStore,
    OAuthFlow,
    OAuthToken,
    OAuthTokenStore,
    TokenManager,
    TokenRefreshError,
)
from .registry import ProviderRegistry, get_registry

__all__ = [
    # Legacy lead provider exports
    "BaseProvider",
    "get_provider",
    "get_provider_capabilities",
    "SyntheticProvider",
    "ApolloProvider",
    # New provider platform
    "Capability",
    "CapabilitySet",
    "HealthCheckResult",
    "HealthMonitor",
    "ProviderStatus",
    "Provider",
    "ProviderSetupError",
    "ProviderSyncError",
    "ProviderPublishError",
    "CompanySize",
    "ConversationStage",
    "EmailDeliveryStatus",
    "GrowthStage",
    "MeetingStatus",
    "ProviderCompany",
    "ProviderContact",
    "ProviderContactRole",
    "ProviderConversation",
    "ProviderDocument",
    "ProviderEmail",
    "ProviderLead",
    "ProviderMeeting",
    "ProviderMessage",
    "InMemoryTokenStore",
    "OAuthFlow",
    "OAuthToken",
    "OAuthTokenStore",
    "TokenManager",
    "TokenRefreshError",
    "ProviderRegistry",
    "get_registry",
]
