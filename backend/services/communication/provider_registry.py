"""Provider Registry — manages provider lifecycle.

Register, get, list, sync, disconnect providers.
Executor never imports Gmail directly.
It only asks registry.get(GMAIL).
"""

from typing import Optional, Type

from services.communication.provider_base import CommunicationProviderBase
from services.communication.provider_models import ProviderType, CommunicationProvider, SyncResult


_registry: dict[ProviderType, Type[CommunicationProviderBase]] = {}
_instances: dict[str, CommunicationProviderBase] = {}


def register_provider(provider_class: Type[CommunicationProviderBase]) -> None:
    """Register a provider implementation class."""
    _registry[provider_class.provider_type] = provider_class


def get_provider_class(provider_type: ProviderType) -> Optional[Type[CommunicationProviderBase]]:
    """Get the registered class for a provider type."""
    return _registry.get(provider_type)


def get_provider(provider_id: str) -> Optional[CommunicationProviderBase]:
    """Get a running provider instance by its database ID."""
    return _instances.get(provider_id)


def instantiate_provider(provider_type: ProviderType, **kwargs) -> Optional[CommunicationProviderBase]:
    """Create a new provider instance from the registry."""
    cls = get_provider_class(provider_type)
    if not cls:
        return None
    return cls(**kwargs)


def register_instance(provider_id: str, instance: CommunicationProviderBase) -> None:
    """Register a running provider instance."""
    _instances[provider_id] = instance


def remove_instance(provider_id: str) -> None:
    """Remove a provider instance."""
    _instances.pop(provider_id, None)


def list_providers() -> dict[str, CommunicationProviderBase]:
    """List all running provider instances."""
    return dict(_instances)


def list_registered_types() -> list[ProviderType]:
    """List all registered provider types."""
    return list(_registry.keys())


def sync_provider(provider_id: str, cursor: str = "") -> Optional[SyncResult]:
    """Sync a provider by its instance ID."""
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.sync(cursor=cursor)


def disconnect_provider(provider_id: str) -> bool:
    """Disconnect a provider and remove it from EVERY runtime store/registry.

    Removes the communication-store record, the provider_registry instance,
    and any outbound provider instance so the Settings API (which aggregates
    from the communication store) never surfaces a disconnected ghost account.
    """
    instance = get_provider(provider_id)
    if not instance:
        return False
    try:
        instance.disconnect()
    except Exception:
        pass
    remove_instance(provider_id)
    try:
        from services.communication.communication_store import store as comm_store
        comm_store.remove_provider(provider_id)
    except Exception:
        pass
    try:
        from services.outbound.outbound_registry import remove_instance as outbound_remove
        outbound_remove(provider_id)
    except Exception:
        pass
    return True


def health_check(provider_id: str):
    """Check provider health."""
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.health()
