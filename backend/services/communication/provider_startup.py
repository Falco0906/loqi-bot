"""Runtime projection between connected communication and outbound providers."""

from __future__ import annotations

import logging

from services.communication.provider_registry import get_provider
from services.outbound.outbound_registry import register_instance as register_outbound_instance


log = logging.getLogger("loqi")


def register_outbound_gmail_instance(communication_provider_id: str) -> None:
    """Configure an outbound Gmail runtime provider from a connected Inbox provider."""
    from services.outbound.gmail_outbound import GmailOutboundProvider

    communication_provider = get_provider(communication_provider_id)
    if not communication_provider:
        log.warning("[outbound] No communication provider found for %s", communication_provider_id)
        return

    access_token = getattr(communication_provider, "_access_token", "")
    refresh_token = getattr(communication_provider, "_refresh_token", "")
    if not access_token and not refresh_token:
        log.warning("[outbound] No tokens available for provider %s", communication_provider_id)
        return

    outbound_provider = GmailOutboundProvider()
    outbound_provider.configure(
        provider_id=communication_provider_id,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=getattr(communication_provider, "_client_id", ""),
        client_secret=getattr(communication_provider, "_client_secret", ""),
        token_expiry=getattr(communication_provider, "_token_expiry", 0.0),
        user_id=getattr(communication_provider, "_user_id", ""),
    )
    register_outbound_instance(communication_provider_id, outbound_provider)
    log.info(
        "[outbound] Registered GmailOutboundProvider instance for %s",
        communication_provider_id,
    )
