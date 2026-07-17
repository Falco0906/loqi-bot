"""Outbound Registry — manages outbound provider lifecycle.

Planner/executor never imports Gmail.
They only ask registry.get(provider_type).
"""
from typing import Optional, Type

from services.outbound.outbound_base import OutboundProviderBase
from services.outbound.outbound_models import (
    DraftMessage,
    SendRequest,
    SendResult,
    ScheduledMessage,
    DraftListResult,
)


_registry: dict[str, Type[OutboundProviderBase]] = {}
_instances: dict[str, OutboundProviderBase] = {}


def register_outbound_provider(provider_class: Type[OutboundProviderBase]) -> None:
    _registry[provider_class.provider_type] = provider_class


def get_provider_class(provider_type: str) -> Optional[Type[OutboundProviderBase]]:
    return _registry.get(provider_type)


def get_provider(provider_id: str) -> Optional[OutboundProviderBase]:
    return _instances.get(provider_id)


def register_instance(provider_id: str, instance: OutboundProviderBase) -> None:
    _instances[provider_id] = instance


def remove_instance(provider_id: str) -> None:
    _instances.pop(provider_id, None)


def list_providers() -> dict[str, OutboundProviderBase]:
    return dict(_instances)


def list_registered_types() -> list[str]:
    return list(_registry.keys())


def create_draft(provider_id: str, draft: DraftMessage) -> Optional[DraftMessage]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.create_draft(draft)


def update_draft(provider_id: str, draft: DraftMessage) -> Optional[DraftMessage]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.update_draft(draft)


def delete_draft(provider_id: str, draft_id: str) -> bool:
    instance = get_provider(provider_id)
    if not instance:
        return False
    return instance.delete_draft(draft_id)


def send(provider_id: str, request: SendRequest) -> Optional[SendResult]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.send(request)


def schedule(provider_id: str, draft: DraftMessage, send_at: str) -> Optional[ScheduledMessage]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.schedule(draft, send_at)


def cancel_schedule(provider_id: str, schedule_id: str) -> bool:
    instance = get_provider(provider_id)
    if not instance:
        return False
    return instance.cancel_schedule(schedule_id)


def fetch_draft(provider_id: str, draft_id: str) -> Optional[DraftMessage]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.fetch_draft(draft_id)


def list_drafts(provider_id: str) -> Optional[DraftListResult]:
    instance = get_provider(provider_id)
    if not instance:
        return None
    return instance.list_drafts()
